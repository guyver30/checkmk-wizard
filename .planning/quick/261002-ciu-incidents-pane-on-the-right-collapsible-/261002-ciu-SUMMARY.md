---
phase: quick-261002-ciu
plan: 01
subsystem: dashboard-react
tags: [layout, incidents, usePaneLayout]
key-files:
  modified:
    - dashboard-react/src/hooks/usePaneLayout.ts
    - dashboard-react/src/lib/incidents.ts
    - dashboard-react/src/components/IncidentList.tsx
    - dashboard-react/src/components/ThreePaneLayout.tsx
    - dashboard-react/src/routes/IndexRoute.tsx
metrics:
  completed: 2026-10-02
---

# Quick 261002-ciu: Incidents pane in the right column

Incident cards moved from above the map into a collapsible Incidents pane at the top of the right column (above Host details), with a persisted count+severity header badge and bar/rail collapse.

## Commits
- ab89098: usePaneLayout incidents fields (same v1 record), worstIncidentStatus, IncidentsSummary, IncidentList fills pane
- 083eec8: ThreePaneLayout right column (incidents over details, "Resize incidents" splitter, bar collapse, rail only when whole column collapsed)
- 55cd57a: IndexRoute wiring, route tests, README and two docs updated

## Verification (real output)
- `npm run test`: 40 files, 543 tests passed
- `npm run typecheck`: clean
- `npm run lint`: warnings only (pre-existing react-hooks/purity warnings, 0 errors; the ThreePaneLayout `expand` dep warning pre-existed)
- `npm run build`: built OK (chunk-size warning pre-existing)
- Leftover grep: no "Resize host details" label, no `max-h-[35vh]`, no "above the topology map / stats strip" in the three docs. Existing usePaneLayout size assertions were updated to include `incidents: 280` and the two new persisted fields.
- Not verified: visual/browser behaviour (no browser available); operator manual checklist in the plan still applies.

## Deviations
None of substance. Decisions: incidents chevron uses side "top" only when stacked over details, otherwise "right"; details-only behaviour is unchanged (rail on collapse). Stale-test fix: old "above the map" route test inverted to "after the map in document order".

## Self-Check: PASSED
