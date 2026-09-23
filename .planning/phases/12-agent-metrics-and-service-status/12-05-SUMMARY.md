---
phase: 12-agent-metrics-and-service-status
plan: 05
subsystem: ui
tags: [react-router, react, vitest, dashboard]

# Dependency graph
requires: []
provides:
  - Device rows in the fleet tree are react-router Links into /details?id={id}
  - PROJECT.md's Out of Scope entry matches REQUIREMENTS.md's already-amended per-service scope wording
affects: [12-04, dashboard-drill-down]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TreeNode device rows: outer div keeps role=\"treeitem\"/aria-label/paddingLeft, inner react-router Link carries the row's visible layout classes and is the actual interactive/focusable element"

key-files:
  created: []
  modified:
    - dashboard-react/src/components/TreeNode.tsx
    - dashboard-react/src/components/Tree.test.tsx
    - dashboard-react/src/components/GroupingControls.test.tsx
    - dashboard-react/src/components/StaleStability.test.tsx
    - .planning/PROJECT.md

key-decisions:
  - "Device row's aria-label stays on the outer treeitem div, not the inner Link, so the accessible name isn't announced twice"
  - "encodeURIComponent applied to device.id before interpolation into /details?id= (T-12-14 mitigation)"

patterns-established: []

requirements-completed: [DASH-11]

# Metrics
duration: 25min
completed: 2026-09-23
---

# Phase 12 Plan 05: Device Row Navigation Summary

**Fleet-tree device rows are react-router Links into `/details?id={id}`, and PROJECT.md's Out of Scope wording now matches the read-only per-service scope Phase 12 actually ships.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-09-23T00:47:00Z (approx.)
- **Completed:** 2026-09-23T01:12:19Z
- **Tasks:** 2/2 completed
- **Files modified:** 5

## Accomplishments
- Every device row in the fleet tree is now a keyboard-reachable `Link` to that device's `/details?id=` drill-down, with `encodeURIComponent` applied to the id
- Group-row expand/collapse behaviour is unchanged (still a plain `onClick`/`aria-expanded` button, no navigation)
- Fixed two other test files (`GroupingControls.test.tsx`, `StaleStability.test.tsx`) that broke because they render `IndexRoute` (and therefore `TreeNode`) without a `Router` context — a direct consequence of adding `Link`
- PROJECT.md's Out of Scope entry no longer forbids the read-only per-service view Phase 12 ships; it now matches `REQUIREMENTS.md`'s already-amended wording and records that the Checkmk deep link (D-17) stays unbuilt

## Task Commits

1. **Task 1: Device rows navigate to the drill-down** - `1060b84` (feat)
2. **Task 2: Amend PROJECT.md's per-service drill-down Out of Scope entry** - `e93c347` (docs)

**Plan metadata:** (this commit, SUMMARY.md)

## Files Created/Modified
- `dashboard-react/src/components/TreeNode.tsx` - device rows render inside a `Link` to `/details?id={encodeURIComponent(device.id)}`; dropped `tabIndex={-1}` since `Link` is natively focusable; group rows untouched
- `dashboard-react/src/components/Tree.test.tsx` - added `MemoryRouter` wrapper to every render that mounts `TreeNode`; added tests asserting a plain-id link's `href`, a space-containing id's encoded `href`, and that a group row's click still calls `onToggle` rather than navigating
- `dashboard-react/src/components/GroupingControls.test.tsx` - added a `renderIndex()` helper wrapping `IndexRoute` in `MemoryRouter` (all 7 call sites), fixing router-context crashes caused by Task 1
- `dashboard-react/src/components/StaleStability.test.tsx` - wrapped its single `render(<IndexRoute />)` in `MemoryRouter` for the same reason
- `.planning/PROJECT.md` - narrowed the Out of Scope bullet that previously forbade any per-service drill-down UI; now records that read-only status/gauges are in scope (Phase 12, DASH-08 through DASH-10) and that write/administration actions plus the external Checkmk deep link (D-17) remain out of scope

## Decisions Made
- Kept the device row's `aria-label` on the outer `role="treeitem"` div rather than moving it onto the `Link`, so the row has exactly one accessible name (per plan instruction, to avoid double-announcing)
- Split the row's classes across two elements: the outer div keeps `role`/`aria-label`/depth-derived `paddingLeft`; the inner `Link` carries the visible `flex items-center gap-2 py-1.5 pr-3 text-sm` layout plus the new `hover:bg-bg-subtle-hover` affordance. Functionally and visually equivalent to the single-element original, since `Link` renders as `display:flex` (block-level flow) inside the padded parent.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed two other test files broken by Task 1's Link change**
- **Found during:** Task 1 (running `npm --prefix dashboard-react test` in full, per the plan's own `<verification>` step, not just the task's scoped `<verify>` command)
- **Issue:** `GroupingControls.test.tsx` (7 tests) and `StaleStability.test.tsx` (1 test) render `IndexRoute`, which nests `TreeNode`. Once `TreeNode`'s device rows render a react-router `Link`, mounting them outside a `Router` context throws (`Cannot destructure property 'basename' of 'React$1.useContext(...)' as it is null`). This broke 5 tests across those two files that expand a tree group during the test.
- **Fix:** Added a `MemoryRouter` wrapper around every `render(<IndexRoute />)` call in both files (via a `renderIndex()` helper in `GroupingControls.test.tsx`, inline in `StaleStability.test.tsx`).
- **Files modified:** `dashboard-react/src/components/GroupingControls.test.tsx`, `dashboard-react/src/components/StaleStability.test.tsx`
- **Verification:** Re-ran `npm --prefix dashboard-react test`; all 5 previously-broken-by-this-change tests now pass.
- **Committed in:** `1060b84` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - regression in two test files caused directly by Task 1's own change)
**Impact on plan:** Necessary to keep `npm --prefix dashboard-react test` passing in full, as the plan's own `<verification>` section requires. No scope creep — both fixes are exclusively `MemoryRouter` wrapper additions, no assertion or component logic changed.

## Issues Encountered
- Baseline verification: to confirm the 2 remaining `GroupingControls.test.tsx` failures ("checking 'Order by severity' reorders groups..." and "expanding two groups, then toggling 'Order by severity'...") were pre-existing and not caused by this plan, I temporarily restored the unmodified `TreeNode.tsx`/`Tree.test.tsx` from `HEAD` and re-ran the full suite. The same 2 failures reproduced identically against the baseline, confirming they predate this plan (likely a clock-drift issue: the tests fix `NOW_MS` to `2026-09-21T12:00:00Z` but the staleness check appears to read the real wall clock, and the sandbox's system date is now past that fixed timestamp). Logged to `.planning/phases/12-agent-metrics-and-service-status/deferred-items.md` per the SCOPE BOUNDARY rule (pre-existing, unrelated to this task) rather than fixed here.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- The fleet tree's device rows are now reachable into `DetailsRoute` for any future plan/phase that renders gauges/service data there (12-01 through 12-04's work in the same wave).
- Two pre-existing `GroupingControls.test.tsx` failures remain unresolved (see deferred-items.md) — not blocking, but should be picked up by a future quick-task or the next phase touching that file.

---
*Phase: 12-agent-metrics-and-service-status*
*Completed: 2026-09-23*

## Self-Check: PASSED

- FOUND: dashboard-react/src/components/TreeNode.tsx
- FOUND: dashboard-react/src/components/Tree.test.tsx
- FOUND: .planning/PROJECT.md
- FOUND: .planning/phases/12-agent-metrics-and-service-status/12-05-SUMMARY.md
- FOUND commit: 1060b84
- FOUND commit: e93c347
- FOUND commit: 09912da
