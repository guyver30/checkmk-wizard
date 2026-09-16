// Staleness derivation for a single device and for the poller's own liveness signal.
//
// D-12: the 3x-poll-interval factor (STALENESS_FACTOR, config.js) is deliberately wider
// than Checkmk's own default staleness factor (1.5x). Checkmk's own checks are scheduled
// locally on the Checkmk host; this dashboard's data instead traverses one extra
// Livestatus query, an MQTT publish, a broker hop and a browser tab, so a single fully
// missed poll cycle would already exceed 1.5x and mark the whole fleet stale. 3x absorbs
// exactly one fully missed cycle before anything is flagged.
//
// D-17: prefer Checkmk's own authoritative `staleness` value (Livestatus `hosts.staleness`,
// see scripts/mqtt_poller.py OPTIONAL_HOST_COLUMNS) when the poller published one, and fall
// back to comparing the payload's own `timestamp` age against the same factor otherwise
// (a payload from a poller predating this field, or a site where the column is absent).
// Wave-1's live probe (plan 11-01) confirmed `staleness` IS present on the target site, but
// that only proves the column exists -- it does not guarantee every row is non-null, so the
// timestamp-age fallback below remains a required, exercised code path, not dead code.
//
// No DOM access, no broker connection, no browser storage, no network calls -- pure
// functions only.

function isDeviceStale(devicePayload, nowMs = Date.now()) {
  if (!devicePayload || typeof devicePayload !== "object") {
    return true; // unknown/malformed payload is not fresh
  }
  if (devicePayload.staleness !== null && devicePayload.staleness !== undefined) {
    // Checkmk expresses staleness in check-interval multiples already -- the same shape
    // as its own UI setting (D-12) -- so compare directly against the factor.
    return devicePayload.staleness >= STALENESS_FACTOR;
  }
  const parsed = Date.parse(devicePayload.timestamp);
  if (Number.isNaN(parsed)) {
    return true; // missing/unparseable timestamp: unknown age is not fresh
  }
  const ageSeconds = (nowMs - parsed) / 1000;
  return ageSeconds >= STALENESS_FACTOR * POLL_INTERVAL_SECONDS;
}

function isPollerStale(pollerStatusPayload, nowMs = Date.now()) {
  // D-13/D-14: an absent payload or an explicit "offline" status means the poller's LWT
  // fired -- treat that as stale immediately, with no age check needed.
  if (!pollerStatusPayload || typeof pollerStatusPayload !== "object") {
    return true;
  }
  if (pollerStatusPayload.status === "offline") {
    return true;
  }
  if (!pollerStatusPayload.last_poll) {
    return false; // a birth message: the poller is up but has not completed a cycle yet
  }
  const parsed = Date.parse(pollerStatusPayload.last_poll);
  if (Number.isNaN(parsed)) {
    return true;
  }
  const ageSeconds = (nowMs - parsed) / 1000;
  return ageSeconds >= STALENESS_FACTOR * POLL_INTERVAL_SECONDS;
}

function pollerOfflineSince(pollerStatusPayload, fallbackRaw = null) {
  // D-14's locked banner string ("Poller offline since HH:MM...") needs a Date to format.
  // `last_poll` is the more precise anchor (the last cycle that actually completed); `since`
  // (the birth-message timestamp) is the fallback when no cycle has completed at all.
  //
  // `fallbackRaw` (state-store.js's lastKnownPollerTimestamp) covers a third case: the
  // poller's MQTT will (scripts/mqtt_poller.py) is the fixed payload `{"status": "offline"}`
  // with neither field, because a will is captured at connect time and any timestamp in it
  // would be the time the poller STARTED, not the time it died. Without this fallback, the
  // retained "offline" payload replacing a dead poller's last heartbeat has no timestamp of
  // its own and this function returns null -- discarding a perfectly good last-known-good
  // time the dashboard already has. Only used when the current payload has neither field.
  if (!pollerStatusPayload || typeof pollerStatusPayload !== "object") {
    return null;
  }
  const raw = pollerStatusPayload.last_poll || pollerStatusPayload.since || fallbackRaw;
  if (!raw) {
    return null;
  }
  const parsed = Date.parse(raw);
  return Number.isNaN(parsed) ? null : new Date(parsed);
}
