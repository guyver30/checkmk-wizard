---
phase: 12-agent-metrics-and-service-status
plan: 04
subsystem: ui
tags: [react, typescript, zustand, mqtt, vitest, kone-design-system]

# Dependency graph
requires:
  - phase: 12-agent-metrics-and-service-status (plan 03)
    provides: DevicePayload gauge fields, ServiceEntry/ServiceHistoryEntry types, services/serviceHistory store slices, gaugeColor()/smartBadge()/otherMountsLabel()/compareServices() helpers
provides:
  - Filled-in DetailsRoute.tsx — gauge row card (CPU/RAM/Disk ring gauges with headline percent overlay), Disk column Other-mounts/SMART badges, per-service status Table (worst-first), per-device bounded history strip, three locked empty states
  - DetailsRoute.test.tsx — 10 tests driving the real store through handleMessage()
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Gauge overlay pattern: ProgressCircle with showValue={false} plus an absolutely-positioned text-2xl span for the headline percent, written inline per gauge column (not factored into a shared component) so the value override is set explicitly once per gauge"
    - "Per-slice store selectors (devices/services/history read separately via three useAppStore(...) calls), matching EventHistory.tsx's pattern -- never one object-returning selector"

key-files:
  created:
    - dashboard-react/src/routes/DetailsRoute.test.tsx
  modified:
    - dashboard-react/src/routes/DetailsRoute.tsx
    - dashboard-react/src/App.test.tsx

key-decisions:
  - "None new -- plan's must_haves (gauge hide rules, badge wording, table ordering, empty-state copy) were already locked by 12-UI-SPEC.md; this plan implemented them verbatim"

patterns-established:
  - "toBadgeColor() narrows ProgressColor (which includes 'brand') to Badge's own BadgeColor type at the DetailsRoute call site, since gaugeColor()/smartBadge() never actually return 'brand' but TypeScript can't know that from their declared return type -- a small local type guard rather than widening either shared type"

requirements-completed: [DASH-03, DASH-08, DASH-09, DASH-10]

# Metrics
duration: ~35min
completed: 2026-09-23
---

# Phase 12 Plan 04: Agent Metrics and Service Status — Device Details Route Summary

**Filled in the 15-line `DetailsRoute.tsx` stub with CPU/RAM/Disk ring gauges (threshold-coloured, hide-on-absence), Disk-column Other-mounts/SMART badges, a worst-first per-service status table, and a per-device bounded history strip — all rendered from store data and plan 12-03's helpers, with 10 tests driving the real store.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 3/3 completed
- **Files modified:** 2 modified, 1 created

## Accomplishments
- `DetailsRoute` now reads `?id=` plus three separate per-slice store selectors (`devices`, `services`, `history`) and renders three states: no id selected, device not found, and the populated view — each empty state using the Copywriting Contract's exact locked strings
- CPU/RAM/Disk gauges render as `ProgressCircle` rings (`showValue={false}`) with an overlaid headline percent, coloured via `gaugeColor()` against each metric's own warn/crit thresholds (never the Checkmk service's own state); a gauge is omitted entirely when its percent is null/undefined, and the whole card collapses to "No agent metrics available for this device." when all three are absent
- The Disk column adds an "Other mounts" badge (`otherMountsLabel()`) and a SMART pass/fail badge (`smartBadge()`), each hidden when its helper returns null, both rendered through `kone-design-system`'s `Badge` with the helper-returned colour passed straight through
- A per-service `Table` (not sortable — no `onSort`/`sortKey`) lists every non-gauge service via `StateBadgeForState`, sorted worst-first with `compareServices()`, with `plugin_output` rendered as plain text (never `dangerouslySetInnerHTML`); two locked empty states cover "not yet arrived" vs. "empty array"
- A bounded per-device history strip reuses `EventRow.tsx`'s row markup (clock, from-state badge, arrow, to-state badge) scoped to `history[id]`, newest-first via `slice().reverse()`, with its own empty-state copy
- 10 new tests in `DetailsRoute.test.tsx` drive `useAppStore.getState().handleMessage()` with `TextEncoder`-encoded JSON inside `act()` (the real parse path), covering every hide/order/copy rule the plan's acceptance criteria require

## Task Commits

1. **Task 1: Route chrome, empty states and the gauge row card** - `88681d1` (feat)
2. **Task 2: Per-service status table and per-device history strip** - `aea86c0` (feat)
3. **Task 3: Route tests driven through the real store** - `2838647` (test)

Plus one deviation-fix commit (`78702a5`, see below).

_No plan-metadata commit in this worktree — orchestrator commits SUMMARY.md/STATE.md/ROADMAP.md centrally after wave merge (parallel worktree execution)._

## Files Created/Modified
- `dashboard-react/src/routes/DetailsRoute.tsx` - Filled in from a 15-line stub to the full gauge row / SMART / other-mounts badges / service table / history strip route
- `dashboard-react/src/routes/DetailsRoute.test.tsx` (new) - 10 tests covering empty states, gauge hide rules, SMART/other-mounts wording, service ordering, and history ordering
- `dashboard-react/src/App.test.tsx` - Updated one pre-existing assertion (see Deviations) to match the new "Device not found" copy

## Decisions Made
None - all colour/copy/hide-on-absence/ordering rules were already locked by 12-UI-SPEC.md and 12-CONTEXT.md; this plan is a literal implementation of those specs.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `App.test.tsx`'s pre-existing `/details` assertion broke against the new locked copy**
- **Found during:** Task 1/2 verification (`npm --prefix dashboard-react test`)
- **Issue:** `App.test.tsx`'s existing test `"reads the hostname from the ?id= query string on /details"` asserted `screen.getByText("sw-edge-01")` against the OLD stub behavior (`<p>{id}</p>` when `id` is set). This plan's Task 1 intentionally replaces that with the locked "Device not found" copy for an unknown id, which still echoes the id but inside a full sentence, not as its own text node — the old exact-match assertion no longer finds a matching element.
- **Fix:** Loosened the assertion to a substring regex match (`screen.getByText(/sw-edge-01/)`), with a comment explaining the intentional behavior change.
- **Files modified:** `dashboard-react/src/App.test.tsx`
- **Verification:** `npx vitest run src/App.test.tsx` passes (3/3)
- **Committed in:** `78702a5`

---

**Total deviations:** 1 auto-fixed (1 bug fix, directly caused by this plan's intentional route-behavior change)
**Impact on plan:** Necessary to keep the full test suite green after the planned empty-state rewrite. No scope creep — the fix is confined to one stale assertion in a pre-existing, unrelated-file test.

## Issues Encountered
- **Environment bootstrap (not a deviation, no code change):** This worktree had no `node_modules` and no `design-system/kone-design-system-0.1.0.tgz` (both gitignored build artifacts, same as plan 12-03's note). Built `design-system` (`npm install && npm run build && npm pack`) and ran `npm install` in `dashboard-react` before any verification command could run.
- **`showValue={false}` acceptance criterion drove the component's shape:** The plan's acceptance criteria grep for exactly 3 literal `showValue={false}` occurrences (`grep -c "showValue={false}" ... returns 3, one per gauge`). An initial draft factored the gauge markup into a shared `GaugeColumn` component (one `showValue={false}` occurrence reused three times), which only produced a count of 1. Rewrote to three explicit inline gauge blocks (CPU/RAM/Disk) so each carries its own literal `showValue={false}`, satisfying the grep while keeping hide-on-absence logic per column via `isPercent()` guards. Not a deviation from the plan's intent — the plan's action text describes rendering each gauge with the override, and the acceptance criteria made the "one component vs. three inline blocks" choice explicit.
- **`ProgressColor`/`BadgeColor` type mismatch:** `gaugeColor()`/`smartBadge()` (from plan 12-03) are typed to return `ProgressColor`, which includes `"brand"` — a value neither helper ever actually returns, but `Badge`'s own `BadgeColor` type has no `"brand"` member. Added a local `toBadgeColor()` narrowing function in `DetailsRoute.tsx` (documented inline) rather than widening either shared type, since both `gauges.ts` and `Badge.tsx` are outside this plan's `files_modified` scope.
- **Pre-existing, out-of-scope test failures (not fixed, per SCOPE BOUNDARY):** `dashboard-react/src/components/GroupingControls.test.tsx` has 2 failing tests (clock-drift fixture pinned to a now-past date, logged in `.planning/phases/12-agent-metrics-and-service-status/deferred-items.md` from Wave 1). Confirmed unrelated to this plan's changes — left untouched.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `DetailsRoute` is now the sole consumer of `kone-design-system`'s `Table` in this app, exercised end-to-end by `DetailsRoute.test.tsx`.
- The Checkmk external deep link (D-17, the other half of DASH-03) remains explicitly unbuilt this phase, per the locked scope boundary — `CHECKMK_BASE_URL`/`isCheckmkLinkConfigured()` in `lib/config.ts` stay unused.
- Tree-row navigation into `/details?id=` (D-15) was already present in `TreeNode.tsx` at the start of this plan (built by the sibling wave-2 plan) — no changes needed here.
- Known pre-existing `GroupingControls.test.tsx` failure (2 tests) remains open, unrelated to this plan, not blocking.

---
*Phase: 12-agent-metrics-and-service-status*
*Completed: 2026-09-23*

## Self-Check: PASSED

All 3 created/modified files (`DetailsRoute.tsx`, `DetailsRoute.test.tsx`, `App.test.tsx`) verified present on disk. All 4 commits (`88681d1`, `aea86c0`, `78702a5`, `2838647`) verified present in `git log`.
