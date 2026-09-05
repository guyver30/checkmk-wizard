# Architecture Research

**Domain:** External-system poller → MQTT broker (retained-message state store) → static browser dashboard, inside an existing rootless-Podman-Compose stack
**Researched:** 2026-09-05
**Confidence:** HIGH (paho-mqtt reconnect API, Mosquitto multi-listener config, MQTT retain semantics — verified against Context7/official sources) / MEDIUM (browser MQTT.js reconnect defaults, some checkpoint-file edge-case tradeoffs — reasoned from verified primitives, not independently load-tested)

## Standard Architecture

### System Overview

```
┌───────────────────────────────────────────────────────────────────────┐
│                     Podman bridge network: cmk_net                    │
│                                                                         │
│  ┌────────────┐        Livestatus/TCP        ┌────────────────────┐   │
│  │  checkmk   │◄──────────(read-only,─────────┤  worker container  │   │
│  │ container  │           port 6557)          │  ┌───────────────┐ │   │
│  │ (OMD site) │                                │  │ checkmk-wizard│ │   │
│  └────────────┘                                │  │  (existing)   │ │   │
│                                                 │  ├───────────────┤ │   │
│                                                 │  │ mqtt_poller.py│ │   │
│                                                 │  │  (NEW)        │ │   │
│                                                 │  └───────┬───────┘ │   │
│                                                 └──────────┼─────────┘   │
│                                                             │ publish     │
│                                                             │ (retained)  │
│                                                    ▼                     │
│                                          ┌──────────────────────┐        │
│                                          │  mosquitto container │        │
│                                          │  listener 1883 (TCP) │        │
│                                          │  listener 9001 (WS)  │◄───┐   │
│                                          │  persistence: on     │    │   │
│                                          └──────────────────────┘    │   │
│                                                                       │   │
│  ┌────────────────────┐                                              │   │
│  │  dashboard (nginx)  │  static files only, no backend, no proxy    │   │
│  │  serves index/      │                                             │   │
│  │  devices/details    │                                             │   │
│  │  .html + JS/CSS     │                                             │   │
│  └──────────┬──────────┘                                             │   │
│             │ HTTP :80 → published to LAN                            │   │
└─────────────┼─────────────────────────────────────────────────────────┼──┘
              │                                                          │
              ▼ browser loads page                                      │
      ┌───────────────┐   MQTT-over-WebSocket, port 9001 (published) ───┘
      │  LAN browser  │───────────────────────────────────────────────────►
      │  (mqtt.js)    │◄─── subscribe lan/devices/#, lan/events/recent ────
      └───────────────┘
```

Two independent network hops matter here: (1) the poller talks to `mosquitto:1883` and `checkmk:6557` **internally**, never publishing those ports to the LAN; (2) the browser talks to `mosquitto:9001` (WebSockets) **directly** over a published port — it does not go through the `dashboard` nginx container at all except to fetch the initial static HTML/JS/CSS. This mirrors how `mosquitto:1883` is already published directly to the LAN today (per the existing `compose.yaml`), so it's consistent with the stack's existing trust model rather than introducing a new one.

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|-------------------------|
| `mqtt_poller.py` (new, runs in `worker`) | Poll Livestatus on an interval, diff against last-known state, publish per-device/topology/history/events to MQTT with retain flags | Single-file async or sync loop using stdlib `socket` (Livestatus, one-shot connect-query-close per cycle) + `paho-mqtt` (persistent connection via `loop_start()`) |
| `mosquitto` broker | Durable retained-message store; two listeners (raw TCP for internal publishers, WebSockets for browser subscribers) | `eclipse-mosquitto:2` image, `mosquitto.conf` with two `listener` blocks, `persistence true` |
| `dashboard` (new nginx container) | Serve static HTML/CSS/JS with zero backend logic | `nginx:alpine`, read-only bind mount of a `dashboard/` directory to `/usr/share/nginx/html` |
| Browser dashboard JS (`mqtt.js`) | Connect to broker over WS, subscribe to wildcard topics, render/merge into DOM, show connection-health indicator | `mqtt.js` `connect('ws://<host>:9001')` with built-in auto-reconnect |
| Checkmk (`checkmk` container) | Source of truth for host/service state — untouched by this milestone except the new host-tag group (via REST, from the existing wizard, not the poller) | Livestatus TCP port 6557, already enabled per `docs/Podman setup...md` §5 |

## Recommended Project Structure

```
docs/src/                        # existing prototypes retained as reference only
├── mqtt_publisher_changes.py    # DO NOT reuse verbatim — see Anti-Patterns
└── mqtt_notify.py

src/checkmk_wizard/
├── livestatus.py                 # existing — extend, don't fork: add the
│                                  # richer Livestatus query used by the
│                                  # poller here so both the wizard's health
│                                  # check and the poller share one client
├── mqtt_poller/                  # NEW — package, not a single loose script,
│   │                              # since it now has real internal structure
│   │                              # (unlike wizard.py's single-file style,
│   │                              # this is a long-running daemon, not a
│   │                              # phase-driven CLI — different lifecycle
│   │                              # justifies a different shape)
│   ├── __main__.py                # entry point: `uv run python -m
│   │                              # checkmk_wizard.mqtt_poller`
│   ├── poller.py                  # poll loop, Livestatus query, diffing
│   ├── mqtt_client.py             # paho-mqtt wrapper: connect/reconnect/
│   │                              # LWT/publish-with-retry, isolated so
│   │                              # poller.py has no paho imports directly
│   ├── topics.py                  # topic-name builders + payload schemas
│   │                              # in one place (single source of truth
│   │                              # for the contract the dashboard reads)
│   └── state.py                   # checkpoint load/save (atomic write)
└── ... (existing modules unchanged)

dashboard/                        # NEW — static site, no build step
├── index.html                    # topology map (vis-network) + stats strip
├── devices.html                  # sortable device table + recent-events
├── details.html                  # per-device drill-down + history strip
├── css/dashboard.css
└── js/
    ├── mqtt-connection.js         # connect/reconnect/backoff, one shared
    │                              # module all 3 pages import
    └── state-store.js             # in-memory device-state map, merge logic
```

### Structure Rationale

- **`mqtt_poller/` as its own package, not folded into `wizard.py`:** the wizard is a one-shot phase pipeline (`asyncio.run(run())` then exit); the poller is a long-running daemon with its own restart/reconnect lifecycle and no interactive prompts. Forcing it into `wizard.py`'s phase-orchestrator shape would fight both designs. Keeping it a sibling package under `src/checkmk_wizard/` (rather than a separate top-level `docs/src/`-style loose script) keeps it inside the `uv`-managed project, testable with the same `pytest`/mock conventions as the rest of the codebase.
- **`mqtt_client.py` isolated from `poller.py`:** the existing codebase's own convention (`api.py`, `site.py`, `remote.py`, `scanner.py`, `livestatus.py` never import each other) extends naturally here — the poll/diff logic shouldn't need to know `paho`'s callback-based API, and the MQTT wrapper shouldn't need to know what a "device" is.
- **`topics.py` as the one file defining every topic string and payload shape:** the dashboard is a separate, un-typed JS codebase with no shared import boundary with Python — a single Python module that documents (in one place, with docstrings) exactly what topics exist and what each payload contains is the closest thing to a shared contract you can get across that language boundary. Point the dashboard's own `js/` comments at this file's docstrings rather than duplicating the description in two places.
- **`dashboard/` as a sibling top-level directory, not under `docs/`:** it's shipped, deployed content (bind-mounted into the new `dashboard` container), not documentation.

## Architectural Patterns

### Pattern 1: Retained-message-per-entity (not full-blob retained snapshot)

**What:** One retained MQTT message per device (`lan/devices/{id}/status`) instead of one giant retained JSON array of every device, as the two prototype scripts do (`checkmk/services/all` retained everything).
**When to use:** Whenever a browser client needs "give me the full current state on subscribe" without a backend query, and the entity count is in the tens-to-low-thousands (broker-side retained-message storage cost is per-topic, trivial at LAN scale).
**Trade-offs:** Subscribers must subscribe to a wildcard (`lan/devices/+/status`) and assemble state from N separate retained deliveries instead of one parse — more assembly code in the browser, but each individual update after startup is O(1) instead of O(n) (you republish/re-parse one device, not the whole fleet), which directly enables the "merge incoming updates, don't re-render from scratch" dashboard requirement.

**Example:**
```python
# topics.py
def device_status_topic(device_id: str) -> str:
    return f"lan/devices/{device_id}/status"

# poller.py — every cycle, every known device, regardless of change:
client.publish(device_status_topic(dev.id), json.dumps(dev.status_payload()),
                qos=1, retain=True)
```
```javascript
// state-store.js — browser side
client.subscribe('lan/devices/+/status');
client.on('message', (topic, payload) => {
  const id = topic.split('/')[2];
  deviceState.set(id, JSON.parse(payload));   // merge, not replace
  renderDevice(id);                            // update one row/node, not the whole table
});
```

### Pattern 2: Broker-persisted retain as the state-recovery mechanism (not a durable/persistent MQTT session)

**What:** Mosquitto's `persistence true` (already configured) writes retained messages to disk, so both a new subscriber *and* a broker restart get the last-known-good value with zero application-level replay logic. This is a different mechanism from MQTT persistent sessions (`clean_session=False` + queued QoS messages), which exist to guarantee delivery of missed *events* to a specific returning client — not to answer "what is the current state."
**When to use:** Any time the requirement is "new client gets current snapshot," not "no client-specific message may ever be missed." This project's dashboard only needs the former.
**Trade-offs:** A persistent session would still leave the "what if the client was never subscribed before" case unsolved (queued messages are per existing subscription, retained messages are not) — so for this dashboard's actual requirement, retain is strictly the right tool, and reaching for persistent sessions/QoS-2 queuing here would be solving the wrong problem.

### Pattern 3: Poller connection resilience — decouple the poll cadence from the MQTT connection lifecycle

**What:** Use `paho.mqtt.client.Client.connect_async()` + `loop_start()` once at process startup, with `reconnect_delay_set(min_delay=1, max_delay=60)`. This starts a background thread that owns connect/reconnect entirely; the poll loop (a separate `while True: sleep(interval)` timer) just calls `client.publish(...)` each cycle and never manages sockets itself.
**When to use:** Any long-running publisher where "how often do I gather new data" and "how do I stay connected to the broker" are genuinely independent concerns — which they are here (poll interval might be 30–60s; broker reconnect should retry every 1–60s with backoff, not wait for the next poll tick).
**Trade-offs:** `paho-mqtt` does **not** automatically re-subscribe or re-publish anything for you across a reconnect (confirmed against the `paho.mqtt.python` source: `reconnect()` never calls `subscribe()` again, and never replays application-level publishes) — since this poller is a **pure publisher** with no subscriptions of its own, that gap doesn't apply; the next poll cycle naturally re-publishes current state once reconnected. If `client.publish()` returns `rc=MQTT_ERR_NO_CONN` (still disconnected), the safe behavior is to simply skip that cycle's publish and let the *next* interval's full status re-publish catch it up — never block the poll loop waiting for reconnection.

**Example:**
```python
# mqtt_client.py
client = mqtt.Client(client_id="checkmk-mqtt-poller", clean_session=True)
client.will_set("lan/poller/status", payload="offline", qos=1, retain=True)
client.reconnect_delay_set(min_delay=1, max_delay=60)
client.on_connect = lambda c, u, f, rc: c.publish("lan/poller/status", "online", qos=1, retain=True)
client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
client.loop_start()   # background thread; never call loop_forever() here —
                       # the main thread runs the poll timer instead
```

### Pattern 4: Livestatus — one-shot connect/query/close per poll cycle, not a kept-alive socket

**What:** Exactly the existing `src/checkmk_wizard/livestatus.py` pattern: open a fresh `socket.create_connection`, send one query, read until EOF, close. Do this once per poll cycle rather than holding one long-lived Livestatus TCP connection across cycles.
**When to use:** Livestatus's wire protocol is request/response-per-connection by design (this is exactly what the existing health-check client already relies on); there is no documented long-lived multiplexed-query mode to keep open safely across a multi-second poll interval.
**Trade-offs:** Slightly more TCP-handshake overhead per cycle (irrelevant at LAN speed and a 30–60s interval) in exchange for trivial reconnect logic — a failed cycle is just "the `with socket.create_connection(...)` raised `OSError`, log it, skip this cycle's publish, try again next interval." No separate Livestatus-specific backoff/retry state machine is needed because the poll interval itself already acts as the retry delay.

## Data Flow

### Poll → Publish → Retain → Subscribe

```
[poll timer fires, every N seconds]
    ↓
[poller: open Livestatus TCP socket to checkmk:6557]
    ↓ GET hosts (Columns: name state parents tags filename ...)
[poller: build per-device status dict from response]
    ↓
[poller: diff against last-cycle checkpoint (see Pattern below)]
    ↓                                   ↓                        ↓
[publish lan/devices/{id}/status] [publish lan/devices/topology] [append+publish
 retain=True, every cycle          retain=True, only if the      lan/devices/{id}/history
 regardless of change]             derived graph changed]        + lan/events/recent,
                                                                  only on detected transition]
    ↓
[poller: write checkpoint file atomically]  ← only after successful publish
    ↓
[mosquitto: stores retained value per topic, persists to disk]
    ↓ (independent of the above, at any later time)
[new browser tab loads dashboard.html → mqtt.js connects ws://host:9001]
    ↓ subscribe lan/devices/+/status, lan/devices/topology, lan/events/recent
[broker immediately delivers the latest retained message per matching topic —
 no query to the poller, no HTTP backend call, works even if the poller is
 currently down (dashboard shows last-known state + a stale-data indicator
 driven by lan/poller/status, see Pattern 3's LWT)]
```

### Startup / restart recovery (the resilience question)

```
[poller process starts — fresh container or restart]
    ↓
[load checkpoint file from bind-mounted app dir, if present]
    ↓
    ├─ checkpoint exists → treat as "warm start": diff this cycle's
    │  Livestatus read against the checkpoint exactly like any other
    │  cycle; genuine transitions get appended to history/events as usual
    │
    └─ checkpoint missing (first-ever run, or the file was deleted) →
       "cold start": publish full current status/topology to their
       retained topics (idempotent — this just re-asserts the current
       truth) but do NOT append anything to history/events, since there
       is no reliable "previous" state to compute a transition from —
       this is exactly the existing prototype's `is_first_run` guard,
       preserved rather than reinvented, because it correctly separates
       "publish what's true now" from "log that something changed"
```

**Why a local checkpoint file (not MQTT-retained-topic rehydration):** an alternative pattern exists — subscribe to your own `lan/devices/+/status` on startup and rebuild "previous state" from what the broker already has retained, needing no local file at all. That is a legitimate, more broker-centric pattern, but it requires a non-deterministic "wait N seconds after SUBACK, assume all retained messages have arrived" heuristic (MQTT has no explicit "end of retained messages" signal) and adds startup latency and complexity for a problem the existing bind-mounted `./app` host directory already solves for free: the `worker` service's `volumes: - ./app:/app:z` mount already persists across container recreation, so a plain JSON file at `/app/mqtt_poller_state.json`, written with the same load/save-with-try/except pattern the existing prototypes already use (just relocated off the OMD filesystem, since the poller must not touch `checkmk`'s filesystem), is simpler and just as resilient. State this as an accepted, deliberate simplification, not an oversight: revisit the retained-topic-rehydration pattern only if the poller is ever moved to run somewhere without a persistent bind mount (e.g. a from-scratch container image with no host volume).

**Known, accepted edge case:** if the process crashes between a successful publish and the checkpoint write, the next cycle re-diffs against one-cycle-stale state, which can append one duplicate transition entry to the bounded history/events log. This is a low-severity, rare (crash-window-sized) cosmetic duplicate in a *bounded* log, not a correctness or data-loss bug — the retained status topics themselves are always idempotently re-published from live Livestatus data regardless. Do not build extra machinery (write-ahead logs, two-phase checkpointing) to close this gap; it is not worth the complexity for a bounded, self-correcting display log.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|---------------------------|
| Home/small-office LAN (tens of devices — this project's actual target) | Exactly the design above: one `GET hosts` Livestatus query per cycle, one retained MQTT message per device, no changes needed. |
| Few hundred devices | Still fine unmodified — Mosquitto's retained-message storage and a few hundred small JSON publishes per cycle are trivial at LAN scale; watch only that the poll interval stays well above the time one Livestatus query + N publishes actually takes (measure, don't guess). |
| Thousands of devices / need for real historical graphing | Out of scope for this milestone per `PROJECT.md` ("no time-series database") — if ever needed, that's a genuinely different architecture (a time-series DB behind a real backend), not an extension of the retained-MQTT pattern; don't try to grow bounded in-memory/retained history arrays to serve that need. |

### Scaling Priorities

1. **First and only realistic bottleneck at this project's scale:** poll interval vs. Livestatus query latency, if the number of onboarded hosts ever grows large enough that a single `GET hosts` call takes a meaningful fraction of the poll interval. Fix: lengthen the interval or narrow the `Columns:` list — not architectural change.
2. Everything else (broker throughput, retained-message storage, browser render cost for a device table/topology map) is non-issue territory at the scale this project targets; do not pre-optimize for it.

## Anti-Patterns

### Anti-Pattern 1: Full-blob retained topics (what the two `docs/src/` prototypes do)

**What people do:** Publish one retained topic containing the entire host+service list (`checkmk/services/all`) and republish the whole thing every cycle, as `mqtt_publisher_changes.py` does.
**Why it's wrong:** Every subscriber (including a dashboard that just wants to update one row) must re-parse the entire blob on every update; it also means a single device flapping causes the same full-fleet payload to be re-retained repeatedly, growing broker retained-message size for no informational gain. This directly conflicts with this milestone's explicit "merge incoming updates... rather than re-rendering from scratch" requirement.
**Do this instead:** Per-device retained topics (Pattern 1 above) — already the direction `PROJECT.md`'s Key Decisions table has chosen; this research corroborates it as the standard fit for the stated requirement, not just a stylistic preference.

### Anti-Pattern 2: Driving the live dashboard via Checkmk notification rules

**What people do:** Have Checkmk fire a notification script (like `mqtt_notify.py`) on every state change, instead of polling Livestatus.
**Why it's wrong:** Notification scripts must be deployed into the `checkmk` container's own OMD filesystem (`/omd/sites/<site>/local/share/check_mk/notifications/` or similar) — which breaks the worker/checkmk container-mode boundary this entire stack is built around (`checkmk-wizard` never touches that filesystem; this milestone's own `PROJECT.md` explicitly rules this out for the same reason). It also can't answer "what is the current full state" on its own — only "something just changed" — so you'd still need a poller anyway for cold-start/dashboard-just-opened scenarios, meaning the notification-script path solves nothing a poller doesn't already have to solve, while adding a filesystem dependency the poller doesn't need.
**Do this instead:** Poll Livestatus over TCP only (already the chosen direction) — a poller is a strict superset of what the notification approach offers here.

### Anti-Pattern 3: Treating MQTT persistent sessions/QoS-2 as "the reliability layer" for state delivery

**What people do:** Reach for `clean_session=False` and QoS 2 everywhere, assuming stronger delivery guarantees automatically solve "the dashboard must always show correct current state."
**Why it's wrong:** Persistent sessions only queue messages for a *specific previously-subscribed client ID* while it's offline — a brand-new browser tab (a new, distinct client every page load, by design, since these are stateless static pages) never benefits from that queue; it always needs the *retained* value instead. QoS 2 additionally requires broker-tracked handshake state per in-flight message for zero real benefit here, since every status publish is immediately superseded by the next cycle's publish anyway (there is nothing to "lose exactly-once" that matters).
**Do this instead:** QoS 1 + `retain=True` for all state-bearing topics (status/topology/history/events); reserve QoS 2 thinking for domains with genuine "this exact single message must be processed exactly once" requirements, which this dashboard does not have.

### Anti-Pattern 4: Writing poller checkpoint state onto the `checkmk` container's filesystem, or into the container's own ephemeral layer

**What people do:** The original prototype writes `STATE_FILE`/`HISTORY_FILE` under `/omd/sites/monitoring/tmp/...` — i.e., inside Checkmk's own OMD tree.
**Why it's wrong:** Doing that from the `worker` container is impossible without a filesystem mount into `checkmk`'s volume, which is exactly the boundary violation `PROJECT.md` rules out; writing it instead into the `worker` container's own ephemeral layer (no volume) would silently reset on every container recreate (not just process restart), turning every redeploy into a spurious "cold start."
**Do this instead:** Write the checkpoint file under the `worker` service's existing bind-mounted `/app` directory (already `./app:/app:z` in `compose.yaml`), which is worker-owned, host-persisted, and touches neither `checkmk`'s filesystem nor anything ephemeral.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|----------------------|-------|
| Checkmk Livestatus (`checkmk:6557`) | One-shot TCP connect/query/close per poll cycle, `GET hosts` with `Columns: name state parents tags filename` (or similar) | Already enabled per `docs/Podman setup...md` §5; internal-only, never publish this port to the LAN (no auth in the Livestatus wire protocol) |
| Mosquitto broker (`mosquitto:1883` internal / `mosquitto:9001` published) | Poller publishes over the internal TCP listener; browsers subscribe over the published WebSockets listener | Same broker, two listeners, same retained-message store underneath — a message retained via the TCP listener is visible to WS subscribers and vice versa |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|----------------|-------|
| `mqtt_poller` ↔ `checkmk` | Livestatus-over-TCP only, read-only queries | Never the REST API for this milestone's live-poll path (REST stays the wizard's job); never the filesystem |
| `mqtt_poller` ↔ `mosquitto` | MQTT publish only (QoS 1, retain=True for state topics) | Poller does not need to subscribe to anything of its own — see Pattern 3 |
| `dashboard` (nginx) ↔ `mosquitto` | **None** — nginx only serves static files; the browser, not nginx, holds the WS connection to `mosquitto:9001` directly | Keeps nginx configuration trivial (no reverse-proxy/Upgrade-header config needed); documented alternative below |
| Browser dashboard ↔ `mosquitto` | MQTT-over-WebSockets, subscribe-only, wildcard topics | `mqtt.js` ships its own reconnect (`reconnectPeriod`, default 1000ms) — the project's own "exponential-backoff reconnect + connection-status indicator" requirement layers UI/UX on top of that, it doesn't need to reimplement the transport-level retry |

**Alternative considered for the nginx↔mosquitto boundary:** reverse-proxy `/mqtt` on the `dashboard` nginx container through to `mosquitto:9001` (requires `proxy_http_version 1.1` plus `Upgrade`/`Connection` header forwarding in nginx config), so the browser only ever talks to one origin/port. This is the more production-grade shape (single origin, easier to add TLS termination later, broker port never directly LAN-exposed) but adds nginx configuration complexity not required by this milestone's stated constraints, and is inconsistent with how `mosquitto:1883` is already published directly to the LAN in the existing stack. Recommend the direct-publish approach (Pattern used above) for this milestone; revisit the reverse-proxy shape only if/when TLS or single-origin browser security policy becomes a real requirement.

### Compose/config wiring specifics

**`mosquitto.conf`** — add a second listener block; the existing top-level `allow_anonymous true` already applies to both listeners (no `per_listener_settings` needed unless the project later wants a stricter policy for the LAN-facing WS listener than the internal TCP one — worth flagging as a future hardening item, not required now):
```text
listener 1883 0.0.0.0
allow_anonymous true
persistence true
persistence_location /mosquitto/data/

listener 9001 0.0.0.0
protocol websockets
```

**`compose.yaml`** — two changes: publish the new Mosquitto WS port, and add the `dashboard` service:
```yaml
services:
  mosquitto:
    # ...unchanged...
    ports:
      - "1883:1883"
      - "9001:9001"      # NEW — MQTT-over-WebSockets for browser clients

  dashboard:               # NEW
    image: nginx:alpine
    container_name: dashboard
    restart: unless-stopped
    volumes:
      - ./app/checkmk-wizard/dashboard:/usr/share/nginx/html:ro,z
    ports:
      - "8081:80"           # avoid clashing with checkmk's published 8080
    networks:
      - cmk_net
```
No new named volumes needed (dashboard content is read-only, sourced from the same repo checkout already bind-mounted for `checkmk-wizard`). No changes needed to the `worker` service beyond what's needed to run the new `mqtt_poller` process (e.g., adding it to whatever process-supervision the worker container already uses, or a second `podman compose exec worker ...` invocation — an operational detail for the roadmap's build-order phase, not an architecture decision).

## Build Order Implications

1. **Mosquitto WebSockets listener + compose wiring** — zero dependency on any other new component; verify with a WS-capable MQTT CLI client (e.g. `mosquitto_sub` doesn't support WS, but `mqtt.js`'s own CLI or a two-line browser console test does) before building anything that depends on it.
2. **Poller skeleton: Livestatus query → per-device retained publish → checkpoint file** — depends only on (1) being reachable, not on the dashboard existing. Verify with `mosquitto_sub -t 'lan/#' -v` (works fine over the existing TCP listener, no WS client needed for this verification step).
3. **Checkmk host-tag group + wizard Phase 5 onboarding prompt** (separate `PROJECT.md` active item) — independent of (2)'s core loop; the poller should read the tag defensively (default `"unknown"` device type when absent) so build order between this and (2) doesn't block either side, but finishing this before end-to-end dashboard testing means test data has real device types instead of placeholders.
4. **`dashboard` nginx container + static pages** — depends on (1) and (2) both being stable, since the dashboard is purely a *consumer* of the topic/payload contract `topics.py` defines; changing that contract after dashboard JS is written means updating both sides, so nail the contract in (2) before investing in (4)'s rendering code.
5. **Dashboard polish** (connection-status indicator, exponential-backoff UX beyond `mqtt.js`'s own defaults, bounded-history rendering) — depends on (4)'s skeleton existing and (2)'s `lan/poller/status` LWT topic being in place to actually have something to indicate.

## Sources

- [Eclipse Paho MQTT Python Client — Context7 `/eclipse-paho/paho.mqtt.python`](https://github.com/eclipse-paho/paho.mqtt.python) — `loop_start`/`loop_forever`/`connect_async` reconnect behavior, confirmed no auto-resubscribe across reconnects (HIGH confidence, verified against library source via Context7)
- [Eclipse paho-dev mailing list — reconnect_delay_set](https://www.eclipse.org/lists/paho-dev/msg01791.html) and corroborating community sources on `reconnect_delay_set(min_delay, max_delay)` exponential backoff, defaults 1s/120s (MEDIUM confidence — behavior consistent across multiple independent sources, not directly pulled from Context7's index)
- [Eclipse Mosquitto — mosquitto.conf man page](https://mosquitto.org/man/mosquitto-conf-5.html) — multiple `listener` blocks, `protocol websockets`, `allow_anonymous` scoping (HIGH confidence, official docs)
- [Cedalo — How to configure MQTT over WebSockets with Mosquitto](https://www.cedalo.com/blog/enabling-websockets-over-mqtt-with-mosquitto) (MEDIUM confidence, corroborating community source)
- [MQTT.js README](https://github.com/mqttjs/MQTT.js/blob/master/README.md) — `reconnectPeriod` default (1000ms), `clean` session option, v2.0.0 resubscribe-on-reconnect behavior (MEDIUM confidence, official repo README)
- Existing repo: `src/checkmk_wizard/livestatus.py`, `docs/src/mqtt_publisher_changes.py`, `docs/src/mqtt_notify.py`, `docs/Podman setup for checkmk, minio, mosquitto, worker.md`, `.planning/PROJECT.md`, `.planning/codebase/ARCHITECTURE.md` (HIGH confidence — primary sources, this project's own code/docs)

---
*Architecture research for: Checkmk-to-MQTT bridge + live network-topology dashboard (checkmk-wizard subsequent milestone)*
*Researched: 2026-09-05*
