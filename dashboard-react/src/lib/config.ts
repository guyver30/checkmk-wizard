// Constants and fallback defaults for the live dashboard.
//
// This file holds only true constants and the defaults runtimeConfig.ts falls back to --
// no per-machine value lives here, and it must NOT be edited per deployment. The Checkmk
// site name and the read-only MQTT WebSocket credentials come from `/config.json` at
// container start instead (see src/lib/runtimeConfig.ts, deploy/dashboard-nginx.conf,
// deploy/.env).
//
// No broker host constant is defined here — the broker host is deliberately NOT
// configured in this file. It is derived at runtime from `location.hostname` (D-02) by
// whichever module owns the MQTT connection, because the poller (scripts/mqtt_poller.py)
// reaches Checkmk over the container-internal name checkmk:5000, which no LAN browser can
// resolve.
//
// DEFAULT_WS_USERNAME/DEFAULT_WS_PASSWORD are the disposable read-only credentials used
// whenever `/config.json` is unreachable or omits them (vite dev/preview, vitest) -- the
// same convention already used by deploy/mosquitto.passwd itself, cmkadmin/cmkadmin, and
// minioadmin/minioadmin. The grant behind them is read-only (`topic read lan/#` in
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
// prefix to Checkmk instead -- see vite.config.ts's `/checkmk-api` proxy entries.
//
// The dashboard's write-capable `topology_editor` Checkmk credential (formerly configured here
// as TOPOLOGY_EDITOR_USER/TOPOLOGY_EDITOR_SECRET, D-04) no longer lives in this file or the
// browser bundle at all -- see checkmkWrite.ts's module header and deploy/dashboard-nginx.conf
// (amended 2026-09-30, quick 260930-hpy).
//
// Amended 2026-09-30 (quick 260930-ixs): the human-facing Checkmk base URL constant, its
// unedited-placeholder sentinel, the link-configured predicate, and the build-time WS/site
// constants they lived alongside are all removed -- the site name and WS credentials are
// runtime values now (see runtimeConfig.ts), not build-time ones, so this file no longer
// carries a placeholder that an operator could forget to edit.

export const WS_PORT = 9002;
export const DEFAULT_CHECKMK_SITE = "dmc";
export const DEFAULT_WS_USERNAME = "wsreader";
export const DEFAULT_WS_PASSWORD = "wsreader";
export const POLL_INTERVAL_SECONDS = 15;
export const STALENESS_FACTOR = 3;
export const HISTORY_MAX_ENTRIES = 20;

export const CHECKMK_REST_ORIGIN = "/checkmk-api";
