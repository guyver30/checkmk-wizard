---
phase: quick-261013-hqy
plan: 01
subsystem: dashboard-react
tags: [performance, vis-network, mqtt, zustand]
key-files:
  modified:
    - dashboard-react/src/components/TopologyMap.tsx
    - dashboard-react/src/components/TopologyMap.test.tsx
    - dashboard-react/src/store/useAppStore.ts
    - dashboard-react/src/store/useAppStore.test.ts
    - dashboard-react/src/store/mqttClient.ts
    - dashboard-react/src/store/mqttClient.test.ts
    - dashboard-react/src/store/selectors.test.ts
    - dashboard-react/README.md
    - docs/MQTT-CONTRACT-WALKTHROUGH.md
    - .gitignore
completed: 2026-10-13
---

# Quick 261013-hqy: Dashboard lag, batched map sync and coalesced MQTT messages

Batches the TopologyMap DataSet sync (one update/remove per DataSet per pass, unchanged items skipped, no x/y on existing nodes) and coalesces MQTT messages into one `useAppStore` update per animation frame.

## Commits

- 88f3fc6 perf(dashboard): batch topology map sync and skip unchanged nodes and edges
- 548e3cc perf(dashboard): coalesce MQTT messages into one store update per frame
- 54ec7a9 docs(dashboard): document batched map sync and message coalescing, ignore Chrome traces

## What changed

**Fix 1 (TopologyMap sync).** A `nodeSignatures` ref stores `JSON.stringify(nodeBaseFields(node, admin))` per node id. New nodes are sent with grid x/y; existing nodes are sent (without x/y) only when the signature changed. Edges are compared against `edges.get(id)` for from/to. One `nodes.remove`, one `nodes.update`, one `edges.update`, one `edges.remove` per pass, each only when non-empty. Signatures are cleared when the mount effect creates fresh DataSets. Existing `nodeBaseFields` output is the unchanged update payload, so the opacity/title restore regression still holds.

**Fix 2 (message coalescing), store-side approach: single `set`.** `handleMessage`'s body became a pure `applyMessage(state, topic, payload)` returning a patch or null. `handleMessage` is unchanged for callers. New `handleMessages(batch)` folds the batch in order over a draft and calls `set` once with only the changed keys (no call if nothing changed). `mqttClient` queues each message and schedules one flush (rAF, or 50 ms timeout when rAF is missing or the tab is hidden); `flushPendingMessages()` is exported. Admin messages go through the same queue and are delivered in arrival order (the app-message run before an admin message is flushed first). `connect` flushes the queue before `resetIncidents`/`resetAnalytics`. `disconnect()` drops the queue; `__resetForTests()` clears it and invalidates any scheduled flush through a generation counter. New `scheduleFlushFn` dep for tests.

**Docs/ignore.** README (map section and MQTT namespace section), MQTT walkthrough Part 3 bullet, `Trace-*.json.gz` in `.gitignore`. Fix 3 (tier-marker colour caching) not done; poller, nginx and compose untouched.

## Existing tests changed (intended behaviour change)

All in `mqttClient.test.ts`, because messages now reach the stores only on flush and through `handleMessages`:

- "routes each message event to ... handleMessage" renamed and now spies `handleMessages`, asserts it is not called before the flush, then called with `[["lan/devices/h1/status", payload]]` after `flushPendingMessages()` (as the plan specified).
- "drops legacy-namespace and other-site messages" now spies `handleMessages` and flushes before the not-called assertions (as specified).
- Two further tests in "admin mode" ("routes admin/ messages to the admin store only", "still routes lan/ messages to the app store") also asserted synchronous delivery and failed after the change. They were not listed in the plan; they now call `flushPendingMessages()` and the lan one spies `handleMessages`. Assertions otherwise unchanged.

`selectors.test.ts` builds a full `AppState` literal, so it gained `handleMessages: () => {}` to keep typecheck green. No other existing test assertions were touched.

## Deviations

- [Rule 3] The extra two mqttClient tests and selectors.test.ts edit above.
- During task 2 I removed a `nodeSignatures.current.clear()` I had added to the mount-effect cleanup in task 1, because it introduced a new oxlint `exhaustive-deps` warning; the clear at mount time already covers remounts. This is in commit 548e3cc together with the task 2 files.

## Verification (actually run in dashboard-react)

- `npm test`: 67 files, 975 tests passed.
- `npm run typecheck`: clean (no output errors).
- `npm run lint`: no errors; only pre-existing warnings (the TopologyMap `navigate` exhaustive-deps warning is pre-existing; no new warning from this change after the cleanup removal).
- Task 1 tests were confirmed RED against the previous TopologyMap.tsx (3 failures) and GREEN with the change. Task 2 tests were written together with the implementation; the 3 pre-existing mqttClient tests failing before I updated them confirmed the behaviour change, but I did not separately run the new tests against the old code.
- `git check-ignore Trace-20261013T124047.json.gz` reports it ignored.

## Not verified

- Not seen in a browser; no new Chrome trace was taken, so the actual reduction in main-thread time is unmeasured.
- The rAF default scheduler and the hidden-tab setTimeout fallback are not covered by tests (tests inject `scheduleFlushFn`).
- Admin-mode behaviour against a live broker was not exercised; only the unit tests.

## Self-Check: PASSED

Commits 88f3fc6, 548e3cc, 54ec7a9 exist; modified files verified present via git status/diff.
