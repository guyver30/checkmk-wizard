---
status: complete
---
# Quick 261002-nbm: empty-canvas click clears admin selection; tree double-click centres the map

User requests after Phase 16 re-test ("all good").
1. Admin mode: a plain click on empty map canvas (not a node or edge) clears the selection. Ctrl/cmd+click on empty canvas and edge clicks still change nothing. This reverses the plan 16-10 choice that an empty-canvas click does nothing (UI-SPEC amended).
2. Outside admin mode: double-clicking a host row in the device tree centres the map on that host via `network.focus` keeping the current zoom. New `store/mapFocusStore.ts` (request with a seq counter so repeat double-clicks re-centre; requests pending at map mount are ignored). Admin mode does not raise the request.

Files: TopologyMap.tsx, TreeNode.tsx, store/mapFocusStore.ts (+tests), test/fakeVisNetwork.ts (focus), Tree.test.tsx, TopologyMap.test.tsx; docs: dashboard-react/README.md, runbook, 16-UI-SPEC.md.
Verified: vitest 44 files / 628 tests pass, typecheck clean, lint no errors. Not checked in a real browser: that vis-network `focus` animates smoothly to a node inside the grouped layout.
