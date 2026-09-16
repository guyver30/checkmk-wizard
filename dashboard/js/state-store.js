// In-memory store for every retained MQTT topic the dashboard consumes.
//
// Every topic published by scripts/mqtt_poller.py is already a complete
// snapshot, never a delta: publish_device_status() republishes a device's
// full status dict every cycle, publish_history()/publish_events() are
// handed the already-truncated bounded array in full, publish_topology()
// sends the whole device list, and publish_poller_status() sends the whole
// liveness object. Because the *contract* guarantees a full snapshot on
// every message, this store always REPLACES a slot and never appends to
// one — appending client-side would double-bound an already-bounded array
// and leak memory on a long-lived kiosk tab. See scripts/mqtt_poller.py for
// the authoritative topic/payload contract; it is not restated here.
//
// This module owns no DOM access and no `mqtt` reference. It receives
// `(topic, payloadBuffer)` from dashboard/js/mqtt-connection.js via
// `store.handleMessage()` and nothing else.
//
// Malformed-payload tolerance mirrors this codebase's own precedent for
// defensively parsing external/restored data
// (scripts/mqtt_poller.py::_normalise_restored_node()'s defensive
// `.get()`/`isinstance` checks) rather than trusting `JSON.parse()`'s
// output shape: a payload that fails to parse, or parses to the wrong
// shape, is dropped and the last-known-good value is kept — it must never
// throw out of the message handler and blank the page.

var store = (function () {
  var devices = new Map(); // hostname -> status payload (object)
  var history = new Map(); // hostname -> array of history entries
  var events = []; // array of event entries
  var topology = null; // { devices: [...], timestamp } or null
  var pollerStatus = null; // { status, since, last_poll, device_count } or null

  var subscribers = {
    device: [],
    topology: [],
    history: [],
    events: [],
    poller: [],
  };

  function subscribe(eventName, handler) {
    if (!subscribers[eventName]) {
      throw new Error("Unknown store event: " + eventName);
    }
    subscribers[eventName].push(handler);
  }

  function notify(eventName, arg) {
    subscribers[eventName].forEach(function (handler) {
      handler(arg);
    });
  }

  function isPlainObject(value) {
    return typeof value === "object" && value !== null && !Array.isArray(value);
  }

  // Returns { ok: true, value } on a well-formed, non-empty payload,
  // { ok: true, value: null } on MQTT's zero-length tombstone payload, or
  // { ok: false } on anything that fails to parse — the caller keeps
  // last-known-good in that case and must not throw.
  function parsePayload(payloadBuffer) {
    if (!payloadBuffer || payloadBuffer.length === 0) {
      return { ok: true, value: null };
    }
    try {
      return { ok: true, value: JSON.parse(payloadBuffer.toString()) };
    } catch (err) {
      return { ok: false };
    }
  }

  function handleDeviceStatus(id, payloadBuffer) {
    var parsed = parsePayload(payloadBuffer);
    if (!parsed.ok) {
      return; // malformed — ignore, keep last-known-good
    }
    if (parsed.value === null) {
      // Zero-length retained payload is MQTT's own tombstone semantic
      // (scripts/mqtt_poller.py::publish_tombstone) — remove the device
      // and its history entry.
      devices.delete(id);
      history.delete(id);
      notify("device", id);
      return;
    }
    if (!isPlainObject(parsed.value)) {
      return; // wrong shape — malformed, drop
    }
    devices.set(id, parsed.value);
    notify("device", id);
  }

  function handleDeviceHistory(id, payloadBuffer) {
    var parsed = parsePayload(payloadBuffer);
    if (!parsed.ok) {
      return;
    }
    if (parsed.value === null) {
      history.set(id, []);
      notify("history", id);
      return;
    }
    if (!Array.isArray(parsed.value)) {
      return;
    }
    history.set(id, parsed.value);
    notify("history", id);
  }

  function handleTopology(payloadBuffer) {
    var parsed = parsePayload(payloadBuffer);
    if (!parsed.ok || parsed.value === null || !isPlainObject(parsed.value)) {
      return;
    }
    topology = parsed.value;
    notify("topology");
  }

  function handleEvents(payloadBuffer) {
    var parsed = parsePayload(payloadBuffer);
    if (!parsed.ok) {
      return;
    }
    if (parsed.value === null) {
      events = [];
      notify("events");
      return;
    }
    if (!Array.isArray(parsed.value)) {
      return;
    }
    events = parsed.value;
    notify("events");
  }

  function handlePollerStatus(payloadBuffer) {
    var parsed = parsePayload(payloadBuffer);
    if (!parsed.ok || parsed.value === null || !isPlainObject(parsed.value)) {
      return;
    }
    pollerStatus = parsed.value;
    notify("poller");
  }

  // Routes one MQTT message into the store. Parses the topic by splitting
  // on "/" and matching segment positions rather than a single regex over
  // the whole string, because the device id segment (parts[2]) is
  // arbitrary text sourced from Checkmk host names.
  function handleMessage(topic, payloadBuffer) {
    var parts = topic.split("/");

    if (parts[1] === "devices" && parts[3] === "status") {
      handleDeviceStatus(parts[2], payloadBuffer);
    } else if (parts[1] === "devices" && parts[3] === "history") {
      handleDeviceHistory(parts[2], payloadBuffer);
    } else if (topic === "lan/devices/topology") {
      handleTopology(payloadBuffer);
    } else if (topic === "lan/events/recent") {
      handleEvents(payloadBuffer);
    } else if (topic === "lan/poller/status") {
      handlePollerStatus(payloadBuffer);
    }
  }

  function deviceIds() {
    return Array.from(devices.keys()).sort();
  }

  // Used only by the node verification harness — never called by page code.
  function reset() {
    devices.clear();
    history.clear();
    events = [];
    topology = null;
    pollerStatus = null;
    subscribers = { device: [], topology: [], history: [], events: [], poller: [] };
  }

  return {
    devices: devices,
    history: history,
    get events() {
      return events;
    },
    get topology() {
      return topology;
    },
    get pollerStatus() {
      return pollerStatus;
    },
    subscribe: subscribe,
    handleMessage: handleMessage,
    deviceIds: deviceIds,
    reset: reset,
  };
})();
