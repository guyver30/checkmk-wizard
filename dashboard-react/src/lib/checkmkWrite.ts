// One of the three lib/store modules that make network calls, alongside runtimeConfig.ts and
// src/store/mqttClient.ts. Every browser write to Checkmk (parents, map_position,
// unmanaged-switch hosts, activation) goes through the single `request()` choke point below,
// the TypeScript port of `src/checkmk_wizard/api.py`'s `_request()` (lines 104-140).
//
// Amended 2026-09-30 (quick 260930-hpy): supersedes Phase 13 D-04's client-embedded
// `topology_editor` credential. The browser no longer authenticates itself at all -- the
// scoped `topology_editor` credential is injected by the dashboard's nginx (or the Vite
// dev/preview proxy in local dev) from `TOPOLOGY_EDITOR_SECRET` in `deploy/.env`, per an
// allow-list of exactly the REST calls this module makes (`deploy/dashboard-nginx.conf`).
// `probeEditingAvailable()` below is how the SPA learns whether that server-side injection
// is configured, since it can no longer read the secret's presence client-side.
//
// Functions ported from api.py, one-to-one:
// - request()              <- CheckmkClient._request() (api.py:104-140)
// - updateHostAttributes()  <- wizard.py's _write_host_attributes() (GET -> drop meta_data ->
//                              merge -> full PUT with If-Match). VERDICT: REPLACE
//                              (scripts/probe_host_attribute_merge.py, live-verified
//                              2026-09-12) -- a partial PUT replaces the whole attribute set
//                              rather than merging into it, so every write here round-trips
//                              the full attribute dict, not just the changed keys.
// - updateParents/setMapPosition <- update_host_attributes() (api.py:214-223), specialised
// - createUnmanagedSwitch() <- create_host() (api.py:193-207). Its fixed attribute set is
//                              13-01's VERDICT V-SWITCH (scripts/probe_topology_rest.py,
//                              live-verified 2026-09-23): {tag_address_family: "no-ip",
//                              tag_agent: "no-agent", tag_snmp_ds: "no-snmp",
//                              tag_device_type: "NetworkDevice"} was accepted on first try.
// - countPendingChanges/activateChanges <- get_pending_changes_etag()/activate_changes()
//                              (api.py:295-320) and bootstrap_automation_user()'s activation
//                              polling loop (api.py:508-532).
// - listPendingChanges/getHostSummary: read-only lookups behind the discovered-hosts banner
//                              (quick 261012-fx1); the pure parsing/classification helpers
//                              live here too because activateChanges' guard needs them.
//
// No DOM access, no broker connection, no browser storage -- the browser Fetch API is the
// only I/O primitive used.

import { CHECKMK_REST_ORIGIN } from "./config";
import { getRuntimeConfig } from "./runtimeConfig";
import { type CriticalityTier, isCriticalityTier } from "./incidents";
import {
  MAP_POSITION_LABEL,
  UNMANAGED_SWITCH_LABEL,
  UNMANAGED_SWITCH_VALUE,
  formatMapPosition,
} from "./topologyLayout";

// must match scripts/mqtt_poller.py (plan 14-07)
export const CRITICALITY_LABEL = "criticality";
export const SERVICE_CRITICALITY_LABEL = "service_criticality";
export const DEPENDS_ON_LABEL = "depends_on";

// A service name may not contain ":", ";" or "=" -- ":" is reserved by Checkmk's own service
// naming, ";"/"=" are the entry/pair separators service_criticality's label value uses.
const INVALID_SERVICE_NAME_CHARS_RE = /[:;=]/;

export class CheckmkWriteError extends Error {
  method: string;
  url: string;
  status: number;
  body: unknown;

  constructor(method: string, url: string, status: number, body: unknown) {
    super(`${method} ${url} -> ${status}`);
    this.name = "CheckmkWriteError";
    this.method = method;
    this.url = url;
    this.status = status;
    this.body = body;
  }
}

// Built per call, not at module load: modules are evaluated before main.tsx's
// loadRuntimeConfig() resolves, so a module-level constant would always see the default site.
function apiPrefix(): string {
  return `${CHECKMK_REST_ORIGIN}/${getRuntimeConfig().checkmkSite}/check_mk/api/1.0`;
}
const DEFAULT_EXPECT = [200, 201, 204];

interface RequestOptions {
  body?: unknown;
  headers?: Record<string, string>;
  expect?: number[];
}

// The single choke point every exported write/read funnels through (api.py:104-140's analog):
// builds the URL, sets Accept, JSON-encodes the body, normalises both a rejected fetch (network
// failure, status 0) and a non-expected HTTP status into one CheckmkWriteError. No Authorization
// header is set here (amended 2026-09-30, quick 260930-hpy) -- nginx (or the Vite dev/preview
// proxy) injects the scoped topology_editor credential server-side and overrides anything the
// client sends, so the browser has nothing to leak into an error message, a Snackbar, or a log.
async function request(method: string, path: string, opts?: RequestOptions): Promise<Response> {
  const url = `${apiPrefix()}${path}`;
  const expect = opts?.expect ?? DEFAULT_EXPECT;
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...opts?.headers,
  };
  if (opts?.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: opts?.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch (err) {
    // status 0 signals "no HTTP response was ever received" -- mirrors api.py's own
    // status_code=0 convention for the equivalent httpx.HTTPError case.
    throw new CheckmkWriteError(method, url, 0, String(err));
  }

  if (!expect.includes(response.status)) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = await response.text().catch(() => "");
    }
    throw new CheckmkWriteError(method, url, response.status, body);
  }
  return response;
}

// Runtime replacement for the old compile-time isTopologyEditingConfigured() placeholder check
// (amended 2026-09-30, quick 260930-hpy): since the browser no longer holds the credential, it
// can only find out whether editing is available by asking Checkmk through the same proxy path
// the rest of this module uses. GET /version must stay on nginx's GET allow-list
// (deploy/dashboard-nginx.conf) for this probe to ever succeed. 200 means the injected
// Authorization header authenticated; a Checkmk site with TOPOLOGY_EDITOR_SECRET unset answers
// 401 to every /checkmk-api/ call (nginx still injects the header, just with an empty secret),
// which resolves this to false, same as any other rejected status or a network failure.
export async function probeEditingAvailable(): Promise<boolean> {
  try {
    await request("GET", "/version");
    return true;
  } catch {
    return false;
  }
}

// Serializes every write behind a module-level promise chain so two rapid edits can never
// race on a stale ETag (the second write's GET only starts once the first write's PUT has
// settled). A failed link never breaks the chain -- the next queued write still runs.
let writeQueue: Promise<unknown> = Promise.resolve();

function serialize<T>(fn: () => Promise<T>): Promise<T> {
  const result = writeQueue.then(fn, fn);
  writeQueue = result.then(
    () => undefined,
    () => undefined,
  );
  return result;
}

// wizard.py:109 _HOST_NAME_RE -- letters/digits/underscore/hyphen/dot only (live-verified
// against the host_config create endpoint's own rejection pattern).
const HOST_NAME_RE = /^[-0-9a-zA-Z_.]+$/;

export function isValidHostName(name: string): boolean {
  return HOST_NAME_RE.test(name);
}

// GET a host's full attribute dict, drop the Checkmk-computed meta_data key (wizard.py:1086-
// 1091), apply the caller's mutation, and PUT the whole dict back with the GET's own ETag.
// REPLACE semantics (see module header) mean sending anything less than the full dict would
// silently strip ipaddress/tags/labels the caller never meant to touch.
async function updateHostAttributes(
  host: string,
  mutate: (attributes: Record<string, unknown>) => Record<string, unknown>,
): Promise<void> {
  const path = `/objects/host_config/${encodeURIComponent(host)}`;
  const getResp = await request("GET", path);
  const etag = getResp.headers.get("ETag");
  if (!etag) {
    throw new CheckmkWriteError("GET", `${apiPrefix()}${path}`, getResp.status, "missing ETag header");
  }
  const json = (await getResp.json()) as { extensions?: { attributes?: Record<string, unknown> } };
  const attributes: Record<string, unknown> = { ...(json.extensions?.attributes ?? {}) };
  delete attributes.meta_data;
  const mutated = mutate(attributes);

  await request("PUT", path, {
    body: { attributes: mutated },
    headers: { "If-Match": etag },
    expect: [200, 204],
  });
}

// Shared label-merge choke point every label writer (setMapPosition, setCriticality,
// setServiceCriticality, updateDependsOn) funnels through: GETs via updateHostAttributes,
// replaces attributes.labels with mutate()'s result over the current string-valued labels
// (REPLACE semantics -- see module header -- so a label key omitted from the mutated map is
// a deletion, not a no-op). Does not call serialize() itself; every exported writer wraps its
// own call in serialize() so callers can see (and tests can assert) which writes are queued.
function updateLabels(
  host: string,
  mutate: (labels: Record<string, string>) => Record<string, string>,
): Promise<void> {
  return updateHostAttributes(host, (attributes) => {
    const raw =
      attributes.labels && typeof attributes.labels === "object"
        ? (attributes.labels as Record<string, unknown>)
        : {};
    const currentLabels: Record<string, string> = {};
    for (const [key, value] of Object.entries(raw)) {
      if (typeof value === "string") {
        currentLabels[key] = value;
      }
    }
    return { ...attributes, labels: mutate(currentLabels) };
  });
}

// Parsing rules mirror scripts/mqtt_poller.py's `_parse_service_criticality` (plan 14-07):
// malformed entries (missing "=", out-of-vocabulary tier, empty name) are dropped rather than
// raising -- a stale/hand-edited label degrades gracefully instead of breaking the panel.
export function parseServiceCriticalityLabel(value: unknown): Record<string, CriticalityTier> {
  const result: Record<string, CriticalityTier> = {};
  if (typeof value !== "string" || value.length === 0) {
    return result;
  }
  for (const entry of value.split(";")) {
    const eq = entry.indexOf("=");
    if (eq <= 0) {
      continue;
    }
    const name = entry.slice(0, eq);
    const tier = entry.slice(eq + 1);
    if (isCriticalityTier(tier)) {
      result[name] = tier;
    }
  }
  return result;
}

export function formatServiceCriticality(map: Record<string, CriticalityTier>): string {
  return Object.keys(map)
    .sort()
    .map((name) => `${name}=${map[name]}`)
    .join(";");
}

// Mirrors scripts/mqtt_poller.py's `_parse_depends_on` (plan 14-07): comma-separated host ids,
// invalid/empty entries dropped rather than raising.
export function parseDependsOnLabel(value: unknown): string[] {
  if (typeof value !== "string" || value.length === 0) {
    return [];
  }
  return value
    .split(",")
    .map((id) => id.trim())
    .filter((id) => id.length > 0 && isValidHostName(id));
}

export function formatDependsOn(ids: string[]): string {
  return ids.join(",");
}

export function setCriticality(host: string, tier: CriticalityTier): Promise<void> {
  if (!isValidHostName(host)) {
    return Promise.reject(new Error(`invalid host name: ${host}`));
  }
  if (!isCriticalityTier(tier)) {
    return Promise.reject(new Error(`invalid criticality tier: ${tier}`));
  }
  return serialize(() =>
    updateLabels(host, (labels) => ({ ...labels, [CRITICALITY_LABEL]: tier })),
  );
}

export function setServiceCriticality(
  host: string,
  serviceName: string,
  tier: CriticalityTier | null,
): Promise<void> {
  if (!isValidHostName(host)) {
    return Promise.reject(new Error(`invalid host name: ${host}`));
  }
  if (serviceName.length === 0 || INVALID_SERVICE_NAME_CHARS_RE.test(serviceName)) {
    return Promise.reject(new Error(`invalid service name: ${serviceName}`));
  }
  if (tier !== null && !isCriticalityTier(tier)) {
    return Promise.reject(new Error(`invalid criticality tier: ${tier}`));
  }
  return serialize(() =>
    updateLabels(host, (labels) => {
      const current = parseServiceCriticalityLabel(labels[SERVICE_CRITICALITY_LABEL]);
      const next = { ...current };
      if (tier === null) {
        delete next[serviceName];
      } else {
        next[serviceName] = tier;
      }
      const rest = { ...labels };
      delete rest[SERVICE_CRITICALITY_LABEL];
      if (Object.keys(next).length === 0) {
        return rest;
      }
      return { ...rest, [SERVICE_CRITICALITY_LABEL]: formatServiceCriticality(next) };
    }),
  );
}

export function updateDependsOn(
  host: string,
  mutate: (ids: string[]) => string[],
): Promise<void> {
  if (!isValidHostName(host)) {
    return Promise.reject(new Error(`invalid host name: ${host}`));
  }
  return serialize(() =>
    updateLabels(host, (labels) => {
      const current = parseDependsOnLabel(labels[DEPENDS_ON_LABEL]);
      const mutated = mutate(current);
      const deduped = Array.from(
        new Set(mutated.filter((id) => id !== host && isValidHostName(id))),
      );
      const rest = { ...labels };
      delete rest[DEPENDS_ON_LABEL];
      if (deduped.length === 0) {
        return rest;
      }
      return { ...rest, [DEPENDS_ON_LABEL]: formatDependsOn(deduped) };
    }),
  );
}

export function updateParents(
  host: string,
  mutate: (parents: string[]) => string[],
): Promise<void> {
  return serialize(() =>
    updateHostAttributes(host, (attributes) => {
      const current = Array.isArray(attributes.parents)
        ? (attributes.parents as unknown[]).filter((p): p is string => typeof p === "string")
        : [];
      const deduped = Array.from(new Set(mutate(current)));
      const next = { ...attributes };
      if (deduped.length === 0) {
        delete next.parents;
      } else {
        next.parents = deduped;
      }
      return next;
    }),
  );
}

export function setMapPosition(host: string, x: number, y: number): Promise<void> {
  return serialize(() =>
    updateLabels(host, (labels) => ({
      ...labels,
      [MAP_POSITION_LABEL]: formatMapPosition(x, y),
    })),
  );
}

// VERDICT V-SWITCH (scripts/probe_topology_rest.py, live-verified 2026-09-23): this exact
// dict produced a zero-service host on the first attempt, no fallback variant needed.
// device_type reuses NetworkDevice rather than a new tag-group value (RESEARCH Pitfall 2 --
// host tag groups cannot be updated over the REST API once created, only via a one-time
// manual WATO edit).
export const UNMANAGED_SWITCH_ATTRIBUTES = {
  tag_address_family: "no-ip",
  tag_agent: "no-agent",
  tag_snmp_ds: "no-snmp",
  tag_device_type: "NetworkDevice",
};

export function createUnmanagedSwitch(
  name: string,
  position: { x: number; y: number },
): Promise<void> {
  if (!isValidHostName(name)) {
    return Promise.reject(new CheckmkWriteError("POST", name, 0, "invalid host name"));
  }
  return serialize(async () => {
    await request("POST", "/domain-types/host_config/collections/all?bake_agent=false", {
      body: {
        host_name: name,
        folder: "/",
        attributes: {
          ...UNMANAGED_SWITCH_ATTRIBUTES,
          labels: {
            [MAP_POSITION_LABEL]: formatMapPosition(position.x, position.y),
            [UNMANAGED_SWITCH_LABEL]: UNMANAGED_SWITCH_VALUE,
          },
        },
      },
      expect: [200, 201],
    });
  });
}

// The shape of a pending_changes entry is NOT live-verified. Per the Checkmk 2.4 source the
// fields are id, user_id, action_name, text and time (possibly under `extensions`), so the
// parser keeps only string/number-typed fields and tolerates anything else being absent.
export interface PendingChange {
  id?: string;
  user_id?: string | null;
  action_name?: string;
  text?: string;
  time?: number | string;
}

// Must match src/checkmk_wizard/api.py TOPOLOGY_EDITOR_USER_ID.
export const TOPOLOGY_EDITOR_USER = "topology_editor";

const PENDING_CHANGES_PATH = "/domain-types/activation_run/collections/pending_changes";

export function parsePendingChanges(json: unknown): PendingChange[] {
  if (typeof json !== "object" || json === null) {
    return [];
  }
  const value = (json as { value?: unknown }).value;
  if (!Array.isArray(value)) {
    return [];
  }
  const result: PendingChange[] = [];
  for (const entry of value) {
    if (typeof entry !== "object" || entry === null || Array.isArray(entry)) {
      continue;
    }
    const top = entry as Record<string, unknown>;
    const nested =
      typeof top.extensions === "object" && top.extensions !== null
        ? (top.extensions as Record<string, unknown>)
        : {};
    const pick = (key: string): unknown => (top[key] !== undefined ? top[key] : nested[key]);
    const change: PendingChange = {};
    const id = pick("id");
    const userId = pick("user_id");
    const actionName = pick("action_name");
    const text = pick("text");
    const time = pick("time");
    if (typeof id === "string") change.id = id;
    if (typeof userId === "string") change.user_id = userId;
    if (typeof actionName === "string") change.action_name = actionName;
    if (typeof text === "string") change.text = text;
    if (typeof time === "string" || typeof time === "number") change.time = time;
    result.push(change);
  }
  return result;
}

// "Created new host web01." and close variants, optionally quoted or wrapped in <tt>. Only a
// name that passes isValidHostName is ever returned, so nothing else reaches the DOM.
const CREATED_HOST_RE =
  /\b(?:created|added)\s+(?:new\s+)?host\s+["'\u2018\u201c]?([^\s"'\u2019\u201d]+?)["'\u2019\u201d]?\.?\s*$/i;

export function extractCreatedHostName(change: Pick<PendingChange, "text">): string | null {
  if (typeof change.text !== "string") {
    return null;
  }
  const plain = change.text.replace(/<[^>]*>/g, "").trim();
  const match = CREATED_HOST_RE.exec(plain);
  if (!match) {
    return null;
  }
  const name = match[1];
  return isValidHostName(name) ? name : null;
}

export function isHostCreation(change: Pick<PendingChange, "text" | "action_name">): boolean {
  if (typeof change.action_name === "string" && /create[-_]host/i.test(change.action_name)) {
    return true;
  }
  return extractCreatedHostName(change) !== null;
}

export function pendingChangeKey(change: PendingChange): string {
  if (typeof change.id === "string" && change.id.length > 0) {
    return change.id;
  }
  return `${change.action_name ?? ""}|${change.text ?? ""}|${change.time ?? ""}`;
}

export interface PendingClassification {
  newHosts: { key: string; host: string }[];
  unnamedHostCreations: number;
  otherForeign: number;
  own: number;
  unknownShape: number;
  allKeys: string[];
}

export function classifyPendingChanges(
  changes: PendingChange[],
  ownUser: string = TOPOLOGY_EDITOR_USER,
): PendingClassification {
  const result: PendingClassification = {
    newHosts: [],
    unnamedHostCreations: 0,
    otherForeign: 0,
    own: 0,
    unknownShape: 0,
    allKeys: [],
  };
  const seenHosts = new Set<string>();
  for (const change of changes) {
    const key = pendingChangeKey(change);
    result.allKeys.push(key);
    if (change.user_id === ownUser) {
      result.own += 1;
      continue;
    }
    if (typeof change.text !== "string" && typeof change.action_name !== "string") {
      result.unknownShape += 1;
      continue;
    }
    const host = extractCreatedHostName(change);
    if (host !== null) {
      if (!seenHosts.has(host)) {
        seenHosts.add(host);
        result.newHosts.push({ key, host });
      }
    } else if (isHostCreation(change)) {
      result.unnamedHostCreations += 1;
    } else {
      result.otherForeign += 1;
    }
  }
  return result;
}

// Reads, deliberately not wrapped in serialize(): they never touch an ETag a write relies on.
export async function listPendingChanges(): Promise<PendingChange[]> {
  const resp = await request("GET", PENDING_CHANGES_PATH);
  return parsePendingChanges(await resp.json());
}

export interface HostSummary {
  name: string;
  ip: string | null;
  folder: string | null;
}

export async function getHostSummary(name: string): Promise<HostSummary> {
  if (!isValidHostName(name)) {
    throw new CheckmkWriteError("GET", name, 0, "invalid host name");
  }
  const resp = await request("GET", `/objects/host_config/${encodeURIComponent(name)}`);
  const json = (await resp.json()) as {
    extensions?: { folder?: unknown; attributes?: { ipaddress?: unknown } };
  };
  const ip = json.extensions?.attributes?.ipaddress;
  const folder = json.extensions?.folder;
  return {
    name,
    ip: typeof ip === "string" ? ip : null,
    folder: typeof folder === "string" ? folder : null,
  };
}

export async function countPendingChanges(): Promise<number> {
  const resp = await request("GET", PENDING_CHANGES_PATH);
  const json = (await resp.json()) as { value?: unknown };
  return Array.isArray(json.value) ? json.value.length : 0;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Widens api.py's 30 x 0.3s activation poll (api.py:508-532) to 60 x 500ms: a browser Apply
// can activate a multi-host batch (13-07), which takes longer than the single-host case that
// poll loop was tuned for. force_foreign_changes defaults to false, so edit-mode Apply can
// never activate another user's unreviewed changes (T-13-17). Amended 2026-10-12 (quick
// 261012-fx1, operator decision): the topology_editor role now holds wato.activateforeign, and
// the discovered-hosts banner -- and only it -- opts in with forceForeignChanges true, passing
// expectedChangeKeys so it never activates a change the operator was not shown.
const ACTIVATION_MAX_POLLS = 60;
const ACTIVATION_POLL_MS = 500;

export interface ActivateOptions {
  forceForeignChanges?: boolean;
  expectedChangeKeys?: string[];
}

export function activateChanges(options?: ActivateOptions): Promise<void> {
  return serialize(async () => {
    const pendingResp = await request("GET", PENDING_CHANGES_PATH);
    const pendingJson = (await pendingResp.json()) as { value?: unknown };
    const pending = Array.isArray(pendingJson.value) ? pendingJson.value : [];
    if (pending.length === 0) {
      return;
    }

    if (options?.expectedChangeKeys !== undefined) {
      const expected = new Set(options.expectedChangeKeys);
      const unexpected = parsePendingChanges(pendingJson).some(
        (change) => !expected.has(pendingChangeKey(change)),
      );
      if (unexpected) {
        throw new CheckmkWriteError(
          "GET",
          `${apiPrefix()}${PENDING_CHANGES_PATH}`,
          409,
          "pending changes changed since confirmation",
        );
      }
    }

    const etag = pendingResp.headers.get("ETag");
    if (!etag) {
      throw new CheckmkWriteError(
        "GET",
        `${apiPrefix()}${PENDING_CHANGES_PATH}`,
        pendingResp.status,
        "missing ETag header",
      );
    }

    const activateResp = await request(
      "POST",
      "/domain-types/activation_run/actions/activate-changes/invoke",
      {
        body: {
          redirect: false,
          sites: [getRuntimeConfig().checkmkSite],
          force_foreign_changes: options?.forceForeignChanges === true,
        },
        headers: { "If-Match": etag },
        expect: [200, 201, 204],
      },
    );
    if (activateResp.status === 204) {
      return;
    }

    const activation = (await activateResp.json()) as {
      id: string;
      extensions?: { is_running?: boolean };
    };
    let isRunning = activation.extensions?.is_running === true;

    for (let i = 0; i < ACTIVATION_MAX_POLLS && isRunning; i++) {
      await sleep(ACTIVATION_POLL_MS);
      // Poll by id, not the response's self-referencing link href: behind the same-origin
      // proxy that href's absolute host/port is Checkmk's own and unreachable from the browser.
      const pollPath = `/objects/activation_run/${encodeURIComponent(activation.id)}`;
      const statusResp = await request("GET", pollPath);
      const statusJson = (await statusResp.json()) as { extensions?: { is_running?: boolean } };
      isRunning = statusJson.extensions?.is_running === true;
    }

    if (isRunning) {
      const pollPath = `/objects/activation_run/${encodeURIComponent(activation.id)}`;
      throw new CheckmkWriteError("GET", `${apiPrefix()}${pollPath}`, 0, "activation timed out");
    }
  });
}
