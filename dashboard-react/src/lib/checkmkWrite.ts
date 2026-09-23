// The one module in lib/ that makes network calls -- the same exception src/store/mqttClient.ts
// is for the broker. Every browser write to Checkmk (parents, map_position, unmanaged-switch
// hosts, activation) goes through the single `request()` choke point below, the TypeScript
// port of `src/checkmk_wizard/api.py`'s `_request()` (lines 104-140). It authenticates as the
// scoped `topology_editor` credential from `./config.ts` (D-04) -- never the wizard's own
// full-power `automation` user.
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
//
// No DOM access, no broker connection, no browser storage -- the browser Fetch API is the
// only I/O primitive used.

import {
  CHECKMK_REST_ORIGIN,
  CHECKMK_SITE,
  TOPOLOGY_EDITOR_SECRET,
  TOPOLOGY_EDITOR_USER,
} from "./config";
import {
  MAP_POSITION_LABEL,
  UNMANAGED_SWITCH_LABEL,
  UNMANAGED_SWITCH_VALUE,
  formatMapPosition,
} from "./topologyLayout";

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

const API_PREFIX = `${CHECKMK_REST_ORIGIN}/${CHECKMK_SITE}/check_mk/api/1.0`;
const DEFAULT_EXPECT = [200, 201, 204];

interface RequestOptions {
  body?: unknown;
  headers?: Record<string, string>;
  expect?: number[];
}

// The single choke point every exported write/read funnels through (api.py:104-140's analog):
// builds the URL, sets Authorization/Accept, JSON-encodes the body, normalises both a rejected
// fetch (network failure, status 0) and a non-expected HTTP status into one CheckmkWriteError.
// Deliberately never copies `headers` into the thrown error, so the Authorization header (and
// therefore TOPOLOGY_EDITOR_SECRET) can never leak into an error message, a Snackbar, or a log.
async function request(method: string, path: string, opts?: RequestOptions): Promise<Response> {
  const url = `${API_PREFIX}${path}`;
  const expect = opts?.expect ?? DEFAULT_EXPECT;
  const headers: Record<string, string> = {
    Authorization: `Bearer ${TOPOLOGY_EDITOR_USER} ${TOPOLOGY_EDITOR_SECRET}`,
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
    throw new CheckmkWriteError("GET", `${API_PREFIX}${path}`, getResp.status, "missing ETag header");
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
    updateHostAttributes(host, (attributes) => {
      const currentLabels =
        attributes.labels && typeof attributes.labels === "object"
          ? (attributes.labels as Record<string, unknown>)
          : {};
      return {
        ...attributes,
        labels: { ...currentLabels, [MAP_POSITION_LABEL]: formatMapPosition(x, y) },
      };
    }),
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

export async function countPendingChanges(): Promise<number> {
  const resp = await request("GET", "/domain-types/activation_run/collections/pending_changes");
  const json = (await resp.json()) as { value?: unknown };
  return Array.isArray(json.value) ? json.value.length : 0;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Widens api.py's 30 x 0.3s activation poll (api.py:508-532) to 60 x 500ms: a browser Apply
// can activate a multi-host batch (13-07), which takes longer than the single-host case that
// poll loop was tuned for. force_foreign_changes stays hard-coded false so the scoped
// topology_editor credential can never activate another user's unreviewed changes (T-13-17).
const ACTIVATION_MAX_POLLS = 60;
const ACTIVATION_POLL_MS = 500;

export function activateChanges(): Promise<void> {
  return serialize(async () => {
    const pendingResp = await request(
      "GET",
      "/domain-types/activation_run/collections/pending_changes",
    );
    const pendingJson = (await pendingResp.json()) as { value?: unknown };
    const pending = Array.isArray(pendingJson.value) ? pendingJson.value : [];
    if (pending.length === 0) {
      return;
    }

    const etag = pendingResp.headers.get("ETag");
    if (!etag) {
      throw new CheckmkWriteError(
        "GET",
        `${API_PREFIX}/domain-types/activation_run/collections/pending_changes`,
        pendingResp.status,
        "missing ETag header",
      );
    }

    const activateResp = await request(
      "POST",
      "/domain-types/activation_run/actions/activate-changes/invoke",
      {
        body: { redirect: false, sites: [CHECKMK_SITE], force_foreign_changes: false },
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
      throw new CheckmkWriteError("GET", `${API_PREFIX}${pollPath}`, 0, "activation timed out");
    }
  });
}
