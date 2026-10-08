---
phase: quick-261008-cnd
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - dashboard-react/src/components/TopologyMap.tsx
  - dashboard-react/src/components/TopologyMap.test.tsx
autonomous: true
requirements: [QUICK-261008-cnd]

must_haves:
  truths:
    - "Dragging one host in edit mode never moves any other host on the topology map"
    - "A placed host (saved map_position or grid position) stays where it is when other hosts move, are added, or are removed"
    - "Physics is off from the moment the Network is constructed, not only after a stabilization event"
  artifacts:
    - path: "dashboard-react/src/components/TopologyMap.tsx"
      provides: "NETWORK_OPTIONS with physics: false; no stabilizationIterationsDone handler; no per-node physics:false keys"
      contains: "physics: false"
    - path: "dashboard-react/src/components/TopologyMap.test.tsx"
      provides: "Regression test asserting physics is false at construction and never re-enabled"
  key_links:
    - from: "NETWORK_OPTIONS"
      to: "new Network(container, { nodes, edges }, NETWORK_OPTIONS)"
      via: "constructor options"
      pattern: "physics: false"
---

<objective>
Stop the topology map from reflowing other hosts when one host is dragged.

Purpose: vis-network runs a physics simulation until `stabilizationIterationsDone` fires and only then turns physics off globally; nodes without a saved position never got a per-node `physics: false`, so they can still be pushed around (the operator reports other hosts re-arranging during a drag). Every node already gets explicit x/y from `withGridPositions` (dashboard-react/src/lib/topologyLayout.ts) and unmanaged switches get explicit x/y in `addNode`, so physics serves no purpose. Turn it off at construction and delete the code that only existed to turn it off later.

Output: edited TopologyMap.tsx and TopologyMap.test.tsx; `npm test` and `npx tsc --noEmit` green in dashboard-react.

Note: the root cause was not reproduced locally; the operator confirms the fix in the browser after deploy.
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/templates/summary.md
</execution_context>

<context>
@./CLAUDE.md
@dashboard-react/src/components/TopologyMap.tsx
@dashboard-react/src/components/TopologyMap.test.tsx
@dashboard-react/src/test/fakeVisNetwork.ts

<interfaces>
Exact locations in dashboard-react/src/components/TopologyMap.tsx (line numbers as of planning):
- Lines 1-2, file header comment: "Mounts the vis-network Network exactly once (physics stabilizes then freezes on first load)".
- Line 253, comment "13-UI-SPEC.md \"Topology Map Rendering\" -- node/edge/physics/interaction options, locked."
- Line 265, inside NETWORK_OPTIONS: `physics: { stabilization: { iterations: 200 } },`
- Line 540, inside addNode's success `callback({... title: UNMANAGED_SWITCH_TITLE, physics: false, x, y, ...})`.
- Lines 571-573: `network.once("stabilizationIterationsDone", () => { network.setOptions({ physics: false }); });`
- Lines 645-649: dragEnd comment ending "A successful write freezes that node's physics so later syncs never move it again."
- Lines 664-667: in dragEnd, `.then(() => { nodesRef.current?.update({ id, physics: false }); onEditSavedRef.current?.(); })`
- Line 777, in the sync effect's `nodes.add({...})`: `...(node.saved ? { physics: false } : {}),`
- Line 701-712: editMode effect's `network.setOptions({ manipulation, interaction })` -- does NOT touch physics; leave it alone.

dashboard-react/src/test/fakeVisNetwork.ts: FakeNetwork exposes `options` (constructor options, merged by setOptions), `setOptionsCalls: Record<string, unknown>[]`, `emit(event)`, `data.nodes`/`data.edges`.

Existing tests in TopologyMap.test.tsx touching physics:
- Line 252 "adds a node with a saved map_position at its exact x/y with physics false" (asserts item.physics === false).
- Line 264 "gives an unsaved node its withGridPositions coordinates without a physics key" (asserts physics undefined).
- Line 276 "calls setOptions with physics false when the fake emits stabilizationIterationsDone".
- Line ~1239 addNode success test: `expect(callback).toHaveBeenCalledWith(expect.objectContaining({ ..., physics: false }))`.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Disable physics at construction, drop redundant physics code, add regression test</name>
  <files>dashboard-react/src/components/TopologyMap.tsx, dashboard-react/src/components/TopologyMap.test.tsx</files>
  <behavior>
    - Regression test: instances[0].options.physics is exactly false right after the first render with one device (before any event is emitted).
    - Regression test: after rendering two devices (one with map_position "300,40", one without), toggling editMode on and off via rerenderMap, and emitting "stabilizationIterationsDone" on the fake, no entry in instances[0].setOptionsCalls has a physics key other than false (i.e. physics is never re-enabled), and both nodes keep the exact x/y they were added with.
    - Saved node test (line 252): still lands at exactly x 300, y 40; it no longer asserts a per-node physics key (assert physics is undefined instead, since the global option now covers it).
    - addNode success test (~line 1239): callback still called with id/label/title, but without requiring physics: false.
  </behavior>
  <action>
Surgical: touch only physics/stabilization lines listed in the interfaces block. Do not change grid, drawing, click, admin, or edit-mode code.

In TopologyMap.tsx:
1. NETWORK_OPTIONS: replace `physics: { stabilization: { iterations: 200 } }` with `physics: false`. Add a short dated comment (repo convention: post-mortem at the fix site) above it, e.g. "Fixed 2026-10-08: physics used to run until stabilizationIterationsDone and was then switched off; nodes with no saved position had no per-node freeze, so dragging one host could shove others. Every node is placed explicitly (withGridPositions, addNode x/y), so physics is off from construction and a placed host only moves when it is itself dragged." Keep the line-253 "locked" comment but drop "physics/" from its list or note the deviation in one clause (user-requested change to the 13-UI-SPEC option).
2. Delete the `network.once("stabilizationIterationsDone", ...)` block (lines 571-573) and its blank line.
3. dragEnd: in `.then(...)` remove only `nodesRef.current?.update({ id, physics: false });`, keep `onEditSavedRef.current?.();`. Edit the comment's last sentence ("A successful write freezes that node's physics...") to drop the physics claim (e.g. "A successful write reports via onEditSaved; physics is off globally, so nothing else ever moves the node.").
4. Sync effect nodes.add: remove the `...(node.saved ? { physics: false } : {}),` line. Do not touch `node.saved` elsewhere; if `saved` becomes unused only in this file that is fine (it is a field on the positioned node from topologyLayout.ts, do not change topologyLayout.ts).
5. addNode success callback: remove the `physics: false,` key; keep x/y.
6. Header comment line 2: replace "(physics stabilizes then freezes on first load)" with "(physics off; every node is placed at an explicit x/y)".

In TopologyMap.test.tsx:
- Replace the line-276 stabilizationIterationsDone test with the regression test(s) from the behavior block. Put a comment above naming the bug: operator report 2026-10-08, dragging one host on the topology map reflowed/re-arranged the other hosts, because physics was only switched off on stabilizationIterationsDone and unsaved nodes had no per-node freeze; fix sets physics false in the constructor options.
- Adjust the line-252 test name and assertion and the ~1239 objectContaining per the behavior block. Leave the line-264 test as is (still valid).
- Write the new test first and confirm it fails against the old options (RED), then apply the source edits (GREEN).

Run in dashboard-react: `npm test` and `npx tsc --noEmit`. Docs: grep found no physics/stabilization mention in docs/*.md, README.md, or dashboard-react; no doc edits needed unless the executor's own grep finds one.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard/dashboard-react && npx vitest run src/components/TopologyMap.test.tsx && npm test && npx tsc --noEmit && test "$(grep -c 'stabiliz' src/components/TopologyMap.tsx)" = "0" && test "$(grep -v '^ *//' src/components/TopologyMap.tsx | grep -c 'physics')" = "1"</automated>
  </verify>
  <done>NETWORK_OPTIONS has `physics: false`; no stabilizationIterationsDone handler; no per-node physics keys in TopologyMap.tsx (the only non-comment `physics` occurrence is NETWORK_OPTIONS); new regression test with bug-naming comment passes; full `npm test` and `tsc --noEmit` pass.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| none new | Client-side rendering option change only; no new input, endpoint, or write path |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-261008cnd-01 | Tampering | TopologyMap dragEnd position write | accept | Write path (setMapPosition, snapToGrid) unchanged; only the post-write per-node physics update is removed |
</threat_model>

<verification>
- `npm test` and `npx tsc --noEmit` pass in dashboard-react.
- Operator check (deploy host, not dev machine): in edit mode drag one host; no other host moves.
</verification>

<success_criteria>
- Physics disabled at Network construction; stabilization handler and redundant per-node physics keys removed.
- Regression test names the bug and guards that physics is never enabled.
- No unrelated lines changed.
</success_criteria>

<output>
Create `.planning/quick/261008-cnd-topology-map-stop-reflow-when-dragging-a/261008-cnd-SUMMARY.md` when done
</output>
