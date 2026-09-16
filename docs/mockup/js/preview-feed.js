// PREVIEW ONLY -- stands in for dashboard/js/mqtt-connection.js.
//
// Exposes the same global `connection` surface (connect/onStatus/disconnect)
// but feeds synthetic, contract-shaped retained messages into
// store.handleMessage() instead of opening a real MQTT-over-WebSockets
// session. Every payload below matches scripts/mqtt_poller.py exactly:
//   lan/devices/{id}/status   publish_device_status()
//   lan/devices/{id}/history  publish_history()
//   lan/devices/topology      publish_topology()
//   lan/events/recent         publish_events()
//   lan/poller/status         publish_poller_status()
// store.parsePayload() calls .toString() and reads .length, so a plain JS
// string stands in for the Buffer a real broker hands over.

var PREVIEW = (function () {
  var NOW = Date.now();

  function iso(offsetSeconds) {
    return new Date(NOW - offsetSeconds * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");
  }

  // A plausible small-site fleet: six folders, every device_type in the
  // locked set, and every state the UI can render (OK / WARN / CRIT /
  // UNKNOWN / DOWN), plus downtime, acknowledged, stale and an
  // UNREACHABLE-vs-DOWN pair so host_state_raw is actually exercised.
  var FLEET = [
    ["lift-a-ctrl-01", "OK",      "GroupController", "Tower A / Machine Room", "Lift A Controller",      0.6, "UP",     false, false, 0],
    ["lift-a-cop-03",  "OK",      "Multimedia",      "Tower A / Car 3",        "Lift A Car 3 Display",   0.8, "UP",     false, false, 0],
    ["lift-a-elink",   "WARN",    "E-link",          "Tower A / Machine Room", "Lift A E-link Gateway",  1.1, "UP",     false, false, 0],
    ["lift-b-ctrl-01", "OK",      "GroupController", "Tower B / Machine Room", "Lift B Controller",      0.5, "UP",     false, false, 0],
    ["lift-b-cop-01",  "CRIT",    "Multimedia",      "Tower B / Car 1",        "Lift B Car 1 Display",   0.9, "UP",     false, false, 0],
    ["lift-b-elink",   "OK",      "E-link",          "Tower B / Machine Room", "Lift B E-link Gateway",  0.7, "UP",     false, false, 0],
    ["acs-turnstile-1","OK",      "ACS",             "Lobby / North",          "North Turnstile Reader", 0.4, "UP",     false, false, 0],
    ["acs-turnstile-2","DOWN",    "ACS",             "Lobby / North",          "South Turnstile Reader", 1.0, "DOWN",   false, false, 0],
    ["acs-door-svc",   "OK",      "ACS",             "Lobby / North",          "Door Service Panel",     0.6, "UP",     true,  false, 0],
    ["sw-core-01",     "OK",      "NetworkDevice",   "Comms Room",             "Core Switch 01",         0.3, "UP",     false, false, 0],
    ["sw-edge-tower-b","DOWN",    "NetworkDevice",   "Comms Room",             "Edge Switch Tower B",    1.2, "UNREACH",false, true,  0],
    ["rtr-wan-01",     "OK",      "NetworkDevice",   "Comms Room",             "WAN Router",             0.5, "UP",     false, false, 0],
    ["kiosk-lobby-01", "UNKNOWN", "other",           "Lobby / South",          "",                       2.1, "UP",     false, false, 0],
    ["sig-lobby-02",   "OK",      "Multimedia",      "Lobby / South",          "Lobby Signage 02",       7.4, "UP",     false, false, 240]
  ];

  function statusPayload(row) {
    return JSON.stringify({
      id: row[0],
      state: row[1],
      in_downtime: row[7],
      acknowledged: row[8],
      device_type: row[2],
      folder: row[3],
      alias: row[4],
      staleness: row[5],
      host_state_raw: row[6],
      timestamp: iso(row[9])
    });
  }

  // 20 entries so the fixed-width strip is fully populated for most hosts;
  // two hosts get short histories so the placeholder slots are visible too.
  function historyPayload(row) {
    var states = ["OK", "OK", "OK", "WARN", "OK", "OK", "CRIT", "WARN", "OK", "OK"];
    var count = row[0] === "kiosk-lobby-01" ? 3 : (row[0] === "sig-lobby-02" ? 11 : 20);
    var entries = [];
    for (var i = count - 1; i >= 0; i--) {
      var to = i === 0 ? row[1] : states[i % states.length];
      var from = i === count - 1 ? null : states[(i + 1) % states.length];
      entries.push({ timestamp: iso(i * 600 + 45), from: from, to: to });
    }
    return JSON.stringify(entries);
  }

  // Checkmk's `parents` attribute, faked. On the real site it is UNSET, which
  // is precisely why the topology map was deferred to Phase 13 -- an
  // auto-built map would render as disconnected dots. Phase 13's first job is
  // teaching the wizard to populate this over REST. Wiring it here lets the
  // map's LAYOUT be judged now without waiting for that.
  //
  // Shaped like a small site network: one WAN router, a core switch beneath
  // it, an edge switch for Tower B, and a redundant core<->edge link. Every
  // other device hangs off whichever switch serves its location.
  var PARENTS = {
    "rtr-wan-01": [],
    "sw-core-01": ["rtr-wan-01"],
    "sw-edge-tower-b": ["sw-core-01", "rtr-wan-01"],
    "lift-a-ctrl-01": ["sw-core-01"],
    "lift-a-cop-03": ["sw-core-01"],
    "lift-a-elink": ["sw-core-01"],
    "acs-turnstile-1": ["sw-core-01"],
    "acs-turnstile-2": ["sw-core-01"],
    "acs-door-svc": ["sw-core-01"],
    "lift-b-ctrl-01": ["sw-edge-tower-b"],
    "lift-b-cop-01": ["sw-edge-tower-b"],
    "lift-b-elink": ["sw-edge-tower-b"],
    "kiosk-lobby-01": ["sw-edge-tower-b"],
    "sig-lobby-02": ["sw-edge-tower-b"]
  };

  function topologyPayload() {
    return JSON.stringify({
      devices: FLEET.map(function (row) {
        return {
          id: row[0],
          parents: PARENTS[row[0]] || [],
          device_type: row[2],
          folder: row[3],
          alias: row[4]
        };
      }),
      timestamp: iso(0)
    });
  }

  function eventsPayload() {
    return JSON.stringify([
      { timestamp: iso(2210), device_id: "sig-lobby-02",    event: "state_change", from: "OK",   to: "WARN" },
      { timestamp: iso(1880), device_id: "sig-lobby-02",    event: "state_change", from: "WARN", to: "OK" },
      { timestamp: iso(1495), device_id: "lift-a-elink",    event: "state_change", from: "OK",   to: "WARN" },
      { timestamp: iso(1130), device_id: "kiosk-lobby-01",  event: "added",        from: null,   to: "UNKNOWN" },
      { timestamp: iso(905),  device_id: "sw-edge-tower-b", event: "state_change", from: "OK",   to: "DOWN" },
      { timestamp: iso(760),  device_id: "acs-turnstile-2", event: "state_change", from: "OK",   to: "DOWN" },
      { timestamp: iso(415),  device_id: "lift-b-cop-01",   event: "state_change", from: "WARN", to: "CRIT" },
      { timestamp: iso(120),  device_id: "lift-a-cop-03",   event: "state_change", from: "WARN", to: "OK" }
    ]);
    // NOTE: chronological, oldest first. That is the poller's own contract --
    // mqtt_poller.py builds this with `state.events + events_this_cycle`, so
    // the newest entry is LAST. Both render paths reverse for display. An
    // earlier version of this file reversed here too, which cancelled that out
    // and showed the oldest event on top.
  }

  function pollerPayload(online) {
    if (!online) {
      return JSON.stringify({ status: "offline" });
    }
    return JSON.stringify({
      status: "online",
      since: iso(86400 * 3),
      last_poll: iso(12),
      device_count: FLEET.length
    });
  }

  function feedAll(pollerOnline) {
    store.handleMessage("lan/devices/topology", topologyPayload());
    FLEET.forEach(function (row) {
      store.handleMessage("lan/devices/" + row[0] + "/status", statusPayload(row));
      store.handleMessage("lan/devices/" + row[0] + "/history", historyPayload(row));
    });
    store.handleMessage("lan/events/recent", eventsPayload());
    store.handleMessage("lan/poller/status", pollerPayload(pollerOnline));
  }

  return {
    fleet: FLEET,
    feedAll: feedAll,
    firstHost: FLEET[0][0],
    setPoller: function (online) {
      store.handleMessage("lan/poller/status", pollerPayload(online));
    },
    setTagGroupMissing: function (missing) {
      // D-16: device_type "unknown" is what raises the tag-group banner.
      var row = FLEET[12].slice();
      row[2] = missing ? "unknown" : "other";
      store.handleMessage("lan/devices/" + row[0] + "/status", statusPayload(row));
    }
  };
})();

// Same public surface as the real mqtt-connection.js.
var connection = (function () {
  var statusHandlers = [];

  function emit(status, detail) {
    statusHandlers.forEach(function (handler) {
      handler(status, detail);
    });
  }

  return {
    connect: function () {
      emit("connecting");
      // Retained messages arrive on SUBACK with no round trip (RESEARCH.md
      // Pattern 1), so the fleet is present the moment we report connected.
      setTimeout(function () {
        PREVIEW.feedAll(true);
        emit("connected");
      }, 260);
    },
    onStatus: function (handler) {
      statusHandlers.push(handler);
    },
    disconnect: function () {
      emit("disconnected");
    }
  };
})();
