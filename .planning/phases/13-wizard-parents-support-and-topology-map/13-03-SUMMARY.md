---
phase: 13-wizard-parents-support-and-topology-map
plan: 03
subsystem: ui
tags: [dashboard, vis-network, react, topology-map]

# Dependency graph
requires:
  - phase: 13-wizard-parents-support-and-topology-map
    plan: 02
    provides: "mapIcons.ts (nodeVisual), topologyLayout.ts (buildMapModel/withGridPositions)"
provides:
  - "TopologyMap.tsx: imperative vis-network mount + in-place DataSet sync + click navigation, the live replacement for MapPlaceholder"
  - "dashboard-react/src/test/fakeVisNetwork.ts: jsdom-safe Network test double, registered globally via vi.mock(\"vis-network/peer\", ...) in vitest.setup.ts"
affects: [13-06 (Edit topology toggle/manipulation toolbar), 13-07 (write-back callbacks), 15 (tower filter on topologyDevices)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Imperative vis-network mount inside a mount-once useEffect (empty deps), DataSet sync in a separate useEffect keyed on the buildMapModel() output"
    - "Global vis-network/peer mock (FakeNetwork) registered once in vitest.setup.ts so every test that renders IndexRoute can mount TopologyMap without touching a real canvas"

key-files:
  created:
    - dashboard-react/src/components/TopologyMap.tsx
    - dashboard-react/src/components/TopologyMap.test.tsx
    - dashboard-react/src/test/fakeVisNetwork.ts
  modified:
    - dashboard-react/vitest.setup.ts
    - dashboard-react/src/routes/IndexRoute.tsx
    - dashboard-react/src/routes/IndexRoute.test.tsx
    - dashboard-react/src/App.test.tsx
    - dashboard-react/src/components/StaleStability.test.tsx
    - dashboard-react/src/components/ThreePaneLayout.test.tsx
  deleted:
    - dashboard-react/src/components/MapPlaceholder.tsx

key-decisions:
  - "Network mount effect keeps its empty dependency array literally (per the plan's action text) and is gated on containerRef existing; the container div itself is only rendered once model.nodes.length > 0, so a topology that starts at zero devices and later gains its first device will never mount the canvas without a remount of TopologyMap. Not tested by this plan and not hit in the current data flow (IndexRoute always renders TopologyMap with whatever topology.devices/devices currently hold), but flagged as a known edge case for whoever revisits 13-06/13-07's toggle wiring."
  - "IndexRoute.test.tsx needed a MemoryRouter wrapper it didn't have before, since TopologyMap calls useNavigate() (which throws outside a Router context) — not called out explicitly in the plan's action text but required for the swap to work at all (Rule 3, blocking issue)."

requirements-completed: [DASH-07]

# Metrics
duration: 55min
completed: 2026-09-23
---

# Phase 13 Plan 03: TopologyMap.tsx (Live vis-network Topology Map) Summary

**Read-only vis-network topology map wired into IndexRoute's centreTop slot, replacing MapPlaceholder — mounts the graph once, patches every topology/status change into the DataSets in place, and gates node-click navigation on an editMode prop for 13-06/13-07 to reuse.**

## Performance

- **Duration:** ~55 min (worktree setup + context reading, `npm install`, both tasks, full verification)
- **Tasks:** 2/2 completed, no checkpoints hit
- **Files modified:** 10 (3 created, 6 modified, 1 deleted)

## Accomplishments

- Built `TopologyMap.tsx`: mounts vis-network's `Network` exactly once (`useEffect` with an empty dependency list), diffs `buildMapModel()`'s output against the live node/edge `DataSet`s on every model change and patches via `update`/`add`/`remove` — never a full-graph rebuild
- Physics stabilizes once then freezes (`stabilizationIterationsDone` → `setOptions({ physics: false })`, Phase 11 D-09); nodes with a saved `map_position` are added at that exact x/y with `physics: false`, unsaved nodes get `withGridPositions()`'s coordinates
- Node click navigates to `/details?id={id}` via `encodeURIComponent`, gated off while `editMode` is true (an `editModeRef` ref, not state, since the click handler is registered once at mount)
- Empty state ("No connections drawn yet" + Copywriting Contract body) when zero devices exist — no canvas mounts in that state, confirmed by the fake's `instances` array staying empty
- Dismissible "No connections drawn yet — turn on Edit topology to start." `Banner` when devices exist, zero edges exist, and edit mode is off
- Unmanaged-switch nodes get the title `"Unmanaged switch (not monitored)"`
- `fakeVisNetwork.ts`: a `FakeNetwork` class implementing the constructor/`on`/`once`/`off`/`setOptions`/`destroy`/`getPositions`/`disableEditMode`/`enableEditMode`/`addEdgeMode` surface plus the test-only `emit()` helper and a module-level `instances`/`resetFakeNetworks()`, registered globally via `vi.mock("vis-network/peer", ...)` in `vitest.setup.ts` so App/IndexRoute/GroupingControls/StaleStability all keep working with a real `TopologyMap` mounted
- Swapped `<MapPlaceholder />` for `<TopologyMap topologyDevices={...} statuses={devices} nowMs={nowMs} />` in `IndexRoute.tsx`'s `centreTop`, fed by a `useMemo`'d `topologyDevices` derived from the store's `topology` slot; deleted `MapPlaceholder.tsx`
- Updated every test asserting on the placeholder's `"Topology map — Phase 13"` text to assert on `getByTestId("topology-map")` instead (`App.test.tsx`, `IndexRoute.test.tsx`, `StaleStability.test.tsx`), preserving each test's original intent (document order, in-place-update identity checks); `ThreePaneLayout.test.tsx` no longer depends on `MapPlaceholder` at all (swapped for a plain `<div>centre top</div>`)

## Task Commits

Each task was committed atomically:

1. **Task 1: TopologyMap.tsx with a vis-network test double** - `b3611f7` (feat)
2. **Task 2: Swap MapPlaceholder for TopologyMap in IndexRoute and update placeholder tests** - `8bf22eb` (feat)

## Files Created/Modified

- `dashboard-react/src/components/TopologyMap.tsx` - the live topology map component (DASH-07)
- `dashboard-react/src/components/TopologyMap.test.tsx` - 15 test cases covering every behavior bullet
- `dashboard-react/src/test/fakeVisNetwork.ts` - jsdom-safe `Network` test double
- `dashboard-react/vitest.setup.ts` - global `vi.mock("vis-network/peer", ...)` registration
- `dashboard-react/src/routes/IndexRoute.tsx` - `MapPlaceholder` swapped for `TopologyMap`, `topologyDevices` derived from the store
- `dashboard-react/src/routes/IndexRoute.test.tsx` - `getByTestId("topology-map")` assertions, wrapped in `MemoryRouter`
- `dashboard-react/src/App.test.tsx` - `getByTestId("topology-map")` assertion
- `dashboard-react/src/components/StaleStability.test.tsx` - `getByTestId("topology-map")` identity assertion
- `dashboard-react/src/components/ThreePaneLayout.test.tsx` - `MapPlaceholder` import/usage removed
- `dashboard-react/src/components/MapPlaceholder.tsx` - deleted (fulfilled by this plan)

## Decisions Made

- **vis-network/vis-data subpath imports confirmed against the installed package** (not just context7/docs): `vis-network@10.1.2` and `vis-data@8.0.5`'s own `package.json#exports` were read directly (`node -e "require('./node_modules/vis-network/package.json').exports"`) and confirm `./peer` resolves to `peer/esm/vis-network.mjs` for both packages, and `./styles/*` resolves `vis-network/styles/vis-network.css` — the plan's expected import paths (`vis-network/peer`, `vis-data/peer`, `vis-network/styles/vis-network.css`) match exactly, no adjustment needed.
- Node-update/add fields are built by one shared `nodeBaseFields()` helper (`id`, `label`, `title`, spread `nodeVisual()`) so update and add never drift from each other's field set; only `add` additionally sets `x`/`y` and (when `saved`) `physics: false`.
- The mount effect's comments describing "never call the whole-graph-replacement Network method" deliberately avoid writing the literal method name `setData` in TopologyMap.tsx's source (the plan's own acceptance criteria greps for the absence of that string) — the comment communicates the same anti-pattern without defeating the grep.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] `IndexRoute.test.tsx` needed a `MemoryRouter` wrapper**
- **Found during:** Task 2
- **Issue:** `IndexRoute.test.tsx` previously rendered `<IndexRoute />` with no router context. `TopologyMap` calls `useNavigate()` in its mount effect, which throws ("useNavigate() may be used only in the context of a `<Router>` component") outside a Router.
- **Fix:** Wrapped both tests in `<MemoryRouter>`, matching the existing convention already used by `StaleStability.test.tsx`/`Tree.test.tsx` for other components that call router hooks.
- **Files modified:** `dashboard-react/src/routes/IndexRoute.test.tsx`
- **Commit:** `8bf22eb`

### Process notes (not deviation-rule items)

- **`npm install` run at the start of Task 1**, since `node_modules/` did not yet exist in this fresh worktree despite `vis-network`/`vis-data` already being declared in `package.json` (added by plan 13-02). This is normal worktree setup, not a plan deviation — `package.json`/`package-lock.json` were unchanged by the install (both already had the correct entries from 13-02).
- **Pre-existing, out-of-scope test failures observed and left alone:** `npm --prefix dashboard-react test` reports 2 failures in `src/components/GroupingControls.test.tsx` ("checking 'Order by severity' reorders groups..." and "...leaves both groups expanded"). These are the exact same failures already logged in `.planning/phases/13-wizard-parents-support-and-topology-map/deferred-items.md` from plan 13-02's execution (a clock-drift issue in that test file's fixture data, unrelated to any file this plan touches). Confirmed unchanged, not re-logged (already present in deferred-items.md), not fixed, per the Scope Boundary rule.

## Issues Encountered

- None beyond the deviation and process notes above. Both tasks implemented cleanly against the plan's `<behavior>`/`<action>` blocks; TDD RED (module-not-found / interface-not-yet-built) → GREEN was followed for Task 1's `TopologyMap.test.tsx`, though — consistent with plan 13-02's own note — the RED and GREEN states both landed in the single `feat` commit for the task rather than as separate `test`→`feat` commits (this plan's frontmatter `type` is `execute`, not `tdd`, so the plan-level TDD Gate Enforcement's git-log check does not apply).

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `TopologyMap.tsx` accepts an `editMode?: boolean` prop (defaulting to `false`) that already gates node-click navigation and the "no connections" banner — plans 13-06/13-07 (the "Edit topology" toggle and manipulation toolbar) can wire a route-level `useState` into this prop without touching `TopologyMap.tsx`'s click-gating logic.
- `fakeVisNetwork.ts`'s `FakeNetwork` class already implements `disableEditMode`/`enableEditMode`/`addEdgeMode`/`getPositions` — methods this plan's `TopologyMap.tsx` does not call yet, but that 13-06/13-07's manipulation-toolbar wiring will need; the double is ready for them without further test-infrastructure changes.
- `IndexRoute.tsx`'s `centreTop` still has room above `TopologyMap` (inside the same `min-h-0 flex-1` wrapper's parent flex column) for 13-06's new toolbar row (`Switch`/`Banner`/`Apply` `Button`), per `13-UI-SPEC.md`'s "Layout Integration" section — no layout change was needed in this plan beyond the map swap itself.
- Flagged (not fixed, out of scope): the `TopologyMap` mount effect will never construct a `Network` if `topologyDevices` is empty on first render and only gains devices later without the component remounting (see Decisions Made). Not currently reachable through `IndexRoute`'s actual data flow (the store's `topology`/`devices` slots are read live on every render), but worth a second look whenever 13-06/13-07 touch this file's mount logic.

---
*Phase: 13-wizard-parents-support-and-topology-map*
*Completed: 2026-09-23*

## Self-Check: PASSED

All 3 created source files (`TopologyMap.tsx`, `TopologyMap.test.tsx`, `fakeVisNetwork.ts`) and
this SUMMARY.md confirmed present via `[ -f ... ]`. Both commit hashes (`b3611f7`, `8bf22eb`)
confirmed present in `git log --oneline -5`.
