---
phase: 16
plan: 06
subsystem: dashboard-react
tags: [admin-mode, topology-map, selection]
requires: [16-04]
provides: [map ctrl/cmd+click admin selection, FAKED node caption]
key-files:
  modified: [dashboard-react/src/components/TopologyMap.tsx, dashboard-react/src/components/TopologyMap.test.tsx]
metrics:
  completed: 2026-10-02
---

# Phase 16 Plan 06: Map admin selection and FAKED marker Summary

TopologyMap supports admin-only ctrl/cmd+click multi-select into the shared useAdminStore selection, with a 3px brand border plus checkmark on selected nodes and a FAKED caption on faked hosts; behavior is unchanged outside admin mode.

## Task 1 (commit a49086a)
- nodeBaseFields takes an optional admin decoration; the cached nodeVisual is spread, never mutated.
- Click handler's first branch handles ctrl/meta in admin mode (toggle node, no-op on empty canvas); plain clicks navigate as before. vis-network multiselect is not enabled.
- Sync effect depends on adminSelected/adminFaked, so selection persists across data refreshes.
- 7 new tests in "TopologyMap admin mode". Verified by running: full vitest suite 585 passed, typecheck clean, lint shows only pre-existing warnings.

## Deviations from Plan
None.

## Assumption Drift (advisory) / note for Plan 08
Assumption A2: modifier keys are read from params.event.srcEvent (ctrlKey/metaKey). Tested only against the FakeNetwork, not in a real browser. Plan 08 must verify. Fallback: window keydown/keyup Control/Meta tracker.

## Self-Check: PASSED
