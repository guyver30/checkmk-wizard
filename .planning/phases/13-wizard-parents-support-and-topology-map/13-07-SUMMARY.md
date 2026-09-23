---
phase: 13-wizard-parents-support-and-topology-map
plan: 07
subsystem: ui
tags: [dashboard, edit-mode, activation, ux]

# Dependency graph
requires:
  - phase: 13-wizard-parents-support-and-topology-map
    plan: 06
    provides: "TopologyMap.tsx editMode/onEditSaved/onEditFailed props (edge/position/unmanaged-switch write wiring)"
provides:
  - "TopologyToolbar.tsx: Edit-topology Switch + pending-changes Banner + Apply changes Button row"
  - "useEditIdleTimeout.ts: 5-minute idle auto-exit timer with touch() reset"
  - "IndexRoute.tsx: editMode/pendingCount/applying/snackbar route-level state, wired to TopologyMap and a batched Apply action"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Route-level UI-session state (editMode/pendingCount/applying/snackbar), never persisted -- same 'lift into the route, not the store' rule openKeys already established"
    - "Single explicit batched Apply action (activateChanges called exactly once per press, re-entry guarded) rather than activating inside every map edit callback, per RESEARCH Pitfall 3"
    - "A fixed bottom-4 right-4 Snackbar is the one feedback surface for both Apply outcomes and every onEditFailed call from the map, with autoDismissMs distinguishing transient success from persistent failure"

key-files:
  created:
    - dashboard-react/src/components/TopologyToolbar.tsx
    - dashboard-react/src/components/TopologyToolbar.test.tsx
    - dashboard-react/src/hooks/useEditIdleTimeout.ts
    - dashboard-react/src/hooks/useEditIdleTimeout.test.ts
  modified:
    - dashboard-react/src/routes/IndexRoute.tsx
    - dashboard-react/src/routes/IndexRoute.test.tsx

key-decisions:
  - "IndexRoute.test.tsx mocks TopologyMap with a stand-in exposing editMode/onEditSaved/onEditFailed as plain props, rather than driving the real vis-network manipulation toolbar through fakeVisNetwork.ts -- the plan's own behavior block offered both options ('invoke via the fake network's manipulation callbacks, or by rendering with a mocked TopologyMap'); TopologyMap.test.tsx already exercises the real callback wiring end-to-end, so re-driving vis-network at the route level would duplicate that coverage without adding confidence in IndexRoute's own logic"
  - "IndexRoute.test.tsx uses fireEvent (not userEvent) for every click/interaction in the new describe block -- userEvent v14's internal pointer-events readiness checks hung indefinitely under vi.useFakeTimers() even with delay: null and advanceTimers configured; fireEvent is synchronous DOM dispatch with no internal timer dependency and works cleanly alongside vi.advanceTimersByTimeAsync() for the auto-dismiss/idle-timeout timing assertions"
  - "A data-testid=\"snackbar\" wrapper div was added around the Snackbar render (not specified by the plan or UI-SPEC) purely as a test hook, mirroring the existing data-testid=\"topology-map\" convention -- makes 'is a Snackbar currently shown' assertions unambiguous against StatsStrip's own role=status element"

requirements-completed: [DASH-12]

# Metrics
duration: ~50min
completed: 2026-09-23
---

# Phase 13 Plan 07: Edit-Topology Toolbar, Apply Flow, Snackbars and Idle Exit Summary

**The "Edit topology" Switch, a client-side pending-changes count, and a single re-entry-guarded "Apply changes" batch activation are now wired end-to-end in IndexRoute, with every write success/failure surfaced through a persistent-or-auto-dismissing Snackbar and a 5-minute idle auto-exit -- completing DASH-12.**

## Performance

- **Duration:** ~50 min (worktree base correction, context reading, two TDD RED/GREEN task cycles including one RED/GREEN debugging detour on test-timer interaction with userEvent, full verification)
- **Tasks:** 2/2 completed, no checkpoints hit
- **Files modified:** 6 (4 created, 2 modified)

## Accomplishments

- **Task 1 — `TopologyToolbar` and `useEditIdleTimeout`:**
  - `TopologyToolbar({ editMode, onEditModeChange, pendingCount, applying, onApply, editingConfigured })` renders a single `flex items-center gap-2 p-3 bg-bg-subtle rounded-md` row: the `Switch` labelled "Edit topology" always renders; a `Banner` (`status="warning"`, "{N} change(s) not yet applied") and an `Apply changes` `Button` (`variant="primary"`, disabled at `pendingCount === 0` or while `applying`, label "Applying…" during `applying`) render only while `editMode` is on. While `editingConfigured` is false, the `Switch` is disabled and a `text-xs text-fg-tertiary` hint ("Editing is off until TOPOLOGY_EDITOR_SECRET is set in src/lib/config.ts.") appears — planner-authored copy, recorded per the plan's own instruction since the UI-SPEC does not define this state.
  - `useEditIdleTimeout(active, onTimeout, timeoutMs = EDIT_IDLE_TIMEOUT_MS)` holds a single `setTimeout` in a ref, armed when `active` becomes true and re-armed by `touch()`, cleared on `active` going false and on unmount; the latest `onTimeout` is read through a ref so the timer never closes over a stale callback.

- **Task 2 — Wiring into `IndexRoute`:**
  - `editMode`/`pendingCount`/`applying`/`snackbar` are `useState` values owned by the route (never persisted — D-02 requires off-on-every-load). `onEditModeChange` reads `countPendingChanges()` as a best-effort informational count when turning edit mode on (a rejection just leaves the client-tracked count as-is, no error surfaced).
  - `onEditSaved` increments the count and calls `touch()`; `onEditFailed({ title, body })` shows a persistent danger Snackbar with the title bolded.
  - `onApply` guards re-entry (`if (applying) return`), calls `activateChanges()` exactly once (`grep -c "activateChanges(" IndexRoute.tsx` → 1), and on success resets the count to 0 and shows a 3-second-auto-dismissing success Snackbar ("Topology updated"); on failure shows a persistent danger Snackbar ("Saved, but not live yet" + the UI-SPEC's exact body text) with the count left unchanged. Never retried in the background.
  - `useEditIdleTimeout(editMode, ...)` turns `editMode` off and shows an info Snackbar ("Edit topology turned off after 5 minutes of inactivity") after 5 minutes without interaction; the wrapping `<div>` around the toolbar+map (inside `centreTop`) carries `onPointerDown`/`onWheel`/`onKeyDown={touch}`.
  - Layout: `centreTop` is now `StatsStrip` → an interaction-tracking wrapper (`flex min-h-0 flex-1 flex-col gap-2`) containing `TopologyToolbar` then the existing `div.min-h-0.flex-1 > TopologyMap`, matching the UI-SPEC's toolbar-row-between-stats-and-canvas placement. `TopologyMap` now receives `editMode`/`onEditSaved`/`onEditFailed`.
  - The Snackbar itself renders in a `fixed bottom-4 right-4 z-50` wrapper (`data-testid="snackbar"`) as a sibling of `ThreePaneLayout`, with `actionLabel="Dismiss"` clearing it.

## Task Commits

Each task followed a RED → GREEN cycle:

1. **Task 1: TopologyToolbar component and useEditIdleTimeout hook**
   - `86a4033` test(13-07): add failing tests for topology toolbar and idle timeout
   - `4a3970f` feat(13-07): add TopologyToolbar and useEditIdleTimeout
2. **Task 2: Wire edit mode, Apply, Snackbars and idle exit into IndexRoute**
   - `3b608f8` test(13-07): add failing tests for edit mode, Apply, Snackbars and idle exit
   - `47a4568` feat(13-07): wire edit mode, Apply, Snackbars and idle exit into IndexRoute

## Files Created/Modified

- `dashboard-react/src/components/TopologyToolbar.tsx` — the Switch/Banner/Apply row
- `dashboard-react/src/components/TopologyToolbar.test.tsx` — 8 `it()` cases covering every documented state
- `dashboard-react/src/hooks/useEditIdleTimeout.ts` — the idle-timeout timer hook
- `dashboard-react/src/hooks/useEditIdleTimeout.test.ts` — 4 `it()` cases (fire, touch()-reset, inactive/unmount no-op)
- `dashboard-react/src/routes/IndexRoute.tsx` — edit-mode state, `TopologyToolbar`/`TopologyMap` wiring, Apply/Snackbar/idle-exit logic; also fixes a pre-existing-style react-hooks/exhaustive-deps lint warning in `useEditIdleTimeout.ts` (Task 1) by switching a single-line `eslint-disable-next-line` to a block-scoped `eslint-disable`/`eslint-enable` pair, since oxlint reported the diagnostic on a line the single-line comment didn't cover
- `dashboard-react/src/routes/IndexRoute.test.tsx` — 8 new `it()` cases covering the toggle's pending-count read (success/rejection), `onEditSaved` increments, Apply success/failure Snackbar timing, `onEditFailed`, and the 5-minute idle auto-exit with a postponing interaction

## Decisions Made

See `key-decisions` in the frontmatter above (mocked-TopologyMap test strategy, `fireEvent` over `userEvent` for fake-timer compatibility, the `data-testid="snackbar"` test hook).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] `userEvent` hung indefinitely under fake timers; switched to `fireEvent`**
- **Found during:** Task 2, first GREEN verification run of `IndexRoute.test.tsx`
- **Issue:** All 7 new interaction-driven tests timed out at 5000ms. `userEvent.setup({ delay: null })`, and even `{ delay: null, advanceTimers: vi.advanceTimersByTime }`, never resolved a single `user.click()` call once `vi.useFakeTimers()` was active — userEvent v14's internal pointer-events-readiness machinery appears to depend on a real clock tick this project's fake-timer setup never supplied.
- **Fix:** Replaced every `userEvent.click(...)` in the new describe block with `fireEvent.click(...)` (synchronous DOM dispatch, already `act()`-wrapped by Testing Library, no internal timer dependency), keeping `vi.advanceTimersByTimeAsync()` for the auto-dismiss/persistence/idle-timeout timing assertions. Removed the now-unused `userEvent` import.
- **Files modified:** `dashboard-react/src/routes/IndexRoute.test.tsx`
- **Verification:** Re-ran `IndexRoute.test.tsx` — all 10 tests (2 pre-existing + 8 new) pass in 1.65s (down from a 35s+ timeout run).
- **Committed in:** `3b608f8` (Task 2 RED commit — the fix landed before the test file was first committed, so no separate commit was needed)

**2. [Rule 1 - Bug] `react-hooks/exhaustive-deps` lint warning in `useEditIdleTimeout.ts` (Task 1) not actually suppressed**
- **Found during:** Task 2's full-suite lint verification (`npm run lint`)
- **Issue:** Task 1's `useEditIdleTimeout.ts` used a single-line `// eslint-disable-next-line react-hooks/exhaustive-deps` comment placed directly above the effect's `}, [active, timeoutMs]);` closing line, following `TopologyMap.tsx`'s established pattern. oxlint reported the diagnostic on a different line (the `arm();` call inside the effect body, not the dependency-array line), so the single-line disable comment landed one line too late and the warning still surfaced.
- **Fix:** Replaced it with a block-scoped `/* eslint-disable react-hooks/exhaustive-deps */` … `/* eslint-enable react-hooks/exhaustive-deps */` pair wrapping the whole effect, which is immune to the exact reported-line mismatch.
- **Files modified:** `dashboard-react/src/hooks/useEditIdleTimeout.ts`
- **Verification:** Re-ran `npm run lint` — the warning is gone; only 3 pre-existing, unrelated warnings remain (`GroupingControls.tsx`, `StateBadge.tsx`, `IndexRoute.tsx:43` from before this plan's edits).
- **Committed in:** `47a4568` (Task 2 GREEN commit, folded in alongside the IndexRoute.tsx implementation since it's a one-line comment-placement fix to Task 1's own file, not a separate architectural change)

---

**Total deviations:** 2 auto-fixed (1 Rule 3 test-tooling blocker, 1 Rule 1 lint-suppression bug). Neither touched product behavior — both are test-infrastructure/lint-comment corrections.
**Impact on plan:** No behavior change to what was planned; the `userEvent`→`fireEvent` switch is a test-authoring detail, and the lint fix corrects a comment placement mistake in code this same plan already committed.

## Issues Encountered

- The full `npm test` run shows the same 2 pre-existing `GroupingControls.test.tsx` clock-drift failures already logged in `deferred-items.md` by plans 13-02/13-03/13-05/13-06 — unrelated to any file this plan touches, confirmed unchanged, not fixed (Scope Boundary rule).
- The worktree's `dashboard-react/node_modules` was not yet installed — ran `npm install` before any test/typecheck/build command (same note as 13-06).

## User Setup Required

None — no new external service configuration. The `topology_editor` credential and `isTopologyEditingConfigured()` gate this plan reads were already provisioned/built by plans 13-04/13-05.

## Next Phase Readiness

- DASH-12 is now complete end-to-end: D-02 toggle, client-side pending count, single batched Apply with the UI-SPEC's exact copy/states, visible failures (never silent), and a 5-minute idle auto-exit. Marked complete in `.planning/REQUIREMENTS.md` (both the checklist entry and the traceability table row).
- DASH-13 (unmanaged switches as check-free Checkmk hosts) remains `Pending` — `TopologyMap.tsx`'s `addNode` (13-06) already implements the write path; DASH-13 was not in this plan's `requirements:` frontmatter and nothing here changes its state. No documentation update was needed: `dashboard-react/README.md`'s `TOPOLOGY_EDITOR_SECRET` entry already cites "map edit mode, 13-06/13-07" and no new configuration constant was introduced by this plan.
- No further plans are known to depend on this one within Phase 13's plan set (`affects: []`).

---
*Phase: 13-wizard-parents-support-and-topology-map*
*Completed: 2026-09-23*

## Self-Check: PASSED

All 6 referenced source files confirmed present via `test -f` (`TopologyToolbar.tsx`,
`TopologyToolbar.test.tsx`, `useEditIdleTimeout.ts`, `useEditIdleTimeout.test.ts`,
`IndexRoute.tsx`, `IndexRoute.test.tsx`) plus this SUMMARY.md. All 4 commit hashes (`86a4033`,
`4a3970f`, `3b608f8`, `47a4568`) confirmed present in `git log --oneline --all`.
