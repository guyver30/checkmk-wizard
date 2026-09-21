# Phase 12: Agent Metrics and Service Status - Context

**Gathered:** 2026-09-21
**Status:** Ready for planning

<domain>
## Phase Boundary

The dashboard's per-device drill-down (`DetailsRoute.tsx`) gains live agent-derived metrics
(CPU/RAM/disk gauges, disk-health/SMART) and a per-service status list, sourced from a new
Livestatus `GET services` query the poller does not currently issue (it issues only `GET
hosts` today). This phase also amends the PROJECT.md Out of Scope entry that currently
forbids duplicating Checkmk's per-service drill-down UI — this phase partially reverses it
by design (ROADMAP scope item 6).

Out of this phase: the vis-network topology map and `parents` wizard support (Phase 13);
SNMP-sourced CPU/RAM/service metrics for non-Linux devices (raised during discussion, not
in scope here — see Deferred); time-series graphing of any metric (permanently out of scope
per PROJECT.md, no time-series database exists).

</domain>

<decisions>
## Implementation Decisions

### Disk & Systemd Scope (carried forward — locked before this discussion, STATE.md 2026-09-12)

- **D-01:** Disk gauge shows `Filesystem /` as the headline (`fs_used_percent`, warn/crit
  80;90 read from perf_data), plus a badge carrying the worst `fs_used_percent` across all
  OTHER mount points on that host. Checkmk emits one `Filesystem <mount>` service per mount
  (live-verified on agent-test 2026-09-12), so the poller's services query must return every
  `Filesystem *` service, not just `/`.
- **D-02:** The per-service list (see below) and any systemd-derived data show ONLY the
  individual systemd services the operator selected during the wizard's Phase 5 "Which
  running services should be actively monitored?" prompt — never the `Systemd Service
  Summary` roll-up. The poller has no access to wizard state, but doesn't need it: Checkmk
  only creates a `Systemd Service <name>` service for wizard-chosen services, so the chosen
  set is derivable from Livestatus alone by filtering `description ~ ^Systemd Service `
  and excluding the literal `Systemd Service Summary`. Live-verified 2026-09-12 (operator
  picked cron, ModemManager, open-vm-tools; exactly those three appeared alongside Summary).

### CPU/RAM Gauges

- **D-03:** When a device has no CPU utilization or Memory service data (SNMP-only/ping-only
  devices today), hide that specific gauge — per-gauge, not all-or-nothing for the row. A
  device missing only CPU shows RAM + Disk; Disk (per D-01) exists on nearly every Linux
  host so in practice most hosts show all three. The rule is driven by "does this service
  exist" rather than "is this a Linux host," so it degrades correctly once SNMP-based
  CPU/RAM checks exist in a future phase (raised by the user during discussion — see
  Deferred) without needing to be revisited.
- **D-04:** Gauge ring color for CPU and RAM reads warn/crit thresholds from the service's
  own `perf_data`, consistent with D-01's disk gauge — NOT the Checkmk service's own
  OK/WARN/CRIT state. (Exact `perf_data` field names/shape for Checkmk's "CPU utilization"
  and "Memory" services on this project's target Linux agent are not yet live-verified —
  flag for research, same live-verification process D-01 went through on agent-test.)

### SMART Disk-Health Display

- **D-05:** SMART status is NOT its own 4th gauge (the DMC-server.png reference only shows
  3). It renders as a worst-of-all-disks badge next to the Disk gauge, mirroring D-01's
  "headline gauge + worst-of badge" pattern. Checkmk creates one `Smart <device>` service
  per physical disk (e.g. `/dev/sda`, `/dev/sdb`) — separate from `Filesystem *` services.
- **D-06:** The SMART badge is hidden entirely (not shown as N/A) when a host has no `Smart
  <device>` services at all — VMs with virtual disks, or hosts where smartmontools setup
  was skipped/failed during onboarding. Same hide-on-absence rule as D-03.
- **D-07:** When at least one disk is failing, the badge reads `"SMART: Fail"` plus a count,
  e.g. `"SMART: 1/2 disks failing"`. Exact wording for the all-pass case (e.g. whether to
  show a count there too, like `"SMART: Pass (2/2)"` vs. bare `"SMART: Pass"`) is Claude's
  discretion.

### Per-Service Status List

- **D-08:** The list shows every service Checkmk currently has for the host (PING, the
  wizard-chosen systemd services per D-02, and anything else the agent/wizard set up) MINUS
  the four services already surfaced as gauges/badges above (`Filesystem *`, `CPU
  utilization`, `Memory`, `Smart <device>`) — including OK rows, not filtered down to
  non-OK only. This is the full "what's being monitored" picture, not just a failure list.
- **D-09:** Each row shows service name + status badge + `plugin_output` text (e.g. "WARN -
  CPU load too high"), so the operator sees *why* without navigating further. Sorted
  worst-first: CRIT/WARN/UNKNOWN before OK.
- **D-10:** Rendered with `kone-design-system`'s existing `Table` component (exported
  alongside `StatusBadge`, `ProgressBar`, `ProgressCircle` — see Code Context), not a custom
  row list like `EventHistory.tsx`.

### MQTT Topic & Publish Cadence

- **D-11:** A new retained topic per device, `lan/devices/{id}/services`, mirrors the
  existing `lan/devices/{id}/status` / `lan/devices/{id}/history` per-device convention.
  It carries the per-service list from D-08 (the non-gauge services) — NOT the gauge values,
  per D-12's split.
- **D-12:** Gauge-backing values (CPU%, RAM%, Filesystem `fs_used_percent`, SMART worst-of
  pass/fail) are added as fields to the EXISTING `lan/devices/{id}/status` payload, which
  already republishes every poll cycle — keeping gauges visually live without a new
  every-cycle topic. `lan/devices/{id}/services` (the D-08 list) republishes only when its
  contents actually change. This split was chosen specifically to solve the cadence concern
  flagged in ROADMAP.md (~21 hosts × ~20 services ≈ 420 rows/cycle would be too much to
  publish on every cycle if it also carried volatile gauge numbers).
- **D-13:** A "change" that triggers a `lan/devices/{id}/services` republish is a service's
  state (OK/WARN/CRIT/UNKNOWN) changing, or the service set itself changing (added/removed)
  — NOT `plugin_output` text drift alone (a chatty check's embedded numbers could otherwise
  cause a republish almost every cycle, reintroducing the row-count problem D-12 solves).
  This mirrors the existing `topology_signature()` change-detection technique in
  `scripts/mqtt_poller.py` (diff a signature of current vs. previous state, publish only on
  difference).
- **D-14:** A bounded per-service transition history IS wanted (the user chose this over the
  simpler snapshot-only recommendation) — this is new work beyond what ROADMAP.md scoped.
  It lives on its own new topic, `lan/devices/{id}/service_history`, kept separate from the
  existing device-level `lan/devices/{id}/history` so neither topic's bounded cap has to
  share space with a very different transition rate, and existing history-consuming code
  (`EventHistory.tsx`, `lan/events/recent`) doesn't need to filter entry types.

### Claude's Discretion

- Exact `perf_data` field names for Checkmk's "CPU utilization" and "Memory" services —
  needs live-verification against the target agent-test host during research/planning, the
  same way D-01's `fs_used_percent`/80;90 shape was verified.
- SMART badge's all-pass wording (bare "SMART: Pass" vs. "SMART: Pass (2/2)").
- Bounded history length for the new `service_history` topic — reuse whatever constant
  backs the existing `append_bounded()` calls for device history/events unless research
  finds a reason to differ.
- Exact amended wording for PROJECT.md's "Duplicating Checkmk's own per-service drill-down
  UI" Out of Scope entry (ROADMAP scope item 6) — mechanical documentation update, not a
  design decision.

</decisions>

<specifics>
## Specific Ideas

- `docs/DMC-server.png` is the explicit visual reference: three circular gauges (CPU/RAM/
  Disk) above a two-tab panel (SERVICES / HISTORY). This phase's SMART badge and per-service
  list correspond to the "SERVICES" side; the existing bounded transition-history strip
  (already built in a prior phase) corresponds to "HISTORY". The reference's "Real-time
  System Process" table (per-process CPU/RAM) and the "Memory Usage (7 day)" time-series
  chart are NOT being built — no process-level data source exists, and time-series
  graphing is permanently out of scope per PROJECT.md.
- The "explain why a host is red" framing (ROADMAP scope item 4) is realized literally: the
  service list's `plugin_output` column (D-09) is meant to answer that question without a
  click-through to Checkmk's own UI.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & prior decisions
- `.planning/ROADMAP.md` §"Phase 12: Agent Metrics and Service Status" — the 6-item scope
  list this phase must cover, including the explicitly-flagged-open cadence question (item 5)
  this discussion resolved as D-12/D-13/D-14.
- `.planning/STATE.md` §"Decisions" — D-01 and D-02 (Phase 12 disk/systemd scope), locked
  2026-09-12 before this discussion session; carried forward verbatim above.
- `.planning/phases/11-live-dashboard/11-CONTEXT.md` §"Deferred Ideas" ("To Phase 12") —
  the original hand-off note this phase was split out of, including the cadence concern and
  the `docs/DMC-server.png` reference.
- `.planning/PROJECT.md` §"Out of Scope" — the "Duplicating Checkmk's own per-service
  drill-down UI" entry this phase partially reverses and must amend on completion.

### Poller (Python)
- `scripts/mqtt_poller.py` — existing structure to extend:
  - `available_host_columns()` / `select_host_columns()` / `build_hosts_query()`
    (lines ~527-573) — defensive column-availability pattern; a services equivalent
    (`available_service_columns` / `build_services_query`) should follow the same shape.
  - `query_devices()` (line 576) — the `GET hosts` round-trip to parse; a parallel
    `query_services()` is the new work for scope item 1.
  - `topology_signature()` (line 398) — existing change-detection technique; the same
    approach should back D-13's state-change-only republish logic.
  - `append_bounded()` (line 380) — existing bounded-list helper, reusable for D-14's new
    per-service history.
  - `_publish_json()` (line 724) and the `TOPIC_*` constants (lines 71-73) — the single
    choke point for all MQTT publishes; new topics/publish functions should follow this
    pattern, not call the client directly.
  - `publish_topology()` / `publish_history()` (lines 762-773) — direct analogs for the new
    `publish_services()` / `publish_service_history()` functions this phase adds.

### Dashboard (React)
- `dashboard-react/src/routes/DetailsRoute.tsx` — current bare stub (`?id=` param, no
  content); this phase fills it in.
- `dashboard-react/src/store/mqttClient.ts` §`SUBSCRIBE_TOPICS` (line ~30) — the wildcard
  topic list to extend with `lan/devices/+/services` and `lan/devices/+/service_history`.
- `dashboard-react/src/store/useAppStore.ts` — needs new per-device state slices for
  services and service history, following whatever pattern the existing status/history
  slices use.
- `dashboard-react/src/components/StateBadge.tsx` + `dashboard-react/src/lib/stateMapping.ts`
  — existing state→color/variant/icon mapping; the per-service list's `StatusBadge` usage
  (D-10) should follow the same color logic for consistency, even though the gauges
  themselves (D-04) intentionally do NOT use this state-based mapping.

### Design system exports (confirmed present)
- `design-system/src/components/index.ts` / `design-system/dist/index.d.ts` — confirms
  `ProgressBar`, `ProgressCircle`, `Table`, `StatusBadge` are already built and exported
  from the `kone-design-system` package `dashboard-react` depends on
  (`dashboard-react/package.json`: `"kone-design-system": "file:../design-system/..."`).
  No new design-system components need to be built for this phase's gauges/list.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `kone-design-system`'s `ProgressCircle` (ring gauge with center value) — direct fit for
  the CPU/RAM/Disk gauges; already used nowhere in `dashboard-react` yet, this is its first
  consumer.
- `kone-design-system`'s `Table` + `StatusBadge` — direct fit for the per-service list (D-10).
- `scripts/mqtt_poller.py`'s `_livestatus_request()` (line 439) — the single TCP/LQL
  round-trip function; a `GET services` query is just a new query string through the same
  function, no new transport code needed.
- `append_bounded()` and `topology_signature()` — both directly reusable for D-13/D-14
  without modification to their signatures, just new call sites.

### Established Patterns
- One Livestatus query → one typed parse function → one or more `publish_*` functions, all
  funneling through `_publish_json()`. New services/service-history work should add
  `query_services()` and `publish_services()`/`publish_service_history()` following this
  exact shape rather than inlining logic into `run_cycle()`.
- "Publish only on change" is already proven for topology (`topology_signature()` diffs a
  hash of current vs. previous state); D-13 reuses this exact technique rather than
  inventing a new diffing approach.
- Dashboard state mapping is centralized in `stateMapping.ts` / `badgeForState()` — any new
  UI element that shows a Checkmk state (the per-service list's badges) should read from
  this table rather than hand-rolling color logic.

### Integration Points
- `run_cycle()` in `scripts/mqtt_poller.py` is where the new `GET services` query and its
  publish calls get wired in alongside the existing `GET hosts` cycle.
- `DetailsRoute.tsx` is the sole UI integration point — currently unstyled, needs the gauge
  row, SMART badge, and service Table added.
- `mqttClient.ts`'s `SUBSCRIBE_TOPICS` and `useAppStore.ts`'s message-handling switch are
  where the two new topics get wired into the frontend's single MQTT choke point.

</code_context>

<deferred>
## Deferred Ideas

- SNMP-sourced CPU/RAM (and potentially other) metrics for non-agent devices (network
  devices, ACS controllers) — raised by the user during the CPU/RAM gauge discussion. Not
  in this phase's scope (Phase 12's `GET services` work targets Linux-agent hosts). D-03's
  "hide on absence, not on device type" fallback rule was deliberately chosen so this can
  land later without revisiting the gauge-hiding logic. No phase currently owns this; flag
  for roadmap consideration.

### Permanently out of scope (reaffirmed, not re-litigated this session)
- Time-series graphing of any metric (PROJECT.md) — the DMC-server.png reference's "Memory
  Usage (7 day)" chart is explicitly not being built.
- Per-process CPU/RAM breakdown (the reference's "Real-time System Process" table) — no
  process-level data source exists in this project's Checkmk agent setup.
- The vis-network topology map and wizard `parents` support — Phase 13, unrelated to this
  phase's scope.

</deferred>

---

*Phase: 12-agent-metrics-and-service-status*
*Context gathered: 2026-09-21*
