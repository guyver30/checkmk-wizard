# Roadmap: checkmk-wizard — MQTT Bridge & Live Dashboard Milestone

## Overview

The existing 7-phase wizard (Phase 1–7, already Validated and out of this milestone's scope) takes a bare Checkmk install to a fully onboarded, monitored network. This milestone bolts on a live view of that network: a resilient MQTT broker, a Livestatus-polling bridge that publishes per-device retained state, a small Checkmk tagging addition so devices carry a type and VLAN, and a static backend-less dashboard that renders it all in real time. The build order follows the project's chosen **Horizontal Layers** structure — broker infrastructure hardened first (persistence + ACLs from day one, not retrofitted), then the poller's topic contract and Livestatus-diff resilience, then the Checkmk tag-group/onboarding integration, and finally the dashboard, which is a pure consumer of the poller's contract and is therefore built last.

## Phases

**Phase Numbering:**

- Continues from the existing wizard's Phase 1–7 (Validated, out of scope for this milestone) — new work starts at Phase 8.
- Integer phases (8, 9, 10, 11): Planned milestone work.
- Decimal phases (8.1, 8.2): Urgent insertions (marked with INSERTED).

- [x] **Phase 8: Broker Infrastructure Hardening** - Mosquitto gains a durable, access-controlled WebSockets listener alongside its existing internal TCP listener
- [x] **Phase 9: Poller Core** - A resilient Livestatus-to-MQTT poller publishes the per-device topic contract and self-heals across restarts (completed 2026-09-09)
- [x] **Phase 10: Checkmk Tag-Group & Onboarding Integration** - A device-type host tag and a folder-derived location/group label are wired into the wizard's onboarding flow (completed 2026-09-11)
- [ ] **Phase 10.1: Bulk Device-Type Tagging and Deployment Gaps** (INSERTED) - Urgent insertion after Phase 10
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

**Plans**: 3 plans
Plans:
**Wave 1**

- [x] 08-01-PLAN.md — Broker config artifacts: mosquitto.conf (two listeners, auth, persistence), mosquitto.acl (read-only wsreader), reproducible password-file generator
- [x] 08-02-PLAN.md — Canonical deploy/compose.yaml (corrected /mosquitto/config mounts, WS on host 9002) + paho-mqtt dependency

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 08-03-PLAN.md — Live smoke test proving BRK-01/02/03, Podman setup doc repointed at deploy/ (all four checks PASSED on real deployment host)

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

**Plans**: 4 plans
Plans:
**Wave 1**

- [x] 09-01-PLAN.md — Poller foundation: env-var config, topic-injection guard, worst-of state aggregation, bounded-log/topology helpers, and the single-round-trip Livestatus JSON query layer with a live column probe

**Wave 2** *(blocked on Wave 1)*

- [x] 09-02-PLAN.md — MQTT layer: birth/LWT client lifecycle, the five publish helpers at their resolved QoS/retain, broker-retained startup reconciliation, and the poll cycle (transitions, tombstones, topology diff, heartbeat)

**Wave 3** *(blocked on Wave 2)*

- [x] 09-03-PLAN.md — Dedicated `poller` compose service, `scripts/smoke_test_poller.py` live verification script, and Podman setup doc coverage of the service, topic contract and smoke test

**Wave 4** *(blocked on Wave 3)*

- [x] 09-04-PLAN.md — Live verification on the deployment host (blocking checkpoint), then record the confirmed Livestatus column set in-source and apply any corrections

### Phase 10: Checkmk Tag-Group & Onboarding Integration

**Goal**: Checkmk captures device type per host and a location/group label is reliably derived from folder structure, without silently mis-tagging existing hosts
**Depends on**: Nothing beyond the existing wizard (technically independent of Phase 9's poller; sequenced third per this milestone's chosen horizontal-layer build order so real device-type/location data exists before dashboard integration testing)
**Requirements**: TAG-01, TAG-02, TAG-03
**Success Criteria** (what must be TRUE):

  1. A new `device_type` host tag group exists in Checkmk with a config-driven, site-specific choice list, and every pre-existing host is defaulted to the neutral `other` value (listed first in the group) rather than a real device type
  2. The wizard's Phase 4 classification flow prompts for device type per host, Phase 5 onboarding applies it, and the tag is set via a REST API attribute shape (`tag_<group_id>`) verified against a live Checkmk 2.4.0p36 site
  3. A host's location/group label is derived from its Checkmk folder association via the REST API's structured folder segments (not raw string splitting), correctly reflecting nested folder moves
  4. Existing wizard Phase 4 classification tests still pass with the new tag prompt added

**Plans**: 6 plans
Plans:
**Wave 1**

- [x] 10-01-PLAN.md — device_types.json config list + stdlib REST/Livestatus shape probe script, run live to resolve the tag-group POST body, the per-host folder field, and the Livestatus tags key shape

**Wave 2** *(blocked on Wave 1)*

- [x] 10-02-PLAN.md — CheckmkClient.create_host_tag_group/get_host_tag_group, the validated device_types loader, and the idempotent tag-group provisioning step with its pre-existing-host default count
- [x] 10-03-PLAN.md — Poller: alias column end-to-end, RestError + REST folder lookup replacing derive_folder's filename parsing, PollerConfig REST credentials with the secret redacted

**Wave 3** *(blocked on Wave 2)*

- [x] 10-04-PLAN.md — Phase 4 device_type/alias prompts, Phase 5 tag_device_type/alias on all three host-creation call sites, and repair of every answer-iterator-driven test
- [x] 10-05-PLAN.md — Poller deployment wiring: compose CMK_REST_* env block, a smoke-test enrichment check, and setup-doc credential provisioning plus the updated topic contract

**Wave 4** *(blocked on Wave 3)*

- [x] 10-06-PLAN.md — Live end-to-end verification (blocking checkpoint), extract_device_type corrected to the confirmed Livestatus key shape, and ROADMAP/REQUIREMENTS/PROJECT terminology reconciliation

### Phase 10.1: Bulk Device-Type Tagging and Deployment Gaps (INSERTED)

**Goal**: An operator can correct device type and alias on already-onboarded hosts without re-promoting them, and the poller/worker deployment stops requiring hand-copied credentials or silent-failure guesswork
**Depends on**: Phase 10
**Requirements**: TAG-04, OPS-01, OPS-02, OPS-03, OPS-04
**Source**: Phase 10 self-identified follow-up findings 1-5 (`.planning/phases/10-checkmk-tag-group-onboarding-integration/10-06-SUMMARY.md`, "Findings for Follow-up"), carried forward by `10-VERIFICATION.md`
**Success Criteria** (what must be TRUE):

  1. A folder-scoped bulk retag flow exists that lists already-onboarded hosts and updates `tag_device_type` and `alias` via `update_host_attributes`, without running promotion or altering the host's monitoring method
  2. The `worker` compose service carries the same `CMK_REST_*` environment block the `poller` service already has, so the wizard re-run and the probe script no longer need a hand-pasted secret
  3. The automation secret the wizard generates on a first run is displayed to the operator at the point it is created, sufficient to populate `deploy/.env` without shelling into the `checkmk` container
  4. The poller applies one consistent failure posture across its two external dependencies (Livestatus and the Checkmk REST credential) rather than exiting for one and degrading for the other
  5. A successful poller start emits a log line identifying the configured site, poll interval, and broker, so a healthy poller is distinguishable from a hung one in `podman logs`

**Plans**: 3 plans

Plans:
- [ ] 10.1-01-PLAN.md — Live-verify whether a partial host-attribute PUT merges or replaces (blocking probe + checkpoint)
- [ ] 10.1-02-PLAN.md — Deployment/observability gaps: worker CMK_REST_* env, automation secret display, poller startup retry and success log
- [ ] 10.1-03-PLAN.md — Detection-driven folder-scoped bulk retag inside Phase 4, with activation and Phase 4 answer-iterator audit

### Phase 11: Live Dashboard

**Goal**: A static, backend-less dashboard renders live Checkmk-derived topology, device status, and history purely by consuming the poller's MQTT contract
**Depends on**: Phase 8, Phase 9, Phase 10
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04, DASH-05, DASH-06
**Success Criteria** (what must be TRUE):

  1. `index.html` renders a live topology map (vis-network) with parent/child links, an at-a-glance stats-by-state strip, and nodes color-coded/icon-coded by device type and grouped/colored by the folder-derived location/group label; incoming updates merge via `DataSet.update()` without a full re-render
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
| 8. Broker Infrastructure Hardening | 0/3 | Not started | - |
| 9. Poller Core | 4/4 | Complete   | 2026-09-09 |
| 10. Checkmk Tag-Group & Onboarding Integration | 6/6 | Complete   | 2026-09-11 |
| 11. Live Dashboard | 0/TBD | Not started | - |
