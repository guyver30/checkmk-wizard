# Requirements: checkmk-wizard — MQTT Bridge & Live Dashboard Milestone

**Defined:** 2026-09-05
**Core Value:** A single Python-based toolchain takes a bare Checkmk install all the way to a fully onboarded, monitored network — and now also to a live, at-a-glance visual picture of that network's topology and health, without needing to duplicate Checkmk's own UI.

## v1 Requirements

### Poller

- [x] **PLR-01**: Poller connects to Checkmk Livestatus over TCP on a configurable interval and queries current host state, service-state summary counts, tags, and parent/folder info
- [x] **PLR-02**: Poller diffs against Livestatus's live current state each cycle (not its own in-memory history), so it self-heals across restarts with no persisted state required
- [x] **PLR-03**: Poller publishes per-device retained status to `lan/devices/{id}/status` every cycle, preserving Checkmk's OK/WARN/CRIT/UNKNOWN/DOWN granularity (not collapsed to plain up/down), including a timestamp for staleness detection
- [x] **PLR-04**: Poller publishes retained topology to `lan/devices/topology` only when topology actually changes (host added/removed/reparented)
- [x] **PLR-05**: Poller publishes a bounded per-device transition history (`lan/devices/{id}/history`) and a bounded global recent-events feed (`lan/events/recent`), appending only on actual state transitions
- [x] **PLR-06**: Poller publishes empty/tombstone retained payloads for devices removed from Checkmk, clearing their status/history/topology entries so they don't persist as permanent ghosts
- [x] **PLR-07**: Poller publishes a birth/Last-Will-and-Testament liveness signal on `lan/poller/status`, so the dashboard can distinguish "the poller itself is down" from "this device is down"
- [x] **PLR-08**: Poller surfaces Checkmk downtime/acknowledgement state in the per-device status payload
- [x] **PLR-09**: Poller issues a `GET services` Livestatus query alongside its existing `GET hosts` query, behind the same defensive column-availability probe, and parses each service's Nagios-format `perf_data` server-side (never in the browser)
- [x] **PLR-10**: Poller adds gauge-backing values (CPU utilisation %, memory used %, `Filesystem /` used %, worst other-mount used %, SMART pass/fail counts) as additive keys on the existing every-cycle `lan/devices/{id}/status` payload
- [x] **PLR-11**: Poller publishes the per-host non-gauge service list (name, state, `plugin_output`) on a new retained `lan/devices/{id}/services` topic, republished only when a service's state or the service set itself changes — never on `plugin_output` text drift
- [x] **PLR-12**: Poller publishes a bounded per-service transition history on `lan/devices/{id}/service_history`, kept separate from the device-level `lan/devices/{id}/history` topic, and tombstones both new topics when a device is removed
- [x] **PLR-13**: Poller adds each host's saved map position and unmanaged-switch marker (read from Checkmk host labels through its existing once-per-cycle REST `host_config` lookup) to the `lan/devices/topology` node shape and to the topology change-detection signature, so every dashboard viewer sees the same saved layout without holding a Checkmk credential

### Broker

- [ ] **BRK-01**: Mosquitto gains a WebSockets listener for browser clients, separate from the existing internal TCP listener the poller uses to publish
- [ ] **BRK-02**: Mosquitto has `persistence true` against a mounted volume, so retained state survives a broker restart
- [ ] **BRK-03**: The WebSocket listener is ACL-scoped to read-only for browser clients; only the poller (via the internal listener) can publish

### Tagging

- [x] **TAG-01**: A new Checkmk host tag group captures device type, with a config-driven, site-specific choice list and a neutral `other` value in first position, so pre-existing hosts aren't silently mis-tagged when the tag group is created
- [x] **TAG-02**: The wizard's Phase 4 classification flow prompts for the device type per host, and Phase 5 onboarding applies it, using an attribute shape verified against a live Checkmk site's REST API
- [x] **TAG-03**: A generic location/group label is derived from the host's Checkmk folder association via the REST API's structured folder segments (not raw string splitting), and consumed by the poller
- [x] **TAG-04**: An operator can bulk-correct device type and alias on already-onboarded hosts, folder-scoped and independent of the promotion flow, so hosts onboarded before the tag group existed do not stay at the neutral `other` value

### Operations

- [x] **OPS-01**: The `worker` compose service carries the same `CMK_REST_*` environment block as the `poller` service, so wizard re-runs and the probe script read credentials from the environment rather than a hand-pasted secret
- [x] **OPS-02**: The automation secret generated on a first wizard run is displayed to the operator when it is created, sufficient to populate `deploy/.env` without shelling into the `checkmk` container
- [x] **OPS-03**: The poller survives a transient Livestatus outage at startup via a bounded retry rather than exiting immediately; the REST credential's enrichment-only, always-degrade posture is deliberately retained (Livestatus is the sole mandatory data source per Phase 10 D-03) and the asymmetry is justified in-source
- [x] **OPS-04**: A successful poller start emits a log line naming the site, poll interval, and broker, so a healthy poller is distinguishable from a hung one in container logs

### Dashboard

- [x] **DASH-01**: `index.html` shows an at-a-glance stats strip (counts by state) above the centre's primary view, merging incoming updates in place rather than re-rendering from scratch. The primary view is the topology map (DASH-07, Phase 13); until that lands it is a sized, labelled placeholder pane
- [ ] **DASH-02**: `devices.html` shows a live sortable device table plus a recent-events panel, updating in place
- [x] **DASH-03**: `details.html` shows a per-device drill-down with a bounded status-history strip, linking out to Checkmk's own UI for full service-level detail
- [ ] **DASH-04**: Dashboard shows a distinct stale/unknown visual state (separate from down) when a device's last-seen timestamp exceeds a threshold, or when the poller's own liveness signal goes stale
- [ ] **DASH-05**: Dashboard shows a connection-status indicator with jittered exponential-backoff reconnect for the MQTT-over-WebSockets connection
- [x] **DASH-06**: Dashboard color-codes/icons hosts by device type and groups/colors by the folder-derived location/group label
- [x] **DASH-07**: `index.html` renders a live topology map (vis-network) with parent/child links, merging incoming updates via `DataSet.update()` rather than re-rendering from scratch
- [x] **DASH-08**: The per-device drill-down renders CPU / RAM / Disk ring gauges whose colour is decided by each metric's OWN `perf_data` warn/crit thresholds (not the Checkmk service state), hiding any individual gauge whose backing service does not exist on that host
- [x] **DASH-09**: The per-device drill-down renders a worst-of-all-disks SMART badge next to the Disk gauge, hidden entirely (not shown as N/A) when the host has no SMART health service
- [x] **DASH-10**: The per-device drill-down renders a per-service status table (service name, state badge, `plugin_output`) covering every service except the gauge-backed ones, sorted worst-first, so an operator can see *why* a host is red without leaving the dashboard
- [x] **DASH-11**: Device rows in the fleet tree navigate to that device's drill-down (`/details?id={id}`), so the drill-down is reachable without hand-typing a URL
- [x] **DASH-12**: While an explicit "Edit topology" mode is switched on (off by default), an operator can draw, reconnect and delete parent/child links and drag host positions on the topology map. Each edit is written to Checkmk's REST API (the `parents` host attribute and a `map_position` host label) with a dedicated, narrowly-scoped automation credential, and goes live only when the operator presses a single "Apply changes" action that runs Checkmk's Activate Changes
- [x] **DASH-13**: From the same edit mode, an operator can add an unmanaged LAN switch as a real Checkmk host (one host per switch) configured so Checkmk runs no checks against it, so it carries parents and a map position like any other host but never raises WARN/CRIT

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Dashboard Polish

- **DASH2-01**: Mobile-responsive layout polish
- **DASH2-02**: Search/filter box on the device table

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| MAC address collection for topology nodes | Not reliably available without Checkmk's HW/SW inventory plugin; would add a new subsystem dependency for one field |
| Checkmk notification rules as the live-update delivery mechanism | Requires deploying scripts into the `checkmk` container's own OMD filesystem, breaking the worker/checkmk container-mode boundary |
| Duplicating Checkmk's per-service *configuration/administration* UI in the new dashboard | Partially reversed 2026-09-21 (Phase 12, DASH-08..DASH-10): a read-only per-service status list and agent metric gauges ARE now in scope, because "why is this host red" could not be answered without them. What stays out is everything beyond read-only status — rule editing, downtime scheduling, acknowledgement, discovery and any other write action remains Checkmk's own UI's job |
| Time-series graphing/charting | No time-series database; a bounded transition-history strip is sufficient for v1's "dig deeper" need |
| In-dashboard alerting/notifications | Checkmk already owns alerting; this dashboard is visualization-only |
| Editable device metadata (alias, device type, folder) in the dashboard | Partially reversed 2026-09-23 (Phase 13, DASH-12/DASH-13): topology editing (parent/child links, map positions, adding unmanaged switches) IS now in scope, persisted in Checkmk's own config via its REST API with no new backend. Editing any other host metadata stays Checkmk's (and the wizard's) job |
| Multi-user accounts/login | Static, backend-less dashboard on a trusted LAN; broker-level ACL is the only access control layer |
| Full L2/LLDP/SNMP auto-discovery of topology | Out of scope for this milestone — parent/child links come from Checkmk's existing `parents` configuration |
| Client-side HTTP polling fallback | MQTT-over-WebSockets is the only transport; no backend exists to poll |
| Browser-side history persistence (localStorage/IndexedDB) | MQTT retained messages already are the persistence layer — no need to duplicate it client-side |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| BRK-01 | Phase 8 | Pending |
| BRK-02 | Phase 8 | Pending |
| BRK-03 | Phase 8 | Pending |
| PLR-01 | Phase 9 | Complete |
| PLR-02 | Phase 9 | Complete |
| PLR-03 | Phase 9 | Complete |
| PLR-04 | Phase 9 | Complete |
| PLR-05 | Phase 9 | Complete |
| PLR-06 | Phase 9 | Complete |
| PLR-07 | Phase 9 | Complete |
| PLR-08 | Phase 9 | Complete |
| TAG-01 | Phase 10 | Complete |
| TAG-02 | Phase 10 | Complete |
| TAG-03 | Phase 10 | Complete |
| TAG-04 | Phase 10.1 | Complete |
| OPS-01 | Phase 10.1 | Complete |
| OPS-02 | Phase 10.1 | Complete |
| OPS-03 | Phase 10.1 | Complete |
| OPS-04 | Phase 10.1 | Complete |
| DASH-01 | Phase 11 | Complete |
| DASH-02 | Phase 11 | Pending |
| DASH-03 | Phase 11 / Phase 12 | Partial |
| DASH-04 | Phase 11 | Pending |
| DASH-05 | Phase 11 | Pending |
| DASH-06 | Phase 11 | Complete |
| DASH-07 | Phase 13 | Complete |
| DASH-12 | Phase 13 | Complete |
| DASH-13 | Phase 13 | Complete |
| PLR-13 | Phase 13 | Complete |
| PLR-09 | Phase 12 | Complete |
| PLR-10 | Phase 12 | Complete |
| PLR-11 | Phase 12 | Complete |
| PLR-12 | Phase 12 | Complete |
| DASH-08 | Phase 12 | Complete |
| DASH-09 | Phase 12 | Complete |
| DASH-10 | Phase 12 | Complete |
| DASH-11 | Phase 12 | Complete |

**Coverage:**
- v1 requirements: 31 total
- Mapped to phases: 31 ✓
- Unmapped: 0

---
*Requirements defined: 2026-09-05*
*Last updated: 2026-09-05 after roadmap creation (Phases 8-11)*
*Split note (2026-09-12): DASH-01 originally conflated two deliverables — "a live topology map (vis-network)" and "an at-a-glance stats strip ... merging incoming updates". Phase 11's `/bm:discuss-phase` session moved the topology map out, because Checkmk's `parents` attribute is unset on the target site so an auto-built map would render as disconnected dots. The map half became **DASH-07**, owned by Phase 13 (Wizard Parents Support and Topology Map), which first teaches the wizard to populate `parents`. DASH-01 keeps the stats-strip half, now paired with the grouped fleet overview that occupies `index.html` until the map lands. DASH-06's "nodes" was reworded to "hosts" in the same pass, since Phase 11 renders a tree and overview tiles rather than graph nodes. See `.planning/phases/11-live-dashboard/11-CONTEXT.md` (Scope Revision) and `11-DISCUSSION-LOG.md` (second session).*

*Re-wording note (2026-09-16): DASH-01's "a grouped fleet overview" became "the centre's primary view" when Phase 11.1 moved the event history into the centre and reserved the centre's main area for the topology map (decisions D-25 and D-27, `.planning/phases/11.1-dashboard-layout-and-light-palette/11.1-CONTEXT.md`). The stats strip, the "above", and the merge-in-place clause are unchanged, so the requirement is **re-worded, not re-scoped** — and stays verifiable in Phase 11.1 against the placeholder. `render-index.js`'s grouped fleet overview is superseded and deleted by D-27; Phase 13 (DASH-07) drops the real map into the placeholder's geometry.*

*Terminology note: TAG-01/02/03 and DASH-06 wording was reframed from "VLAN"/"unknown"/"Phase 5" to "location/group label"/"other"/"Phase 4 prompt, Phase 5 apply" during Phase 10's `/bm:discuss-phase` session, per decisions D-01, D-02, D-06 and D-07 (`.planning/phases/10-checkmk-tag-group-onboarding-integration/10-CONTEXT.md`).*

*Phase 12 requirement note (2026-09-21, added during `/bm:plan-phase 12`): Phase 12's ROADMAP entry carried `Requirements: TBD`. PLR-09..PLR-12 and DASH-08..DASH-11 were minted in this planning pass to cover the six prose scope items ROADMAP.md already describes for Phase 12, per `12-RESEARCH.md`'s "Phase Requirements" recommendation. **DASH-03 is deliberately marked Partial, not Complete**: Phase 12 delivers only its bounded per-device status-history-strip half (decision D-16). Its "linking out to Checkmk's own UI for full service-level detail" clause was explicitly declined for this phase (decision D-17) — `CHECKMK_BASE_URL`/`isCheckmkLinkConfigured()` already exist in `dashboard-react/src/lib/config.ts` for whenever that half is built. DASH-03 must not be flipped to Complete by Phase 12's verification. See `.planning/phases/12-agent-metrics-and-service-status/12-CONTEXT.md`.*

*Phase 13 requirement note (2026-09-23, added during `/bm:plan-phase 13`): ROADMAP.md's Phase 13 entry anticipated "requirement IDs covering the wizard's `parents` support". The discuss-phase session replaced that wizard-CLI approach with an in-dashboard topology editor (13-CONTEXT.md Scope Revision, D-01..D-07), so the minted IDs describe that instead: DASH-12 (edit mode, write-back, batched Apply), DASH-13 (unmanaged switches as check-free Checkmk hosts) and PLR-13 (the poller carries saved positions to every viewer). PLR-13 widens PLR-04's "host added/removed/reparented" trigger to also include a saved-position or unmanaged-marker change; the change-only publishing rule itself is unchanged. The "Drag-and-drop topology editing" Out of Scope row was narrowed in the same pass. See `.planning/phases/13-wizard-parents-support-and-topology-map/13-CONTEXT.md`.*
