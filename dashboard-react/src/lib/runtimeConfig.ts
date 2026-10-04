// Runtime, per-deployment configuration loaded from /config.json before first render.
//
// One dashboard image runs on every machine: the Checkmk site name and the read-only MQTT
// WebSocket credentials are rendered by the dashboard's own nginx from deploy/.env
// (deploy/dashboard-nginx.conf's `location = /config.json`), not baked into the JS bundle.
// Under vite dev/preview (and vitest) there is no /config.json, so every field falls back to
// its own default individually -- see parseRuntimeConfig(). The third lib/store module
// allowed to do network I/O, alongside checkmkWrite.ts and mqttClient.ts (adminMode.ts,
// historyClient.ts and triageMode.ts later became the fourth, fifth and sixth).

import { DEFAULT_CHECKMK_SITE, DEFAULT_WS_PASSWORD, DEFAULT_WS_USERNAME } from "./config";

export interface RuntimeConfig {
  checkmkSite: string;
  wsUsername: string;
  wsPassword: string;
}

const DEFAULTS: RuntimeConfig = {
  checkmkSite: DEFAULT_CHECKMK_SITE,
  wsUsername: DEFAULT_WS_USERNAME,
  wsPassword: DEFAULT_WS_PASSWORD,
};

// wizard.py's site-name rule: starts with a letter, up to 16 letters/digits/underscores --
// also a subset of the nginx allow-list's [A-Za-z0-9_]+ path segment (T-ixs-02).
const SITE_ID_RE = /^[A-Za-z][A-Za-z0-9_]{0,15}$/;

export function parseRuntimeConfig(raw: unknown): RuntimeConfig {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return { ...DEFAULTS };
  }
  const obj = raw as Record<string, unknown>;
  const checkmkSite =
    typeof obj.checkmkSite === "string" && SITE_ID_RE.test(obj.checkmkSite)
      ? obj.checkmkSite
      : DEFAULTS.checkmkSite;
  const wsUsername =
    typeof obj.wsUsername === "string" && obj.wsUsername !== ""
      ? obj.wsUsername
      : DEFAULTS.wsUsername;
  const wsPassword =
    typeof obj.wsPassword === "string" && obj.wsPassword !== ""
      ? obj.wsPassword
      : DEFAULTS.wsPassword;
  return { checkmkSite, wsUsername, wsPassword };
}

let current: RuntimeConfig = { ...DEFAULTS };

// GETs /config.json once before first render (see main.tsx). Never rejects -- a hung
// request, a non-OK response (404 under vite dev, which has no nginx), and a non-JSON body
// (vite dev's SPA fallback returns index.html) all resolve to the defaults, so a failure
// here can never block rendering (T-ixs-04).
export async function loadRuntimeConfig(fetchFn: typeof fetch = fetch): Promise<RuntimeConfig> {
  try {
    const response = await fetchFn("/config.json", {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) {
      current = { ...DEFAULTS };
      return current;
    }
    const body: unknown = await response.json();
    current = parseRuntimeConfig(body);
  } catch {
    current = { ...DEFAULTS };
  }
  return current;
}

// Called once by main.tsx before mount in admin mode (?admin=1): swaps in the write-capable
// MQTT login while leaving the site name untouched.
export function applyAdminCredentials(wsUsername: string, wsPassword: string): void {
  current = { ...current, wsUsername, wsPassword };
}

export function getRuntimeConfig(): RuntimeConfig {
  return current;
}

// Test-only: sets (or, with no argument, resets to defaults) the module-level config.
// Mirrors mqttClient.ts's __resetForTests naming style.
export function __setRuntimeConfigForTests(cfg?: Partial<RuntimeConfig>): void {
  current = { ...DEFAULTS, ...cfg };
}
