# Feature Research

**Domain:** Minimal, real-time LAN topology + device-status dashboard, backend-less (static HTML/JS + MQTT), fed by a Checkmk-Livestatus-polling publisher
**Researched:** 2026-09-05
**Confidence:** MEDIUM-HIGH (core MQTT/JS library behavior verified via Context7 official docs; monitoring-UX conventions verified via multiple independent sources; some homelab-specific claims are WebSearch-sourced and marked LOW where noted)

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete or actively misleading.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Live per-device status (color-coded) on both map and table | Core promise of "at-a-glance health" — this is the reason the dashboard exists | LOW | Already scoped. Preserve Checkmk's OK/WARN/CRIT/UNKNOWN/DOWN granularity — don't collapse to a single up/down boolean, or the dashboard becomes *less* informative than a glance at Checkmk. |
| Topology map with parent/child links | Matches the explicit PRTG-style map+list duality in PROJECT.md | MEDIUM | vis-network confirmed (via Context7) to support `physics.stabilization` events (`stabilizationIterationsDone`, `stabilized`) — freeze physics after initial layout settles rather than running the force simulation forever (see Anti-Features). |
| Sortable device table | Standard expectation once you have a list of >~10 items; a map alone doesn't scale to "find device X" | LOW | Already scoped. |
| Per-device drill-down (identity + bounded history) | Users expect to click a device and see "what is this, and what just happened to it" | LOW-MEDIUM | Already scoped as `details.html`. |
| Connection/feed-health indicator ("connected" + reconnect state) | Any live dashboard that goes silent without saying so trains users to distrust it | LOW | Already scoped. See Stale Detection section below for the specific pattern. |
| **Distinct "stale/unknown" state, separate from "down"** | The single most important correctness property of a retained-MQTT dashboard — see dedicated section below | LOW-MEDIUM | **Not yet explicit in PROJECT.md active requirements — recommend promoting to an explicit requirement.** Without it, a dead poller silently freezes the dashboard on its last-known (possibly all-green) state forever, because MQTT retained messages never expire on their own. |
| At-a-glance stats strip (counts by state) | Already an established PRTG-style convention scoped in PROJECT.md | LOW | Trivial to derive client-side from the in-memory device map; no new topic needed. |
| Bounded recent-events panel | Already scoped (`lan/events/recent`) | LOW | See History Retention section — this should be the *only* history mechanism, no browser storage needed. |
| Link-out to Checkmk's own UI for full service detail | Explicit non-goal to duplicate Checkmk's UI (PROJECT.md) | LOW | Simple deep-link using host name, e.g. to Checkmk's host detail view. |
| Auto-reconnect on MQTT/WebSocket drop | A dashboard that just dies silently on a Wi-Fi blip or broker restart is broken for its core use case (leave-it-open wall/tab display) | LOW-MEDIUM | mqtt.js (Context7-verified) has `reconnectPeriod` but it is a **fixed interval by default, not exponential backoff** — PROJECT.md's "exponential-backoff MQTT reconnect" requires manually increasing `reconnectPeriod` (or calling `end()`/`reconnect()`) on the client's `reconnect`/`close` events. Flag this as slightly more implementation effort than "just set an option." |

### Differentiators (Competitive Advantage)

Not required for the dashboard to feel complete, but meaningfully improve on naive DIY approaches and align with the project's core value (visual picture without duplicating Checkmk).

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Surface Checkmk downtime/acknowledgement state on map + table | Prevents planned maintenance from visually looking identical to a real outage — directly addresses the "alert fatigue / stops paying attention" failure mode common in homelab monitoring setups | LOW-MEDIUM | Livestatus already exposes `scheduled_downtime_depth` / `acknowledged` columns; the poller can pass these through in the existing status payload at near-zero marginal cost. |
| Device-type icons on the map (from the new host tag group) | Turns an undifferentiated node graph into a recognizable network diagram (routers vs. switches vs. IoT) without needing real topology discovery | LOW | Purely a rendering concern once the tag is set during onboarding (already scoped). |
| VLAN-based grouping/coloring on the map | Free visual structure derived from Checkmk folder path (already scoped, no new config) | LOW | vis-network supports node grouping natively. |
| Explicit poller/feed-liveness signal (birth/LWT on the poller's own MQTT connection), separate from per-device staleness | Catches "the whole pipeline died" (poller crashed, lost Livestatus connection) distinctly from "this one device stopped reporting" — most DIY MQTT dashboards only handle per-device state and miss this class of failure entirely | LOW | Standard MQTT convention (Last Will + retained birth message on a dedicated `lan/poller/status` topic); confirmed as the recommended pattern in current MQTT/Home Assistant practice (see Sources). |
| Merge-not-rebuild rendering | Avoids flicker, lost scroll position, and lost sort order on every update — a common DIY dashboard failure | MEDIUM | Already scoped in PROJECT.md; worth calling out as a differentiator because most quick DIY dashboards just re-render the whole DOM on every MQTT message. |
| Basic search/filter box on the device table | Once a LAN has 30+ devices, a sortable-only table becomes tedious to scan | LOW | Not currently in PROJECT.md's Active requirements. Recommend as a cheap v1.x add — pure client-side string match over the already-held in-memory device list, no new topic or backend needed. |
| Mobile-responsive layout | Matches the PRTG-style "check status from your phone" use case implied by the UX inspiration | LOW | Pure CSS; no build step required to add basic responsive breakpoints. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|------------------|-------------|
| Historical time-series graphing/charting (Grafana-style zoom/pan) | "Wouldn't it be nice to see CPU/latency trends over time?" | Requires a time-series database and a much larger UI surface; already explicitly out of scope in PROJECT.md | Link out to Checkmk's own graphing UI, which already does this well |
| In-dashboard alerting (push notifications, sounds, email) | Feels like a natural extension of "live status" | Duplicates Checkmk's mature notification engine; introduces alert-fatigue risk if thresholds aren't carefully tuned (a documented top failure mode in DIY homelab monitoring) | Keep Checkmk as the single source of alerting truth; the dashboard is read-only visualization |
| Drag-and-drop topology editing with saved node positions | Users want to arrange the map "just so" | No backend exists to persist layout; would either require adding one (violates the no-backend constraint) or silently losing arrangement on every reload, which is worse than not offering it | Auto-layout via vis-network physics, stabilized once per load; accept that layout may shift slightly between sessions |
| Editable device metadata from the dashboard (rename, retag, add notes) | Seems convenient to manage everything in one place | Would require a write-back path into Checkmk (new API surface, auth, conflict handling) — well beyond "read-only visualization" | Link out to Checkmk's WATO UI for any edits; the wizard already owns tag assignment at onboarding time |
| Multi-user accounts / login / personalized views | "Feels like a real app should have login" | No backend to hold sessions/preferences; adds real complexity for a LAN-local, single-team tool | Rely on network-level access control (VPN/LAN-only reachability), consistent with the rest of the container stack |
| Full L2/LLDP/SNMP topology auto-discovery (true wire-level map, MAC-based) | "The map should reflect the *actual* physical wiring" | Already explicitly out of scope in PROJECT.md — not reliably available without Checkmk's inventory plugin; adds a new subsystem for marginal value | Use Checkmk's Livestatus `parents` column (logical/monitoring topology) — good enough for an at-a-glance picture |
| Client-side HTTP polling as a fallback/primary update mechanism | "What if MQTT/WebSockets aren't reliable?" | Defeats the entire point of an event-driven, no-backend design; reintroduces polling-interval latency and server load the architecture was built to avoid | Trust MQTT retained messages + reconnect-with-backoff; a well-implemented reconnect handles broker restarts fine |
| Persisting event/status history in browser `localStorage`/`IndexedDB` | "So history survives a refresh" | Unnecessary complexity (quota limits, stale-data-across-tabs, migration on schema change) when the poller already maintains bounded, retained history server-side (broker-held) | Rely entirely on the retained `lan/devices/{id}/history` and `lan/events/recent` topics — a fresh page load/subscribe immediately rehydrates full bounded history from the broker with zero browser-side storage |
| Unauthenticated/unrestricted MQTT WebSocket listener with full topic access | "Simplest possible setup" | Any LAN client that finds the dashboard URL can also subscribe (or worse, publish) directly to the broker, potentially corrupting retained state for every viewer | Scope the WebSocket listener to a read-only ACL user for browser subscribers, separate from the poller's publish credentials |

## Feature Dependencies

```
[Poller: per-device status topic w/ timestamp field]
    └──requires──> [Stale/unknown state distinct from down]
                       └──enhances──> [Connection/feed-health indicator]

[Poller: birth + Last-Will-and-Testament on lan/poller/status]
    └──enables──> [Feed-liveness signal] (differentiator)
                       └──enhances──> [Stale/unknown state] (catches whole-pipeline failure, not just one device)

[Host tag group: device type] (wizard Phase 5)
    └──requires──> [Device-type icons on map]

[Folder-path VLAN derivation]
    └──requires──> [VLAN-based grouping/coloring on map]

[lan/devices/topology retained topic]
    └──requires──> [Topology map view]
                       └──enhances──> [Device-type icons], [VLAN grouping]

[lan/devices/{id}/history, lan/events/recent — bounded, retained]
    └──requires──> [Per-device drill-down history strip], [Recent-events panel]
    └──replaces──> [Browser-side history storage] (anti-feature — made unnecessary)

[Per-device topics + "merge not rebuild"]
    └──requires──> [Sortable device table without flicker]
                       └──enhances──> [Search/filter box] (differentiator, cheap add-on)

[Exponential-backoff reconnect] ──conflicts with──> [mqtt.js default reconnectPeriod behavior]
    (mqtt.js's built-in reconnectPeriod is fixed-interval; backoff must be layered on manually)
```

### Dependency Notes

- **Stale/unknown state requires a timestamp in the per-device status payload:** without a "last updated at" field in `lan/devices/{id}/status`, the browser has no way to distinguish "this is current" from "this is a retained message from an hour ago because the poller died." This should be added to the payload contract regardless of which phase implements the UI for it.
- **Feed-liveness signal enhances (but does not replace) per-device staleness:** a poller can be alive and connected to MQTT while its Livestatus connection to Checkmk itself has failed. Per-device timestamp staleness catches that case even when the poller's own MQTT heartbeat looks fine — the two checks are complementary, not redundant.
- **Search/filter is a pure client-side enhancement over the sortable table:** it has no new topic dependency and can be added at any point after the table exists, making it a natural v1.x candidate rather than a v1 blocker.
- **Exponential backoff conflicts with mqtt.js's default option semantics:** this is a real (small) implementation cost, not just a config flag — worth flagging so it isn't underestimated during implementation planning.

## MVP Definition

### Launch With (v1)

Everything already captured in PROJECT.md's Active requirements, plus one addition:

- [ ] Poller publishes per-device status (every cycle) + topology (on change) + bounded history/events — already scoped
- [ ] Three-page dashboard (map, table, drill-down) with connection-status indicator and merge-not-rebuild rendering — already scoped
- [ ] Device-type tag + folder-derived VLAN feeding map rendering — already scoped
- [ ] **Timestamp field in the per-device status payload + a distinct "stale/unknown" visual state** — recommended addition; without it the dashboard can silently show false-green data indefinitely after a poller crash, which is a worse failure mode than showing nothing

### Add After Validation (v1.x)

- [ ] Search/filter box on the device table — add once real device counts make plain sorting feel slow
- [ ] Surface Checkmk downtime/acknowledgement state on map + table — add once the basic status pipeline is proven, to cut down on "is this a real outage?" confusion during planned maintenance
- [ ] Poller-liveness (birth/LWT) indicator, separate from per-device staleness — add once the basic per-device staleness check is working and the team wants to also catch whole-pipeline failures

### Future Consideration (v2+)

- [ ] Mobile-responsive layout polish — defer if the dashboard is primarily viewed on a wall display/desktop initially
- [ ] Read-only ACL'd WebSocket listener (vs. an initially open one) — worth doing before wider LAN exposure, but not blocking for a first internal validation pass

**Permanently excluded** (per PROJECT.md Out of Scope — not deferred, decided against): time-series graphing, notification-rule-based live updates, per-service drill-down duplication of Checkmk's UI, MAC-based topology/inventory, editable topology, multi-user accounts, and browser-side history persistence.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|----------------------|----------|
| Live per-device status (map + table) | HIGH | LOW | P1 |
| Topology map with parent/child links | HIGH | MEDIUM | P1 |
| Sortable device table | HIGH | LOW | P1 |
| Per-device drill-down + bounded history | HIGH | LOW-MEDIUM | P1 |
| Connection/feed-health indicator | HIGH | LOW | P1 |
| Stale/unknown state (distinct from down) | HIGH | LOW-MEDIUM | P1 |
| Exponential-backoff reconnect | MEDIUM | LOW-MEDIUM | P1 |
| Device-type icons on map | MEDIUM | LOW | P2 |
| VLAN grouping/coloring on map | MEDIUM | LOW | P2 |
| Downtime/acknowledgement surfacing | MEDIUM | LOW-MEDIUM | P2 |
| Poller-liveness (birth/LWT) indicator | MEDIUM | LOW | P2 |
| Search/filter on device table | MEDIUM | LOW | P2 |
| Mobile-responsive layout | LOW-MEDIUM | LOW | P3 |
| Read-only ACL'd WebSocket listener | MEDIUM (security) | LOW | P2 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

## Stale Detection & History Retention — Direct Answers

### What's standard for "stale" detection in a live MQTT dashboard?

Two complementary, well-established patterns, both grounded in current MQTT/monitoring practice (Home Assistant's `expire_after`/availability-topic model, and the general MQTT birth/Last-Will-and-Testament convention):

1. **Per-device data-age check (the important one here):** because this architecture republishes each device's `lan/devices/{id}/status` on *every* poll cycle (not just on change), the payload should include a timestamp (or the browser can timestamp on receipt). The dashboard compares "now" to "last received" and flags the device as **stale/unknown** — a visually distinct grey state, separate from both "up" (green) and "down" (red) — once the gap exceeds roughly **2-3× the poll interval**. This threshold multiplier (not exactly 1×) is standard across monitoring tools (Zabbix "no data," Icinga/Nagios freshness checking, PRTG's grey "unknown" sensor state) specifically to avoid false staleness flags from a single missed/delayed cycle.
2. **Feed/poller-liveness check (birth + Last Will and Testament):** the poller's own MQTT client publishes a retained "online" message on connect and registers a retained "offline" Last Will on the same connection, targeting a dedicated topic (e.g. `lan/poller/status`). If the poller process dies or loses its broker connection, the broker automatically publishes the offline will — even though every device's last retained status message still says whatever it last said. This is the standard MQTT idiom for detecting "the publisher itself is gone," and it is *not* redundant with per-device staleness: a poller can stay connected to MQTT while its Livestatus link to Checkmk has failed, so both checks matter.

**The critical correctness point:** MQTT retained messages never expire on their own. A dashboard that only trusts the retained `status` payload's *content* (not its age) will show a fully green board forever after the poller crashes. This is the single most important pitfall to design against up front — it should be treated as a table-stakes requirement, not an afterthought.

### What's a sane minimal event/history retention model for a browser-only (no backend) app?

Given the architecture already commits to bounded, retained MQTT topics (`lan/devices/{id}/history`, `lan/events/recent`) maintained **server-side by the poller** (a ring buffer of, e.g., the last 20-50 transitions per device and last 100-200 events globally):

- **The browser needs no persistent storage at all.** No `localStorage`, no `IndexedDB`, no client-side database. On every page load or reconnect, subscribing to the retained history/events topics immediately rehydrates the full bounded history from the broker — that's the specific advantage of using MQTT retained messages as the persistence layer instead of reinventing one in the browser.
- The browser only needs an **in-memory** array/ring buffer matching the same bound as the server-side topic, purely for rendering (e.g., the history strip component). This avoids browser-storage quota issues, cross-tab sync headaches, and schema-migration concerns that come with `localStorage`/`IndexedDB`-based approaches — all common unnecessary complexity in DIY dashboards that try to "remember more than the backend does."
- Accept the one real trade-off: if the MQTT broker itself is restarted and loses its retained-message store before the poller republishes, there's a brief gap in history availability. For a LAN-local tool with a broker running in the same Compose stack as the poller, this is a negligible and acceptable risk — not worth solving with a database.

### Common DIY network dashboard mistakes to deliberately avoid

- **Retained-message staleness blindness** (above) — the most architecture-specific risk for this exact design.
- **Full-DOM-rebuild-on-every-message rendering** — causes flicker, lost scroll position, lost sort/filter state; already correctly identified and scoped against in PROJECT.md ("merge, don't rebuild").
- **Leaving force-directed physics simulation running indefinitely** on the topology map — burns CPU/battery on a display meant to be left open, and produces a non-deterministic, jittery layout on every reload. vis-network's documented `stabilization` events (`stabilizationIterationsDone`, `stabilized`) exist precisely so physics can be run once and then frozen — use them rather than leaving `physics.enabled: true` running forever.
- **Collapsing rich state into a single boolean** — Checkmk already distinguishes OK/WARN/CRIT/UNKNOWN/DOWN and downtime/acknowledgement; a dashboard that reduces this to plain up/down throws away information users already had and increases the "why is this red, it's just in scheduled maintenance" alert-fatigue problem documented as a common homelab-monitoring failure mode.
- **Treating shallow reachability as health** — not a direct risk here since Checkmk already performs real checks, but worth stating as a design principle: the dashboard should surface Checkmk's actual check state, not re-derive a cruder one (e.g., from raw ping) that discards signal.
- **Unauthenticated MQTT WebSocket exposure** — a common DIY shortcut ("just open the WebSocket listener to everyone") that lets any LAN client subscribe to (or, worse, publish/corrupt) retained state; scope a read-only ACL for browser subscribers.
- **Polling intervals mismatched to the underlying data source** — publishing/re-rendering far more often than Checkmk's own check interval adds load and false precision without adding freshness; the poll interval should track Checkmk's actual check cadence.
- **Building a stateful topology editor without a backend to persist it** — a natural-feeling feature request that silently fails (arrangement lost on reload) or forces scope creep into adding a backend; addressed above as an anti-feature.

## Sources

- [MQTT Essentials: Last Will and Testament — HiveMQ](https://www.hivemq.com/blog/mqtt-essentials-part-9-last-will-and-testament/) — MEDIUM confidence (vendor blog, but describes the standard protocol-level mechanism consistently with the MQTT spec)
- [Using MQTT for Availability and Retained State — Albert Nisbet](https://albert.nz/mqtt-availability-retained-state) — MEDIUM confidence, corroborates the birth+will retained-topic pattern
- [Home Assistant MQTT Sensor docs — `expire_after`](https://www.home-assistant.io/integrations/sensor.mqtt/) — HIGH confidence, official docs confirming the expire-after/staleness convention in a widely-deployed MQTT consumer
- [Home Assistant MQTT Binary Sensor docs — availability topics/birth-will](https://www.home-assistant.io/integrations/binary_sensor.mqtt/) — HIGH confidence, official docs
- Context7 `/mqttjs/mqtt.js` official README docs — HIGH confidence: confirms `reconnectPeriod` (fixed-interval, not exponential by default) and the `will` connection option shape
- Context7 `/visjs/vis-network` official docs/examples — HIGH confidence: confirms `physics.stabilization` config and `stabilizationIterationsDone`/`stabilized` events for freezing layout after initial settle
- [The Biggest Monitoring Mistake Most Home Labs Make](https://bleevht.substack.com/p/the-biggest-monitoring-mistake-most) — LOW-MEDIUM confidence (single blog, but consistent with well-known alert-fatigue/false-confidence patterns cited across multiple sources)
- General PRTG/Zabbix/Icinga/Nagios "unknown/stale sensor" conventions — MEDIUM confidence, based on training-data knowledge of these tools' documented sensor-state models (grey/unknown as a distinct third state alongside up/down); not independently re-verified against each tool's current docs in this pass — flag as worth a quick spot-check if precise threshold defaults matter later
- `.planning/PROJECT.md` — project-specific scope, decisions, and existing architecture (primary source for what's already decided vs. open)

---
*Feature research for: minimal MQTT-based LAN topology/status dashboard (checkmk-wizard subsequent milestone)*
*Researched: 2026-09-05*
