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

### Broker

- [ ] **BRK-01**: Mosquitto gains a WebSockets listener for browser clients, separate from the existing internal TCP listener the poller uses to publish
- [ ] **BRK-02**: Mosquitto has `persistence true` against a mounted volume, so retained state survives a broker restart
- [ ] **BRK-03**: The WebSocket listener is ACL-scoped to read-only for browser clients; only the poller (via the internal listener) can publish

### Tagging

- [ ] **TAG-01**: A new Checkmk host tag group captures device type (server/switch/router/iot/etc.) with a neutral `unknown` default value, so pre-existing hosts aren't silently mis-tagged when the tag group is created
- [ ] **TAG-02**: The wizard's Phase 5 onboarding flow prompts for and sets the device-type tag per host, using an attribute shape verified against a live Checkmk site's REST API
- [ ] **TAG-03**: VLAN is derived from the host's Checkmk folder path via the REST API's structured folder segments, not raw string splitting

### Dashboard

- [ ] **DASH-01**: `index.html` shows a live topology map (vis-network) with an at-a-glance stats strip (counts by state), merging incoming updates via `DataSet.update()` rather than re-rendering from scratch
- [ ] **DASH-02**: `devices.html` shows a live sortable device table plus a recent-events panel, updating in place
- [ ] **DASH-03**: `details.html` shows a per-device drill-down with a bounded status-history strip, linking out to Checkmk's own UI for full service-level detail
- [ ] **DASH-04**: Dashboard shows a distinct stale/unknown visual state (separate from down) when a device's last-seen timestamp exceeds a threshold, or when the poller's own liveness signal goes stale
- [ ] **DASH-05**: Dashboard shows a connection-status indicator with jittered exponential-backoff reconnect for the MQTT-over-WebSockets connection
- [ ] **DASH-06**: Dashboard color-codes/icons nodes by device type and groups/colors by VLAN

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
| Duplicating Checkmk's per-service drill-down UI in the new dashboard | Link out to Checkmk's UI instead — this project isn't replacing Checkmk |
| Time-series graphing/charting | No time-series database; a bounded transition-history strip is sufficient for v1's "dig deeper" need |
| In-dashboard alerting/notifications | Checkmk already owns alerting; this dashboard is visualization-only |
| Drag-and-drop topology editing / editable device metadata | No backend to persist edits; topology and metadata are derived read-only from Checkmk |
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
| TAG-01 | Phase 10 | Pending |
| TAG-02 | Phase 10 | Pending |
| TAG-03 | Phase 10 | Pending |
| DASH-01 | Phase 11 | Pending |
| DASH-02 | Phase 11 | Pending |
| DASH-03 | Phase 11 | Pending |
| DASH-04 | Phase 11 | Pending |
| DASH-05 | Phase 11 | Pending |
| DASH-06 | Phase 11 | Pending |

**Coverage:**
- v1 requirements: 20 total
- Mapped to phases: 20 ✓
- Unmapped: 0

---
*Requirements defined: 2026-09-05*
*Last updated: 2026-09-05 after roadmap creation (Phases 8-11)*
