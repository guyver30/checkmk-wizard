# Roadmap: checkmk-wizard — MQTT Bridge & Live Dashboard Milestone

## Overview

The existing 7-phase wizard (Phase 1–7, already Validated and out of this milestone's scope) takes a bare Checkmk install to a fully onboarded, monitored network. This milestone bolts on a live view of that network: a resilient MQTT broker, a Livestatus-polling bridge that publishes per-device retained state, a small Checkmk tagging addition so devices carry a type and VLAN, and a static backend-less dashboard that renders it all in real time. The build order follows the project's chosen **Horizontal Layers** structure — broker infrastructure hardened first (persistence + ACLs from day one, not retrofitted), then the poller's topic contract and Livestatus-diff resilience, then the Checkmk tag-group/onboarding integration, and finally the dashboard, which is a pure consumer of the poller's contract and is therefore built last.

## Phases

**Phase Numbering:**
- Continues from the existing wizard's Phase 1–7 (Validated, out of scope for this milestone) — new work starts at Phase 8.
- Integer phases (8, 9, 10, 11): Planned milestone work.
- Decimal phases (8.1, 8.2): Urgent insertions (marked with INSERTED).

- [ ] **Phase 8: Broker Infrastructure Hardening** - Mosquitto gains a durable, access-controlled WebSockets listener alongside its existing internal TCP listener
- [ ] **Phase 9: Poller Core** - A resilient Livestatus-to-MQTT poller publishes the per-device topic contract and self-heals across restarts
- [ ] **Phase 10: Checkmk Tag-Group & Onboarding Integration** - A device-type host tag and folder-derived VLAN are wired into the wizard's onboarding flow
- [ ] **Phase 11: Live Dashboard** - A static 3-page dashboard renders topology, device status, and history live from the poller's MQTT contract

## Phase Details

### Phase 8: Broker Infrastructure Hardening
**Goal**: The MQTT broker is durable and access-controlled, ready to serve both the poller and browser clients before either is built against it
**Depends on**: Nothing (first phase of this milestone; existing wizard Phase 1-7 already Validated)
**Requirements**: BRK-01, BRK-02, BRK-03
**Success Criteria** (what must be TRUE):
  1. A browser-based MQTT client (e.g. `mosquitto_sub -L ws://...` or `mqtt.js`) can connect over a WebSockets listener that is distinct from the existing internal TCP listener the poller uses to publish
  2. Restarting the mosquitto container preserves previously retained messages, because `persistence true` is set against a mounted volume
  3. The WebSocket listener enforces a read-only ACL — a WS client can subscribe to any topic but a publish attempt is rejected; only the poller's internal TCP connection can publish
  4. `compose.yaml` exposes the new WebSockets port to the LAN alongside the existing `1883` port
**Plans**: TBD

### Phase 9: Poller Core
**Goal**: A long-running poller keeps MQTT retained state in sync with Checkmk Livestatus, self-healing across restarts with no persisted state of its own required
**Depends on**: Phase 8
**Requirements**: PLR-01, PLR-02, PLR-03, PLR-04, PLR-05, PLR-06, PLR-07, PLR-08
**Success Criteria** (what must be TRUE):
  1. `mosquitto_sub` on `lan/devices/+/status` shows retained per-device status with full OK/WARN/CRIT/UNKNOWN/DOWN granularity, a timestamp, and downtime/acknowledgement flags, republished every poll cycle
  2. Restarting the poller process does not cause an incorrect republish storm — status matches Livestatus's live current state each cycle, not the poller's own in-memory history
  3. `lan/devices/topology` republishes only when a host is added, removed, or reparented; unrelated poll cycles produce no new topology publish
  4. Deleting a host from Checkmk produces empty tombstone payloads on its `lan/devices/{id}/status` and `lan/devices/{id}/history` topics within one poll cycle, and it disappears from `lan/devices/topology`; bounded `lan/devices/{id}/history` and `lan/events/recent` feeds append only on actual state transitions
  5. `lan/poller/status` carries a birth message on poller startup and moves to an offline/LWT state when the poller process dies ungracefully
**Plans**: TBD

### Phase 10: Checkmk Tag-Group & Onboarding Integration
**Goal**: Checkmk captures device type per host and VLAN is reliably derived from folder structure, without silently mis-tagging existing hosts
**Depends on**: Nothing beyond the existing wizard (technically independent of Phase 9's poller; sequenced third per this milestone's chosen horizontal-layer build order so real device-type/VLAN data exists before dashboard integration testing)
**Requirements**: TAG-01, TAG-02, TAG-03
**Success Criteria** (what must be TRUE):
  1. A new `device_type` host tag group exists in Checkmk with values including server/switch/router/iot/etc., and every pre-existing host is defaulted to a neutral `unknown` value rather than a real device type
  2. Running the wizard's Phase 5 onboarding flow prompts for device type per host, and the tag is set via a REST API attribute shape (`tag_<group_id>`) verified against a live Checkmk 2.4.0p35 site
  3. A host's VLAN value is derived from its Checkmk folder path via the REST API's structured folder segments (not raw string splitting), correctly reflecting nested folder moves
  4. Existing wizard Phase 5 onboarding tests still pass with the new tag prompt added
**Plans**: TBD

### Phase 11: Live Dashboard
**Goal**: A static, backend-less dashboard renders live Checkmk-derived topology, device status, and history purely by consuming the poller's MQTT contract
**Depends on**: Phase 8, Phase 9, Phase 10
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04, DASH-05, DASH-06
**Success Criteria** (what must be TRUE):
  1. `index.html` renders a live topology map (vis-network) with parent/child links, an at-a-glance stats-by-state strip, and nodes color-coded/icon-coded by device type and grouped/colored by VLAN; incoming updates merge via `DataSet.update()` without a full re-render
  2. `devices.html` shows a live sortable device table and a recent-events panel that update in place as MQTT messages arrive
  3. `details.html` shows a per-device drill-down with a bounded status-history strip and a link out to Checkmk's own UI for that host
  4. A device whose last-seen timestamp exceeds a staleness threshold, or whose poller liveness signal (`lan/poller/status`) is stale, is shown in a distinct stale/unknown visual state separate from "down"
  5. The dashboard shows a connection-status indicator and reconnects with jittered exponential backoff when the MQTT-over-WebSockets connection drops
**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 8 → 9 → 10 → 11

| Phase | Plans Complete | Status | Completed |
|-------|-----------------|--------|-----------|
| 8. Broker Infrastructure Hardening | 0/TBD | Not started | - |
| 9. Poller Core | 0/TBD | Not started | - |
| 10. Checkmk Tag-Group & Onboarding Integration | 0/TBD | Not started | - |
| 11. Live Dashboard | 0/TBD | Not started | - |
