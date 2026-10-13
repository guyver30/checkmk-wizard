---
phase: quick-261013-hqy
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - dashboard-react/src/components/TopologyMap.tsx
  - dashboard-react/src/components/TopologyMap.test.tsx
  - dashboard-react/src/store/useAppStore.ts
  - dashboard-react/src/store/useAppStore.test.ts
  - dashboard-react/src/store/mqttClient.ts
  - dashboard-react/src/store/mqttClient.test.ts
  - dashboard-react/README.md
  - docs/MQTT-CONTRACT-WALKTHROUGH.md
  - .gitignore
autonomous: true
requirements: [QUICK-261013-hqy]

must_haves:
  truths:
    - "One TopologyMap sync pass makes at most one nodes.update, one nodes.remove, one edges.update and one edges.remove call"
    - "A re-render whose map model is unchanged makes no DataSet calls at all, so vis-network does not redraw"
    - "An update to a node that is already on the map never carries x or y (Phase 11 D-09). New nodes still get their grid x/y"
    - "A burst of MQTT messages is applied in one flush on the next animation frame (50 ms setTimeout fallback), with one useAppStore set and so one subscriber notification"
    - "Arrival order, last write wins per topic, tombstones and the reset-on-reconnect behaviour are unchanged"
    - "npm test, npm run typecheck and npm run lint pass in dashboard-react"
  artifacts:
    - path: "dashboard-react/src/components/TopologyMap.tsx"
      provides: "Batched, diff-skipping sync effect"
      contains: "nodeSignatures"
    - path: "dashboard-react/src/store/useAppStore.ts"
      provides: "Pure applyMessage reducer plus handleMessages(batch) with a single set"
      contains: "handleMessages"
    - path: "dashboard-react/src/store/mqttClient.ts"
      provides: "Message queue, scheduled flush, flushPendingMessages export"
      exports: ["flushPendingMessages", "connect", "disconnect", "__resetForTests"]
    - path: ".gitignore"
      contains: "Trace-*.json.gz"
  key_links:
    - from: "dashboard-react/src/store/mqttClient.ts"
      to: "useAppStore.getState().handleMessages"
      via: "flushPendingMessages()"
      pattern: "handleMessages\\("
    - from: "dashboard-react/src/components/TopologyMap.tsx sync effect"
      to: "DataSet.update(array)"
      via: "one batched call per pass"
      pattern: "nodes\\.update\\(nodeChanges"
---

<objective>
Fix the dashboard's main-thread lag (Chrome traces, 50 hosts: about 82% of main-thread time in the TopologyMap sync effect). The effect calls the DataSet once per item. With physics off, each DataSet event makes vis-network run a full synchronous `_redraw`, so one pass costs about 100 redraws. The pass reruns for every MQTT message, and a page refresh replays about 50 retained topics back to back.

Fix 1: batch the map sync and skip unchanged items. Fix 2: coalesce incoming MQTT messages so that one frame applies them as one store update. Fix 3 (caching tier-marker colours in drawTierMarkers) is out of scope and must NOT be done. Do not touch the poller, nginx or the compose files.

Output: the batched sync, the coalesced message handling, tests for both, updated docs, and a `.gitignore` entry for Chrome trace files.
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@./CLAUDE.md
@dashboard-react/src/components/TopologyMap.tsx
@dashboard-react/src/store/mqttClient.ts
@dashboard-react/src/store/useAppStore.ts
@dashboard-react/src/test/fakeVisNetwork.ts

<interfaces>
TopologyMap.tsx (current):
- `nodeBaseFields(node: MapNode, admin?: AdminDecoration)` (~L285) returns `{ id, label, title, ...visual }` and, for a selected node, adds `borderWidth: 3` and a `color` override. It has no x/y. `title` may be the explicit value undefined. This matters: DataSet.update MERGES, and the regression test "restores full opacity and the plain title once a consequence node's incident closes" (TopologyMap.test.tsx ~L697) depends on the update object still overwriting fields exactly as it does today. Keep using nodeBaseFields output unchanged as the update payload.
- The mount effect (~L565, deps [hasNodes]) creates `new DataSet` for nodes and edges and sets `nodesRef`/`edgesRef`/`networkRef`. Its cleanup nulls them.
- The sync effect (~L723-799, deps [model, adminMode, adminSelected, adminFaked]) prunes the pending overlays (pendingEdgeAdds, pendingEdgeRemovals, pendingNodeAdds), builds effectiveNodes/effectiveEdges, runs `withGridPositions`, then loops per item over update/add/remove.
- dragEnd calls `nodesRef.current?.update({ id, x, y })`. Leave it as it is.

TopologyMap.test.tsx helpers: `instances` and `resetFakeNetworks` from ../test/fakeVisNetwork, `device(overrides)`, `renderMap(...)` returning `{ rerender }`. `instances[0].data.nodes` and `.edges` are the REAL vis-data DataSet instances (only Network is faked), so `vi.spyOn(instances[0].data.nodes as any, "update")` works.

useAppStore.ts: `create<AppState>()((set, get) => ({ ..., handleMessage: (topic, payload) => {...} }))`. handleMessage (~L139-305) branches on `topic.split("/")`. Each branch either returns early (malformed input, keep last-known-good) or calls `set({...get().slice, ...})` once and returns.

adminStore.ts: `handleAdminMessage(topic, payload)`, a separate store with few, rare messages.

mqttClient.ts: `ConnectDeps { connectFn?, randomFn?, setTimeoutFn? }`. Module singletons `client`, `attempt`, `reconnectTimer`. `client.on("message")` strips the site prefix and routes `admin/` topics to `useAdminStore.getState().handleAdminMessage(rel, payload)` and everything else to `useAppStore.getState().handleMessage(rel, payload)`. The `connect` handler calls `resetIncidents()` and `resetAnalytics()` before subscribing. `disconnect()` has no callers in page code. `__resetForTests()` clears the singletons.

mqttClient.test.ts: `createFakeClient()` returns a fake with `emit(event, ...args)`. Two tests drive `fake.emit("message", ...)`: "routes each message event to useAppStore.getState().handleMessage" (~L226) spies on handleMessage, and "drops legacy-namespace and other-site messages before any store" (~L242). No other test file emits "message"; the other tests call handleMessage directly, and that API stays.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Batch the TopologyMap sync and skip unchanged items</name>
  <files>dashboard-react/src/components/TopologyMap.tsx, dashboard-react/src/components/TopologyMap.test.tsx</files>
  <behavior>
    - Test A: render a map with N >= 3 nodes and M >= 2 edges, spy on `instances[0].data.nodes` update/add/remove and `.edges` update/add/remove, then rerender with one device's state changed (new statuses object). Expect `nodes.update` called exactly once with an array, the array to hold only the changed node, `nodes.add`/`nodes.remove` and the edges methods not called, and no array item to have an `x` or `y` key (`"x" in item` is false).
    - Test B: rerender with fresh but deep-equal topologyDevices and statuses objects, so the effect really reruns. Expect zero calls to every spied nodes or edges method.
    - Test C: rerender adding one new host and dropping one existing host. Expect at most one `nodes.update` (or `nodes.add`) call, in which only the new node's item carries x/y, and exactly one `nodes.remove` call with an array that holds the dropped id. Expect edges to change through at most one update/add call and one remove call.
    - Every existing TopologyMap.test.tsx and TopologyMapDrawing.test.tsx test still passes unchanged, in particular the opacity/title restore regression (~L697), the dimmed and inferred-root tests, the admin selection/faked decoration tests and the pending-edit overlay tests.
  </behavior>
  <action>
In the sync effect, keep the overlay pruning and the construction of effectiveNodes/effectiveEdges/positioned exactly as they are. Replace only the per-item DataSet loops.

Add a ref `nodeSignatures = useRef(new Map<string, string>())`. It holds the last-applied signature per node id. The signature is `JSON.stringify(nodeBaseFields(node, admin))`: about 50 small objects, it captures label, title, the visual fields and the admin decoration (✓ label, FAKED, borderWidth, colour override), and a field that changes to undefined also changes the string. Clear this map in the mount effect right after the new DataSets are created (and in its cleanup), because a remount (hasNodes toggling) starts from empty DataSets.

For each positioned node, compute `fields = nodeBaseFields(node, admin)` and its signature:
- If the id is NOT in existingNodeIds, push `{ ...fields, x: node.x, y: node.y }`. Only new nodes get x/y.
- If the id exists and its signature differs from nodeSignatures, push `fields` with no x/y, per Phase 11 D-09.
- If the signature is equal, push nothing.
Record the signature in the map for every pushed item. Collect removed ids (in existingNodeIds, not in effectiveNodeIds) into an array and delete them from nodeSignatures. Then issue at most `nodes.update(nodeChanges)` once (DataSet.update upserts, so one call adds new ids and merges existing ones) and `nodes.remove(removedNodeIds)` once, each only when its array is non-empty. Name the array `nodeChanges` so the key_link grep matches.

Edges: an edge has only id/from/to. Compare against the live item, `edges.get(edge.id)`. Push `{ id, from, to }` when the edge is missing or its from/to differ, collect removed ids, then issue at most one `edges.update(edgeChanges)` and one `edges.remove(removedEdgeIds)`, each only when non-empty.

Order the calls: node removes and node updates first, then edge updates/removes. This keeps edges from referencing nodes that are not there yet, which is the same order as today.

Update the comment above the sync effect. It must say that the pass is batched into at most one call per DataSet operation and skips unchanged items, because each DataSet event triggers a full synchronous vis-network redraw with physics off (quick 261013-hqy, Chrome trace: about 100 redraws per pass at 50 hosts). Also fix the stale "nodes.update() / nodes.add()" wording above nodeBaseFields. Do not touch dragEnd, drawTierMarkers (fix 3 is out of scope), addNode/addEdge/the manipulation callbacks, or anything else.

Write tests A-C first in TopologyMap.test.tsx, in a new `describe("sync batching (quick 261013-hqy)")` that follows the existing renderMap/rerender pattern (copy the rerender tree from the ~L697 test). Run them and see them fail, then implement.
  </action>
  <verify>
    <automated>cd dashboard-react && npx vitest run src/components/TopologyMap.test.tsx src/components/TopologyMapDrawing.test.tsx</automated>
  </verify>
  <done>Tests A-C pass. All existing TopologyMap tests pass without changes to their assertions. The sync effect has no per-item nodes.add/nodes.update/edges.add/edges.update calls left: `grep -n "nodes.add(\|edges.add(" dashboard-react/src/components/TopologyMap.tsx` shows no hit inside the sync effect.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Coalesce MQTT messages into one store update per frame</name>
  <files>dashboard-react/src/store/useAppStore.ts, dashboard-react/src/store/useAppStore.test.ts, dashboard-react/src/store/mqttClient.ts, dashboard-react/src/store/mqttClient.test.ts</files>
  <behavior>
    - useAppStore: `handleMessages([[t1,p1],...,[tN,pN]])` for N device status messages produces exactly ONE notification to a `useAppStore.subscribe` listener, and the final `devices` contains all N.
    - useAppStore: in one batch, a status message followed by a tombstone (empty payload) for the same host leaves the host absent (devices and services). A tombstone followed by a status leaves it present. Two statuses for one host keep the last one (last write wins).
    - useAppStore: a batch that holds only malformed payloads produces zero notifications. Existing useAppStore.test.ts tests that call handleMessage directly still pass unchanged.
    - mqttClient: N `fake.emit("message", "sites/site1/lan/devices/hX/status", ...)` calls with an injected `scheduleFlushFn` that captures the callback leave the store unchanged before the flush. After the captured callback (or `flushPendingMessages()`) runs, the store holds all N devices and a subscribe listener fired exactly once.
    - mqttClient: only one flush is scheduled per burst, so the capturing scheduler is called once for N messages. A later message after the flush schedules again.
    - mqttClient: admin topics go through the same queue. After the flush, handleAdminMessage has received them in arrival order.
    - mqttClient: `__resetForTests()` clears the queue, and a flush callback captured before the reset applies nothing when it is invoked later.
    - mqttClient: a queued message from before a reconnect is applied BEFORE the reset on the `connect` event. Emit an incident status, then emit "connect", and expect incidents empty after the flush. The reset must not be overtaken by a stale queued message.
  </behavior>
  <action>
useAppStore.ts. Choose the single-`set` option, because React render batching alone would still notify zustand subscribers N times, and the spec asks for one subscriber notification. Record this choice in the SUMMARY. Make a mechanical refactor:
- Move the body of handleMessage into a module-level pure function `applyMessage(state: AppState, topic: string, payload: Uint8Array): Partial<AppState> | null`.
- Replace every `get()` with `state`.
- Replace every `set(patch); return;` with `return patch;`.
- Replace every early `return;` (malformed or ignored) with `return null;`.
- Keep every comment and branch exactly, so the topic parsing, the tombstone handling and the lastKnownPollerTimestamp logic do not change.
Then:
- `handleMessage(topic, payload)` becomes: compute the patch from `get()` and `set(patch)` when it is non-null. The API is unchanged for existing callers and tests.
- Add `handleMessages(batch: ReadonlyArray<readonly [string, Uint8Array]>)` to AppState. It folds the batch in order over `let draft = get()` (`draft = { ...draft, ...patch }` per non-null patch, tracking which keys changed), then calls `set` ONCE with only the changed keys, or does not call it when nothing changed.

mqttClient.ts:
- Add `scheduleFlushFn?: (cb: () => void) => void` to ConnectDeps. The default scheduler uses `requestAnimationFrame(cb)` when `typeof requestAnimationFrame === "function"` and `document.visibilityState !== "hidden"` (rAF does not fire in hidden tabs). Otherwise it uses `activeSetTimeoutFn(cb, 50)`.
- Add module state: `pendingMessages: Array<[string, Uint8Array]>`, `flushScheduled = false` and `flushGeneration = 0`.
- The message handler keeps the prefix strip and drop exactly as they are. It pushes `[rel, payload]` and, if no flush is scheduled, sets the flag and calls the scheduler with a callback that captures the current generation and calls `flushPendingMessages()` only when the generation is still current.
- Export `flushPendingMessages()`. It swaps the queue out, clears the flag, and walks the batch in arrival order, accumulating consecutive non-admin messages into a run. On reaching an `admin/` message it first calls `useAppStore.getState().handleMessages(run)` for the run so far, then `useAdminStore.getState().handleAdminMessage(rel, payload)`. At the end it calls handleMessages for the remaining run. This keeps admin topics in their relative order, and in practice each frame is still one app-store set. All of this runs synchronously in one task, so React batches the renders.
- In the `connect` handler, call `flushPendingMessages()` FIRST, before resetIncidents/resetAnalytics. Messages from the previous session then land before the reset, and the retained replay after SUBACK rebuilds state as today.
- `disconnect()`: DROP the queue (clear the array, bump the generation, reset the flag). It has no page callers and is teardown only, and any later connect rebuilds from the retained replay. Document this in a comment there.
- `__resetForTests()`: clear the queue, bump the generation, reset the flag, and restore the default scheduler.
- Extend the header comment with one paragraph on why messages are coalesced (quick 261013-hqy: a burst of retained topics used to cause one store set, one React commit and one TopologyMap sync pass each).

mqttClient.test.ts:
- Update "routes each message event to useAppStore.getState().handleMessage" to spy on `handleMessages`, call `flushPendingMessages()`, and expect it called with `[["lan/devices/h1/status", payload]]`. This is an intended behaviour change; say so in the test name or comment and in the SUMMARY.
- In "drops legacy-namespace...", call `flushPendingMessages()` before the not-called assertions and spy on handleMessages as well.
- Add the new behaviour tests above. Use an injected capturing `scheduleFlushFn`, so no fake timers are needed.

Write the tests first and see them fail, then implement.
  </action>
  <verify>
    <automated>cd dashboard-react && npx vitest run src/store</automated>
  </verify>
  <done>All src/store tests pass, the new burst/one-notification, ordering, tombstone, reset and reconnect tests included. handleMessage keeps its signature. `grep -n "handleMessage(rel" dashboard-react/src/store/mqttClient.ts` returns nothing, because messages only reach the app store through flushPendingMessages.</done>
</task>

<task type="auto">
  <name>Task 3: Docs, .gitignore and the full gate</name>
  <files>dashboard-react/README.md, docs/MQTT-CONTRACT-WALKTHROUGH.md, .gitignore</files>
  <action>
- Repo-root `.gitignore`: add `Trace-*.json.gz` with a one-line comment saying these are Chrome performance traces. Do NOT stage or commit the two untracked Trace-*.json.gz files.
- dashboard-react/README.md:
  - Near the MQTT namespace paragraph (~L72), add a short paragraph: incoming messages are queued and applied once per animation frame (50 ms setTimeout fallback when rAF is unavailable or the tab is hidden) through `useAppStore.handleMessages`, in arrival order with a single store update, and the queue is flushed before the reset on reconnect.
  - In the topology map section (grep `TopologyMap.tsx`, ~L489), add one sentence: the map sync issues at most one DataSet update/remove per pass, skips unchanged nodes and edges, and never sends x/y for nodes already on the map.
- docs/MQTT-CONTRACT-WALKTHROUGH.md, Part 3 "How a message becomes state" (~L325): add one bullet on the per-frame batching, and that order and last-write-wins are unchanged.
- Grep both docs for "handleMessage" and "nodes.update" and fix any statement that the new behaviour makes wrong. Change nothing else (surgical).
- Run the full gate in dashboard-react: `npm test`, `npm run typecheck`, `npm run lint`. Fix anything they flag in the files of this plan.
- Commits: code commits must not include PROMPT_LOG.md, .planning/HANDOFF.json or the Trace files. Stage the paths explicitly and do not push.
  </action>
  <verify>
    <automated>cd dashboard-react && npm test && npm run typecheck && npm run lint && cd .. && git check-ignore -q Trace-20261013T124047.json.gz && echo IGNORED</automated>
  </verify>
  <done>All three npm gates pass, the trace files are ignored, the README and walkthrough describe the batching, and no doc claims per-message store updates or per-item map updates.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| broker -> browser | MQTT payloads (already untrusted; parsed and validated by the store's existing per-topic checks) |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-hqy-01 | Denial of service | mqttClient message queue | mitigate | The queue is drained every frame (or 50 ms), so a burst stays bounded by one frame of traffic, and the flush is O(n) with a single set. Before this change, the per-message redraw was the actual DoS vector. |
| T-hqy-02 | Tampering | applyMessage refactor | mitigate | A mechanical refactor that keeps every existing validation branch. The existing useAppStore tests (malformed, tombstone, wrong shape) must pass unchanged. |
| T-hqy-03 | Tampering | stale messages across reconnect | mitigate | The queue is flushed before resetIncidents/resetAnalytics on connect, with a test for it. |
</threat_model>

<verification>
- `cd dashboard-react && npm test && npm run typecheck && npm run lint`: all green.
- The TopologyMap sync makes at most one call per DataSet operation per pass and none when unchanged (Task 1 tests).
- A burst of N messages produces one store notification after the flush (Task 2 tests).
- No changes to scripts/, deploy/, the nginx or compose files, or drawTierMarkers.
</verification>

<success_criteria>
- One sync pass makes at most one nodes.update, one nodes.remove, one edges.update and one edges.remove. An unchanged model makes zero calls. Existing-node updates carry no x/y.
- An MQTT burst is applied in one flush with one useAppStore set. Order, tombstones and last-write-wins are preserved. The queue flushes before the reconnect reset. disconnect() drops the queue, and __resetForTests() clears it and cancels a pending flush.
- The README and MQTT walkthrough are updated, and `Trace-*.json.gz` is in .gitignore.
- The SUMMARY states the single-set choice (handleMessages) and the intended test change in mqttClient.test.ts.
</success_criteria>

<output>
Create `.planning/quick/261013-hqy-dashboard-lag-batch-map-sync-updates-and/261013-hqy-SUMMARY.md` when done
</output>
