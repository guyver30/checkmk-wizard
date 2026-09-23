// Per-deployment configuration for the live dashboard.
//
// This file replaces dashboard/js/config.js for the React app; it is the file D-37's
// deployment-doc callout points at as the one file an operator edits per deployment,
// loaded before everything else that needs it.
//
// No broker host constant is defined here — the broker host is deliberately NOT
// configured in this file. It is derived at runtime from `location.hostname` (D-02) by
// whichever module owns the MQTT connection, because the poller (scripts/mqtt_poller.py)
// reaches Checkmk over the container-internal name checkmk:5000, which no LAN browser can
// resolve — CHECKMK_BASE_URL below is a separate, human-facing link and must be edited
// per deployment.
//
// WS_USERNAME/WS_PASSWORD are deliberately-committed disposable read-only credentials,
// the same convention already used by deploy/mosquitto.passwd itself, cmkadmin/cmkadmin,
// and minioadmin/minioadmin. The grant behind them is read-only (`topic read lan/#` in
// deploy/mosquitto.acl), which bounds the exposure to reading the device list, never
// writing anything back to the broker.
//
// POLL_INTERVAL_SECONDS and HISTORY_MAX_ENTRIES mirror DEFAULT_POLL_INTERVAL_SECONDS and
// DEFAULT_HISTORY_MAX_ENTRIES in scripts/mqtt_poller.py and must be kept in step with it
// if the poller's own environment configuration changes.
//
// CHECKMK_REST_ORIGIN is a same-origin path prefix, not a URL. A browser page served from
// the dashboard's own origin cannot call Checkmk's REST API on a different origin (Checkmk's
// port 8080) unless Checkmk answers CORS preflights -- live-verified it does not (13-01's
// `scripts/probe_topology_rest.py`, VERDICT V-CORS, 2026-09-23: an OPTIONS preflight returned
// status 405 with no `Access-Control-*` response headers at all). The dashboard's own Vite
// dev/preview server (and, post-cutover, the same nginx container per D-42) forwards this
// prefix to Checkmk instead -- see vite.config.ts's `/checkmk-api` proxy entries. Only if a
// future V-CORS re-check comes back ALLOWED may this be set to the literal CHECKMK_BASE_URL.
//
// TOPOLOGY_EDITOR_USER/TOPOLOGY_EDITOR_SECRET are, unlike WS_USERNAME/WS_PASSWORD above,
// WRITE-capable: this credential edits and adds Checkmk hosts and activates its own pending
// changes (13-06/13-07 call checkmkWrite.ts, which authenticates with it). It is scoped to
// the narrow `topology_editor` role that `scripts/provision_topology_editor.py` provisions
// over REST -- never the wizard's own full-power `automation` user from
// `bootstrap_automation_user()` (D-04). Its secret comes from that script's one-time output
// and must be pasted in below, replacing the placeholder. Embedding a write-capable secret
// client-side is acceptable under this project's existing trusted-LAN, no-multi-user-accounts
// posture (same convention as the already-committed disposable WS_USERNAME/WS_PASSWORD above).

export const WS_PORT = 9002;
export const WS_USERNAME = "wsreader";
export const WS_PASSWORD = "wsreader";
export const POLL_INTERVAL_SECONDS = 60;
export const STALENESS_FACTOR = 3;
export const HISTORY_MAX_ENTRIES = 20;
export const CHECKMK_BASE_URL = "http://<HOST_IP>:8080";
export const CHECKMK_SITE = "dmc";

export const CHECKMK_BASE_URL_PLACEHOLDER = "http://<HOST_IP>:8080";

/**
 * D-20: the Checkmk deep link must be disabled while CHECKMK_BASE_URL is still the
 * unedited placeholder, since it would otherwise point nowhere a browser can reach.
 * Named here so the check has one home instead of a string comparison scattered across
 * views.
 */
export function isCheckmkLinkConfigured(): boolean {
  return CHECKMK_BASE_URL !== CHECKMK_BASE_URL_PLACEHOLDER;
}

export const CHECKMK_REST_ORIGIN = "/checkmk-api";

export const TOPOLOGY_EDITOR_USER = "topology_editor";
export const TOPOLOGY_EDITOR_SECRET_PLACEHOLDER = "<TOPOLOGY_EDITOR_SECRET>";
export const TOPOLOGY_EDITOR_SECRET = TOPOLOGY_EDITOR_SECRET_PLACEHOLDER;

/** Pure predicate behind isTopologyEditingConfigured(), kept separate so it is directly testable. */
export function isSecretConfigured(value: string): boolean {
  return value !== TOPOLOGY_EDITOR_SECRET_PLACEHOLDER;
}

/**
 * D-04: edit-mode map writes (13-06/13-07) must stay disabled until an operator has run
 * `scripts/provision_topology_editor.py` and pasted its one-time secret output in here,
 * the same "still the placeholder" gate isCheckmkLinkConfigured() uses for CHECKMK_BASE_URL.
 */
export function isTopologyEditingConfigured(): boolean {
  return isSecretConfigured(TOPOLOGY_EDITOR_SECRET);
}
