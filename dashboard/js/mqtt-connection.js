// The single choke point for the dashboard's MQTT-over-WebSockets lifecycle.
//
// Every listener mqtt.js can emit is attached in this one module and
// nowhere else — render modules never attach their own listeners to the
// raw client (dashboard/js/state-store.js's `handleMessage()` is the only
// way a message reaches the rest of the page). This mirrors this
// codebase's existing "one choke point normalizes every failure" shape
// (scripts/mqtt_poller.py::_publish_json()/_livestatus_request()).
//
// mqtt.js's own `reconnectPeriod` option is a FIXED interval with no
// growth and no jitter (verified against the mqtt.js README, 2026-09-12,
// per 11-RESEARCH.md Pattern 3/Pitfall 1) — passing a bigger number only
// changes the fixed interval, it does not satisfy DASH-05's "jittered
// exponential backoff" requirement, and a fixed interval means every open
// dashboard tab would retry in lockstep after a shared broker restart.
// `reconnectPeriod: 0` disables the built-in retry entirely; this module
// drives every retry itself, from the `close` event, with the standard
// `min(max, base * 2**attempt) * jitter` formula.

var connection = (function () {
  var BASE_DELAY_MS = 1000;
  var MAX_DELAY_MS = 30000;

  var client = null;
  var attempt = 0;
  var reconnectTimer = null;
  var statusHandlers = [];

  var SUBSCRIBE_TOPICS = [
    'lan/devices/+/status',
    'lan/devices/+/history',
    'lan/devices/topology',
    'lan/events/recent',
    'lan/poller/status',
  ];

  function onStatus(handler) {
    statusHandlers.push(handler);
  }

  function reportStatus(phase, delayMs) {
    statusHandlers.forEach(function (handler) {
      handler({ phase: phase, delayMs: delayMs });
    });
  }

  function scheduleReconnect() {
    var growth = BASE_DELAY_MS * 2 ** attempt;
    var capped = Math.min(MAX_DELAY_MS, growth);
    var delay = capped * (0.5 + Math.random() * 0.5);
    attempt += 1;
    reportStatus('reconnecting', delay);
    reconnectTimer = setTimeout(function () {
      client.reconnect();
    }, delay);
  }

  function connect() {
    reportStatus('connecting');

    // D-02: the broker host is derived at runtime from the page's own
    // origin so the dashboard works unchanged from any LAN device —
    // nginx and mosquitto are published from the same host.
    var url = 'ws://' + location.hostname + ':' + WS_PORT;

    client = mqtt.connect(url, {
      username: WS_USERNAME,
      password: WS_PASSWORD,
      reconnectPeriod: 0, // disable mqtt.js's own fixed-interval retry — see header comment
      clean: true, // default; retained-message delivery on SUBACK is independent of clean-session
    });

    client.on('connect', function () {
      attempt = 0;
      clearTimeout(reconnectTimer);
      // Subscribing is what triggers the broker's retained-message replay
      // on SUBACK — no cache-warming request of any kind is needed or
      // permitted (11-RESEARCH.md Don't-Hand-Roll table).
      client.subscribe(SUBSCRIBE_TOPICS);
      reportStatus('connected');
    });

    client.on('close', scheduleReconnect);

    client.on('offline', function () {
      reportStatus('disconnected');
    });

    // Always attach an 'error' listener — an unhandled 'error' event can
    // abort the rest of page initialization and leave a blank page whose
    // only visible symptom is silence (11-RESEARCH.md Pitfall 3). Never
    // rethrow here.
    client.on('error', function (err) {
      console.error('MQTT error', err);
    });

    client.on('message', function (topic, payload) {
      store.handleMessage(topic, payload);
    });
  }

  function disconnect() {
    clearTimeout(reconnectTimer);
    if (client) {
      client.end(true);
    }
  }

  return {
    connect: connect,
    onStatus: onStatus,
    disconnect: disconnect,
  };
})();
