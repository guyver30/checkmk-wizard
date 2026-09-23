---
phase: 13-wizard-parents-support-and-topology-map
plan: 05
subsystem: dashboard-checkmk-rest
tags: [dashboard, checkmk-rest, fetch, vite-proxy, typescript]

# Dependency graph
requires:
  - phase: 13 (plan 13-01)
    provides: Live-verified Checkmk REST API findings (scripts/probe_topology_rest.py VERDICTs V-SWITCH, V-PARENTS, V-LABELS, V-CORS)
  - phase: 13 (plan 13-02)
    provides: topologyLayout.ts (formatMapPosition, MAP_POSITION_LABEL, UNMANAGED_SWITCH_LABEL/VALUE), mapIcons.ts, types.ts
provides:
  - checkmkWrite.ts, the browser-side Checkmk REST writer (updateParents, setMapPosition, createUnmanagedSwitch, activateChanges, countPendingChanges, isValidHostName)
  - config.ts CHECKMK_REST_ORIGIN/TOPOLOGY_EDITOR_USER/TOPOLOGY_EDITOR_SECRET and isTopologyEditingConfigured()
  - vite.config.ts same-origin /checkmk-api proxy (server + preview)
affects: [13-06 (map edit wiring), 13-07 (Apply changes), 13-08 (deployment/cutover docs)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single fetch() choke point (request()) normalizing every REST failure into one CheckmkWriteError type, TypeScript port of api.py's _request()"
    - "Module-level promise-chain write serialization (serialize<T>()) to prevent stale-ETag races between rapid edits"
    - "GET -> drop meta_data -> mutate -> full PUT with If-Match (REPLACE semantics per probe_host_attribute_merge.py VERDICT)"
    - "Same-origin dev/preview proxy for a REST API that does not answer CORS preflights"

key-files:
  created:
    - dashboard-react/src/lib/checkmkWrite.ts
    - dashboard-react/src/lib/checkmkWrite.test.ts
    - dashboard-react/src/lib/config.test.ts
  modified:
    - dashboard-react/src/lib/config.ts
    - dashboard-react/vite.config.ts
    - dashboard-react/README.md

key-decisions:
  - "CHECKMK_REST_ORIGIN is a same-origin path prefix (/checkmk-api), not a literal URL, because 13-01's VERDICT V-CORS came back NOT ALLOWED (405, no Access-Control-* headers) -- confirmed load-bearing, not optional, per the plan objective"
  - "updateParents deletes the parents key entirely (does not send parents: []) when the result list is empty, per the plan's behavior spec"
  - "activateChanges polls activation_run by id, never the response's self link href, since that href's absolute host/port is unreachable from the browser behind the same-origin proxy"
  - "Activation poll bound widened from api.py's 30 x 0.3s to 60 x 500ms to tolerate a browser Apply activating a multi-host batch"

requirements-completed: [DASH-12, DASH-13]

# Metrics
duration: 10min
completed: 2026-09-23
---

# Phase 13 Plan 05: Browser-side Checkmk REST writer Summary

**TypeScript port of api.py's GET-ETag-PUT and activation-polling patterns (checkmkWrite.ts), gated behind a same-origin /checkmk-api Vite proxy because Checkmk answers no CORS preflight.**

## Performance

- **Duration:** ~10 min (across two tasks, TDD RED/GREEN each)
- **Started:** 2026-09-23T13:49:46+08:00 (first commit)
- **Completed:** 2026-09-23T13:56:57+08:00 (last commit), verification re-run after resume
- **Tasks:** 2/2
- **Files modified:** 6 (3 created, 3 modified)

## Accomplishments
- `checkmkWrite.ts`: a tested, serialized, REPLACE-safe REST writer (`updateParents`, `setMapPosition`, `createUnmanagedSwitch`, `activateChanges`, `countPendingChanges`, `isValidHostName`, `CheckmkWriteError`, `UNMANAGED_SWITCH_ATTRIBUTES`) with exactly one `fetch()` call site
- `config.ts`: `CHECKMK_REST_ORIGIN`, scoped write-capable `TOPOLOGY_EDITOR_USER`/`TOPOLOGY_EDITOR_SECRET` constants, `isSecretConfigured()`/`isTopologyEditingConfigured()` gates
- `vite.config.ts`: shared `server.proxy`/`preview.proxy` entry for `/checkmk-api`, overridable via `CHECKMK_PROXY_TARGET`, confirmed load-bearing given 13-01's V-CORS verdict (NOT ALLOWED)
- `dashboard-react/README.md` §4 updated to document the two new operator-edited config constants

## Task Commits

Each task followed the TDD RED -> GREEN cycle:

1. **Task 1: config.ts constants and the Vite same-origin proxy**
   - `b6c1177` test(13-05): add failing test for TOPOLOGY_EDITOR_SECRET config helpers
   - `c3f6bc9` feat(13-05): add scoped topology_editor config and the same-origin Checkmk proxy
2. **Task 2: checkmkWrite.ts, the REST writer ported from api.py**
   - `56e2db3` test(13-05): add failing test for checkmkWrite.ts REST writer
   - `01eb2ab` feat(13-05): add checkmkWrite.ts, the browser-side Checkmk REST writer

**Plan metadata:** (this commit) docs(13-05): complete browser-side Checkmk REST writer plan

## Files Created/Modified
- `dashboard-react/src/lib/checkmkWrite.ts` - the REST writer: request() choke point, updateHostAttributes()/updateParents()/setMapPosition() (GET-drop meta_data-mutate-PUT), createUnmanagedSwitch(), countPendingChanges(), activateChanges() (bounded poll), isValidHostName(), CheckmkWriteError, UNMANAGED_SWITCH_ATTRIBUTES
- `dashboard-react/src/lib/checkmkWrite.test.ts` - 19 `it()` cases covering every behavior bullet in the plan, including secret non-leak and write-serialization ordering
- `dashboard-react/src/lib/config.ts` - CHECKMK_REST_ORIGIN, TOPOLOGY_EDITOR_USER/SECRET(_PLACEHOLDER), isSecretConfigured(), isTopologyEditingConfigured()
- `dashboard-react/src/lib/config.test.ts` - tests for isSecretConfigured()/isTopologyEditingConfigured()
- `dashboard-react/vite.config.ts` - shared `/checkmk-api` proxy object referenced by both `server.proxy` and `preview.proxy`
- `dashboard-react/README.md` - §4 documents TOPOLOGY_EDITOR_SECRET and CHECKMK_REST_ORIGIN as operator-edited constants

## Decisions Made
- Shared a single `checkmkApiProxy` object between `server.proxy` and `preview.proxy` in vite.config.ts rather than duplicating the entry, per the plan's "identical entries" instruction — DRY and functionally identical; acceptance grep (`grep -c "/checkmk-api" vite.config.ts` >= 2) still passes (3 matches: header comment + proxy key + rewrite regex).
- `updateParents`'s empty-result case deletes the `parents` key entirely rather than sending `parents: []`, matching the plan's explicit behavior bullet (V-PARENTS's live probe only exercised the non-empty round-trip, so this choice — not the probe — determines the empty-list wire shape).
- `activateChanges`'s "activation timed out" case sets `body: "activation timed out"` on the thrown `CheckmkWriteError` rather than folding that text into `message`, keeping `CheckmkWriteError`'s message format (`${method} ${url} -> ${status}`) uniform across every throw site as the plan's action text specifies.
- Updated `README.md` §4 per the global CLAUDE.md documentation-update rule (the two new constants are exactly the kind of "one file an operator edits per deployment" content that section already documents) — not in the plan's `files_modified` list, but directly relevant and minimal (11 added lines).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed acceptance-criteria grep collisions in checkmkWrite.ts's own header comments**
- **Found during:** Task 2, acceptance-criteria verification
- **Issue:** Two header/inline comments accidentally contained the plan's own acceptance-check grep targets as literal substrings — `"fetch() only"` matched `grep -c "fetch(" checkmkWrite.ts` (expected exactly 1, initially 2), and `the response's "self" link href` matched `grep -n '"self"'` (expected 0 matches, initially 1).
- **Fix:** Reworded both comments to keep the same explanation without the colliding substrings (`"the browser Fetch API is the only I/O primitive used"`, `"the response's self-referencing link href"`).
- **Files modified:** `dashboard-react/src/lib/checkmkWrite.ts`
- **Verification:** Re-ran `grep -c "fetch(" checkmkWrite.ts` (now 1) and `grep -n '"self"' checkmkWrite.ts` (now empty), then re-ran the full test suite and typecheck to confirm no regression.
- **Committed in:** `01eb2ab` (part of Task 2 commit — caught and fixed before committing)

**2. [Test-authoring bug, not a deviation rule] Fixed a mock-response reuse bug in checkmkWrite.test.ts's own error-shape test**
- **Found during:** Task 2, first GREEN run
- **Issue:** The "non-2xx response" test called `countPendingChanges()` twice against a `mockResolvedValueOnce` fetch mock that only had one queued response, so the second call's fetch mock returned `undefined`.
- **Fix:** Changed to `mockResolvedValue` (not `Once`) so both calls in that test get the same mocked 404 response.
- **Files modified:** `dashboard-react/src/lib/checkmkWrite.test.ts`
- **Committed in:** `01eb2ab` (part of Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 Rule 1 bug in product-code comments, 1 test-authoring bug caught before commit)
**Impact on plan:** Both fixes were caught and corrected before the GREEN commit landed; no scope creep, no behavior change to the shipped writer.

## Issues Encountered
- The worktree's `dashboard-react/node_modules` was not yet installed (independent of the main checkout's, per the worktree isolation note) — ran `npm install` inside the worktree before any test/typecheck command, as expected.
- The full `npm test` run surfaces 2 pre-existing failures in `dashboard-react/src/components/GroupingControls.test.tsx` (fixed-`NOW_MS` fixture drifting stale against the real system clock as calendar time advances). Neither test touches any file this plan modifies; already logged in `.planning/phases/13-wizard-parents-support-and-topology-map/deferred-items.md` from plan 13-02's execution — not re-logged here, just reconfirmed still present and still out of scope.

## User Setup Required

None yet for this plan specifically — `TOPOLOGY_EDITOR_SECRET` stays the shipped placeholder (`isTopologyEditingConfigured()` returns `false`) until an operator runs `scripts/provision_topology_editor.py` (plan 13-04) and pastes its one-time secret output into `config.ts`. That operator step is documented in `dashboard-react/README.md` §4 and gates plan 13-06/13-07's edit-mode UI, not this plan's own verification.

## Next Phase Readiness
- Plan 13-06 (map edit wiring) and plan 13-07 (Apply changes) can now call `updateParents`, `setMapPosition`, `createUnmanagedSwitch`, `countPendingChanges`, and `activateChanges` directly — no plan should call `fetch()` itself for a Checkmk write.
- The same-origin `/checkmk-api` proxy is confirmed load-bearing (13-01 V-CORS: NOT ALLOWED) and wired in both `server.proxy` and `preview.proxy`; `CHECKMK_PROXY_TARGET` lets a deployment point it somewhere other than `http://localhost:8080`.
- No blockers for 13-06/13-07. Plan 13-08's deployment docs still need the post-cutover nginx `location` block equivalent to this plan's Vite proxy (already flagged in this plan's own header comment).

---
*Phase: 13-wizard-parents-support-and-topology-map*
*Completed: 2026-09-23*

## Self-Check: PASSED

All 7 referenced files confirmed present on disk (`dashboard-react/src/lib/checkmkWrite.ts`, `checkmkWrite.test.ts`, `config.ts`, `config.test.ts`, `dashboard-react/vite.config.ts`, `dashboard-react/README.md`, this SUMMARY.md). All 4 commit hashes (`b6c1177`, `c3f6bc9`, `56e2db3`, `01eb2ab`) confirmed present in `git log --oneline --all`.
