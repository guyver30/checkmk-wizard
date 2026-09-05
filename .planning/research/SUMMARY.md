# Project Research Summary

**Project:** checkmk-wizard — MQTT bridge + live network-topology dashboard milestone
**Domain:** Monitoring-to-MQTT bridge (Checkmk Livestatus poller) + retained-message-driven, backend-less static browser dashboard
**Researched:** 2026-09-05
**Confidence:** HIGH

## Executive Summary

This milestone extends the existing checkmk-wizard project with a Python poller that bridges Checkmk's Livestatus data to MQTT, and a static, buildless HTML/JS dashboard (topology map + device table + drill-down) that renders that data live via MQTT-over-WebSockets. Experts building this pattern converge on the same shape: publish one **retained MQTT message per entity** (not one giant blob), let Mosquitto's retained-message store do all the "give a new client the current state" work, and keep the browser dumb — subscribe, merge into an in-memory `DataSet`/map, never re-render from scratch. The stack is well-established and low-risk: `paho-mqtt` 2.1.0 (with the v2 `CallbackAPIVersion`, not the v1 pattern the project's own prototype scripts use), `mqtt.js` 5.x, and `vis-network`'s standalone UMD bundle with its `DataSet.update()` upsert API, all loadable via CDN `<script>` tags with zero build step — Mosquitto 2.x already supports a native WebSockets listener, so no reverse proxy or second broker is needed.

The recommended approach is a one-shot-connect/query/close Livestatus poll every 30-60s (mirroring the existing `livestatus.py` client, not a kept-alive socket), diffed **against Livestatus's actual current state each cycle** (not against the poller's own in-memory memory of what it last published — this is the single biggest resilience decision, since it makes the poller self-healing across restarts). Per-device status republishes every cycle (QoS 0, retain); topology, tombstones, and history/events republish only on change (QoS 1, retain, since there's no "next cycle" to self-correct a dropped rare publish). The dashboard is architecturally decoupled from the wizard's phase-pipeline shape — it's a long-running daemon, not a CLI phase — and should live as its own `mqtt_poller/` package with an isolated `mqtt_client.py` wrapper and a single `topics.py` defining the wire contract, following the existing codebase's convention of non-cross-importing modules.

The key risks all cluster around **things retained messages don't automatically handle**: stale-forever data for decommissioned devices (no tombstone = permanent ghost devices), a broker restart silently wiping retained state if `persistence true` isn't set, an unauthenticated WebSocket listener letting any LAN device forge or clear state (MQTT pub/sub gives write access by default, unlike a typical read-only web leak), and a dashboard that can't visually distinguish "device is actually down" from "my own MQTT connection dropped" (retained messages never expire on their own, so a dead poller freezes the dashboard on stale-but-plausible data forever unless a timestamp + staleness threshold is designed in from day one). A secondary, Checkmk-specific risk is the new `device_type` host-tag group: Checkmk auto-assigns its first/default tag value to **every pre-existing host** the moment the tag group is created, with no "unset" state — defaulting that first choice to a real device type (e.g., "server") will silently mis-tag every host onboarded before this milestone. All of these are cheap to design against up front and expensive to retrofit, so they should be treated as v1 requirements, not deferred hardening.

## Key Findings

### Recommended Stack

The stack is small, mature, and CDN-installable with no build tooling, matching the project's existing no-framework/`uv`-managed-Python style. See `.planning/research/STACK.md` for full version/compatibility details.

**Core technologies:**
- `paho-mqtt` 2.1.0 (Python, `worker` container poller) — the de facto standard sync Python MQTT publisher; must use the v2 `CallbackAPIVersion` API, not the v1 pattern already present in `docs/src/mqtt_publisher_changes.py`/`mqtt_notify.py`
- `vis-network` 10.1.2 standalone UMD bundle (bundles `vis-data`) — physics-based graph rendering with a first-class `DataSet.update()` upsert API, exactly matching the "merge, don't rebuild" requirement
- `mqtt.js` 5.15.2 browser UMD bundle — the current standard browser MQTT client, works via a single `<script>` tag, built-in (fixed-interval, not exponential) reconnect
- Eclipse Mosquitto 2.1.2 — already the chosen broker; has a native `protocol websockets` listener, so no second broker or nginx WS-proxy is required

### Expected Features

See `.planning/research/FEATURES.md` for the full landscape, dependency graph, and prioritization matrix.

**Must have (table stakes):**
- Live per-device status (color-coded, preserving Checkmk's OK/WARN/CRIT/UNKNOWN/DOWN granularity, not collapsed to up/down)
- Topology map with parent/child links, sortable device table, per-device drill-down with bounded history
- Connection/feed-health indicator with auto-reconnect
- **A distinct "stale/unknown" state, separate from "down"** — flagged by research as a critical gap not yet explicit in PROJECT.md's active requirements; requires adding a timestamp field to the per-device status payload

**Should have (competitive):**
- Surface Checkmk downtime/acknowledgement state (near-zero marginal cost via Livestatus columns already available)
- Device-type icons and VLAN-based coloring on the map (both already scoped, pure rendering once data exists)
- Poller/feed-liveness signal via MQTT birth + Last-Will-and-Testament on `lan/poller/status`
- Search/filter box on the device table (cheap, pure client-side, no new topic)

**Defer (v2+):**
- Mobile-responsive layout polish
- Read-only ACL'd WebSocket listener can be phased in, but note PITFALLS research treats unauthenticated WS as a *critical* pre-launch risk, not a deferrable one — reconcile this tension in roadmap sequencing (see Phase suggestions below)

**Explicitly out of scope (not deferred, decided against):** time-series graphing/charting, in-dashboard alerting, drag-and-drop topology editing, editable device metadata, multi-user accounts/login, full L2/LLDP/SNMP auto-discovery, client-side HTTP polling fallback, browser-side history persistence.

### Architecture Approach

A poller runs inside the existing `worker` container, one-shot-querying Livestatus over TCP each cycle and publishing per-entity retained MQTT messages to Mosquitto; a new lightweight `dashboard` nginx container serves static files only, while the browser talks **directly** to Mosquitto's WebSockets listener (no reverse proxy through nginx) — mirroring how `mosquitto:1883` is already published directly to the LAN today. Full detail, including compose/config diffs, is in `.planning/research/ARCHITECTURE.md`.

**Major components:**
1. `mqtt_poller/` (new Python package in `worker`) — poll loop, Livestatus diff, MQTT publish, checkpoint persistence; isolated `mqtt_client.py` wrapper and `topics.py` single-source-of-truth for the wire contract
2. `mosquitto` broker — two listeners (internal TCP for the poller, LAN-published WebSockets for browsers), `persistence true` against a mounted volume, retained messages as the sole state-recovery mechanism (not MQTT persistent sessions/QoS-2, which solve a different problem)
3. `dashboard` (new nginx container) — zero backend logic, serves `index.html`/`devices.html`/`details.html` + JS/CSS; browser's `mqtt.js` owns the live WebSocket connection directly

### Critical Pitfalls

Full detail (10 pitfalls, technical debt table, recovery strategies) in `.planning/research/PITFALLS.md`.

1. **Stale retained state for decommissioned/renamed devices** — "publish only on change" has no tombstone; deleting a host from Checkmk never clears its retained topics. Avoid by diffing the current vs. previously-known device-ID set every cycle and publishing empty retained payloads for removed devices.
2. **Poller restart loses "last known state,"** causing silent desync or a republish storm. Avoid by always diffing against Livestatus's actual current state (source of truth), not the poller's in-memory publish history.
3. **Mosquitto restart silently discards all retained messages** unless `persistence true` + a mounted `persistence_location` is explicitly configured — must be part of the same config pass as the WebSockets listener, not an afterthought.
4. **Unauthenticated WebSocket listener** gives any LAN device write access to forge or clear retained state (MQTT pub/sub ≠ read-only web leak). Requires an ACL file with a read-only WS user, separate from the poller's publish-capable, container-internal-only listener.
5. **New `device_type` tag group silently mis-tags every pre-existing host** with the group's first/default choice (Checkmk has no "unset" state). Default must be a neutral value like `unknown`, not a real device type.

## Implications for Roadmap

Based on research, suggested phase structure (numbering here is milestone-relative, to be reconciled with the project's existing 7-phase wizard numbering during roadmap creation):

### Phase A: Broker infrastructure hardening
**Rationale:** Zero dependency on any other new component (per ARCHITECTURE.md's Build Order); but PITFALLS.md identifies persistence and ACL/auth gaps as *critical* and expensive to retrofit once the dashboard assumes anonymous access — so this must be more than "add a WS listener," it must include persistence and ACL scoping from the start.
**Delivers:** `mosquitto.conf` with two listeners (internal TCP for poller, LAN-facing WS for browsers, ACL-scoped read-only), `persistence true` against a mounted volume, `compose.yaml` port/service wiring.
**Addresses:** Connection/feed-health prerequisite (nothing works without a reachable, durable broker).
**Avoids:** Pitfall 3 (persistence not enabled), Pitfall 4 (unauthenticated WS listener).

### Phase B: Poller core (topic contract, Livestatus diff, resilience)
**Rationale:** Depends only on Phase A being reachable, not on the dashboard existing; the topic/payload contract this phase defines becomes the fixed interface the dashboard is built against — get it right before investing in rendering code (per ARCHITECTURE.md's Build Order Implications).
**Delivers:** `mqtt_poller/` package — `topics.py` contract, per-device/topology/history/events publishing with correct per-topic QoS, checkpoint-file-based restart resilience, device-removal tombstoning, birth/LWT on `lan/poller/status`.
**Uses:** `paho-mqtt` 2.1.0 (v2 callback API), `Client.loop_start()` + `reconnect_delay_set()`.
**Implements:** Retained-message-per-entity pattern; one-shot Livestatus connect/query/close per cycle.
**Avoids:** Pitfall 1 (no tombstone), Pitfall 2 (in-memory-only diff state), Pitfall 7 (per-topic QoS misuse), Pitfall 10 (fragile folder-path VLAN parsing — use REST API structured folder segments, not string splitting).

### Phase C: Checkmk tag-group + onboarding integration
**Rationale:** Independent of Phase B's core loop (poller should read the tag defensively with a safe default), but must be resolved before end-to-end dashboard testing to get real device types instead of placeholders; the default-value decision here has a one-way door risk (mis-tagging every existing host) that's cheap to get right now and costly to fix later.
**Delivers:** New `device_type` host-tag group with a neutral (`unknown`) default; wizard Phase 5 prompt sets it via REST API using the correct `tag_<group_id>` attribute shape, verified live (not just mocked).
**Addresses:** Device-type icons and VLAN-grouping differentiators from FEATURES.md.
**Avoids:** Pitfall 8 (silent default mis-tagging of pre-existing hosts), Pitfall 9 (wrong REST API attribute shape).

### Phase D: Dashboard (map, table, drill-down)
**Rationale:** Depends on Phases A and B being stable, since the dashboard is a pure consumer of the topic contract; changing the contract after dashboard JS is written means updating both sides.
**Delivers:** New `dashboard` nginx container serving `index.html` (topology map + stats strip), `devices.html` (sortable table + recent events), `details.html` (drill-down + history); shared `mqtt-connection.js` and `state-store.js` modules; merge-not-rebuild rendering via vis-network's `DataSet.update()`.
**Addresses:** All P1 table-stakes features from FEATURES.md, plus the recommended stale/unknown-state addition.
**Avoids:** Pitfall 5 (unjittered reconnect thundering herd — add jitter to backoff), Pitfall 6 (unbounded browser-side memory growth — replace, don't append, bounded history arrays).

### Phase Ordering Rationale

- Broker hardening (persistence + ACLs) comes first because retrofitting auth after the dashboard already assumes anonymous access requires reworking both sides together (PITFALLS.md), and because every later phase depends on the broker being reachable and durable.
- Poller precedes dashboard because the dashboard is architecturally a pure consumer of the poller's topic/payload contract (ARCHITECTURE.md's explicit build-order recommendation) — building UI against an unstable contract is wasted rework.
- Tag-group/onboarding work can run in parallel with poller development (loose coupling via a defensive default) but must land before dashboard integration testing so real device-type data exists.
- Dashboard is last because it has no independent value until the data pipeline beneath it is trustworthy — a pretty map over unreliable/stale data is worse than no map.

### Research Flags

Phases likely needing deeper research during planning:
- **Poller core (Phase B):** the exact reconciliation strategy (startup diff against live Livestatus vs. broker-side retained rehydration) and per-topic QoS choices are nuanced enough (see PITFALLS.md Pitfall 2 and 7) to warrant a `--research-phase` pass confirming the chosen approach against the final topic contract.
- **Tag-group/onboarding (Phase C):** REST API attribute shape for custom host tags has a documented history of silent failures in this exact codebase (CONCERNS.md precedent with SNMP attributes) — needs a live-site verification step, not just planning-time research.

Phases with standard patterns (skip research-phase):
- **Broker infrastructure (Phase A):** Mosquitto multi-listener + persistence + ACL config is well-documented, official-docs-verified (HIGH confidence in STACK.md/ARCHITECTURE.md).
- **Dashboard (Phase D):** vis-network `DataSet` merge pattern and mqtt.js browser usage are both HIGH-confidence, officially documented, CDN-installable patterns with working examples already verified.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All core library versions/APIs verified against official docs, PyPI/jsdelivr metadata, or Context7-indexed source |
| Features | MEDIUM-HIGH | Core MQTT/JS library behavior verified via official docs; monitoring-UX conventions (staleness thresholds, PRTG/Zabbix "unknown" state) verified across multiple sources but not independently re-checked against each tool's current docs |
| Architecture | HIGH (core patterns) / MEDIUM (some edge-case tradeoffs) | paho-mqtt reconnect API, Mosquitto multi-listener config, and MQTT retain semantics verified against official/Context7 sources; browser mqtt.js reconnect defaults and checkpoint-file edge cases are reasoned from verified primitives, not independently load-tested |
| Pitfalls | MEDIUM-HIGH | MQTT/Mosquitto claims verified against community docs, GitHub issues, and the Mosquitto man page; Checkmk tag-group claims verified against official docs and a real forum bug report; exact behavior of some Mosquitto WS config options (e.g. `bind_interface` support) flagged as needing a spot-check against the installed version |

**Overall confidence:** HIGH

### Gaps to Address

- **Stale/unknown dashboard state is not yet an explicit PROJECT.md requirement** — FEATURES.md recommends promoting it to a v1 requirement; roadmap/requirements definition should confirm this addition explicitly with the user rather than assuming it.
- **Exact Checkmk REST API attribute shape for the new `device_type` tag** (`tag_<group_id>` convention) should be verified against a live Checkmk 2.4.0p35 site before the onboarding phase is considered done — this project has a prior documented precedent (SNMP attribute shape) of shipping unverified REST payload shapes.
- **Folder-path → VLAN derivation approach** (structured REST API folder segments vs. raw string splitting) needs a concrete implementation decision during phase planning, not left as an open question.
- **Read-only ACL'd WS listener timing:** FEATURES.md's MVP table places this as a v1.x/deferred item, while PITFALLS.md treats unauthenticated WS as a critical, hard-to-retrofit risk — the roadmap should resolve this tension explicitly (this summary recommends treating it as part of Phase A, not deferred).
- **Exact Mosquitto WS config edge cases** (e.g., `bind_interface`/`per_listener_settings` interaction) are MEDIUM confidence and should be spot-checked against the actual installed Mosquitto version during Phase A implementation.

## Sources

### Primary (HIGH confidence)
- Eclipse Paho — official migration guide (`CallbackAPIVersion.VERSION2` constructor/signatures)
- PyPI `paho-mqtt` project page/JSON API — confirmed 2.1.0, `requires-python >=3.7`
- Eclipse Mosquitto — official download page and `mosquitto.conf(5)` man page
- jsdelivr package data API — confirmed vis-network 10.1.2, mqtt.js 5.15.2, vis-data 8.0.5
- vis-data official docs (`DataSet` API) and vis-network official examples (`dynamicData.html`)
- MQTT.js official README (GitHub)
- Context7 `/eclipse-paho/paho.mqtt.python` and `/visjs/vis-network` — reconnect/resubscribe behavior, `stabilization` events
- Checkmk official docs — Host tags
- Project files: `src/checkmk_wizard/livestatus.py`, `docs/src/mqtt_publisher_changes.py`, `docs/src/mqtt_notify.py`, `.planning/PROJECT.md`, `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/CONCERNS.md`

### Secondary (MEDIUM confidence)
- HiveMQ MQTT Essentials blog series (Last Will and Testament; Persistent Sessions; Retained Messages)
- Home Assistant MQTT Sensor/Binary Sensor docs (`expire_after`, availability/birth-will convention)
- Eclipse paho-dev mailing list — `reconnect_delay_set` defaults
- Cedalo blog — Mosquitto WebSockets configuration
- Checkmk Community Forum — REST API custom-tag bug report (500 error on wrong attribute shape)
- GitHub issues: Koenkk/zigbee2mqtt#30619 (stale retained availability), eclipse/mosquitto#769, rabbitmq/rabbitmq-mqtt#74

### Tertiary (LOW confidence)
- "The Biggest Monitoring Mistake Most Home Labs Make" (single blog, alert-fatigue pattern) — consistent with well-known conventions but not independently corroborated
- General PRTG/Zabbix/Icinga/Nagios "unknown/stale sensor" threshold conventions — based on general knowledge of these tools' documented state models, not re-verified against current docs in this pass

---
*Research completed: 2026-09-05*
*Ready for roadmap: yes*
