// Per-deployment configuration for the live dashboard.
//
// The dashboard has no server-side process and no build step (D-01/D-02/D-20,
// .planning/phases/11-live-dashboard/11-CONTEXT.md), so this classic script is the
// browser-side equivalent of a compose `environment:` block: one file an operator edits
// per deployment, loaded before every other dashboard script.
//
// WS_USERNAME/WS_PASSWORD are disposable default credentials, checked into the repo
// deliberately, to be rotated before exposing this dashboard beyond a trusted LAN — the
// same convention already used by deploy/mosquitto.passwd itself, cmkadmin/cmkadmin, and
// minioadmin/minioadmin. The grant behind them is read-only (`topic read lan/#` in
// deploy/mosquitto.acl), which bounds the exposure to reading the device list, never
// writing anything back to the broker.
//
// CHECKMK_BASE_URL must be edited per deployment: the browser cannot derive it, because
// the poller (scripts/mqtt_poller.py) reaches Checkmk over the container-internal name
// checkmk:5000, which no LAN browser can resolve (D-20).
//
// POLL_INTERVAL_SECONDS and HISTORY_MAX_ENTRIES mirror DEFAULT_POLL_INTERVAL_SECONDS and
// DEFAULT_HISTORY_MAX_ENTRIES in scripts/mqtt_poller.py and must be kept in step with it
// if the poller's own environment configuration changes.
//
// No broker host constant is defined here — D-02 requires it be derived at runtime from
// location.hostname, in the connection module that consumes this file.

const WS_PORT = 9002;
const WS_USERNAME = "wsreader";
const WS_PASSWORD = "wsreader";
const POLL_INTERVAL_SECONDS = 60;
const STALENESS_FACTOR = 3;
const HISTORY_MAX_ENTRIES = 20;
const CHECKMK_BASE_URL = "http://<HOST_IP>:8080";
const CHECKMK_SITE = "dmc";
