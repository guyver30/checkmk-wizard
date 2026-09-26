---
phase: 14-fleet-intelligence
plan: 03
subsystem: dashboard
tags: [dashboard, tree, topology-map, incidents, dimming]

requires:
  - phase: 14-fleet-intelligence (plan 14-02)
    provides: "IncidentLookup type, buildIncidentLookup(), IncidentMembership shape from lib/incidents.ts"
provides:
  - "treeModel.ts buildTree(options.incidentLookup) — TreeDeviceNode.dimmed/incidentId/incidentRole/inferredRoot"
  - "TreeNode.tsx dimmed-row rendering: opacity-50 details link, 'See incident' badge/link, 'Inferred, not confirmed' badge"
  - "topologyLayout.ts buildMapModel(..., incidentLookup) — MapNode.dimmed/incidentId/incidentRole/inferredRoot"
  - "mapIcons.ts nodeVisual(deviceType, state, emphasis) — 'dimmed'/'inferred-root' NodeEmphasis variants"
  - "TopologyMap.tsx incidentLookup prop — dimmed node styling/title, consequence-node click routes to /?incident={id}"
affects: [14-04]

tech-stack:
  added: []
  patterns:
    - "Plain optional parameter for derived-lookup data (incidentLookup), never a store read — same discipline as orderBySeverity/topologyDevices"
    - "vis-network click handler reads latest derived state through a ref (modelRef), mirroring the existing editModeRef pattern, since the handler is registered once in the mount effect"

key-files:
  created: []
  modified:
    - dashboard-react/src/lib/treeModel.ts
    - dashboard-react/src/lib/treeModel.test.ts
    - dashboard-react/src/components/TreeNode.tsx
    - dashboard-react/src/components/Tree.test.tsx
    - dashboard-react/src/lib/topologyLayout.ts
    - dashboard-react/src/lib/topologyLayout.test.ts
    - dashboard-react/src/lib/mapIcons.ts
    - dashboard-react/src/lib/mapIcons.test.ts
    - dashboard-react/src/components/TopologyMap.tsx
    - dashboard-react/src/components/TopologyMap.test.tsx

key-decisions:
  - "Inferred-root styling uses STATE_HEX.WARN (#f97316) with a dashed border on the map and a warning/soft Badge in the tree, never DOWN/UNREACH red — an inferred root's own Checkmk state is UP (unchecked), so red would assert something monitoring cannot see (D-04)"
  - "Map click on a consequence node navigates to /?incident={id}; the tree keeps its device-name link to /details plus a separate 'See incident' link, so the details page stays reachable from the tree"

requirements-completed: [DASH-15]

duration: 10min
completed: 2026-09-26
---

# Phase 14 Plan 03: Dimmed Consequence Treatment (Tree + Topology Map) Summary

**Consequence hosts of an open incident now render dimmed and link to their incident — in the fleet tree via an additive `incidentLookup` option on `buildTree`, and on the topology map via a 4th `incidentLookup` parameter on `buildMapModel` plus a new `NodeEmphasis` variant on `nodeVisual` — while incident roots keep full alarm styling and inferred (unmanaged-switch) roots get a distinct dashed warning border.**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-09-26

## Accomplishments

- `treeModel.ts`: `TreeDeviceNode` gains `dimmed`/`incidentId`/`incidentRole`/`inferredRoot`; `BuildTreeOptions` gains a plain `incidentLookup?: IncidentLookup` parameter (never a store read, same discipline as `orderBySeverity`)
- `TreeNode.tsx`: a dimmed device row's details `<Link>` gets `opacity-50` and its own state badge is replaced by a neutral "See incident" badge wrapped in a `<Link to="/?incident={id}">`; an inferred root shows a warning/soft "Inferred, not confirmed" `Badge` instead; a non-incident row is byte-for-byte unchanged
- `topologyLayout.ts`: `MapNode` gains the same four fields; `buildMapModel` gains a 4th `incidentLookup: IncidentLookup = new Map()` parameter, populated identically to `treeModel.ts`'s mapping
- `mapIcons.ts`: `nodeVisual` gains a 3rd `emphasis: NodeEmphasis = "normal"` parameter (`"normal" | "dimmed" | "inferred-root"`), cache key extended to `${deviceType}|${state}|${emphasis}`; `"dimmed"` sets `opacity: 0.4` and flattens the border to neutral (`#96969f`, width 2, no dashes); `"inferred-root"` recolors the icon itself and its border to the warning hue (`#f97316`, width 3, dashed `[6, 3]`)
- `TopologyMap.tsx`: new `incidentLookup?: IncidentLookup` prop threaded into the `buildMapModel` `useMemo` (added to its deps); `nodeBaseFields` picks emphasis/title from `node.inferredRoot`/`node.dimmed`/`node.unmanaged` in that priority order; a new `modelRef` (kept current via an effect on `model`) lets the once-registered click handler read the latest node and, outside edit mode, route a consequence-node click to `/?incident={id}` instead of `/details?id={id}`

## Task Commits

1. **Task 1: Tree dimming — treeModel incident fields and TreeNode rendering** - `58b63bd` (feat)
2. **Task 2: Map dimming — MapNode incident fields, nodeVisual emphasis, TopologyMap prop and click routing** - `33cfb68` (feat)

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified

- `dashboard-react/src/lib/treeModel.ts` — `incidentLookup` option, four new `TreeDeviceNode` fields
- `dashboard-react/src/lib/treeModel.test.ts` — 3 new `buildTree` behavior cases (consequence/root/unrelated, inferred root, no-lookup default)
- `dashboard-react/src/components/TreeNode.tsx` — dimmed-row/inferred-root rendering
- `dashboard-react/src/components/Tree.test.tsx` — 3 new rendering cases
- `dashboard-react/src/lib/topologyLayout.ts` — `incidentLookup` 4th parameter, four new `MapNode` fields
- `dashboard-react/src/lib/topologyLayout.test.ts` — 3 new `buildMapModel` behavior cases; two pre-existing `withGridPositions` fixtures updated with the new required `MapNode` fields (Rule 3, see Deviations)
- `dashboard-react/src/lib/mapIcons.ts` — `NodeEmphasis` type, `nodeVisual`'s 3rd parameter and dimmed/inferred-root styling
- `dashboard-react/src/lib/mapIcons.test.ts` — 3 new `emphasis` behavior cases; 2 pre-existing assertions corrected (see Deviations)
- `dashboard-react/src/components/TopologyMap.tsx` — `incidentLookup` prop, `modelRef`, emphasis/title selection, consequence-click routing
- `dashboard-react/src/components/TopologyMap.test.tsx` — 6 new cases (dimmed node styling, consequence click → `/?incident=`, non-consequence click → `/details`, edit-mode no-op, inferred-root styling, no-lookup unchanged)

## Decisions Made

- Inferred-root styling: warning hue (`STATE_HEX.WARN` #f97316) with a dashed border on the map, and a `Badge color="warning" variant="soft"` reading "Inferred, not confirmed" in the tree — matches the plan's locked rationale (D-04: an inferred root's own state is UP/unchecked, so DOWN/UNREACH red would assert something monitoring cannot see).
- Map click on a consequence node navigates to `/?incident={id}`; the tree keeps the device-name link to `/details` plus a separate "See incident" link, so the details page stays reachable from the tree.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Pre-existing stale `mapIcons.test.ts` assertions fixed as directed by the orchestrator's setup instructions**
- **Found during:** environment setup (full `npm test` baseline, matching the known issue logged in `deferred-items.md` during plan 14-02)
- **Issue:** two assertions in `deviceTypeSvg`'s test block expected `fill="#141414"` / an old `internet.svg` path fragment (`"15.1001 7.9"`) that no longer exist — the device-type icons became stroke-based (`fill="none" stroke="currentColor"`) in commit `a427d92`, well before this plan
- **Fix:** corrected the two assertions to match the current, correct icon markup (no icon SVG file touched); this plan already modifies `mapIcons.test.ts` for its own `NodeEmphasis` tests, so the orchestrator's setup instructions directed fixing this in the same file as a separate commit
- **Files modified:** `dashboard-react/src/lib/mapIcons.test.ts`
- **Verification:** `npm test -- src/lib/mapIcons.test.ts` — 17/17 passed after the fix
- **Committed in:** `43170f4` (test, separate from both feature task commits)

**2. [Rule 3 - Blocking] Fixed a typecheck break in `topologyLayout.test.ts`'s `withGridPositions` fixtures and `TopologyMap.tsx`'s `addNode` pending-overlay object caused by the new required `MapNode` fields**
- **Found during:** Task 2 verification (`npm run typecheck`)
- **Issue:** `withGridPositions`'s two test fixtures (hand-built `MapNode`-shaped literals) and `TopologyMap.tsx`'s `pendingNodeAdds.current.set(name, {...})` call no longer satisfied the `MapNode` interface once `dimmed`/`incidentId`/`incidentRole`/`inferredRoot` became required fields
- **Fix:** added `dimmed: false, incidentId: null, incidentRole: null, inferredRoot: false` to all three literals, matching every other `MapNode`-producing site
- **Files modified:** `dashboard-react/src/lib/topologyLayout.test.ts`, `dashboard-react/src/components/TopologyMap.tsx`
- **Verification:** `npm run typecheck` exits 0; `npm test` (full suite) 401/401 passed afterward
- **Committed in:** `33cfb68` (part of Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3, blocking type-check/pre-existing-test fixes required for the plan's own verification commands to pass). No scope creep — every touched file was already in the plan's `files_modified` list or is the pre-existing stale-test fix the orchestrator's setup instructions explicitly directed to this plan.

## Issues Encountered

- `dashboard-react/node_modules` and `design-system/kone-design-system-0.1.0.tgz` were absent in this worktree (not shared across worktrees; the tarball is a gitignored build artifact). Copied the prebuilt tarball from the main checkout's `design-system/` directory and ran `npm install` before any test/typecheck/lint command, per the orchestrator's environment-setup instructions.
- The known pre-existing `mapIcons.test.ts` failure (2 assertions, logged in `deferred-items.md` during plan 14-02) is now fixed — see Deviations item 1. No other pre-existing failures were found; the full `npm test` suite is 401/401 green.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Plan 14-04 can now wire a live `incidentLookup` (built from `lib/incidents.ts`'s `buildIncidentLookup(selectOpenIncidents(store.incidents))`) into `IndexRoute.tsx`'s `buildTree(...)` and `<TopologyMap incidentLookup={...} />` calls — both consumers are additive/optional, so this plan's changes require no further modification to accept live data.
- `/?incident={id}` is now a real, reachable link from both the tree and the map; plan 14-04's `IncidentList`/`IncidentCard` work can rely on this query param existing as a deep-link target.

---
*Phase: 14-fleet-intelligence*
*Completed: 2026-09-26*

## Self-Check: PASSED

All modified files verified present (`treeModel.ts`, `treeModel.test.ts`, `TreeNode.tsx`, `Tree.test.tsx`,
`topologyLayout.ts`, `topologyLayout.test.ts`, `mapIcons.ts`, `mapIcons.test.ts`, `TopologyMap.tsx`,
`TopologyMap.test.tsx`); all three task/deviation commits (`58b63bd`, `43170f4`, `33cfb68`) verified
present in `git log --oneline --all`; full `npm test` suite 401/401 passed, `npm run typecheck` exit 0,
`npm run lint` exit 0 (pre-existing warnings only, no new ones).
