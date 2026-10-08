# Quick 261008-cnd: Topology map physics off at construction

Physics is now `false` in `NETWORK_OPTIONS`, so no host can be pushed around when another is dragged. The stabilization handler and the per-node `physics: false` keys, which only existed to switch it off later, are removed.

Commit: 7eb7263

## Changes
- `dashboard-react/src/components/TopologyMap.tsx`: `physics: false` in `NETWORK_OPTIONS` with a dated post-mortem comment. Removed the `stabilizationIterationsDone` handler, the per-node `physics: false` in the sync effect, in `addNode`, and in `dragEnd`. Updated the header and dragEnd comments.
- `dashboard-react/src/components/TopologyMap.test.tsx`: new regression test (physics false at construction, never re-enabled, x/y unchanged across edit-mode toggles and a stabilization event). Saved-node and addNode tests no longer expect a per-node physics key.

## Verification (run)
- RED: new test failed against old options (`{stabilization: ...}` instead of `false`).
- `npx vitest run src/components/TopologyMap.test.tsx`: 71/71 passed.
- `npm test`: 833/833 passed.
- `npx tsc --noEmit`: exit 0.
- `grep -c stabiliz` in TopologyMap.tsx is 0. The only non-comment `physics` occurrence is in `NETWORK_OPTIONS`.
- No docs mention physics, so there were no doc edits.

## Not verified
The root cause was not reproduced. The operator must confirm in the browser after deploy: in edit mode, drag one host and check that no other host moves.

## Deviations
None.
