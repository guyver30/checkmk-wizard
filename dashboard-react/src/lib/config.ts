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
