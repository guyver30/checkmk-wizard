---
phase: 12-agent-metrics-and-service-status
plan: 03
subsystem: ui
tags: [react, typescript, zustand, mqtt, vitest]

# Dependency graph
requires:
  - phase: 11.1-dashboard-layout-and-light-palette
    provides: kone-design-system component library, useAppStore/mqttClient choke points, DevicePayload/HistoryEntry/EventEntry type shapes
provides:
  - DevicePayload gauge fields (cpu/ram/disk/disk_other_worst/smart), typed number|null per the wire contract
  - ServiceEntry and ServiceHistoryEntry payload types
  - services and serviceHistory store slices fed by two new subscribed MQTT topics
  - gaugeColor(), smartBadge(), otherMountsLabel() pure helpers in lib/gauges.ts
  - SEVERITY_ORDER and compareServices() in lib/serviceSort.ts
affects: [12-04-plan (DetailsRoute presentation layer consumes these types/store slices/helpers)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Gauge ring colour derived from a metric's own warn/crit thresholds, never from Checkmk service state (D-04) — kept in a dedicated lib/gauges.ts module, deliberately separate from stateMapping.ts's state-to-badge colour table"
    - "Hide-on-absence: a null gauge/badge value returns null from its helper (React renders nothing) rather than a placeholder string — no 'N/A' badges anywhere"

key-files:
  created:
    - dashboard-react/src/lib/gauges.ts
    - dashboard-react/src/lib/gauges.test.ts
    - dashboard-react/src/lib/serviceSort.ts
    - dashboard-react/src/lib/serviceSort.test.ts
  modified:
    - dashboard-react/src/lib/types.ts
    - dashboard-react/src/store/mqttClient.ts
    - dashboard-react/src/store/mqttClient.test.ts
    - dashboard-react/src/store/useAppStore.ts
    - dashboard-react/src/store/useAppStore.test.ts
    - dashboard-react/src/store/selectors.test.ts

key-decisions:
  - "None new — plan's must_haves (D-01/D-03/D-04/D-06/D-09) were already locked by 12-UI-SPEC.md; this plan implemented them, made no new product decisions"

patterns-established:
  - "Pure gauge/sort helper modules (lib/gauges.ts, lib/serviceSort.ts) with zero DOM/store/network access, mirroring lib/staleness.ts's shape — DetailsRoute (12-04) renders from these, keeping computation out of the component"

requirements-completed: [DASH-08, DASH-09, DASH-10]

# Metrics
duration: ~25min
completed: 2026-09-23
---

# Phase 12 Plan 03: Dashboard Data Layer for Gauges and Service Status Summary

**Extended the dashboard's Zustand store and type layer with two new MQTT-fed slices (`services`, `serviceHistory`), fifteen typed gauge fields on `DevicePayload`, and four tested pure helpers (`gaugeColor`, `smartBadge`, `otherMountsLabel`, `compareServices`) — no UI changes yet.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 3/3 completed
- **Files modified:** 6 modified, 4 created

## Accomplishments
- `DevicePayload` now carries all fifteen Phase 12 gauge fields (`cpu_*`, `ram_*`, `disk_*`, `disk_other_worst_*`, `smart_*`) by their exact wire name, each `number | null` (or `string | null` for the mount name) and optional, per this file's existing "untrusted JSON, loosely typed" convention; the stale `services?: unknown` placeholder is removed
- `mqttClient.ts` subscribes `lan/devices/+/services` and `lan/devices/+/service_history` through the existing single-array choke point — no other change to the module
- `useAppStore.ts` gained `services: Record<string, ServiceEntry[]>` and `serviceHistory: Record<string, ServiceHistoryEntry[]>`, fed by two `handleMessage` branches that are literal mirrors of the existing `history` branch (same `parsePayload`/`isPlainObject`/`Array.isArray` guards, same last-known-good-on-malformed contract, same tombstone-on-zero-length-payload semantics); the existing status tombstone branch now also clears both new slices so a removed device leaves nothing orphaned
- `lib/gauges.ts` and `lib/serviceSort.ts` are new, fully tested, zero-dependency pure-function modules ready for the Plan 12-04 route to render from

## Task Commits

1. **Task 1: Payload types for gauges, service rows and service history** - `7370bb4` (feat)
2. **Task 2: Subscribe the two new topics and route them into the store** - `64ce45c` (feat)
3. **Task 3: Pure helpers for gauge colour, SMART/other-mount badges and service sort order** - `89030e8` (feat)

_No plan-metadata commit in this worktree — orchestrator commits SUMMARY.md/STATE.md/ROADMAP.md centrally after wave merge (parallel worktree execution)._

## Files Created/Modified
- `dashboard-react/src/lib/types.ts` - Added 15 gauge fields to `DevicePayload`, removed `services?: unknown`, added `ServiceEntry`/`ServiceHistoryEntry`
- `dashboard-react/src/store/mqttClient.ts` - Added `lan/devices/+/services` and `lan/devices/+/service_history` to `SUBSCRIBE_TOPICS`
- `dashboard-react/src/store/mqttClient.test.ts` - Added a dedicated `SUBSCRIBE_TOPICS` assertion for the two new wildcard topics
- `dashboard-react/src/store/useAppStore.ts` - Added `services`/`serviceHistory` state, two `handleMessage` branches, extended the status tombstone to clear all four per-device slices
- `dashboard-react/src/store/useAppStore.test.ts` - Added services/service_history branch tests (well-formed, malformed-keeps-last-known-good, wrong-shape-dropped, zero-length-tombstone) and an all-four-slices tombstone test
- `dashboard-react/src/store/selectors.test.ts` - Added the two new required `AppState` fields to the test fixture (Rule 3 fix, see Deviations)
- `dashboard-react/src/lib/gauges.ts` (new) - `gaugeColor()`, `smartBadge()`, `otherMountsLabel()`
- `dashboard-react/src/lib/gauges.test.ts` (new) - Boundary tests for all three
- `dashboard-react/src/lib/serviceSort.ts` (new) - `SEVERITY_ORDER`, `compareServices()`
- `dashboard-react/src/lib/serviceSort.test.ts` (new) - Sort-order and tie-break tests

## Decisions Made
None - all colour/copy/hide-on-absence rules were already locked by 12-UI-SPEC.md and 12-PATTERNS.md; this plan is a literal implementation of those specs.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `selectors.test.ts`'s `AppState` fixture missing new required fields**
- **Found during:** Task 2 (`npm --prefix dashboard-react run typecheck`)
- **Issue:** Adding `services`/`serviceHistory` to the `AppState` interface made the pre-existing `stateWithDevices()` test helper in `selectors.test.ts` (an unrelated file, not in this plan's `files_modified` list) fail to typecheck — it constructs a literal `AppState` object missing the two new required fields.
- **Fix:** Added `services: {}` and `serviceHistory: {}` to the fixture, matching the store's own initial-state shape.
- **Files modified:** `dashboard-react/src/store/selectors.test.ts`
- **Verification:** `npm --prefix dashboard-react run typecheck` exits 0
- **Committed in:** `64ce45c` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary to keep the codebase typechecking after the planned `AppState` interface change. No scope creep — the fix is confined to a stale test fixture, not new behavior.

## Issues Encountered
- **Environment bootstrap (not a deviation, no code change):** This worktree had no `node_modules` and no `design-system/kone-design-system-0.1.0.tgz` (both gitignored build artifacts). Built `design-system` (`npm install && npm run build && npm pack`) and ran `npm install` in `dashboard-react` before any verification command could run. This is per-worktree environment setup, not a plan deviation.
- **Pre-existing, out-of-scope test failure (not fixed, per SCOPE BOUNDARY):** `dashboard-react/src/components/GroupingControls.test.tsx` has 2 failing tests ("Order by severity" reorders groups / "leaves both groups expanded") that fail identically in isolation, on files last touched by an unrelated Phase 11.1 commit (`f3d637d`), with no diff from this plan. Confirmed pre-existing and unrelated to gauge/service-store changes — left untouched per the deviation rules' scope boundary (only fix issues directly caused by this plan's changes).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plan 12-04 (DetailsRoute presentation) can now read `useAppStore((s) => s.services[id])` / `s.serviceHistory[id]` and render `DevicePayload`'s gauge fields through `gaugeColor()`/`smartBadge()`/`otherMountsLabel()`, and sort the service table with `compareServices()` — all typed and tested, no computation left to do in the route component.
- Known pre-existing `GroupingControls.test.tsx` failure (2 tests) is unrelated to this plan and remains open; not blocking for 12-04.

---
*Phase: 12-agent-metrics-and-service-status*
*Completed: 2026-09-23*

## Self-Check: PASSED

All 10 created/modified files verified present on disk. All 3 task commits (`7370bb4`, `64ce45c`, `89030e8`) verified present in `git log`.
