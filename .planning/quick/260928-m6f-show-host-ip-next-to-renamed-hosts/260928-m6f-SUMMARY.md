---
phase: quick-260928-m6f
plan: 01
subsystem: dashboard
tags: [mqtt, livestatus, react, display-naming, dashboard-react]

# Dependency graph
requires:
  - phase: quick-260928-l4h
    provides: host details right-hand pane (HostDetails.tsx header this plan also updates)
provides:
  - "scripts/mqtt_poller.py publishes `address` (Livestatus hosts.address) on every device status payload"
  - "dashboard-react display helpers displayAddress()/displayNameWithAddress() and their use across incident cards, map labels, event rows, device tree tooltip and host details header"
affects: [dashboard-react, mqtt_poller]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "New per-device fields are carried status-payload-only (never widening topology_signature()/_normalise_restored_node()) unless a caller actually needs them off the topology entry, avoiding a forced topology republish on upgrade"

key-files:
  created: []
  modified:
    - scripts/mqtt_poller.py
    - tests/test_mqtt_poller.py
    - dashboard-react/src/lib/types.ts
    - dashboard-react/src/lib/display.ts
    - dashboard-react/src/lib/display.test.ts
    - dashboard-react/src/lib/treeModel.ts
    - dashboard-react/src/lib/treeModel.test.ts
    - dashboard-react/src/lib/topologyLayout.ts
    - dashboard-react/src/lib/topologyLayout.test.ts
    - dashboard-react/src/components/TreeNode.tsx
    - dashboard-react/src/components/IncidentList.tsx
    - dashboard-react/src/components/EventRow.tsx
    - dashboard-react/src/components/HostDetails.tsx
    - dashboard-react/README.md
    - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
    - .planning/todos/done/2026-09-28-show-host-ip-next-to-renamed-hosts.md

key-decisions:
  - "OD-1..OD-5 (operator, locked 2026-09-28): show the IP whenever displayName differs from address; empty when address is empty/missing; tree shows it as a hover tooltip; incident cards/map labels/event rows use `name (ip)`; host details header also uses `name (ip)`."
  - "Planner decision: carry `address` only on the per-device status payload, not on the topology node/topology_nodes()/topology_signature()/_normalise_restored_node() — every dashboard name site already reads the status payload, and widening the topology signature would force a republish on upgrade for no consumer benefit."

patterns-established: []

requirements-completed: [TODO-2026-09-28-host-ip]

# Metrics
duration: unset (start time not captured at agent spawn)
completed: 2026-09-28
---

# Quick Task 260928-m6f: Show Host IP Next to Renamed Hosts Summary

**Poller publishes each host's Livestatus `address` on its status payload; dashboard appends `(ip)` to renamed-host names on incident cards, map labels, event rows and the host details header, and shows it as a tree hover tooltip — with no change when the name already equals the IP or none is known.**

## Performance

- **Completed:** 2026-09-28
- **Tasks:** 3/3 completed
- **Files modified:** 16

## Accomplishments
- `scripts/mqtt_poller.py` adds `address` to `OPTIONAL_HOST_COLUMNS`, `DeviceSnapshot.address`, and publishes it on `lan/devices/{id}/status` — degrading to `""` on a missing column, truncated row, or non-string value, exactly like the existing `alias` field.
- `dashboard-react/src/lib/display.ts` gains `displayAddress()` (returns the trimmed address only when it differs from `displayName()`) and `displayNameWithAddress()` (`"name (ip)"` or bare name), applied at every required name site: `IncidentList.tsx` (root label + View-devices + Dependent devices), `EventRow.tsx`, `topologyLayout.ts` (status-payload branch only), and `HostDetails.tsx`'s two headers.
- `treeModel.ts`/`TreeNode.tsx`: the tree keeps `label: displayName(device)` unchanged (so sort order is untouched) and adds `address: displayAddress(device)`, rendered as a `title` attribute on the device name span.
- Docs updated: the Podman setup doc's MQTT topic contract table and payload-key paragraph now list/describe `address`; `dashboard-react/README.md`'s Incidents section gained a "Name/IP display" note describing the full rule.
- The originating todo moved from `.planning/todos/pending/` to `.planning/todos/done/`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Poller publishes `address` on the device status payload** - `bfcf30b` (feat)
2. **Task 2: Dashboard helper and all name sites** - `90fe1ae` (feat)
3. **Task 3: Docs and todo closure** - `ae02bb4` (docs)

_Note: this quick task was executed under an explicit orchestrator instruction to commit one atomic commit per task (code changes only), rather than the plan's `tdd="true"` RED/GREEN/REFACTOR sub-commit convention — tests were still written first and confirmed against the pre-change code path per task before the implementation was added, just folded into the single task commit._

## Files Created/Modified
- `scripts/mqtt_poller.py` - `address` in `OPTIONAL_HOST_COLUMNS`, `DeviceSnapshot.address`, parsed/stripped like `alias`, published as an additive status-payload key
- `tests/test_mqtt_poller.py` - membership, absent-column, truncated-row, non-string, populated-value and whitespace-trim tests for `address`; exact-payload-keys test updated
- `dashboard-react/src/lib/types.ts` - `DevicePayload.address?: string` (not added to `TopologyNode`, per the planner decision)
- `dashboard-react/src/lib/display.ts` - `displayAddress()`, `displayNameWithAddress()`
- `dashboard-react/src/lib/display.test.ts` - behavior cases for both new helpers
- `dashboard-react/src/lib/treeModel.ts` / `.test.ts` - `TreeDeviceNode.address`, one new test asserting it flows through
- `dashboard-react/src/lib/topologyLayout.ts` / `.test.ts` - status-branch label uses `displayNameWithAddress`; one new test asserting a `router (192.168.0.1)` map label
- `dashboard-react/src/components/TreeNode.tsx` - `title={device.address || undefined}` on the device name span
- `dashboard-react/src/components/IncidentList.tsx` - `nameFor` built with `displayNameWithAddress`
- `dashboard-react/src/components/EventRow.tsx` - `rawLabel` built with `displayNameWithAddress`
- `dashboard-react/src/components/HostDetails.tsx` - both `<h1>` headers use `displayNameWithAddress`
- `dashboard-react/README.md` - new Name/IP display note under §5c Incidents
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` - `address` added to the status-payload key list and payload-keys paragraph
- `.planning/todos/done/2026-09-28-show-host-ip-next-to-renamed-hosts.md` - moved from `pending/`

## Decisions Made
None beyond the operator/planner decisions already locked in the plan (OD-1..OD-5, and the status-payload-only `address` placement) — executed as specified.

## Deviations from Plan

None - plan executed exactly as written. One clarification: the orchestrator's explicit constraint ("Commit each task atomically") was applied over the plan's default `tdd="true"` RED→GREEN sub-commit convention — see the Task Commits note above.

## Issues Encountered
None. All three verify commands in every task, and the plan's overall four-command verification, passed on the first run with no fixture breakage in the existing dashboard/poller test suites.

## User Setup Required
None - no external service configuration required. The `address` Livestatus column is standard and requires no site configuration; a site or older poller without it degrades to an empty string exactly as designed.

## Next Phase Readiness
Feature is complete and self-contained. No follow-on work identified.

---
*Phase: quick-260928-m6f*
*Completed: 2026-09-28*

## Self-Check: PASSED

All 16 files listed in `key-files.modified` verified present on disk. All 3 task commits (`bfcf30b`, `90fe1ae`, `ae02bb4`) verified present in `git log`.
