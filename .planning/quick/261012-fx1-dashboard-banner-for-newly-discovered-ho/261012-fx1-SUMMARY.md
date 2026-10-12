# Quick 261012-fx1: Dashboard banner for newly discovered hosts - Summary (PARTIAL)

**Status: Tasks 2 and 3 complete; Task 1 NOT done (blocked by the permission system).**

## What was done

- **Task 2 (commit 0053b77):** `dashboard-react/src/lib/checkmkWrite.ts` gains `parsePendingChanges`,
  `extractCreatedHostName`, `isHostCreation`, `pendingChangeKey`, `classifyPendingChanges`,
  `listPendingChanges`, `getHostSummary`, and `activateChanges(options)` with a
  `forceForeignChanges` opt-in (default false) and an `expectedChangeKeys` guard that throws a 409
  `CheckmkWriteError` without POSTing when a change appeared that the operator was not shown.
  74 checkmkWrite tests pass.
- **Task 3 (commit bb01d7b):** `DiscoveredHostsBanner.tsx` (+ tests) wired into `IndexRoute.tsx` above
  `TopologyToolbar`, enabled only when editing is available and admin mode is off. Second
  confirmation when other users' non-host changes ride along, per-session "Not now" via a guarded
  sessionStorage, generic "N pending changes" fallback. `dashboard-react/README.md` documents it and
  amends the T-13-17 paragraph.

## What was NOT done (Task 1)

The attempt to invert the `wato.activateforeign not in TOPOLOGY_EDITOR_PERMISSIONS` assertion in
`tests/test_api.py` (and the same assertion plus the exact-tuple assertion in
`tests/test_provision_topology_editor.py`) was denied by the auto-mode permission classifier
("Security Test Removal"). I did not work around it. Consequently none of the Task 1 changes exist:

- `src/checkmk_wizard/api.py`: `"wato.activateforeign"` NOT appended to `TOPOLOGY_EDITOR_PERMISSIONS`
- `tests/test_api.py`, `tests/test_provision_topology_editor.py`: not updated (the latter also needs
  its exact-tuple and `not in` assertions changed; the plan did not list that file, found by grep)
- comment amendments in `api.py`, `scripts/provision_topology_editor.py`, `deploy/dashboard-nginx.conf`
- `CLAUDE.md`, `docs/WIZARD-OPERATION.md`, `docs/DEPLOY-NEW-MACHINE.md`,
  `docs/Podman setup for checkmk, minio, mosquitto, worker.md`

Until the role is granted `wato.activateforeign`, the banner's Activate will be rejected by Checkmk
and surface the "Activation failed" snackbar.

## Verification actually run

- `uv run pytest -q`: 1196 passed (no Python changes were made).
- `dashboard-react`: `npm test` 951 passed (66 files); `npm run typecheck` clean; `npm run lint`
  no errors (pre-existing warnings only).
- Not verified: the pending-changes JSON shape (id / user_id / action_name / text / time) is NOT
  live-verified against a Checkmk site; the parser is defensive and tests use assumed phrasings.
  No browser/live check of the banner was performed.

## Deviations

- **[Rule 3 - Blocking]** `dashboard-react/node_modules` and `design-system/dist` + tarball did not
  exist. Followed the README precondition: `npm --prefix design-system ci && run build && npm pack`,
  then `npm ci` in `dashboard-react`. All outputs are gitignored (git status clean apart from
  PROMPT_LOG.md and this plan dir).
- The `.test.ts` for checkmkWrite showed an on-disk change notice mid-run; no content was lost.

## Self-Check

Commits 0053b77 and bb01d7b exist; files above exist. Task 1 incomplete, so the plan is NOT fully
complete.

## Update 2026-10-12 — Task 1 completed by the orchestrator

Task 1 (grant `wato.activateforeign`, flip the tests, amend T-13-17 notes) was blocked in the
executor by the permission classifier and completed afterwards with the operator's explicit
confirmation, commit f03dc17. Also updated `tests/test_provision_topology_editor.py`, which the
plan had not listed. `uv run pytest`: 1196 passed; dashboard `npm test` passed. Still not
live-verified: the pending-change JSON shape and the banner in a browser.
