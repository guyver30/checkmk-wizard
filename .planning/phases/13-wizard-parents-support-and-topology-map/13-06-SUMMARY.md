---
phase: 13-wizard-parents-support-and-topology-map
plan: 06
subsystem: ui
tags: [dashboard, vis-network, edit-mode, checkmk-rest]

# Dependency graph
requires:
  - phase: 13-wizard-parents-support-and-topology-map
    plan: 03
    provides: "TopologyMap.tsx (read-only vis-network mount + DataSet sync), fakeVisNetwork.ts test double"
  - phase: 13-wizard-parents-support-and-topology-map
    plan: 05
    provides: "checkmkWrite.ts (updateParents, setMapPosition, createUnmanagedSwitch, isValidHostName, CheckmkWriteError)"
provides:
  - "TopologyMap.tsx editMode wiring: addEdge/editEdge/deleteEdge/addNode manipulation callbacks, dragEnd position persistence, pending-edit overlay, onEditSaved/onEditFailed props"
  - "index.css manipulation-toolbar CSS restyle (.vis-manipulation/.vis-button/.vis-active/.vis-delete)"
  - "fakeVisNetwork.ts: lastManipulation() and disableEditModeCallCount for direct manipulation-callback testing"
affects: [13-07 (Edit-topology toggle, Apply changes batching, Snackbar/Banner feedback UI)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Manipulation callbacks (addEdge/editEdge/deleteEdge/addNode) defined as plain async functions in the component body, closing over stable refs (nodesRef/edgesRef/onEditSavedRef/onEditFailedRef/pending-edit maps) so re-registering them via setOptions only on [editMode] changes never goes stale"
    - "Pending-edit overlay (pendingEdgeAdds/pendingEdgeRemovals/pendingNodeAdds refs) merged into the model in the existing DataSet-sync effect, self-pruning once the live topology catches up to a locally-made edit"
    - "Effect declaration order is load-bearing: the mount effect (constructs the Network) must run before the editMode-gating effect (calls network.setOptions), so a component that renders with editMode=true on its very first render still gets the manipulation toolbar wired up"

key-files:
  created: []
  modified:
    - dashboard-react/src/components/TopologyMap.tsx
    - dashboard-react/src/components/TopologyMap.test.tsx
    - dashboard-react/src/test/fakeVisNetwork.ts
    - dashboard-react/src/index.css

key-decisions:
  - "Position-save failure copy (title 'Couldn't save that position') is planner discretion, modelled on the UI spec's connection-error copy, since the UI spec does not define drag-position-failure text"
  - "addNode failure copy (title 'Couldn't add that switch', three body variants for invalid name / duplicate name / rejected write) is planner discretion, following the same '{what failed}' / '{what to check}' pattern as the UI spec's connection-error copy, since the UI spec defines no add-switch copy"
  - "deleteEdge loops over data.edges and calls window.confirm once per edge before writing any of them, aborting the whole batch on the first cancel -- the UI spec's confirm text and the plan's tested behavior only cover the single-edge case, so this multi-edge extension is a straightforward generalization, not a new design decision"
  - "GSD plan/phase numbers and decision IDs (D-XX, 13-RESEARCH.md, 13-UI-SPEC.md) are deliberately absent from new comments in TopologyMap.tsx/index.css -- substance was translated to plain behavioral prose instead, per this session's project-context instruction. Pre-existing comments in TopologyMap.tsx (written by plan 13-03) that already used this citation style were left untouched (surgical-changes rule)"

requirements-completed: []

# Metrics
duration: ~65min
completed: 2026-09-23
---

# Phase 13 Plan 06: Editable Topology Map (Edge/Position/Unmanaged-Switch Wiring) Summary

**TopologyMap's editMode prop now drives vis-network's built-in manipulation toolbar end-to-end: drawing, reconnecting and deleting parent/child edges and dragging node positions write to Checkmk's REST API through checkmkWrite.ts, and adding a node creates a real, check-free unmanaged-switch host -- all gated behind editMode, all reversible on failure, none of it ever calling Activate Changes.**

## Performance

- **Duration:** ~65 min (worktree base correction, context reading including live source verification of vis-network's manipulation option/callback contracts, two TDD RED/GREEN task cycles, full verification)
- **Tasks:** 2/2 completed, no checkpoints hit
- **Files modified:** 4 (0 created, 4 modified)

## Accomplishments

- **Task 1 — edge editing, position drag, edit-mode gating:**
  - `editMode` now gates vis-network's `manipulation`/`interaction.dragNodes` options via `network.setOptions()`; turning edit mode off also calls `network.disableEditMode()`. `editNode` is never passed (no "Edit Node" button); `deleteNode` stays `false` (node deletion is never offered from the dashboard).
  - `addEdge`/`editEdge`/`deleteEdge` all write through `checkmkWrite.updateParents`, matching the edge convention "an edge from A to B means A is B's parent, so it writes to host B". Self-loops and duplicate edges are rejected without a write. `editEdge` distinguishes a same-child rename (one `updateParents` call) from a different-child move (two sequential calls: remove from the old child, add to the new), patches the edge `DataSet` itself, and tells vis-network not to apply its own result (`callback(null)`) since the edge id changes. `deleteEdge` confirms via `window.confirm()` with UI-spec copy naming both device labels before writing.
  - `dragEnd` is registered once at mount and reads `editModeRef.current` at call time; a successful `setMapPosition` freezes that node's `physics` so later syncs never move it again.
  - A pending-edit overlay (`pendingEdgeAdds`/`pendingEdgeRemovals`/`pendingNodeAdds` refs) is merged into the DataSet-sync effect's model, keeping a locally-made edit visible across incoming topology updates until the live data (post-Activate-Changes, post-poll) reflects it, then self-pruning.
  - Every write failure calls `onEditFailed` with UI-spec copy and never leaves a phantom edge/node; every success calls `onEditSaved` exactly once. `activateChanges` is never referenced (confirmed by `grep`).
  - Found and fixed during implementation: the gating effect must run *after* the network-construction (mount) effect, since React runs effects in declaration order and the gating effect bails out early if `networkRef.current` is still null -- see Deviations.

- **Task 2 — unmanaged-switch creation (addNode) and toolbar CSS:**
  - `addNode` prompts for a name (`window.prompt`), validates it with `checkmkWrite.isValidHostName` plus a duplicate-node-id check, then calls `checkmkWrite.createUnmanagedSwitch(name, {x, y})` at the rounded drop position. On success the new node gets the `PEND`-state visual (`nodeVisual("NetworkDevice", "PEND")`), the `"Unmanaged switch (not monitored)"` title, `physics: false`, and is recorded in the `pendingNodeAdds` overlay so it survives topology updates until the poller catches up.
  - `dashboard-react/src/index.css` gained the UI spec's exact `.vis-manipulation`/`.vis-button`/`.vis-active`/`.vis-delete` restyle, confirmed against `node_modules/vis-network/styles/vis-network.css` -- no class-name mapping was needed, the shipped 10.x classes match the spec verbatim.

## Task Commits

Each task followed a RED -> GREEN cycle:

1. **Task 1: Edge editing, position drag and edit-mode gating**
   - `b9c1ce1` test(13-06): add failing tests for edit-mode edge/position wiring
   - `e54764d` feat(13-06): wire edge editing, position drag and edit-mode gating
2. **Task 2: Add an unmanaged switch (addNode) and restyle the toolbar CSS**
   - `37f353b` test(13-06): add failing tests for addNode unmanaged-switch creation
   - `bd88621` feat(13-06): add unmanaged-switch creation and toolbar CSS restyle

## Files Created/Modified

- `dashboard-react/src/components/TopologyMap.tsx` - `editMode`-gated manipulation callbacks (`addEdge`/`editEdge`/`deleteEdge`/`addNode`), `dragEnd` position persistence, pending-edit overlay, `onEditSaved`/`onEditFailed` props
- `dashboard-react/src/components/TopologyMap.test.tsx` - 18 new `it()` cases (33 total) covering gating, all four manipulation callbacks' success/failure/edge-case paths, and the pending-overlay's add/remove/prune behavior
- `dashboard-react/src/test/fakeVisNetwork.ts` - `lastManipulation()` accessor and `disableEditModeCallCount` counter
- `dashboard-react/src/index.css` - manipulation-toolbar CSS restyle matching the design system's neutral/accent/destructive button styling

## Decisions Made

See `key-decisions` in the frontmatter above (position/switch failure copy, multi-edge `deleteEdge` generalization, and the deliberate absence of GSD plan/decision-ID citations in new comments).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Reordered the mount and gating `useEffect`s so manipulation wiring works on the very first render**
- **Found during:** Task 1, first GREEN run (tests rendering directly with `editMode: true` failed with `TypeError: addEdge is not a function`)
- **Issue:** The editMode-gating effect (which calls `network.setOptions({ manipulation: {...} })`) was declared before the network-construction (mount) effect. React runs effects in declaration order, so on a component's first render the gating effect fired first, found `networkRef.current` still `null`, and returned early -- the manipulation callbacks were never registered until a *second* render (e.g. toggling `editMode` off then on). A component that mounts directly with `editMode={true}` (a realistic case, not just a test artifact) would silently have no working toolbar.
- **Fix:** Moved the gating effect's declaration to after the mount effect, and added a comment explaining why declaration order matters here.
- **Files modified:** `dashboard-react/src/components/TopologyMap.tsx`
- **Verification:** Re-ran the full `TopologyMap.test.tsx` suite (28/28 passed with the reorder, vs. 9 failures before it) and the acceptance-criteria greps.
- **Committed in:** `e54764d` (Task 1 GREEN commit)

**2. [Test-authoring correction, not a deviation rule] Two overlay tests' bare `vi.fn()` callbacks didn't mutate the DataSet**
- **Found during:** Task 1, verifying the pending-overlay tests
- **Issue:** For `addEdge`/`deleteEdge`, the actual `nodes.add()`/`edges.remove()` DataSet mutation happens inside vis-network's own manipulation-system code when it receives the callback's result (confirmed by reading `node_modules/vis-network/dist/vis-network.cjs`'s `_performAddEdge`/`deleteSelected`) -- `TopologyMap.tsx`'s own `addEdge`/`deleteEdge` only ever *calls* the callback, it never mutates the DataSet directly for these two (unlike `editEdge`, which does mutate the DataSet itself). Two tests called the manipulation function directly with a bare `vi.fn()` standing in for vis-network's real callback, so the DataSet mutation these tests expected to observe never happened.
- **Fix:** Changed those two tests' callback argument to a small function that mirrors vis-network's own post-callback behavior (`edges.add(result)` / `edges.remove(result.edges)`), matching the source-verified contract.
- **Files modified:** `dashboard-react/src/components/TopologyMap.test.tsx`
- **Committed in:** `e54764d` (Task 1 GREEN commit, caught and fixed before committing)

---

**Total deviations:** 1 auto-fixed Rule 1 bug (effect ordering), 1 test-authoring correction caught before commit.
**Impact on plan:** The effect-ordering fix is a genuine correctness fix with real-world consequence (edit mode wouldn't work if a route ever mounted `TopologyMap` with `editMode` already `true`); the test fix corrects a test double's fidelity to the real library's behavior, no product-code scope creep.

## Issues Encountered

- None beyond the deviations above. Both tasks' behavior bullets and acceptance criteria were satisfied on the second implementation pass (after the effect-ordering fix).
- Confirmed the pre-existing, out-of-scope `GroupingControls.test.tsx` clock-drift failures (already logged in `deferred-items.md` by plan 13-02/13-03/13-05) are still present and unchanged by this plan's full `npm test` run -- not touched, per the Scope Boundary rule.
- The worktree's `dashboard-react/node_modules` was not yet installed (independent of the main checkout's, per the worktree isolation note) -- ran `npm install` before any test/typecheck/build command.

## User Setup Required

None -- no external service configuration required. (The `topology_editor` scoped credential this plan's writes depend on was already provisioned by plan 13-04/13-05's setup steps.)

## Next Phase Readiness

- `TopologyMap.tsx` now exposes `onEditSaved?: () => void` and `onEditFailed?: (failure: { title: string; body: string }) => void` -- plan 13-07's "Edit topology" `Switch`/`Banner`/`Apply changes` `Button` toolbar row can wire these directly: `onEditSaved` increments a pending-changes counter, `onEditFailed` drives a `Snackbar`.
- Every write in this plan applies immediately to Checkmk but is never activated (`activateChanges` is never called, confirmed by `grep`) -- 13-07 owns the single batched Apply action and the `countPendingChanges`/`activateChanges` calls from `checkmkWrite.ts`.
- The pending-edit overlay (`pendingEdgeAdds`/`pendingEdgeRemovals`/`pendingNodeAdds`) already handles "local edit not yet reflected by the live topology" for edges and nodes; 13-07 does not need to add its own overlay layer, only surface the *count* of pending edits (which it can track itself via `onEditSaved` calls, per the UI spec's "tracked client-side" note).
- **DASH-12/DASH-13 are not marked complete by this plan.** Both requirements explicitly describe the write going live "only when the operator presses a single 'Apply changes' action" (DASH-12) -- that toggle/Apply/feedback UI is plan 13-07's scope, not built here. `REQUIREMENTS.md` is left untouched (still `Pending`); whichever plan finishes the Apply flow should mark them complete.

---
*Phase: 13-wizard-parents-support-and-topology-map*
*Completed: 2026-09-23*

## Self-Check: PASSED

All 4 referenced files confirmed present via `test -f` (`TopologyMap.tsx`, `TopologyMap.test.tsx`,
`fakeVisNetwork.ts`, `index.css`) plus this SUMMARY.md. All 4 commit hashes (`b9c1ce1`, `e54764d`,
`37f353b`, `bd88621`) confirmed present in `git log --oneline --all`.
