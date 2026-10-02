// Admin mode (`?admin=1`, D-07): the fourth lib module allowed to do network I/O (only
// loadAdminConfig), alongside runtimeConfig.ts, checkmkWrite.ts and mqttClient.ts. It never
// imports a store; main.tsx bridges the loadAdminConfig result into the admin store.

import type { DevicePayload } from "./types";
import { applyAdminCredentials } from "./runtimeConfig";

export const ADMIN_TOPIC_CMD = "admin/cmd";
export const ADMIN_TOPIC_ACK = "admin/ack";
export const ADMIN_TOPIC_FAKED = "admin/faked";
export const ADMIN_MAX_HOSTS = 200;

export type AdminAction = "up" | "down" | "unreach" | "restore" | "restore_all";
export type FakedState = "UP" | "DOWN" | "UNREACH";

export interface AdminCommand {
  id: string;
  action: AdminAction;
  hosts: string[];
}

export interface AdminAckEntry {
  host: string;
  state: "UP" | "DOWN" | "UNREACH" | "RESTORED";
  cascaded: boolean;
}

export interface AdminAck {
  id: string;
  ok: boolean;
  action: string;
  detail: string;
  applied: AdminAckEntry[];
  skipped: string[];
}

export function detectAdminMode(search: string): boolean {
  return new URLSearchParams(search).get("admin") === "1";
}

// Read once at module load: navigation helpers that rewrite the search string cannot drop
// admin mode later in the page's life.
let adminMode = typeof location !== "undefined" ? detectAdminMode(location.search) : false;

export function isAdminMode(): boolean {
  return adminMode;
}

// Test-only.
export function __setAdminModeForTests(on: boolean): void {
  adminMode = on;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseAdminConfig(
  raw: unknown,
): { wsUsername: string; wsPassword: string } | null {
  if (!isPlainObject(raw)) {
    return null;
  }
  const { wsUsername, wsPassword } = raw;
  if (
    typeof wsUsername !== "string" ||
    wsUsername === "" ||
    typeof wsPassword !== "string" ||
    wsPassword === ""
  ) {
    return null;
  }
  return { wsUsername, wsPassword };
}

// GETs /admin-config.json (the write-capable wsadmin login). Never rejects: any failure
// resolves false and leaves the read-only credentials untouched.
export async function loadAdminConfig(fetchFn: typeof fetch = fetch): Promise<boolean> {
  try {
    const response = await fetchFn("/admin-config.json", {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) {
      return false;
    }
    const parsed = parseAdminConfig(await response.json());
    if (!parsed) {
      return false;
    }
    applyAdminCredentials(parsed.wsUsername, parsed.wsPassword);
    return true;
  } catch {
    return false;
  }
}

// Deliberately not crypto.randomUUID(), which only exists in secure contexts; the dashboard
// is served over plain http on the LAN.
export function newCommandId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function buildAdminCommand(
  action: AdminAction,
  hosts: string[],
  id: string,
): AdminCommand {
  const deduped = action === "restore_all" ? [] : [...new Set(hosts)];
  if (deduped.length > ADMIN_MAX_HOSTS) {
    throw new Error(`Too many hosts: ${deduped.length} (max ${ADMIN_MAX_HOSTS})`);
  }
  return { id, action, hosts: deduped };
}

const ACK_STATES = new Set(["UP", "DOWN", "UNREACH", "RESTORED"]);
const FAKED_STATES = new Set(["UP", "DOWN", "UNREACH"]);

export function parseAdminAck(raw: unknown): AdminAck | null {
  if (!isPlainObject(raw)) {
    return null;
  }
  if (typeof raw.id !== "string" || typeof raw.ok !== "boolean") {
    return null;
  }
  const applied: AdminAckEntry[] = [];
  if (Array.isArray(raw.applied)) {
    for (const entry of raw.applied) {
      if (
        isPlainObject(entry) &&
        typeof entry.host === "string" &&
        typeof entry.state === "string" &&
        ACK_STATES.has(entry.state)
      ) {
        applied.push({
          host: entry.host,
          state: entry.state as AdminAckEntry["state"],
          cascaded: entry.cascaded === true,
        });
      }
    }
  }
  const skipped = Array.isArray(raw.skipped)
    ? raw.skipped.filter((s): s is string => typeof s === "string")
    : [];
  return {
    id: raw.id,
    ok: raw.ok,
    action: typeof raw.action === "string" ? raw.action : "",
    detail: typeof raw.detail === "string" ? raw.detail : "",
    applied,
    skipped,
  };
}

export function parseAdminFaked(raw: unknown): Record<string, FakedState> {
  const out: Record<string, FakedState> = {};
  if (!isPlainObject(raw) || !isPlainObject(raw.hosts)) {
    return out;
  }
  for (const [host, state] of Object.entries(raw.hosts)) {
    if (typeof state === "string" && FAKED_STATES.has(state)) {
      out[host] = state as FakedState;
    }
  }
  return out;
}

const NO_FOLDER = "(no folder)";

// Subfolders included: "/net" matches "/net" and "/net/x" but not "/network".
export function hostsInFolder(
  folder: string,
  devices: Record<string, DevicePayload>,
): string[] {
  const ids: string[] = [];
  for (const [id, device] of Object.entries(devices)) {
    const f = (device.folder ?? "").trim();
    const match =
      folder === NO_FOLDER ? f === "" : f === folder || f.startsWith(`${folder}/`);
    if (match) {
      ids.push(id);
    }
  }
  return ids.sort();
}

// Mirrors the poller's plan_admin_actions DOWN rule (D-01/D-02) for the confirm dialog
// preview only; the poller stays authoritative and its ack lists what it actually applied.
export function previewCascade(selected: string[], topologyDevices: unknown[]): string[] {
  const children = new Map<string, string[]>();
  const unmanaged = new Set<string>();
  for (const entry of topologyDevices) {
    if (!isPlainObject(entry) || typeof entry.id !== "string") {
      continue;
    }
    if (entry.unmanaged === true) {
      unmanaged.add(entry.id);
    }
    if (Array.isArray(entry.parents)) {
      for (const parent of entry.parents) {
        if (typeof parent === "string") {
          const list = children.get(parent) ?? [];
          list.push(entry.id);
          children.set(parent, list);
        }
      }
    }
  }
  const selectedSet = new Set(selected);
  const visited = new Set<string>();
  const result = new Set<string>();
  const queue: string[] = [];
  for (const root of selected) {
    if (!unmanaged.has(root)) {
      queue.push(root);
    }
  }
  while (queue.length > 0) {
    const node = queue.shift() as string;
    if (visited.has(node)) {
      continue;
    }
    visited.add(node);
    for (const child of children.get(node) ?? []) {
      if (!selectedSet.has(child)) {
        result.add(child);
      }
      if (!unmanaged.has(child)) {
        queue.push(child);
      }
    }
  }
  return [...result].sort();
}
