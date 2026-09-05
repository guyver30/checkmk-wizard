# Stack Research

**Domain:** Checkmk-to-MQTT bridge (Python poller) + static browser topology dashboard (vis-network + mqtt.js over Mosquitto WebSockets)
**Researched:** 2026-09-05
**Confidence:** HIGH

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `paho-mqtt` | **2.1.0** (latest on PyPI; requires Python >=3.7) | Python MQTT publisher client used by the `worker` container's poller | Eclipse Foundation's reference Python MQTT client — the de facto standard for a synchronous Python publisher. It's also what the project's own prototype scripts (`docs/src/mqtt_publisher_changes.py`, `docs/src/mqtt_notify.py`) already used (v1 API), so upgrading in place is lower-risk than switching client libraries. |
| `vis-network` | **10.1.2** (standalone UMD bundle, bundles `vis-data`) | Topology graph rendering in `index.html` | Purpose-built physics-based network/graph visualization library with a first-class `DataSet` incremental-update API — exactly what "merge, don't rebuild" streaming updates need. No build step required (single `<script>` tag). |
| `mqtt.js` | **5.15.2** (browser UMD bundle) | MQTT-over-WebSockets client in the static dashboard | The standard MQTT client for browsers — is what `paho-mqtt`'s own JS sibling (`paho-mqtt.js`) has effectively been superseded by in community usage; actively maintained, built-in exponential-style reconnect, works via a single `<script>` tag with no bundler. |
| Eclipse Mosquitto | **2.1.2** (current stable line; already in the compose stack) | MQTT broker with an added WebSockets listener | Already the chosen broker per `PROJECT.md`; Mosquitto 2.x has native `protocol websockets` listener support — no external bridge (e.g. `nginx` MQTT-WS proxying) needed. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Python standard library `json`, `time`/`threading`, `logging.handlers.RotatingFileHandler` | stdlib | Payload serialization, poll-loop timing, log rotation | Poller is a simple synchronous loop (Livestatus query → diff → publish → sleep) reusing the pattern already proven in `docs/src/mqtt_publisher_changes.py`; no new dependency needed for these. |
| `paho-mqtt`'s built-in `Client.loop_start()` | bundled | Runs the MQTT network loop (including automatic reconnect) on a background thread | Use this rather than `loop_forever()` because the poller's main thread needs to run its own Livestatus-poll `while True` loop — `loop_start()` frees the main thread for that while still keeping the MQTT connection alive/reconnecting in the background. |
| vis-network's `vis-data` `DataSet` (bundled in the standalone build) | 8.0.5 (bundled) | Incremental node/edge state container | `nodes.update()` / `edges.update()` upsert-by-id with a shallow merge — this is the mechanism for turning "message arrived on `lan/devices/{id}/status`" into a targeted graph mutation instead of `network.setData()` (which redraws/resets everything, including zoom/pan and physics layout). |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Browser DevTools / `mosquitto_sub -t '#' -v` | Manual verification of the MQTT topic contract during development | No test framework needed for the static dashboard per project's "no build step" constraint; `mosquitto_sub` (already ships with the `mosquitto` image/CLI tools) is sufficient to eyeball retained-message payloads while building the poller. |
| `pytest` + `pytest-asyncio` (already in `pyproject.toml`) | Unit tests for the poller's change-detection logic | Reuse the existing test stack; the poller's diffing logic (old-state vs new-state) is pure/synchronous and testable without a real broker — mock or stub `paho-mqtt`'s `Client.publish` rather than spinning up a real Mosquitto instance in unit tests. |

## Installation

```bash
# Python poller dependency (worker container / pyproject.toml)
uv add paho-mqtt

# Dashboard: no npm/build step — pin exact versions via CDN <script> tags
# vis-network (standalone bundle includes vis-data's DataSet):
# https://cdnjs.cloudflare.com/ajax/libs/vis-network/10.1.2/standalone/umd/vis-network.min.js
# mqtt.js:
# https://cdn.jsdelivr.net/npm/mqtt@5.15.2/dist/mqtt.min.js
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|--------------------------|
| `paho-mqtt` (sync, `Client.loop_start()`) | `aiomqtt` / `gmqtt` (asyncio-native) | If the poller were rewritten around `asyncio` (matching the wizard's `httpx`/`asyncssh` async style) — but `livestatus.py`'s Livestatus client is a blocking raw socket, so the poller is inherently synchronous already; introducing asyncio here would add complexity without a matching async Livestatus client to pair it with. |
| Mosquitto's native `protocol websockets` listener | An `nginx` WebSocket reverse-proxy in front of a plain-TCP Mosquitto listener | Only needed if you require a single public HTTPS port (443) fronting both the dashboard and MQTT-WS via `wss://` path-based routing — the project's own nginx container could do this, but for a LAN-only stack, exposing Mosquitto's WS listener directly on its own port is simpler and has one fewer moving part to debug. |
| `vis-network` | Cytoscape.js, D3.js force-directed graphs | Cytoscape/D3 make sense if you need more exotic layout algorithms or graph analysis (centrality, clustering) — vis-network's simpler API and built-in physics engine is the better fit for "draw hosts + parent links and keep it updated," which is all this dashboard needs. |
| `mqtt.js` | `paho-mqtt.js` (Eclipse's JS client) | Historically the "official" pairing with `paho-mqtt` (Python), but `paho-mqtt.js` has seen far less recent maintenance/community adoption for browser use than `mqtt.js`; `mqtt.js` is what current tutorials (EMQX, HiveMQ) recommend for new browser MQTT work. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|--------------|
| `mqtt.Client()` with no `callback_api_version` argument, and `on_connect(client, userdata, flags, rc)` 4-arg callbacks (the pattern in `docs/src/mqtt_publisher_changes.py`/`mqtt_notify.py`) | This is the paho-mqtt **v1** callback API. Since paho-mqtt 2.0, `Client()` requires an explicit `CallbackAPIVersion`, and v1 callback signatures are deprecated (still work under `CallbackAPIVersion.VERSION1` but emit no forward-compat benefits and use a raw integer `rc`). Directly reusing the prototype scripts' code as-is will run under a compatibility shim, not the current API. | `mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)` with the VERSION2 callback signature: `on_connect(client, userdata, flags, reason_code, properties)` — `reason_code` is a `ReasonCode` object (compares to `0`/strings cleanly) rather than a bare int. |
| `network.setData({nodes, edges})` on every incoming MQTT message | Fully re-renders the graph: resets zoom/pan/selection and restarts the physics simulation on every update — directly conflicts with the project's explicit "merge, don't rebuild" requirement and will look like the graph "jumps"/flickers on every poll cycle. | `nodes.update([...])` / `edges.update([...])` on the existing `DataSet` instances — upserts by `id`, shallow-merges changed fields, preserves camera/physics state. |
| A second, separate MQTT broker or bridge (e.g. running a Node.js `aedes` broker) just to get WebSockets support | Unnecessary — Mosquitto 2.x has native WS support (`protocol websockets` on a listener), and Mosquitto is already the chosen broker in the compose stack per `PROJECT.md`. | A second `listener` block in the existing `mosquitto.conf` with `protocol websockets`. |
| Loading vis-network's core `vis-network.min.js` (non-standalone) without also loading `vis-data` separately | The non-standalone `dist/vis-network.min.js` build expects `vis-data`'s `DataSet`/`DataView` to be provided separately; forgetting the second script tag causes a silent `vis.DataSet is not a constructor` failure. | The **standalone** UMD build (`standalone/umd/vis-network.min.js`), which bundles `vis-data` — one script tag, no missing-dependency footgun, matches the "no build step" constraint. |

## Stack Patterns by Variant

**If the poller needs TLS between `worker` and `mosquitto` (not required for a LAN-only compose network, but worth flagging):**
- Use `client.tls_set()` (paho-mqtt) and `wss://` + `certfile`/`keyfile` on the Mosquitto listener
- Because plain `mqtt://`/`ws://` sends credentials and payloads in cleartext — acceptable for a container-internal bridge network but not if the dashboard is ever exposed beyond the LAN

**If retained-message payload size becomes a concern (e.g. `lan/devices/{id}/history` growing unbounded):**
- Enforce the "bounded" constraint (already scoped in `PROJECT.md`) in the *poller*, not via Mosquitto's `message_size_limit`
- Because Mosquitto has no built-in "keep last N" semantics for retained messages — the poller must truncate the history list itself before publishing, exactly as the existing prototype's `MAX_HISTORY = 10` pattern already does

**If the dashboard ever needs offline/cached state before the first MQTT message arrives:**
- Rely on Mosquitto's **retained messages** (`retain=True` on every publish, per the topic contract in `PROJECT.md`) plus `mqtt.js`'s default behavior of receiving retained messages immediately on `subscribe()`
- Because this avoids needing any server-side state/cache — a freshly-loaded browser tab gets the full current topology/status the instant it subscribes, with no backend round-trip

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|------------------|-------|
| `paho-mqtt` 2.1.0 | Python 3.11 (project's pinned version) | No compatibility issues; `paho-mqtt` only requires Python >=3.7. |
| `paho-mqtt` 2.1.0 client | Mosquitto 2.1.2 broker | Both support MQTT v3.1.1 and v5; paho-mqtt defaults to MQTT v3.1.1 unless `protocol=mqtt.MQTTv5` is passed to `Client()` — no v5-specific features are needed for this project's topic/retain-based contract, so the default is fine. |
| `vis-network` 10.1.2 | `vis-data` (bundled, 8.0.5) | Only relevant if loading the non-standalone build separately; the standalone bundle keeps these in lockstep automatically. |
| `mqtt.js` 5.15.2 browser bundle | Mosquitto 2.1.2's `websockets` listener | mqtt.js 5.x uses the browser's native `WebSocket` API under the hood for `ws://`/`wss://` URLs — no polyfill needed on any evergreen browser. |
| Mosquitto `protocol websockets` listener | Legacy (non-`http_api`) WS mode | Mosquitto's docs note plain "legacy websockets" support (as opposed to newer `http_api` protocol mode) has a reduced feature set (e.g., subprotocol negotiation quirks) — irrelevant here since mqtt.js speaks the standard `mqtt` WebSocket subprotocol Mosquitto expects by default. |

## Sources

- Eclipse Paho — [Migrations: Callback API Version 2](https://eclipse.dev/paho/files/paho.mqtt.python/html/migrations.html) — HIGH confidence, official migration guide; verified `Client(CallbackAPIVersion.VERSION2)` constructor and `on_connect(client, userdata, flags, reason_code, properties)` signature
- PyPI — [paho-mqtt project page](https://pypi.org/project/paho-mqtt/) and JSON API (`pypi.org/pypi/paho-mqtt/json`) — HIGH confidence, confirmed current release **2.1.0**, `requires-python >=3.7`
- Eclipse Mosquitto — [official download page](https://mosquitto.org/download/) — HIGH confidence, confirmed current stable release **2.1.2**
- Eclipse Mosquitto — [mosquitto.conf(5) man page](https://mosquitto.org/man/mosquitto-conf-5.html) — HIGH confidence, official docs; confirmed `listener <port>` + `protocol websockets` syntax, `http_dir` option, `allow_anonymous`/`listener_allow_anonymous`
- Docker Hub — `eclipse-mosquitto` [tags listing](https://hub.docker.com/_/eclipse-mosquitto) (via API) — HIGH confidence, confirmed `2.1.2` and `2` tags are current as of the compose stack's likely base image
- jsdelivr package data API (`data.jsdelivr.com/v1/packages/npm/vis-network`, `.../mqtt`, `.../vis-data`) — HIGH confidence, machine-readable npm "latest" dist-tags; confirmed **vis-network 10.1.2**, **mqtt.js 5.15.2**, **vis-data 8.0.5**
- cdnjs — [vis-network library page](https://cdnjs.com/libraries/vis-network) — HIGH confidence, confirmed standalone UMD bundle path and that it includes `vis-data`
- vis-data official docs — [DataSet API](https://visjs.github.io/vis-data/data/dataset.html) — HIGH confidence, confirmed `update()` upsert/shallow-merge semantics vs. full replacement
- vis-network official examples — [dynamicData.html source](https://raw.githubusercontent.com/visjs/vis-network/master/examples/network/data/dynamicData.html) — HIGH confidence, confirmed `nodes.add()`/`nodes.update()`/`nodes.remove()` usage pattern
- MQTT.js official README — [github.com/mqttjs/MQTT.js](https://raw.githubusercontent.com/mqttjs/MQTT.js/main/README.md) — HIGH confidence, confirmed browser CDN usage (`unpkg.com/mqtt/dist/mqtt.min.js`), `ws://`/`wss://`-only browser constraint, `reconnectPeriod` (default 1000ms)/`reconnectOnConnackError`/`connectTimeout` (default 30000ms) options, and `connect`/`reconnect`/`offline`/`close`/`error` events for connection-status UI
- Project files — `docs/src/mqtt_publisher_changes.py`, `docs/src/mqtt_notify.py` (read directly) — HIGH confidence for identifying the prototype scripts' outdated v1 paho-mqtt callback pattern that must not be copied forward as-is

---
*Stack research for: Checkmk-to-MQTT bridge + live network-topology dashboard*
*Researched: 2026-09-05*
