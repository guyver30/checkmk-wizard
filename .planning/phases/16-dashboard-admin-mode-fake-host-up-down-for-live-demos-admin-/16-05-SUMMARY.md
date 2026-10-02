---
phase: 16-dashboard-admin-mode-fake-host-up-down-for-live-demos-admin-
plan: 05
subsystem: dashboard-react
tags: [admin-mode, react, zustand, kone-design-system]
requires: ["16-04"]
provides:
  - AdminBanner and AdminActionBar (confirm dialog, ack wait, result Snackbar)
  - Tree admin selection (host checkbox, ctrl/cmd+click, folder tri-state) and FAKED badge
  - Admin mode wired into IndexRoute; topology edit disabled in admin mode
key-files:
  created:
    - dashboard-react/src/components/AdminBar.tsx
    - dashboard-react/src/components/AdminBar.test.tsx
  modified:
    - dashboard-react/src/components/Tree.tsx
    - dashboard-react/src/components/TreeNode.tsx
    - dashboard-react/src/components/Tree.test.tsx
    - dashboard-react/src/components/TopologyToolbar.tsx
    - dashboard-react/src/components/TopologyToolbar.test.tsx
    - dashboard-react/src/routes/IndexRoute.tsx
    - dashboard-react/src/routes/IndexRoute.test.tsx
decisions:
  - "Confirm button uses design-system Button variant destructive (no color prop exists) for down/unreach/restore_all"
  - "Ghost button mapped to variant tertiary (no ghost variant in kone-design-system)"
  - "Restore all dialog count comes from the faked map, not the selection"
metrics:
  tasks: 3
  completed: 2026-10-02
---

# Phase 16 Plan 05: Admin UI (banner, action bar, tree selection) Summary

Admin-only chrome for `?admin=1`: a persistent ADMIN MODE banner, a bottom action bar whose every action goes through a confirm dialog (exact host names, cascade preview for Set DOWN), ack-driven result feedback with a 15 s no-answer timeout, tree selection with folder tri-state checkboxes, and a FAKED badge. Non-admin rendering is unchanged.

## Commits

- dc6c632, 580f798, 89aaa28: AdminBar.tsx and tests (task 1; the latter two are comment/format follow-ups)
- 4a29d23: Tree/TreeNode admin selection and FAKED badge (task 2)
- cfb3ec8: IndexRoute wiring and TopologyToolbar `disabledReason` (task 3)

## Verification (actually run)

- `npm run test`: 43 files, 603 tests passed (AdminBar 14 cases, Tree 23 incl. 8 admin cases, plus IndexRoute and TopologyToolbar additions)
- `npm run typecheck`: exit 0
- `npm run lint`: exit 0 (only pre-existing warnings in unrelated files)
- `npm run build`: succeeded
- Not verified: real browser rendering, the real broker ack round trip, banner 40px height (no live host/GUI available).

## Deviations from Plan

**1. [Rule 3 - Blocking] Design-system Button variants.** The plan said "ghost" and "danger color", but `ButtonVariant` is primary|secondary|tertiary|destructive|neutral. Used `tertiary` for Clear selection and `destructive` for the destructive confirms.

**2. [Rule 1] "Last:" line hidden on timeout results.** A timed-out result has count 0 and no real action outcome, so the "Last: ..." line is only shown for real acks.

No other deviations. `expirePending` timer is started by AdminActionBar on confirm (as noted in the 16-04 summary).

## Assumption Drift (advisory)

- Found during: Task 1. Planned: confirm button "color danger". Actual: `Button` has no color prop; `variant="destructive"` used. Why: design-system API.
- Folder checkbox includes subfolders (UI-SPEC assumption 4); still to be confirmed in UAT.

## Known Stubs

None. The map half of selection (ctrl+click on map nodes, map FAKED badge) is out of scope for this plan.

## Self-Check: PASSED
