---
phase: 13-wizard-parents-support-and-topology-map
plan: 02
subsystem: ui
tags: [dashboard, vis-network, react, pure-functions, topology]

# Dependency graph
requires:
  - phase: 11.1-dashboard-layout-and-light-palette
    provides: display.ts (displayName/effectiveState), staleness.ts (isDeviceStale), stateMapping.ts, the pure lib/ module convention
provides:
  - "vis-network@^10.1.2 and vis-data@^8.0.5 installed as npm dependencies of dashboard-react"
  - "Six vendored device-type SVGs at dashboard-react/src/assets/icons/device-types/, byte-identical to the kone-design-system source"
  - "mapIcons.ts: STATE_HEX, deviceTypeSvg, recoloredDataUri, nodeVisual (data-URI icon builder with CRIT/UNREACH/DOWN border differentiation, cached per deviceType|state)"
  - "topologyLayout.ts: buildMapModel, initialGridPositions, parseMapPosition, formatMapPosition, withGridPositions, and the MAP_POSITION_LABEL/UNMANAGED_SWITCH_LABEL/GRID_SPACING constants"
  - "TopologyNode interface in types.ts (all fields optional, buildMapModel is the runtime guard)"
affects: [13-03 (TopologyMap.tsx component), 13-04 (poller map_position/unmanaged fields), 13-05 (browser Checkmk write client)]

# Tech tracking
tech-stack:
  added: [vis-network, vis-data]
  patterns:
    - "Pure, DOM-free lib/ modules (mapIcons.ts, topologyLayout.ts) mirroring display.ts's header-comment contract and defensive-fallback convention"
    - "Vendored SVG assets imported with Vite's ?raw suffix, recolored via string-replace into a data:image/svg+xml URI, cached by a composite key to avoid re-encoding unchanged nodes"

key-files:
  created:
    - dashboard-react/src/lib/mapIcons.ts
    - dashboard-react/src/lib/mapIcons.test.ts
    - dashboard-react/src/lib/topologyLayout.ts
    - dashboard-react/src/lib/topologyLayout.test.ts
    - dashboard-react/src/assets/icons/device-types/internet.svg
    - dashboard-react/src/assets/icons/device-types/api.svg
    - dashboard-react/src/assets/icons/device-types/secured.svg
    - dashboard-react/src/assets/icons/device-types/videocam.svg
    - dashboard-react/src/assets/icons/device-types/controls.svg
    - dashboard-react/src/assets/icons/device-types/circle.svg
  modified:
    - dashboard-react/package.json
    - dashboard-react/package-lock.json
    - dashboard-react/src/lib/types.ts

key-decisions:
  - "buildMapModel/topologyLayout.ts take a plain device-list parameter and never read the store (D-11 forward-compatibility for Phase 15's tower filter)"
  - "nodeVisual() caches its generated data URI in a module-level Map keyed by deviceType|state so a DataSet.update() of an unchanged node does not re-encode"

patterns-established:
  - "Canvas-compatible SVG recoloring: fill=\"#141414\" string-replace + encodeURIComponent, transcribing hex values from 13-UI-SPEC.md rather than reading CSS custom properties (which canvas code cannot access)"

requirements-completed: [DASH-07]

# Metrics
duration: 25min
completed: 2026-09-23
---

# Phase 13 Plan 02: Topology Data Layer (mapIcons, topologyLayout) Summary

**Pure, unit-tested vis-network data layer — state-coloured SVG icon builder and topology-to-node/edge model with grid placement — with vis-network/vis-data installed as npm deps.**

## Performance

- **Duration:** ~4 min of active work (two atomic commits, both tasks completed without checkpoints)
- **Started:** 2026-09-23T13:22:00+08:00 (approx, worktree branch-check completion)
- **Completed:** 2026-09-23T13:28:16+08:00
- **Tasks:** 2/2 completed
- **Files modified:** 13 (10 created, 3 modified)

## Accomplishments
- Installed `vis-network@^10.1.2`/`vis-data@^8.0.5` as npm dependencies (both legitimacy-audited [OK] in 13-RESEARCH.md) and vendored the six device-type SVGs byte-for-byte
- Built `mapIcons.ts`: the `STATE_HEX` palette (8 states), `deviceTypeSvg()` lookup (never throws, falls back to circle.svg), `recoloredDataUri()` (fill-color string-replace + `encodeURIComponent` data URI), and `nodeVisual()` (full vis-network node style with the CRIT/UNREACH/DOWN border-weight/dash differentiation table from 13-UI-SPEC.md, cached per `deviceType|state`)
- Built `topologyLayout.ts`: `buildMapModel()` turns a raw topology device list + device statuses into a defensive node/edge model (skips malformed entries, dangling parent refs, duplicate ids, non-array `parents`; mirrors the STALE-overrides-state rule from `store/selectors.ts`), plus `parseMapPosition`/`formatMapPosition` (strict `^-?\d{1,6},-?\d{1,6}$` codec) and `initialGridPositions`/`withGridPositions` (row-major grid, saved positions preserved, unsaved nodes offset below the largest saved y)
- Added `TopologyNode` interface to `types.ts` (all fields optional; `buildMapModel` is the documented runtime guard)

## Task Commits

Each task was committed atomically:

1. **Task 1: Install vis-network/vis-data, vendor device-type SVGs, build mapIcons.ts** - `893e78f` (feat)
2. **Task 2: topologyLayout.ts (buildMapModel, grid, position codec) and TopologyPayload types** - `045f424` (feat)

_Note: both tasks had `tdd="true"`; test files were written and run to confirm RED (module-not-found failure) before the implementation was written and re-run to confirm GREEN, but each task's test+implementation landed in a single `feat` commit rather than separate `test`→`feat` commits — see Deviations._

## Files Created/Modified
- `dashboard-react/package.json` / `package-lock.json` - add `vis-network`, `vis-data` dependencies
- `dashboard-react/src/assets/icons/device-types/{internet,api,secured,videocam,controls,circle}.svg` - byte-identical vendored copies from `web_assets/kone-design-system-main/packages/kone-ds-assets/icons/`
- `dashboard-react/src/lib/mapIcons.ts` - state-hex table, device-type SVG lookup, data-URI recolor, cached node-visual builder
- `dashboard-react/src/lib/mapIcons.test.ts` - 15 test cases covering every behavior bullet
- `dashboard-react/src/lib/topologyLayout.ts` - map-position codec, grid layout, `buildMapModel`/`withGridPositions`
- `dashboard-react/src/lib/topologyLayout.test.ts` - 23 test cases covering every behavior bullet
- `dashboard-react/src/lib/types.ts` - added `TopologyNode` interface, doc comment on `TopologyPayload.devices`

## Decisions Made
- None beyond what CONTEXT.md/UI-SPEC.md/PATTERNS.md already locked (D-08, D-09, D-11 applied as specified). No new architectural decisions were required during execution.

## Deviations from Plan

### Auto-fixed Issues

None — no bugs, missing-critical-functionality, or blocking issues were encountered; both tasks implemented cleanly against the plan's `<behavior>`/`<action>` blocks on the first pass.

### Process note (not a deviation rule, documented for transparency)

**Combined RED+GREEN commit per task, rather than separate `test(...)`/`feat(...)` commits.** The `tdd_execution` reference describes a two-commit pattern (`test(...)` after RED, `feat(...)` after GREEN) for `tdd="true"` tasks. For both tasks in this plan, the RED state (test file added, run, confirmed failing on "module not found") and GREEN state (implementation added, run, confirmed passing) were both verified via actual `npm test` runs, but the resulting diff was staged and committed once per task rather than as two separate commits. This plan's frontmatter `type` is `execute`, not `tdd`, so the plan-level TDD Gate Enforcement's git-log check (which requires a `test(...)` commit before a `feat(...)` commit) does not apply here. No functional impact — the RED/GREEN discipline was followed procedurally, only the commit granularity differs from the task-level convention.

## Issues Encountered

- **Stale worktree branch base:** at agent start, `git merge-base HEAD <expected-base>` did not match the expected base commit — the worktree branch (`worktree-agent-ab430410d809c7bd3`) had been left on an old commit from a prior, unrelated phase (11.1). Per the `worktree_branch_check` step's own instructions, ran `git reset --hard <expected-base>` (verified clean working tree first via `git status --short`) to correct it before any task work began.
- **Full `npm --prefix dashboard-react test` run shows 2 pre-existing failures** in `src/components/GroupingControls.test.tsx`, unrelated to any file this plan touches. Logged to `.planning/phases/13-wizard-parents-support-and-topology-map/deferred-items.md` per the Scope Boundary rule (not fixed, not in scope).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `mapIcons.ts` and `topologyLayout.ts` are ready for plan 13-03 (`TopologyMap.tsx`) to import directly — `buildMapModel(topologyDevices, statuses, nowMs)` produces the exact `{ nodes, edges }` shape the vis-network `DataSet`s need, and `nodeVisual(deviceType, state)` produces the exact per-node style object.
- `npm --prefix dashboard-react run build` succeeds — the `?raw` SVG imports resolve correctly in a production Vite build, confirming plan 13-03 can rely on the same import mechanism.
- Not a blocker, but worth flagging for 13-03/13-04: this plan's `buildMapModel` signature intentionally omits any tag/filter parameter (D-11) — Phase 15's tower filter, when it arrives, should call `buildMapModel` with an already-filtered `topologyDevices` array rather than needing a new parameter.

---
*Phase: 13-wizard-parents-support-and-topology-map*
*Completed: 2026-09-23*
