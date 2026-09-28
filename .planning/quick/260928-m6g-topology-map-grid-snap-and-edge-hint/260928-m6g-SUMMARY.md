---
phase: quick-260928-m6g
plan: 01
subsystem: dashboard
tags: [vis-network, canvas, react, dashboard-react, topology-map]

# Dependency graph
requires:
  - phase: quick-260928-m6f
    provides: topology label code (nodeBaseFields/label building) in TopologyMap.tsx and topologyLayout.ts, which this plan re-read and left untouched
provides:
  - "MAP_SNAP_SPACING constant and snapToGrid(value) pure helper in topologyLayout.ts (GRID_SPACING / 3 = 50)"
  - "TopologyMap.tsx beforeDrawing grid hook (drawGrid), snapped dragEnd write, edit-mode edge-direction hint overlay"
  - "FakeNetwork test double gains DOMtoCanvas/getScale stubs so the grid hook can run under jsdom"
affects: [dashboard-react]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "vis-network's beforeDrawing canvas hook is used for map-wide decoration (the grid) that must pan/zoom with the map without any DataSet/node involvement -- ctx is already in network coordinates at that point"

key-files:
  created: []
  modified:
    - dashboard-react/src/lib/topologyLayout.ts
    - dashboard-react/src/lib/topologyLayout.test.ts
    - dashboard-react/src/components/TopologyMap.tsx
    - dashboard-react/src/components/TopologyMap.test.tsx
    - dashboard-react/src/test/fakeVisNetwork.ts
    - dashboard-react/README.md
    - .planning/todos/done/2026-09-26-topology-map-grid-snap-and-edge-hint.md

key-decisions:
  - "D-01..D-05 (operator, locked 2026-09-26, see todo): grid always visible in both modes; snap only on dragEnd before the setMapPosition write (no migration of existing off-grid positions); arrows stay parent->child with an edit-mode hint explaining the direction; spacing derived from existing layout constants; no new dependencies (drawn via vis-network's own beforeDrawing hook)."
  - "Planner choice: MAP_SNAP_SPACING = GRID_SPACING / 3 = 50 -- every auto-layout slot (150) lands exactly on a grid intersection, while 50px gives enough resolution to arrange a dense map (150 would be too coarse)."
  - "Planner choice: GRID_LINE_COLOR = '#ececef' as a hard-coded hex constant, matching how NETWORK_OPTIONS already hard-codes its palette -- the map has no theme tokens today, so no theme plumbing was introduced."
  - "Planner choice: the edge-direction hint is rendered inside TopologyMap itself (absolutely positioned, bottom-left of the canvas, editMode-gated), not in TopologyToolbar -- keeps it next to where edges are actually drawn and testable in TopologyMap.test.tsx, and avoids the manipulation toolbar at the top."
  - "Line-count cap (400 lines per axis) in drawGrid mitigates threat T-m6g-02 (denial of service via an extreme zoom-out generating an unbounded number of grid lines)."

patterns-established: []

requirements-completed: [TODO-2026-09-26-grid-snap-edge-hint]

# Metrics
duration: unset (start time not captured at agent spawn)
completed: 2026-09-28
---

# Quick Task 260928-m6g: Topology Map Grid, Snap-to-Grid, and Edge-Direction Hint Summary

**A faint 50px grid drawn behind the vis-network topology map via `beforeDrawing` (visible and pan/zoom-following in both modes), hosts snapping to that grid on drag before the `map_position` write, and an edit-mode-only overlay explaining the parent→child edge direction.**

## Performance

- **Completed:** 2026-09-28
- **Tasks:** 3/3 completed
- **Files modified:** 7

## Accomplishments
- `dashboard-react/src/lib/topologyLayout.ts` gains `MAP_SNAP_SPACING` (= `GRID_SPACING / 3` = 50) and a pure `snapToGrid(value)` that rounds to the nearest multiple of that spacing and normalises a `-0` result to `0`.
- `TopologyMap.tsx`'s `dragEnd` handler now snaps the dropped `x`/`y` to the grid, visibly moves the node there (`nodesRef.current?.update({ id, x, y })`) before calling `setMapPosition`, so the saved label is already on-grid. Read-only drags and the failure path are unchanged.
- `TopologyMap.tsx` registers an unconditional `beforeDrawing` handler (`drawGrid`) on the vis-network `Network` that strokes a faint grid across the currently visible network-coordinate range, using the container's `DOMtoCanvas` bounds and `getScale()` for a consistent ~1px line width at any zoom; a 400-lines-per-axis cap skips drawing at extreme zoom-out (mitigates the plan's threat T-m6g-02).
- An edit-mode-only overlay ("Drag from the parent (uplink) to the child device") is rendered bottom-left of the canvas; `arrows: "to"` is unchanged.
- `dashboard-react/src/test/fakeVisNetwork.ts` gains `DOMtoCanvas`/`getScale` stubs (identity / `1`) so the grid hook is exercisable under jsdom via `instances[0].emit("beforeDrawing", ctx)`.
- `dashboard-react/README.md` §5 documents the grid, the snap-then-save behaviour (including that pre-existing off-grid saved positions are untouched until next dragged), and the edge-direction hint.
- The originating todo moved from `.planning/todos/pending/` to `.planning/todos/done/`.

## Task Commits

Each task was committed atomically:

1. **Task 1: snapToGrid helper and snapped dragEnd write** - `f63b1df` (feat)
2. **Task 2: beforeDrawing grid and edit-mode edge-direction hint** - `2fca3f8` (feat)
3. **Task 3: README update and move the todo to done** - `940285d` (docs)

_Note: this quick task was executed under an explicit orchestrator instruction to commit one atomic commit per task (code changes only), rather than the plan's `tdd="true"` RED→GREEN sub-commit convention for Tasks 1 and 2 — tests were written together with the implementation in each task's single commit, and verified to pass (they were not separately committed failing first)._

## Files Created/Modified
- `dashboard-react/src/lib/topologyLayout.ts` - `MAP_SNAP_SPACING`, `snapToGrid()`
- `dashboard-react/src/lib/topologyLayout.test.ts` - `snapToGrid` behavior tests (rounding cases, `-0` normalisation)
- `dashboard-react/src/components/TopologyMap.tsx` - snapped `dragEnd` write, `GRID_LINE_COLOR`/`MAX_GRID_LINES_PER_AXIS`/`EDGE_DIRECTION_HINT` constants, `drawGrid()`, `beforeDrawing` registration, hint overlay JSX
- `dashboard-react/src/components/TopologyMap.test.tsx` - updated snapped-position dragEnd assertions (including a read-only "node did not move" assertion), new "TopologyMap grid and edge hint" describe block
- `dashboard-react/src/test/fakeVisNetwork.ts` - `DOMtoCanvas()`/`getScale()` stubs
- `dashboard-react/README.md` - §5 grid/snap/edge-direction-hint bullets
- `.planning/todos/done/2026-09-26-topology-map-grid-snap-and-edge-hint.md` - moved from `pending/`

## Decisions Made
None beyond the operator decisions (D-01..D-05) and planner choices already locked in the plan — executed as specified.

## Deviations from Plan

None - plan executed exactly as written. See the Task Commits note above re: the orchestrator's atomic-commit-per-task instruction superseding the plan's `tdd="true"` RED/GREEN sub-commit convention.

## Issues Encountered
None. All per-task verify commands and the plan's overall four-command verification (`npm test`, `npm run typecheck`, `npm run build`, `grep 'arrows: "to"'`) passed on the first run with no fixture breakage in the existing 40-file dashboard-react test suite.

## User Setup Required
None - no external service configuration required. Purely a client-side rendering/interaction change; no new dependency, no backend/API surface.

## Next Phase Readiness
Feature is complete and self-contained. No follow-on work identified.

---
*Phase: quick-260928-m6g*
*Completed: 2026-09-28*

## Self-Check: PASSED

All 7 files listed in `key-files.modified` verified present on disk. All 3 task commits
(`f63b1df`, `2fca3f8`, `940285d`) verified present in `git log`.
