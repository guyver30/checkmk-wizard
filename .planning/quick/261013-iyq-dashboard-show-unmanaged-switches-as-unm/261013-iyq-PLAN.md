---
phase: quick-261013-iyq
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - dashboard-react/src/lib/display.ts
  - dashboard-react/src/lib/display.test.ts
  - dashboard-react/src/lib/stateMapping.ts
  - dashboard-react/src/lib/stateMapping.test.ts
  - dashboard-react/src/lib/mapIcons.ts
  - dashboard-react/src/lib/mapIcons.test.ts
  - dashboard-react/src/lib/topologyLayout.ts
  - dashboard-react/src/lib/topologyLayout.test.ts
  - dashboard-react/src/components/TopologyMap.tsx
  - dashboard-react/src/components/TopologyMap.test.tsx
  - dashboard-react/src/lib/grouping.ts
  - dashboard-react/src/lib/grouping.test.ts
  - dashboard-react/src/lib/treeModel.ts
  - dashboard-react/src/lib/treeModel.test.ts
  - dashboard-react/src/routes/IndexRoute.tsx
  - dashboard-react/src/store/selectors.ts
  - dashboard-react/src/store/selectors.test.ts
  - dashboard-react/src/components/StatsStrip.tsx
  - dashboard-react/src/components/StatsStrip.test.tsx
  - dashboard-react/src/components/StateBadge.tsx
  - dashboard-react/src/components/StateBadge.test.tsx
  - dashboard-react/src/components/HostDetails.tsx
  - dashboard-react/src/components/HostDetails.test.tsx
  - dashboard-react/README.md
autonomous: true
requirements: [QUICK-261013-iyq]

must_haves:
  truths:
    - "An unmanaged switch whose own state is UNKNOWN or OK (including after an admin fake UP) shows as a neutral grey 'Unmanaged' on the map, in the tree, in the state badge and in host details"
    - "An unmanaged switch whose own state is DOWN or UNREACH (real or faked) still shows DOWN or UNREACH"
    - "An inferred-root unmanaged switch keeps its dashed warning border and the title 'Inferred root cause, not confirmed'; its dimmed consequences are unchanged"
    - "The switch's map tooltip and host details show a hint such as '3 of 4 devices behind it are up', or 'No devices connected'"
    - "The header stats strip never counts an Unmanaged switch as OK or UNKNOWN; it appears under a neutral 'Unmanaged N' badge"
    - "A host that is not unmanaged and is UNKNOWN still shows UNKNOWN exactly as before"
  artifacts:
    - path: "dashboard-react/src/lib/display.ts"
      provides: "UNMANAGED_STATE, displayState(), stateLabel(); stateClass/stateIcon know UNMANAGED"
      contains: "export function displayState"
    - path: "dashboard-react/src/lib/topologyLayout.ts"
      provides: "unmanagedIdsFromTopology(), unmanagedChildrenHint(); MapNode.hint; buildMapModel uses displayState"
      contains: "export function unmanagedChildrenHint"
    - path: "dashboard-react/src/lib/mapIcons.ts"
      provides: "STATE_HEX.UNMANAGED and BORDER_STYLE.UNMANAGED (neutral grey)"
      contains: "UNMANAGED"
    - path: "dashboard-react/src/store/selectors.ts"
      provides: "StateCounts gains UNMANAGED; unmanaged switches never counted as OK/UNKNOWN"
      contains: "UNMANAGED"
  key_links:
    - from: "dashboard-react/src/lib/topologyLayout.ts"
      to: "displayState"
      via: "buildMapModel node state"
      pattern: "displayState\\("
    - from: "dashboard-react/src/lib/treeModel.ts"
      to: "displayState / unmanagedIds"
      via: "buildTree option unmanagedIds"
      pattern: "unmanagedIds"
    - from: "dashboard-react/src/store/selectors.ts"
      to: "state.topology"
      via: "unmanagedIdsFromTopology in makeSelectStateCounts"
      pattern: "unmanagedIdsFromTopology"
    - from: "dashboard-react/src/components/HostDetails.tsx"
      to: "StateBadge unmanaged prop + unmanagedChildrenHint"
      via: "useAppStore selectors returning primitives"
      pattern: "unmanagedChildrenHint"
---

<objective>
Show an unmanaged switch (topology flag `unmanaged === true`, host label `unmanaged_switch=yes`, no IP/agent/SNMP, zero services) as a neutral "Unmanaged" state instead of the misleading UNKNOWN (no services) or OK (fabricated passive result after an admin fake DOWN then UP), with a children-derived hint, while keeping real/faked DOWN/UNREACH and the poller's inferred-root behaviour (D-11) exactly as today.

Purpose: operator decision 2026-10-13 -- "ensure the inferred down is maintained if all its children are down. Unmanaged is better than unknown."
Output: one front-end-only mapping helper in lib/display.ts used by map, tree, badge, host details and stats; tests; README update. The poller and the MQTT contract are NOT changed.
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/templates/summary.md
</execution_context>

<context>
@./CLAUDE.md
@.planning/STATE.md
@dashboard-react/src/lib/display.ts
@dashboard-react/src/lib/topologyLayout.ts
@dashboard-react/src/lib/mapIcons.ts
@dashboard-react/src/lib/stateMapping.ts

<background>
Facts already established by the planner (no need to rediscover):

- The device status payload (`DevicePayload`, store `s.devices`) does NOT carry the unmanaged flag. Only the topology payload does: `s.topology.devices[]` entries with `unmanaged: true` (types.ts `TopologyPayload.devices?: unknown[]`, `TopologyNode.unmanaged?: boolean`). So every consumer needs a set of unmanaged ids derived from `s.topology?.devices`. IndexRoute already has `topologyDevices` (IndexRoute.tsx ~L61-65).
- Current state derivation sites: `effectiveState()` (display.ts), used by topologyLayout.ts `buildMapModel` (~L124, `isDeviceStale ? "STALE" : effectiveState`), treeModel.ts `buildTree` (~L91, `state: effectiveState(device)`, `stale: isDeviceStale(...)`; TreeNode.tsx L139 renders `device.stale ? "STALE" : device.state`), grouping.ts `rollUpGroup` (~L112, severity worst + `nonOkCount` excludes only OK/PEND), store/selectors.ts `makeSelectStateCounts` (~L35), StateBadge.tsx `StateBadge` (~L27). `SEVERITY_RANK` in grouping.ts has no entry for new states (unknown keys fall back to the UNKNOWN rank 2).
- `stateClass`/`stateIcon` in display.ts currently have no callers outside display.ts (still add the state, per the task spec).
- StatsStrip `DISPLAY_ORDER`/`STATE_COLOR` are keyed on `keyof StateCounts`; StateBadge and StateBadgeForState render the raw `state` string as the badge text; `badgeForState` falls back to the UNKNOWN spec for unrecognised strings.
- Map: `nodeBaseFields()` in TopologyMap.tsx (~L286-315) picks emphasis `inferred-root` > `dimmed` > `normal`, and title `INFERRED_ROOT_TITLE` > `DIMMED_NODE_TITLE` > `UNMANAGED_SWITCH_TITLE` (only when `node.unmanaged`). `nodeVisual(deviceType, state, emphasis)` caches by `${deviceType}|${state}|${emphasis}` (state already in the key) and for `inferred-root` ignores the state hex entirely (warning hue + dashed [6,3] border). So inferred-root precedence is preserved automatically as long as emphasis selection is untouched. The optimistic Add-Node path (~L545-548, `nodeVisual("NetworkDevice", "PEND")` + `title: UNMANAGED_SWITCH_TITLE`) stays as is.
- Existing tests that assert the plain title: TopologyMap.test.tsx L454, L742, L1262 expect `"Unmanaged switch (not monitored)"` -- update them to the new title form.
- Incidents come from the poller (`lan/incidents`), needs/narration from the analytics container; the dashboard does not create incidents/alerts from UNKNOWN itself. AdminBar/adminMode (faked set, selection, `previewCascade`) only use ids and the `unmanaged` flag for the cascade preview, not the display state -- do not touch them.

Poller inferred-root rule (scripts/mqtt_poller.py ~L926-985, READ ONLY, do not change): an `unmanaged` host with >= 2 direct children whose `host_state_raw` is DOWN or UNREACH, at least one DOWN, becomes an inferred root. A lone non-OK child under an unmanaged switch is NOT inferred (it is its own plain root). So "all its children down" yields the inferred-root styling only when the switch has >= 2 children (at least one DOWN); a switch with exactly one child that is DOWN shows plain "Unmanaged" with hint "0 of 1 device behind it is up". Record this in the SUMMARY; do not change the rule. `compute_overall_state` (~L703) is also read-only.
</background>

<interfaces>
New contracts (Task 1 creates them, Task 2 consumes them):

display.ts
- `export const UNMANAGED_STATE = "UNMANAGED";`
- `export function displayState(device: DevicePayload | null | undefined, unmanaged: boolean, nowMs?: number): string`
- `export function stateLabel(state: string): string` -- "Unmanaged" for UNMANAGED_STATE, otherwise the state string unchanged.

topologyLayout.ts
- `export function unmanagedIdsFromTopology(topologyDevices: unknown): Set<string>`
- `export function unmanagedChildrenHint(switchId: string, topologyDevices: unknown, statuses: Record<string, DevicePayload>, nowMs: number): string`
- `MapNode` gains `hint: string | null`.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Shared displayState helper, Unmanaged palette, children hint, and the map</name>
  <files>dashboard-react/src/lib/display.ts, dashboard-react/src/lib/display.test.ts, dashboard-react/src/lib/stateMapping.ts, dashboard-react/src/lib/stateMapping.test.ts, dashboard-react/src/lib/mapIcons.ts, dashboard-react/src/lib/mapIcons.test.ts, dashboard-react/src/lib/topologyLayout.ts, dashboard-react/src/lib/topologyLayout.test.ts, dashboard-react/src/components/TopologyMap.tsx, dashboard-react/src/components/TopologyMap.test.tsx</files>
  <behavior>
    - displayState(device with state UNKNOWN, unmanaged=true) returns "UNMANAGED"
    - displayState(device with state OK and host_state_raw UP, i.e. after a faked UP, unmanaged=true) returns "UNMANAGED"
    - displayState(device with state DOWN, host_state_raw DOWN, unmanaged=true) returns "DOWN"; with host_state_raw UNREACH returns "UNREACH"
    - displayState(stale device with state UNKNOWN, unmanaged=true) returns "UNMANAGED"; displayState(stale DOWN device, unmanaged=true) returns "STALE" (non-unmanaged staleness rule unchanged)
    - displayState(device UNKNOWN, unmanaged=false) returns "UNKNOWN"; stale non-unmanaged returns "STALE" (identical to today's `isDeviceStale ? "STALE" : effectiveState`)
    - displayState(undefined, unmanaged=true) returns "UNMANAGED" (no status yet)
    - stateLabel("UNMANAGED") is "Unmanaged"; stateLabel("DOWN") is "DOWN"; stateClass("UNMANAGED") is "state-unmanaged"; stateIcon("UNMANAGED") is not the UNKNOWN icon
    - badgeForState("UNMANAGED") is neutral, label "Unmanaged", distinct from STALE's (variant or icon) and from UNKNOWN's black
    - nodeVisual("NetworkDevice", "UNMANAGED") uses the neutral grey hex for border and icon; nodeVisual(..., "UNMANAGED", "inferred-root") still uses the warning hex and dashes [6,3]
    - unmanagedChildrenHint: 4 children, 3 up -> "3 of 4 devices behind it are up"; 2 of 2 up -> "2 of 2 devices behind it are up"; 1 child down -> "0 of 1 device behind it is up"; no children -> "No devices connected"; only direct children (entries whose `parents` include the switch id) count; a child counts as up when it has a status, is not stale, and its effectiveState is not DOWN or UNREACH
    - unmanagedIdsFromTopology ignores malformed entries and returns only ids with `unmanaged === true`
    - buildMapModel: unmanaged node with UNKNOWN status gets state "UNMANAGED" and a non-null hint; unmanaged DOWN stays "DOWN"; non-unmanaged nodes get hint null and unchanged state
    - TopologyMap: plain unmanaged node title is `Unmanaged switch (not monitored) — <hint>`; an inferred-root unmanaged node still gets title "Inferred root cause, not confirmed" and the inferred-root visual; a dimmed node keeps DIMMED_NODE_TITLE
  </behavior>
  <action>
Write the failing tests first (display.test.ts, stateMapping.test.ts, mapIcons.test.ts, topologyLayout.test.ts, and update TopologyMap.test.tsx L454/L742/L1262 plus one new inferred-root-unmanaged case), then implement:

1. display.ts: add `UNMANAGED_STATE = "UNMANAGED"` and `displayState(device, unmanaged, nowMs = Date.now())`. Rule: compute `eff = effectiveState(device)`; if `unmanaged` and `eff` is "UNKNOWN" or "OK", return UNMANAGED_STATE regardless of staleness; otherwise return `isDeviceStale(device, nowMs) ? "STALE" : eff` (exactly today's rule, so non-unmanaged hosts and an unmanaged switch that is DOWN/UNREACH/WARN/CRIT/PEND behave as before). Import isDeviceStale from ./staleness (no cycle: staleness.ts imports only config/types). Document the staleness decision in a comment: a check-free switch has no checks, so Checkmk's `staleness` column grows while the switch is merely quiet; showing STALE would be as misleading as UNKNOWN, and poller liveness is already surfaced by PollerOfflineBanner. A faked DOWN refreshes staleness, so it still shows DOWN. Add `stateLabel(state)`. Add "unmanaged" to stateClass's known set and `UNMANAGED` to stateIcon: grep the kone-design-system package (node_modules/kone-design-system, its CSS) for an existing neutral `icon-*` class not already used by another state (e.g. a minus/info/link-style circle) and note the choice in a comment. Do not reuse another state's icon (UNREACH's icon-status-unavailable, UNKNOWN's icon-question-circle-filled).
2. stateMapping.ts: add `UNMANAGED: { color: "neutral", variant: "soft", iconName: <same class as stateIcon UNMANAGED or null>, label: "Unmanaged" }`; if that collides visually with PEND (neutral soft, no icon), give it the icon so it is never distinguishable by colour alone, matching the file's STALE/UNKNOWN rule. Update the header comment.
3. mapIcons.ts: `STATE_HEX.UNMANAGED = "#96969f"` (neutral-400, the existing NEUTRAL_400 tone; not green/amber/red, distinct from UNKNOWN's #111114 and STALE/PEND's #55555f) and `BORDER_STYLE.UNMANAGED = { borderWidth: 2, borderDashes: false }`. Do not change nodeVisual's emphasis logic (inferred-root keeps precedence). Cache key already includes state -- leave as is.
4. topologyLayout.ts: add `unmanagedIdsFromTopology(topologyDevices)` (array guard, isValidEntry, `unmanaged === true`) and `unmanagedChildrenHint(switchId, topologyDevices, statuses, nowMs)` with the exact wording from <behavior> (verb/noun agree with the total: total 1 -> "device ... is", else "devices ... are"). Add `hint: string | null` to MapNode; in buildMapModel replace the state expression with `displayState(status, entry.unmanaged === true, nowMs)` and set `hint` to the children hint for unmanaged entries (compute children once from validEntries, not per node via a full rescan, to keep it O(n)), else null. Update the header comment that mentions the STALE rule.
5. TopologyMap.tsx nodeBaseFields: keep the inferredRoot > dimmed precedence; for the plain unmanaged branch use `node.hint ? \`${UNMANAGED_SWITCH_TITLE} — ${node.hint}\` : UNMANAGED_SWITCH_TITLE`. Confirm the batched sync's changed-field comparison includes `title` so a hint change updates the tooltip (it already sends title in the base fields; just verify, do not refactor). Leave the optimistic Add-Node path untouched.

Do not modify scripts/mqtt_poller.py, adminMode.ts, AdminBar.tsx, or the MQTT contract.
  </action>
  <verify>
    <automated>cd /home/kone/claude_projects/checkmk-config/dashboard-react && npx vitest run src/lib/display.test.ts src/lib/stateMapping.test.ts src/lib/mapIcons.test.ts src/lib/topologyLayout.test.ts src/components/TopologyMap.test.tsx</automated>
  </verify>
  <done>All five test files pass, including the new UNMANAGED/UNREACH/DOWN/inferred-root/hint cases; `git diff --stat scripts/` is empty.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Tree, group roll-up, stats strip, state badge and host details use displayState</name>
  <files>dashboard-react/src/lib/grouping.ts, dashboard-react/src/lib/grouping.test.ts, dashboard-react/src/lib/treeModel.ts, dashboard-react/src/lib/treeModel.test.ts, dashboard-react/src/routes/IndexRoute.tsx, dashboard-react/src/store/selectors.ts, dashboard-react/src/store/selectors.test.ts, dashboard-react/src/components/StatsStrip.tsx, dashboard-react/src/components/StatsStrip.test.tsx, dashboard-react/src/components/StateBadge.tsx, dashboard-react/src/components/StateBadge.test.tsx, dashboard-react/src/components/HostDetails.tsx, dashboard-react/src/components/HostDetails.test.tsx</files>
  <behavior>
    - buildTree with `unmanagedIds` containing sw1 (status UNKNOWN): sw1's node has state "UNMANAGED" and stale false; with sw1 DOWN: state "DOWN"; a non-unmanaged UNKNOWN host is unchanged
    - rollUpGroup with an unmanaged UNKNOWN switch alone: worst is not UNKNOWN (rank 0) and nonOkCount 0; an unmanaged DOWN switch still counts and ranks as DOWN
    - makeSelectStateCounts on a store whose topology marks sw1 unmanaged: sw1 (UNKNOWN or OK) counts under UNMANAGED, not UNKNOWN or OK; sw1 DOWN counts under DOWN; a non-unmanaged UNKNOWN host still counts under UNKNOWN; a store with topology null behaves as today
    - StatsStrip renders "Unmanaged N" (neutral badge) only when N > 0, after the other states; existing order unchanged
    - StateBadge with `unmanaged` true and UNKNOWN device shows text "Unmanaged"; without the prop behaves exactly as today
    - HostDetails for an unmanaged switch shows the "Unmanaged" badge and the children hint text (e.g. "No devices connected"); for a normal host no hint is shown
  </behavior>
  <action>
Tests first (add cases to the listed test files; update existing StateCounts literals in StatsStrip.test.tsx/selectors.test.ts for the new UNMANAGED key), then implement:

1. grouping.ts: add `UNMANAGED: 0` to SEVERITY_RANK (neutral, like OK/PEND, so unmanaged never drives a group's worst or severity sort). Give `rollUpGroup` an optional trailing parameter `unmanagedIds: ReadonlySet<string> = new Set()` and derive each device's state via `displayState(device, unmanagedIds.has(id), nowMs)` -- keep the existing staleness branch for non-UNMANAGED results (stale non-unmanaged devices still set `hatched` and are skipped); exclude UNMANAGED from `nonOkCount` alongside OK/PEND.
2. treeModel.ts: add `unmanagedIds?: ReadonlySet<string>` to BuildTreeOptions; pass it to rollUpGroup; for each device compute `shown = displayState(device, unmanagedIds.has(id), nowMs)`, set `state: shown === "STALE" ? effectiveState(device) : shown` and `stale: shown === "STALE"` so TreeNode.tsx (renders `stale ? "STALE" : state`) needs no change and an unmanaged quiet switch never renders STALE.
3. IndexRoute.tsx: `const unmanagedIds = useMemo(() => unmanagedIdsFromTopology(topologyDevices), [topologyDevices]);` and pass it in the buildTree options (main call ~L137 and add it to the deps). The `buildTree(devices, nextMode)` call (~L173) only reads group keys -- leave it.
4. selectors.ts: add `UNMANAGED: 0` to ZERO_COUNTS and type `StateCounts = Record<DeviceState | "STALE" | "UNMANAGED", number>`; inside selectStateCounts build `unmanagedIdsFromTopology(state.topology?.devices)` once per call and key each device by `displayState(device, ids.has(id), nowMs)` (iterate Object.entries to get the id). useShallow still compares a flat counts object, so no render loop.
5. StatsStrip.tsx: append "UNMANAGED" at the end of DISPLAY_ORDER with STATE_COLOR "neutral"; render the badge text through `stateLabel(state)` so it reads "Unmanaged N".
6. StateBadge.tsx: add optional `unmanaged?: boolean` prop; state = `displayState(device, unmanaged === true, nowMs)`; render `stateLabel(state)` as the badge text in both StateBadge and StateBadgeForState (label only differs for UNMANAGED, so every existing badge text is unchanged).
7. HostDetails.tsx: read two primitives from the store -- `const unmanaged = useAppStore((s) => unmanagedIdsFromTopology(s.topology?.devices).has(id));` and `const hint = useAppStore((s) => unmanaged ? unmanagedChildrenHint(id, s.topology?.devices, s.devices, nowMs) : null)` (strings/booleans compare by value, so this does not reintroduce per-frame re-renders from the recent lag fix). Pass `unmanaged={unmanaged}` to both `<StateBadge device={device} />` sites (~L440, ~L497) and render the hint as a small `text-sm text-fg-tertiary` line directly under the header row in both branches when non-null.

Then check the remaining places UNKNOWN/OK are counted or sorted and confirm by grep that none needs a change (do not edit them unless they show the switch's own state): AlertsPane, NeedsPane, IncidentList/IncidentCard, EventHistory/EventRow, HistoryChart, ForecastChart, AdminBar, adminMode. Event history keeps the poller's recorded from/to transitions verbatim (historic record, not the switch's current state) -- note this in the SUMMARY. Do not touch the poller.
  </action>
  <verify>
    <automated>cd /home/kone/claude_projects/checkmk-config/dashboard-react && npx vitest run src/lib/grouping.test.ts src/lib/treeModel.test.ts src/store/selectors.test.ts src/components/StatsStrip.test.tsx src/components/StateBadge.test.tsx src/components/HostDetails.test.tsx src/components/Tree.test.tsx src/routes/IndexRoute.test.tsx</automated>
  </verify>
  <done>Listed tests pass, including the new unmanaged cases; a non-unmanaged UNKNOWN host still renders and counts as UNKNOWN everywhere.</done>
</task>

<task type="auto">
  <name>Task 3: Docs, full verification run, and commits</name>
  <files>dashboard-react/README.md</files>
  <action>
1. Run the full gate in dashboard-react: `npm test`, `npm run typecheck`, `npm run lint`. Fix any failure caused by this change (for example other tests that build StateCounts literals or assert unmanaged titles). Record the real pass counts/output for the SUMMARY.
2. Code commit (exclude PROMPT_LOG.md, .planning/, and any Trace files; stage files by explicit path): `feat(dashboard): show unmanaged switches as Unmanaged with a children hint`.
3. README.md: update the map "Read-only behaviour" state list (~L131, add Unmanaged), the Add Node bullet (~L184) and the inferred-incident section (~L420-430) to describe: the neutral grey "Unmanaged" state for an unmanaged switch whose own state is UNKNOWN/OK (including faked UP); DOWN/UNREACH still shown; staleness not applied to a quiet unmanaged switch; the tooltip/host-details hint wording ("N of M devices behind it are up" / "No devices connected"); the stats strip's "Unmanaged N" badge; and that the inferred-root styling (>= 2 non-OK children, at least one DOWN; a lone DOWN child does not infer) takes precedence. Grep `docs/` for "Unmanaged switch"/"unmanaged" (hits: "Incident demo with fake check results.md", "Podman setup ...md"); update only lines that list the switch's displayed state (e.g. a demo step saying it shows UNKNOWN or OK). Do not edit .planning/ UI-SPEC files (none list unmanaged display states).
4. Docs commit separately: `docs(dashboard): document the Unmanaged switch state`. Do not push.
5. SUMMARY must state: front-end-only (poller and MQTT contract unchanged); the D-11 rule outcome (>= 2 non-OK children with one DOWN -> inferred root; a single DOWN child -> plain "Unmanaged" with "0 of 1 device behind it is up"); the staleness decision; the icon class chosen; and the places checked but left unchanged (event history, incidents, needs, alerts, admin faked set, history/forecast).
  </action>
  <verify>
    <automated>cd /home/kone/claude_projects/checkmk-config/dashboard-react && npm test && npm run typecheck && npm run lint</automated>
  </verify>
  <done>All three commands green; two commits (code, docs) on master, nothing pushed; PROMPT_LOG.md and .planning/ not in either commit; README describes the Unmanaged state.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| MQTT broker -> browser | Untrusted topology/status JSON (`unmanaged`, `parents`, `state`) |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-iyq-01 | Tampering | unmanagedIdsFromTopology / unmanagedChildrenHint | mitigate | Array guard + isValidEntry; only `unmanaged === true` counts; non-string parents ignored; never throws on malformed input |
| T-iyq-02 | Information disclosure | Map tooltip hint | accept | Hint is a count of ids already visible on the map; vis-network string title, no HTML injection (no user strings in the hint) |
| T-iyq-03 | Repudiation | Masking a real outage as "Unmanaged" | mitigate | Only UNKNOWN/OK map to Unmanaged; DOWN/UNREACH pass through; inferred-root precedence unchanged; tests enforce both |
</threat_model>

<verification>
- `npm test`, `npm run typecheck`, `npm run lint` all pass in dashboard-react.
- `git diff HEAD~2 --stat -- scripts/` is empty (poller unchanged).
- grep confirms `displayState(` is used in topologyLayout.ts, treeModel.ts, grouping.ts, selectors.ts and StateBadge.tsx.
</verification>

<success_criteria>
- Unmanaged switch UNKNOWN or OK (faked UP) -> neutral grey "Unmanaged" on map, tree, badge, host details; stats strip shows it under "Unmanaged", never OK/UNKNOWN.
- Unmanaged switch DOWN/UNREACH unchanged; inferred root styling/title unchanged.
- Tooltip and host details show the children hint.
- Non-unmanaged hosts render exactly as before.
- README updated; code and docs in separate commits; nothing pushed.
</success_criteria>

<output>
Create `.planning/quick/261013-iyq-dashboard-show-unmanaged-switches-as-unm/261013-iyq-SUMMARY.md` when done
</output>
