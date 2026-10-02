---
phase: quick-261002-ciu
verified: 2026-10-02T00:00:00Z
status: human_needed
score: 7/7 must-haves verified (code and tests); visual behaviour needs human check
has_blocking_gaps: false
human_verification:
  - test: "Open the dashboard with no host selected"
    expected: "The centre column holds only the map and event history. The right column shows the Incidents pane with a count badge, or 'No open incidents'."
    why_human: "Layout and visual appearance cannot be verified in jsdom."
  - test: "Select a host, then drag the 'Resize incidents' divider and the column divider"
    expected: "Host details sits below Incidents and both dividers resize smoothly."
    why_human: "Drag interaction and real-browser layout."
  - test: "Collapse Incidents, then collapse Host details, then reload"
    expected: "The incidents header bar and badge stay visible. With both collapsed the column becomes a 40px rail that still shows the badge. States and sizes persist across reload."
    why_human: "Visual check of the rail and bar."
  - test: "Toggle Edit topology"
    expected: "Incidents, host details and event history disappear and the map fills the centre."
    why_human: "Visual check."
  - test: "Open /?incident=<id>"
    expected: "The matching card is highlighted and scrolled into view inside the right pane."
    why_human: "scrollIntoView and highlight need a real browser."
---

# Quick 261002-ciu Verification

**Goal:** Move incident cards into a collapsible right column above host details.

## Automated results (run on main, merge 336e7a0)
- `npm run test`: 40 files, 543 tests passed.
- `npm run typecheck`: clean.
- `npm run lint`: warnings only. The `expand` exhaustive-deps warning in ThreePaneLayout.tsx:187 comes from the pre-existing detailsKey re-expand effect, which the plan said to keep.
- `npm run build`: succeeded.
- No TBD, FIXME or XXX markers in the touched component and hook files.

## Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | The incidents pane is in the right column and the centre holds only the map and history | VERIFIED | `IndexRoute.tsx` centreTop holds only the toolbar, CriticalityEditor and TopologyMap. `incidents=` is passed as a separate prop, and `ThreePaneLayout` renders it in the right column (`rightColumn = incidents \|\| details`). |
| 2 | With `?host=`, details sits below incidents in the same column | VERIFIED | The stacked rows (`sizes.incidents px 4px 1fr`) and the "Resize incidents" splitter are in `ThreePaneLayout.tsx`. Tests cover this. |
| 3 | The header always shows the count and worst-severity badge, or "No open incidents" at zero | VERIFIED | `IncidentsSummary` uses `worstIncidentStatus`, sets data-severity and aria-label, and passes the summary as `headerExtra`. The badge is a bare count next to the title rather than literal "Incidents (N)" text. |
| 4 | Collapsing keeps the header visible, and a fully collapsed column becomes a 40px rail with the badge | VERIFIED | `collapsedAs` bar/rail, `columnRailed` and `COLLAPSED_RAIL_PX` are in `ThreePaneLayout.tsx`. Tests pass. |
| 5 | Collapsed state and height persist in the existing v1 record | VERIFIED | `usePaneLayout.ts` has `incidentsHeight` and `incidentsCollapsed` with typeof checks and clamping, no key bump. Tests pass. |
| 6 | Edit mode shows no incidents, no details and no history | VERIFIED | `incidents={editMode ? undefined : ...}`, `centreBottom={editMode ? undefined : ...}`, `details={hostId && !editMode ...}`. |
| 7 | `?incident=` highlight and card links to details still work | VERIFIED | `highlightedId` is still passed to `IncidentList`, and the `IndexRoute.test` highlight and close tests pass in the full suite. |

Tests and docs: updated for `usePaneLayout`, `incidents`, `IncidentList`, `ThreePaneLayout` and `IndexRoute`. `dashboard-react/README.md` is rewritten for the new layout, and the two docs files under `docs/` are edited. A grep for "above the topology map" and "above the stats strip" in README.md and docs/*.md returned no hits.

## Gaps
None.
