---
phase: 14-fleet-intelligence
plan: 02
subsystem: dashboard
tags: [dashboard, zustand, mqtt, incidents, typescript]

requires:
  - phase: 14-fleet-intelligence (plan 14-01)
    provides: "IncidentPayload MQTT contract on lan/incidents/{incident_id}/status (poller side)"
provides:
  - "lib/incidents.ts: pure incident normalization, D-12 sort ordering, host->incident lookup, duration formatting, D-04-safe copy helpers"
  - "IncidentPayload and extended TopologyNode types in lib/types.ts"
  - "useAppStore incidents slice, wholesale-replace + tombstone-aware + malformed-tolerant"
  - "mqttClient subscription to lan/incidents/+/status"
affects: [14-03, 14-04, 14-05]

tech-stack:
  added: []
  patterns:
    - "One source-of-truth rank table per derived ordering (CRITICALITY_RANK in incidents.ts, mirrors grouping.ts's SEVERITY_RANK convention)"
    - "Pure-logic module with no DOM/broker/storage/network access (incidents.ts, matches treeModel.ts's header convention)"

key-files:
  created:
    - dashboard-react/src/lib/incidents.ts
    - dashboard-react/src/lib/incidents.test.ts
  modified:
    - dashboard-react/src/lib/types.ts
    - dashboard-react/src/store/useAppStore.ts
    - dashboard-react/src/store/useAppStore.test.ts
    - dashboard-react/src/store/mqttClient.ts
    - dashboard-react/src/store/mqttClient.test.ts
    - dashboard-react/src/store/selectors.test.ts

key-decisions:
  - "Incident duration buckets show at most two units (s | min | h+min | d+h), matching the plan's exact worked examples rather than a general-purpose duration formatter"
  - "buildIncidentLookup takes an already-sorted incident array and relies on first-insertion-wins; sort order is the caller's (selectOpenIncidents's) responsibility, not re-derived inside the lookup builder"

requirements-completed: [DASH-14, DASH-15]

duration: 10min
completed: 2026-09-26
---

# Phase 14 Plan 02: Incident Data Layer Summary

**Pure incident normalization/ordering module plus a Zustand `incidents` slice and `lan/incidents/+/status` MQTT subscription, giving the dashboard a live, correctly ordered set of open incidents and a host→incident lookup ready for cards and dimming.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-09-26T04:40:30Z (approx., per STATE.md phase-execution-start timestamp)
- **Completed:** 2026-09-26T04:49:40Z
- **Tasks:** 2 completed
- **Files modified:** 8 (2 created, 6 modified)

## Accomplishments
- `lib/incidents.ts`: `CRITICALITY_TIERS`/`CRITICALITY_RANK`, `normalizeIncident` (untrusted-JSON runtime guard), `sortIncidents`/`selectOpenIncidents` (D-12 worst-criticality-then-duration ordering), `buildIncidentLookup` (host→incident membership, root vs. consequence, dependents excluded per D-15), `formatIncidentDuration`, `consequenceSummary`, `incidentStatus` — all D-04-safe (never asserts "not operating" from UNREACH-only evidence)
- `lib/types.ts`: `IncidentPayload` type plus `TopologyNode.criticality`/`service_criticality`/`depends_on` fields for plan 14-07 to populate later
- `useAppStore.ts`: new `incidents: Record<string, IncidentPayload>` slice — wholesale-replace on message, delete-on-tombstone, drop-and-keep-last-known-good on malformed/wrong-shape payload, never a destructive `set(..., true)`
- `mqttClient.ts`: `SUBSCRIBE_TOPICS` now includes `lan/incidents/+/status`, so retained incidents replay on connect

## Task Commits

1. **Task 1: IncidentPayload/TopologyNode types and pure lib/incidents.ts** - `1fd1b61` (feat)
2. **Task 2: incidents store slice and lan/incidents/+/status subscription** - `83b6e32` (feat)

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified
- `dashboard-react/src/lib/incidents.ts` - Pure incident normalization/ordering/lookup/formatting logic
- `dashboard-react/src/lib/incidents.test.ts` - 34 unit tests covering every behavior bullet
- `dashboard-react/src/lib/types.ts` - `IncidentPayload` + extended `TopologyNode`
- `dashboard-react/src/store/useAppStore.ts` - `incidents` slice + `handleMessage` branch
- `dashboard-react/src/store/useAppStore.test.ts` - 4 new `handleMessage - incidents` tests
- `dashboard-react/src/store/mqttClient.ts` - `lan/incidents/+/status` added to `SUBSCRIBE_TOPICS`
- `dashboard-react/src/store/mqttClient.test.ts` - test asserting the new topic is subscribed
- `dashboard-react/src/store/selectors.test.ts` - fixture fix (see Deviations)

## Decisions Made
- Duration formatting shows exactly the unit granularity the plan's worked examples demand (seconds alone under a minute; minutes alone under an hour; hours+minutes under a day; days+hours beyond that) rather than a general N-unit breakdown, since the plan's four examples pin this exact shape.
- `buildIncidentLookup` does not sort its input; it assumes the caller (`selectOpenIncidents`) already produced D-12 order, so "first incident wins" on a duplicate host id reduces to "first array element wins."

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Own D-04 wording violation caught by the plan's own acceptance grep**
- **Found during:** Task 1 verification (`grep -c "not operating" incidents.ts` initially returned 1, not the required 0)
- **Issue:** A source comment explaining the `consequenceSummary` D-04 constraint itself contained the literal forbidden phrase "not operating"
- **Fix:** Reworded the comment to convey the same rationale without using the locked phrase
- **Files modified:** `dashboard-react/src/lib/incidents.ts`
- **Verification:** `grep -c "not operating" dashboard-react/src/lib/incidents.ts` now returns `0`; `npm test -- src/lib/incidents.test.ts` and `npm run typecheck` re-run clean afterward
- **Committed in:** `1fd1b61` (part of Task 1 commit)

**2. [Rule 3 - Blocking] Fixed a typecheck break in an unrelated test fixture caused by the new required `AppState.incidents` field**
- **Found during:** Task 2 verification (`npm run typecheck`)
- **Issue:** `selectors.test.ts`'s hand-built `AppState` object (used to test selectors, not part of this plan's file list) no longer satisfied the `AppState` interface once `incidents` became a required field
- **Fix:** Added `incidents: {}` to that fixture, matching the same field every other slice already has
- **Files modified:** `dashboard-react/src/store/selectors.test.ts`
- **Verification:** `npm run typecheck` exits 0; `npm test` for `src/store` still passes 37/37
- **Committed in:** `83b6e32` (part of Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking)
**Impact on plan:** Both fixes were required for the plan's own stated acceptance criteria/verification commands to pass. No scope creep — no other files were touched.

## Issues Encountered
- The full `npm test` suite (not the plan's scoped verify commands) has 2 pre-existing failures in `dashboard-react/src/lib/mapIcons.test.ts` (expects `fill="#141414"` in device-type SVG markup that isn't present). Neither `mapIcons.ts` nor its test is touched by this plan, and the file was last modified in commit `a427d92`, well before this plan's work — confirmed pre-existing and out of scope per the Scope Boundary rule. Logged to `.planning/phases/14-fleet-intelligence/deferred-items.md` rather than fixed.
- `dashboard-react/node_modules` was absent in this worktree (not shared across worktrees) and `design-system/kone-design-system-0.1.0.tgz` (the file-based npm dependency) was also absent, since it's a gitignored build artifact. Copied the prebuilt tarball from the main checkout's `design-system/` directory (not tracked by git; same artifact `npm install` in the main checkout already produced) and ran `npm install` before any test/typecheck/lint command — required for the plan's own verify steps to run at all.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Plan 14-03 (dimming) and 14-04 (cards) can now build directly on `lib/incidents.ts`'s exports and the `incidents` store slice — the data foundation this plan promised is live and unit-tested.
- Plan 14-07 (poller-side criticality/dependency labels) has its `TopologyNode` fields already typed and waiting.

---
*Phase: 14-fleet-intelligence*
*Completed: 2026-09-26*

## Self-Check: PASSED

All created/modified files verified present (`incidents.ts`, `incidents.test.ts`, `types.ts`,
`useAppStore.ts`, `mqttClient.ts`, `deferred-items.md`); both task commits (`1fd1b61`,
`83b6e32`) verified present in `git log --oneline --all`.
