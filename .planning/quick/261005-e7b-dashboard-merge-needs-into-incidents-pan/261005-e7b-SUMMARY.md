---
phase: quick-261005-e7b
plan: 01
subsystem: dashboard-react
tags: [dashboard, triage, tabs, 14.2]
requires: [14.2 needs pane, triage menu]
provides: [combined Incidents & needs tabbed pane, triage in every dashboard mode]
affects: [ThreePaneLayout, IndexRoute, NeedRow, usePaneLayout]
key-files:
  created:
    - dashboard-react/src/components/AlertsPane.tsx
    - dashboard-react/src/components/AlertsPane.test.tsx
  modified:
    - dashboard-react/src/components/ThreePaneLayout.tsx
    - dashboard-react/src/components/NeedRow.tsx
    - dashboard-react/src/components/NeedsPane.tsx
    - dashboard-react/src/components/IncidentList.tsx
    - dashboard-react/src/routes/IndexRoute.tsx
    - dashboard-react/src/hooks/usePaneLayout.ts
    - dashboard-react/README.md
    - deploy/dashboard-nginx.conf
    - .planning/phases/14.2-fleet-failure-prediction-and-incident-narration/14.2-CONTEXT.md
    - .planning/phases/14.2-fleet-failure-prediction-and-incident-narration/14.2-UI-SPEC.md
decisions:
  - "Triage visible in every mode (reverses 14.2 D-24) so ?admin=1 demos can triage"
  - "Edit mode: combined pane stays, Incidents tab disabled, Needs forced, prior tab restored on exit"
metrics:
  completed: 2026-10-05
---

# Quick 261005-e7b: Merge Needs into the Incidents pane Summary

One "Incidents & needs" right-column pane with Incidents | Needs tabs, a combined worst-severity header, and Triage available in normal view, `?admin=1` and edit mode.

## Commits

- dd2e791: AlertsPane (tabs, persistence, edit-mode rule, ?incident focus) and AlertsSummary
- 7aac6f4: Triage ungated in NeedRow; ThreePaneLayout reduced to one `alerts` slot; orphaned `needs` collapse flag removed from usePaneLayout
- 91101a5: IndexRoute wiring, test updates, D-24/D-25/D-26 amendments, UI-SPEC, README, nginx comment

## Behavior

- Tabs: accessible tablist/tab/tabpanel with arrow/Home/End keys; inactive panel stays mounted but `hidden` so the tier filter state survives a switch. Selected tab persisted at `dashboard-react.alertsTab.v1` (guarded; bad value falls back to Incidents).
- Header summary: count = incidents + needs; colour = danger incident, then warning incident or immediate need, then urgent, then standard. Rule documented in `AlertsPane.tsx`.
- Edit mode rule (user approved): the pane stays visible, Incidents disabled, Needs forced, stored choice never overwritten, prior tab returns on exit. Event history and host details still hide in edit mode.
- `?incident=` link selects the Incidents tab (outside edit mode).
- Right column width is `sizes.details` (420 default); the 640px minimum is gone.
- Collapsed state reuses the existing `incidentsCollapsed` persisted field; `needsCollapsed` was removed (old stored values are ignored).

## Why a local tab strip instead of kone-design-system SegmentedControl

The DS control has no disabled option (needed to disable Incidents in edit mode), no keyboard navigation, no aria-controls/tabpanel linkage and string-only labels (the tabs carry count badges). The local strip copies SegmentedControl's Tailwind classes so it looks identical. Recorded in UI-SPEC.

## Verification (actually run)

- `npx vitest run` (full): 55 files, 763 tests passed.
- `npm run typecheck`: clean.
- `npm run lint` (oxlint): exit with warnings only, no errors. One new warning: `react(set-state-in-effect)` at AlertsPane.tsx (the `focusIncidentId` effect, which syncs selection from the URL).
- `npm run build`: succeeded (existing chunk-size warning only).
- `NeedRow.tsx`/`NeedsPane.tsx` contain 0 `editMode` references; CONTEXT.md has 3 dated amendment lines; no changes under analytics/ or deploy/compose.yaml.
- Not verified: behavior in a real browser or against a live broker (publishing to `needs/triage/cmd`); tests mock `publishTriage`.

## Deviations from Plan

- [Rule 1 - Bug] In edit mode `select()` could rewrite the stored tab (e.g. ArrowLeft on the only enabled tab); `select` is now a no-op in edit mode. Found by the AlertsPane test. Commit dd2e791.
- [Rule 3] Tab accessible names needed a literal space between label and count badge (`Incidents 2`). Commit dd2e791.
- The worktree HEAD was not at the expected base; reset to 2507579 as instructed.

## Deploy note

Picking this up needs `podman compose build dashboard`, then a full `podman compose down && podman compose up -d` on the deploy host (a single-container restart breaks Checkmk egress). Nothing was deployed, pushed or restarted.

## Known stale comment (left per constraint)

`deploy/compose.yaml` around line 541 still says "first triage action in edit mode"; it was not edited.

## Known Stubs

None.

## Self-Check: PASSED

AlertsPane.tsx and AlertsPane.test.tsx exist; commits dd2e791, 7aac6f4, 91101a5 present in git log.
