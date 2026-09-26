---
phase: 14-fleet-intelligence
plan: 01
subsystem: poller
tags: [mqtt, incidents, root-cause, livestatus, python]

# Dependency graph
requires:
  - phase: 13-wizard-parents-support-and-topology-map
    provides: "parents/unmanaged host labels, host_state_raw DOWN/UNREACH distinction consumed by the grouping algorithm"
provides:
  - "compute_incidents(): pure root-cause grouping over DeviceSnapshot.parents/host_state_raw, with D-11 unmanaged-switch inference and D-15 worst-affected-criticality closure"
  - "incident_signature() change-only republish key"
  - "publish_incident()/publish_incident_tombstone() on retained lan/incidents/{id}/status, QoS 1"
  - "PollerState.previous_incidents self-heal via reconcile_state()'s lan/incidents/+/status wildcard subscription"
  - "DeviceSnapshot.last_state_change/criticality/depends_on fields with safe defaults -- the incident payload contract is final; plan 14-07 only populates the label-sourced fields"
affects: [14-02-dashboard-incident-list, 14-07-criticality-and-dependency-label-editing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure grouping function (compute_incidents) over already-fetched snapshots, no I/O, mirroring topology_nodes()'s dict-out shape"
    - "Change-only retained-topic publish + zero-length-payload tombstone, reusing _publish_json()/publish_tombstone()'s exact QoS-1 contract"
    - "In-memory-only incident state (PollerState.previous_incidents), self-healed at startup from retained lan/incidents/+/status topic names only -- never the payload body"

key-files:
  created: []
  modified:
    - scripts/mqtt_poller.py
    - tests/test_mqtt_poller.py

key-decisions:
  - "D-04 applied to PLR-14: in an inferred incident (unmanaged-switch root) every consequence is classified not_observable, never confirmed_down, even one that is itself DOWN -- Checkmk cannot see past the switch so 'confirmed down' would overclaim"
  - "Transitive (not one-hop) depends_on closure for worst-affected criticality, per 14-RESEARCH.md Open Question 1 resolution already adopted into the plan"
  - "Host-level criticality only feeds incident severity in this phase; per-service criticality is stored but not consulted here (Open Question 3)"

patterns-established:
  - "compute_incidents()/incident_signature() live right after topology_nodes()/topology_signature() -- new pure-transform functions in this module are grouped by data flow, not insertion order"
  - "publish_incident()/publish_incident_tombstone() sit next to publish_device_status()/publish_tombstone() -- one choke point (_publish_json) per non-tombstone publish"

requirements-completed: [PLR-14, PLR-15, PLR-16]

# Metrics
duration: 12min
completed: 2026-09-26
---

# Phase 14 Plan 1: Poller Root-Cause Incident Engine Summary

**Poller groups DOWN/UNREACH hosts into root-cause incidents each cycle (D-11 unmanaged-switch inference, D-15 worst-affected criticality) and publishes them to retained, tombstoned, change-only `lan/incidents/{id}/status` MQTT topics with zero persisted incident state.**

## Performance

- **Duration:** ~12 min (commit-timestamp window; wall-clock session time was longer due to context reading)
- **Started:** 2026-09-26T04:40:34Z
- **Completed:** 2026-09-26T04:52:48Z
- **Tasks:** 2 completed
- **Files modified:** 2

## Accomplishments
- `compute_incidents()`: pure root-cause grouping algorithm implementing plain-root selection, D-11 unmanaged-switch inference (sibling-evidence gated), contiguous non-OK chain walking with cycle guards (parent-cycle regression test included), D-04 consequence classification, transitive worst-affected criticality with the D-15 one-tier reduction for still-UP dependents, and `since` from Livestatus's `last_state_change`
- `incident_signature()` gives PLR-16's change-only republish rule a stable key that also reacts to a criticality/dependency label edit (not just a DOWN/UNREACH change)
- `publish_incident()`/`publish_incident_tombstone()` on new retained `lan/incidents/{id}/status` topics, QoS 1, following the exact `publish_device_status`/`publish_tombstone` contract already established for per-device topics
- `PollerState.previous_incidents` + `reconcile_state()`'s new `lan/incidents/+/status` wildcard subscription (subscribed before the `TOPIC_TOPOLOGY` barrier, confirmed by test) gives full self-heal on restart with zero incident state written to disk
- `DeviceSnapshot` gained `last_state_change` (parsed defensively from the new optional Livestatus column, degrading to `None` on absence/zero/non-numeric) plus `criticality`/`depends_on` with safe defaults, finalizing the incident payload contract for plan 14-02's dashboard consumer before plan 14-07 wires the label read path

## Task Commits

1. **Task 1: last_state_change column, DeviceSnapshot fields, and pure compute_incidents()** - `4918e4d` (feat)
2. **Task 2: Publish, tombstone and self-heal incidents in run_cycle/reconcile_state** - `c4a5a92` (feat)

**Plan metadata:** (this commit, see final_commit below)

_Note: both tasks were `tdd="true"`; tests were written alongside each task's implementation in the same commit (flat `def test_*` functions per this file's own established convention, no `class Test...` groupings) rather than as a separate RED-then-GREEN commit pair, matching how prior phases in this same test file are structured._

## Files Created/Modified
- `scripts/mqtt_poller.py` - `compute_incidents()`, `incident_signature()`, `publish_incident()`, `publish_incident_tombstone()`, `incident_status_topic()`, `INCIDENT_ID_PREFIX`, `CRITICALITY_TIERS`/`DEFAULT_CRITICALITY`, `DeviceSnapshot.last_state_change`/`criticality`/`depends_on`, `PollerState.previous_incidents`, `reconcile_state()`/`run_cycle()` incident self-heal wiring, `last_state_change` added to `OPTIONAL_HOST_COLUMNS` and parsed in `query_devices()`
- `tests/test_mqtt_poller.py` - 17 `test_compute_incidents_*` functions covering every documented behavior case, `test_incident_signature_reflects_dependents_and_worst_criticality`, `query_devices`/`OPTIONAL_HOST_COLUMNS` tests for `last_state_change`, and `run_cycle`/`reconcile_state` tests for publish/tombstone/self-heal

## Decisions Made
None beyond what CONTEXT.md/PLAN.md already locked (D-04, D-11, D-15, and the plan's own transitive-closure/host-level-only resolutions) - followed plan as specified.

## Deviations from Plan

None - plan executed exactly as written. Both tasks' `<action>` steps were implemented literally, including the exact algorithm steps (a-i) and label/constant placement conventions specified in the plan text.

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required. `last_state_change`'s live-column presence on the real 2.4.0p36.cre site remains unverified (14-RESEARCH.md Pitfall 2/Assumption A3) - this is explicitly deferred to plan 14-05's `--check-columns` live probe per the plan's own dated comment; the poller degrades gracefully (`since: null` for every incident) if the column turns out to be absent, so this is not a blocker for this plan's completion.

## Next Phase Readiness
- The incident payload contract (`lan/incidents/{incident_id}/status`, all 9 keys plus `timestamp`) is final and byte-exact-stable for plan 14-02's dashboard `IncidentList`/`IncidentCard` consumer to build against.
- `DeviceSnapshot.criticality`/`depends_on` already exist with safe defaults (`"low"`/`[]`), so plan 14-07 (label read path via `fetch_host_config()`/`HostConfigInfo`) only needs to populate these two fields from Checkmk labels - no `compute_incidents()` change required.
- No blockers. The known v1 limitation (an independently-DOWN descendant folding into an upstream incident, 14-RESEARCH.md Pitfall 1) is documented in `compute_incidents()`'s own docstring and was a deliberate, plan-endorsed ship-as-designed choice, not a defect to fix in this plan.

---
*Phase: 14-fleet-intelligence*
*Completed: 2026-09-26*

## Self-Check: PASSED

- FOUND: scripts/mqtt_poller.py
- FOUND: tests/test_mqtt_poller.py
- FOUND: .planning/phases/14-fleet-intelligence/14-01-SUMMARY.md
- FOUND commit: 4918e4d (Task 1)
- FOUND commit: c4a5a92 (Task 2)
