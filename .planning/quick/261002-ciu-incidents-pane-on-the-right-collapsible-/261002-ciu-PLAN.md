---
phase: quick-261002-ciu
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - dashboard-react/src/hooks/usePaneLayout.ts
  - dashboard-react/src/hooks/usePaneLayout.test.ts
  - dashboard-react/src/lib/incidents.ts
  - dashboard-react/src/lib/incidents.test.ts
  - dashboard-react/src/components/IncidentList.tsx
  - dashboard-react/src/components/IncidentList.test.tsx
  - dashboard-react/src/components/ThreePaneLayout.tsx
  - dashboard-react/src/components/ThreePaneLayout.test.tsx
  - dashboard-react/src/routes/IndexRoute.tsx
  - dashboard-react/src/routes/IndexRoute.test.tsx
  - dashboard-react/README.md
  - docs/Incident demo with fake check results.md
  - docs/Podman setup for checkmk, minio, mosquitto, worker.md
autonomous: true
requirements: [QUICK-261002-ciu]

must_haves:
  truths:
    - "With no host selected and edit mode off, the right column shows an Incidents pane; the centre column holds only the toolbar + topology map (top) and event history (bottom)."
    - "With ?host= set, the Host details pane appears BELOW the Incidents pane in the same right column; Close still clears only ?host=."
    - "The Incidents pane header is always visible: 'Incidents' plus a count badge coloured danger/warning by the worst open incident (incidentStatus); with zero open incidents it reads a quiet 'No open incidents'."
    - "Collapsing the Incidents pane leaves its header (count + severity badge) visible; when every pane in the right column is collapsed the column becomes a 40px rail that still shows the count badge and the expand chevrons."
    - "Incidents collapsed state and incidents height persist across reload via usePaneLayout's existing guarded-storage record (dashboard-react.paneLayout.v1)."
    - "In topology edit mode there is no Incidents pane, no Host details pane and no event history; the map gets the full centre."
    - "?incident= still highlights + scrolls to the matching card; card device links still open the host details pane."
  artifacts:
    - path: "dashboard-react/src/components/ThreePaneLayout.tsx"
      provides: "Right column stacking incidents (top) and details (bottom), bar/rail collapse modes"
      contains: "incidentsSummary"
    - path: "dashboard-react/src/hooks/usePaneLayout.ts"
      provides: "incidents pane height + collapsed persistence"
      contains: "incidentsCollapsed"
    - path: "dashboard-react/src/lib/incidents.ts"
      provides: "worstIncidentStatus helper"
      exports: ["worstIncidentStatus"]
    - path: "dashboard-react/src/components/IncidentList.tsx"
      provides: "IncidentsSummary header component + IncidentList filling a pane"
      exports: ["IncidentList", "IncidentsSummary"]
  key_links:
    - from: "dashboard-react/src/routes/IndexRoute.tsx"
      to: "ThreePaneLayout incidents/incidentsSummary props"
      via: "incidents={editMode ? undefined : <IncidentList .../>}"
      pattern: "incidentsSummary="
    - from: "dashboard-react/src/components/ThreePaneLayout.tsx"
      to: "usePaneLayout incidents key"
      via: "collapsed.incidents / sizes.incidents"
      pattern: "collapsed\\.incidents"
    - from: "dashboard-react/src/components/IncidentList.tsx"
      to: "lib/incidents worstIncidentStatus"
      via: "IncidentsSummary badge colour"
      pattern: "worstIncidentStatus"
---

<objective>
Move the open-incident cards out of the centre column (above the map) into the right column of
the dashboard, as a collapsible "Incidents" pane stacked ABOVE the host details pane. The map and
event history reclaim the full centre column.

Purpose: the incident list was eating up to 35vh above the map; a right-side pane keeps incidents
always reachable (header with count + worst-severity badge) without shrinking the topology map.
Output: restructured ThreePaneLayout right column, persisted incidents pane state, IndexRoute
wiring, updated tests and docs.
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/templates/summary.md
</execution_context>

<context>
@./CLAUDE.md
@.planning/STATE.md
@dashboard-react/src/components/ThreePaneLayout.tsx
@dashboard-react/src/hooks/usePaneLayout.ts
@dashboard-react/src/routes/IndexRoute.tsx
@dashboard-react/src/components/IncidentList.tsx

<interfaces>
<!-- Extracted from the codebase. Use directly. -->

dashboard-react/src/components/ThreePaneLayout.tsx (current):
- export interface ThreePaneLayoutProps { tree; centreTop; centreBottom?; details?; detailsKey?: string | null; onCloseDetails?: () => void }
- const COLLAPSED_RAIL_PX = 40
- type PaneSide = "left" | "right" | "bottom"; COLLAPSE_ROTATION = { left: 180, right: 0, bottom: 90 }
- function CollapsiblePane({ title, side, collapsed, onToggleCollapse, onClose?, children }) -- title drives aria labels ("Collapse {title.toLowerCase()}", "Expand ...", "Close ..."); collapsed => header shows only the chevron (justify-center px-1), title + close hidden, children unmounted.
- Details splitter: vertical, mirrored value (bounds.details.min + bounds.details.max - sizes.details), label "Resize host details".
- Re-expand rule: useEffect on detailsKey -> expand("details") when a new truthy key arrives.
- gridTemplateColumns = details ? `${tree}px 4px 1fr 4px ${detailsColumnWidth}px` : `${tree}px 4px 1fr`

dashboard-react/src/hooks/usePaneLayout.ts:
- STORAGE_KEY = "dashboard-react.paneLayout.v1"; DEFAULTS { treeWidth: 320, eventsHeight: 260, detailsWidth: 420 }
- export const PANE_BOUNDS = { tree {200,640}, events {120,600}, details {280,800} }
- PersistedLayout { treeWidth, eventsHeight, treeCollapsed, eventsCollapsed, detailsWidth, detailsCollapsed }
- readInitialState(): per-field typeof check + clamp fallback; toRecord(state)
- usePaneLayout() returns { sizes, collapsed, setSize(pane, n), toggleCollapse(pane), expand(pane), commit(), bounds: PANE_BOUNDS }
- writes go through readJson/writeJson from ../lib/guardedStorage (try/catch guarded already)

dashboard-react/src/lib/incidents.ts:
- export interface Incident { id; root; confirmedDown: string[]; rootState; inferred; worstCriticality; ... }
- export function incidentStatus(incident: Incident): "danger" | "warning"
- export function selectOpenIncidents(record): Incident[]  (already D-12 sorted)

dashboard-react/src/components/IncidentList.tsx:
- export function IncidentList({ incidents, devices, nowMs, highlightedId? })
- empty state: <div className="text-xs text-fg-tertiary"><p className="font-semibold">No open incidents</p><p>Every device the poller can reach is reporting normally.</p></div>
- non-empty: <section aria-label="Open incidents" className="flex max-h-[35vh] shrink-0 flex-col gap-2 overflow-y-auto"> ... IncidentCard per incident; scrollIntoView effect keyed on [highlightedId, hasTarget]

kone-design-system: import { Badge } from "kone-design-system"; <Badge color="danger"|"warning"|... variant="solid"|"soft"|"outline" icon?>text</Badge> (see StateBadge.tsx / stateMapping.ts).

IndexRoute.tsx ~255-336: ThreePaneLayout with centreTop = <div className="flex h-full flex-col gap-2 p-3">{!editMode && <IncidentList incidents devices nowMs highlightedId={highlightedIncidentId} />}<div ... onPointerDown/onWheel/onKeyDown={touch}>toolbar, CriticalityEditor, TopologyMap</div></div>; centreBottom={editMode ? undefined : <EventHistory hostId={hostId} />}; details={hostId && !editMode ? <HostDetails id={hostId} /> : undefined}; detailsKey={hostId}; onCloseDetails.

Scripts (dashboard-react/package.json): test = "vitest run", typecheck = "tsc -b --noEmit", lint = "oxlint", build = "tsc -b && vite build". Run via `npm run <script>` from dashboard-react/. No Python involved.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Persisted incidents pane state, worst-severity helper, IncidentsSummary header</name>
  <files>dashboard-react/src/hooks/usePaneLayout.ts, dashboard-react/src/hooks/usePaneLayout.test.ts, dashboard-react/src/lib/incidents.ts, dashboard-react/src/lib/incidents.test.ts, dashboard-react/src/components/IncidentList.tsx, dashboard-react/src/components/IncidentList.test.tsx</files>
  <behavior>
    - usePaneLayout with empty storage: sizes = { tree: 320, events: 260, details: 420, incidents: 280 }, collapsed all false including incidents (update existing toEqual assertions to include the new key).
    - A persisted { incidentsHeight: 99999, incidentsCollapsed: "x" } clamps height to PANE_BOUNDS.incidents.max (600) and falls back collapsed to false; an old v1 record without incidents fields still restores tree/events/details (per-field fallback).
    - toggleCollapse("incidents") flips collapsed.incidents and writes incidentsCollapsed into the same STORAGE_KEY record.
    - worstIncidentStatus([]) === null; any incident whose incidentStatus is "danger" makes it "danger"; only warning incidents => "warning".
    - IncidentsSummary with 0 incidents renders the text "No open incidents" (quiet, text-fg-tertiary) and no badge.
    - IncidentsSummary with N>0 renders a Badge with text N inside a wrapper carrying data-testid="incidents-severity" and data-severity equal to the worst status, with an aria-label like "3 open incidents".
    - IncidentList empty state no longer repeats the bold "No open incidents" line (the pane header now says it) -- it renders only the body sentence "Every device the poller can reach is reporting normally."
  </behavior>
  <action>
usePaneLayout.ts: add an `incidents` pane key (height of the incidents pane inside the right column). DEFAULTS.incidentsHeight = 280; PANE_BOUNDS.incidents = { min: 120, max: 600 }; PersistedLayout gains incidentsHeight: number and incidentsCollapsed: boolean; PaneSizes/PaneCollapsed gain `incidents`; readInitialState adds the same per-field typeof+clamp fallback; toRecord writes both new fields. Do NOT bump STORAGE_KEY to v2 -- extend the existing comment (same additive reasoning as the 260928-l4h details fields) noting 261002-ciu added the incidents fields. Note in a short comment that `sizes.details` is now the whole right column's width (incidents + details share it), kept under the `details` key so a saved width survives. Update usePaneLayout.test.ts expectations and add tests for the behaviors above.

lib/incidents.ts: add `export function worstIncidentStatus(incidents: Incident[]): "danger" | "warning" | null` built on the existing incidentStatus (do not duplicate its rules). Add unit tests in incidents.test.ts following that file's existing fixture style.

IncidentList.tsx: (a) add `export function IncidentsSummary({ incidents }: { incidents: Incident[] })` -- zero => `<span className="truncate text-xs text-fg-tertiary">No open incidents</span>`; otherwise a span wrapper (data-testid="incidents-severity", data-severity={worst}, aria-label=`${N} open incident(s)`) around kone-design-system `<Badge color={worst} variant="solid">{N}</Badge>`. Colour choice is planner discretion: reuse the danger/warning vocabulary the cards' Message status already uses (incidentStatus), so the header colour always agrees with the worst card; the heading word "Incidents" itself comes from the pane title (Task 2), so header reads "Incidents [N]". (b) Change the non-empty section's className from "flex max-h-[35vh] shrink-0 flex-col gap-2 overflow-y-auto" to "flex flex-col gap-2 p-3" -- the 35vh cap existed only because it sat above the map; the hosting pane's body already scrolls (overflow-auto), and scrollIntoView keeps working there. Keep aria-label="Open incidents" and the highlight/scroll effect untouched. (c) Empty state: drop the bold "No open incidents" paragraph, keep the body sentence, add p-3 padding. Update IncidentList.test.tsx's empty-list test accordingly and add IncidentsSummary tests.
  </action>
  <verify>
    <automated>cd dashboard-react && npm run test -- src/hooks/usePaneLayout.test.ts src/lib/incidents.test.ts src/components/IncidentList.test.tsx</automated>
  </verify>
  <done>New and updated tests pass; usePaneLayout exposes sizes.incidents/collapsed.incidents persisted in the v1 record; worstIncidentStatus and IncidentsSummary exported.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: ThreePaneLayout right column -- incidents on top, details below, bar/rail collapse</name>
  <files>dashboard-react/src/components/ThreePaneLayout.tsx, dashboard-react/src/components/ThreePaneLayout.test.tsx</files>
  <behavior>
    - Without incidents and details props: 3 grid columns, 2 separators (existing tests unchanged).
    - With only `incidents` (+ `incidentsSummary`): a right column renders with an "Incidents" pane titled "Incidents", the summary node visible in its header, a "Collapse incidents" button, and a column resize separator named "Resize right column"; gridTemplateColumns has 5 entries.
    - Collapsing incidents with no details present: column width becomes 40px (rail); the rail still shows the summary node and an "Expand incidents" button; children unmounted.
    - With incidents AND details, both expanded: incidents content appears before host details content in document order, and a horizontal separator "Resize incidents" exists between them; dragging it down increases the incidents row height (no mirroring needed -- top pane's own height).
    - With incidents AND details, incidents collapsed: incidents header bar (title "Incidents" + summary + Expand chevron) remains visible above an expanded details pane; column keeps its full width; no "Resize incidents" separator.
    - With incidents AND details, details collapsed: details shrinks to a header bar at the bottom of the column showing "Host details", "Expand host details" and "Close host details"; incidents fills the rest.
    - Both collapsed: column becomes the 40px rail with both expand chevrons and the incidents summary.
    - Details-only (no incidents prop) keeps today's behaviour: Collapse -> 40px rail with "Expand host details"; Close calls onCloseDetails; detailsKey change re-expands; persisted collapsed + mount keeps collapsed (existing tests keep passing, only the column separator name changes to "Resize right column").
    - Collapsed incidents state survives an unmount/remount (persisted via usePaneLayout).
  </behavior>
  <action>
Add props `incidents?: ReactNode` and `incidentsSummary?: ReactNode` to ThreePaneLayoutProps (comment: omitted in topology edit mode). The right column renders when `incidents || details`.

CollapsiblePane: add optional `headerExtra?: ReactNode` (rendered right after the title in the header; in a rail it renders under the chevron) and `collapsedAs?: "rail" | "bar"` (default "rail", preserving current behaviour for tree/events). In "bar" mode a collapsed pane keeps the full header (title, headerExtra, chevron, and close button if onClose) and only unmounts its body; in "rail" mode keep today's centred-chevron header but stack it as flex-col items-center gap-1 so headerExtra (the count badge) stays visible. Add "top" to PaneSide with COLLAPSE_ROTATION top: 270 (chevron points up when collapsing the top pane of the column).

Right column layout (decision recorded per locked "decide bar vs rail" item -- chose bar inside a stacked column, rail only when nothing in the column is expanded, so the count badge is always visible and the column never wastes width):
- `columnRailed` = every present right-column pane is collapsed (incidents absent or collapsed AND details absent or collapsed).
- Column width = columnRailed ? COLLAPSED_RAIL_PX : sizes.details. gridTemplateColumns = rightColumn ? `${tree}px 4px 1fr 4px ${columnWidth}px` : `${tree}px 4px 1fr`.
- Keep the existing mirrored vertical column splitter, relabelled "Resize right column" (it now resizes the whole column).
- Inside the column, a grid (h-full min-h-0 min-w-0): if columnRailed, render the present panes as rails stacked (flex-col), incidents first (side "right", collapsedAs "rail"). Otherwise rows: incidents only => "1fr"; details only => "1fr"; both expanded => `${sizes.incidents}px 4px 1fr` with a horizontal Splitter (value sizes.incidents, bounds.incidents, label "Resize incidents", onResize setSize("incidents"), onResizeCommit commit); incidents collapsed => "auto 1fr"; details collapsed => "1fr auto".
- Incidents pane: title "Incidents", side "top", collapsedAs columnRailed ? "rail" : "bar", headerExtra={incidentsSummary}, toggle toggleCollapse("incidents"). Details pane: title "Host details", side columnRailed ? "right" : "bottom", collapsedAs as above, onClose onCloseDetails. When details is the only pane, keep side "right"/rail behaviour so existing tests hold.
- Keep the detailsKey re-expand effect as is.
Update the layout docstring to describe the right column. Keep changes surgical: do not touch tree/events behaviour. Update ThreePaneLayout.test.tsx: rename the "resize host details" separator query, keep existing tests passing, add tests for the behaviors above (read grid.style.gridTemplateColumns / gridTemplateRows the same way the existing tests do).
  </action>
  <verify>
    <automated>cd dashboard-react && npm run test -- src/components/ThreePaneLayout.test.tsx src/hooks/usePaneLayout.test.ts</automated>
  </verify>
  <done>All ThreePaneLayout tests (old and new) pass; the right column stacks incidents above details with bar collapse, rails only when fully collapsed, and keeps the summary badge visible in every state.</done>
</task>

<task type="auto">
  <name>Task 3: Wire IndexRoute, update route tests and docs, full verification</name>
  <files>dashboard-react/src/routes/IndexRoute.tsx, dashboard-react/src/routes/IndexRoute.test.tsx, dashboard-react/README.md, docs/Incident demo with fake check results.md, docs/Podman setup for checkmk, minio, mosquitto, worker.md</files>
  <action>
IndexRoute.tsx: remove IncidentList from centreTop -- centreTop becomes the existing touch wrapper (toolbar, CriticalityEditor, TopologyMap) with the outer p-3 padding kept, so the map and event history take the whole centre column. Pass `incidents={editMode ? undefined : <IncidentList incidents={incidents} devices={devices} nowMs={nowMs} highlightedId={highlightedIncidentId} />}` and `incidentsSummary={<IncidentsSummary incidents={incidents} />}` (import IncidentsSummary). details/detailsKey/onCloseDetails/centreBottom unchanged. Rewrite the centreTop comment block: incidents now live in the right column above host details (261002-ciu); edit mode still hides incidents, event history and host details.

IndexRoute.test.tsx: replace "renders the incident card above the topology map..." with "renders the incident card in the right column, after the map in document order, even with no host selected" (incidentRegion follows the map: compareDocumentPosition(map) & DOCUMENT_POSITION_PRECEDING; a "Collapse incidents" button exists; keep the "See incident" tree assertion). Add: at /?host=web1 with an open incident, the incident region precedes the Host details pane content. The "No open incidents" and edit-mode tests should still pass (header summary text; absent in edit mode) -- also assert the "Collapse incidents" button is absent in edit mode. Keep the highlight (?incident=) and "Close removes ?host= but keeps ?incident=" tests passing.

Docs (Edit tool, surgical): dashboard-react/README.md -- section 5c "Above the topology map, IncidentList..." -> the Incidents pane at the top of the right column (header "Incidents" + count badge coloured by the worst open incident, "No open incidents" when none; collapsible, collapsed state + height persisted by usePaneLayout; when every right-column pane is collapsed the column becomes a 40px rail still showing the badge); the Host details paragraph (~line 185) -> opens BELOW the Incidents pane in the right column, column splitter now resizes both, collapsing details shrinks it to a header bar unless incidents is collapsed too; edit-mode bullet (~line 142) stays accurate, adjust wording if needed. docs/Incident demo with fake check results.md line ~73 "appears above the stats strip" -> "appears in the Incidents pane at the top of the right-hand column". docs/Podman setup... line ~663 "appears above the topology map" -> same wording.

Then run the full dashboard-react verification: npm run test, npm run typecheck, npm run lint, npm run build. Fix any failures caused by this change.
  </action>
  <verify>
    <automated>cd dashboard-react && npm run test && npm run typecheck && npm run lint && npm run build</automated>
  </verify>
  <done>Full vitest suite, typecheck, oxlint and production build pass; grep -n "above the topology map\|above the stats strip" over the three docs returns no incident-related hits; IncidentList is no longer referenced inside centreTop.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| URL query -> UI | `?incident=` / `?host=` are user-controllable and already handled (T-14-12) |
| localStorage -> UI | persisted pane record may be corrupt/hostile |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-ciu-01 | Tampering | usePaneLayout incidents fields | mitigate | per-field typeof check + clamp to PANE_BOUNDS.incidents, fallback to defaults; storage access via guardedStorage readJson/writeJson (try/catch) |
| T-ciu-02 | Tampering | IncidentList highlightedId | accept | unchanged existing CSS.escape + try/catch handling; this change only moves the component |
| T-ciu-03 | Denial of Service | layout render | accept | pure client-side layout, no new data sources or network calls |
</threat_model>

<verification>
- cd dashboard-react && npm run test && npm run typecheck && npm run lint && npm run build
- grep -n "IncidentList" dashboard-react/src/routes/IndexRoute.tsx shows it only as the `incidents=` prop, not inside centreTop.

Manual visual check for the operator (executor has no browser):
1. Open the dashboard with no host selected: centre column = map + event history only; right column shows the Incidents pane with "Incidents" + coloured count badge (or "No open incidents").
2. Click a host (map/tree/card link): Host details appears below Incidents; drag the "Resize incidents" divider and the column divider.
3. Collapse Incidents: header bar with badge stays; collapse Host details too: column becomes a 40px rail still showing the badge; expand again. Reload: collapsed states and sizes persist.
4. Toggle Edit topology: incidents, host details and event history disappear; the map fills the centre.
5. Open /?incident=<id>: the matching card is highlighted and scrolled into view in the right pane.
</verification>

<success_criteria>
- Incidents render in the right column above host details, visible with or without a selected host, absent in edit mode.
- Header always shows count + worst-severity badge (or "No open incidents"), including when collapsed/railed.
- Collapsed state and height persist via usePaneLayout's v1 record.
- All dashboard-react tests, typecheck, lint and build pass; docs describe the new layout.
</success_criteria>

<output>
Create `.planning/quick/261002-ciu-incidents-pane-on-the-right-collapsible-/261002-ciu-SUMMARY.md` when done
</output>
