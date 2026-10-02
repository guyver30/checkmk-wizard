---
phase: 16-dashboard-admin-mode-fake-host-up-down-for-live-demos-admin-
plan: 10
subsystem: dashboard-react
tags: [admin-mode, selection, gap-closure]
requirements: [D-11, D-12, D-13]
key-files:
  modified:
    - dashboard-react/src/store/adminStore.ts
    - dashboard-react/src/components/TopologyMap.tsx
    - dashboard-react/src/components/TreeNode.tsx
    - dashboard-react/src/routes/IndexRoute.tsx
    - dashboard-react/src/components/AdminBar.tsx
    - .planning/phases/16-dashboard-admin-mode-fake-host-up-down-for-live-demos-admin-/16-UI-SPEC.md
metrics:
  completed: 2026-10-02
---

# Phase 16 Plan 10: Admin selection gap closure Summary

In admin mode a plain click on a map node or tree row now selects exactly that host (ctrl/cmd+click toggles), host details are suppressed, a "Select all" button selects only the currently listed hosts, and the Restore dialog copy describes the demo baseline.

## Commits
- dee9e75: replaceSelection store action; map and tree plain-click select, no navigation
- 705d074: IndexRoute hides host details in admin mode and passes visibleHostIds; AdminBar Select all, new hint and restore copy; UI-SPEC amended

## Verification (actually run)
- `npx vitest run`: 43 files, 619 tests passed
- `npm run typecheck`: clean
- `npm run lint`: warnings only, all in files/lines not introduced here (StateBadge, GroupingControls, StatsStrip, ThreePaneLayout, TopologyMap navigate dep); no errors
- `npm run build`: succeeded

## Deviations from Plan
None. Both tasks were committed per task; the IndexRoute and its test changes for both tasks landed in the second commit because they share files.

## Notes
- Select all uses the tree model (all groups' children), deduplicated and sorted; disabled when configError, nothing listed, or selection already equals the listed set.
- Empty-canvas/edge click in admin mode is a no-op (also no longer clears ?host= there, since details are off in admin mode).

## Known Stubs
None.

## Self-Check: PASSED
