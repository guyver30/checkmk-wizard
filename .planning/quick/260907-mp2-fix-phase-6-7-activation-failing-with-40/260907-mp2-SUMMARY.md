---
phase: quick-260907-mp2
plan: 01
subsystem: api
tags: [checkmk, rest-api, activation, wato]

# Dependency graph
requires: []
provides:
  - Phase 6 and Phase 7 activation no longer fails with a 401 on cmkadmin's leftover Phase 1 pending changes
affects: [wizard-phase6-discovery, wizard-phase7-activation]

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - src/checkmk_wizard/wizard.py
    - src/checkmk_wizard/api.py
    - tests/test_wizard.py

key-decisions:
  - "force_foreign_changes=True is unconditional at the wizard's single activation call site (_activate_pending_changes) — no CLI flag/env var/prompt added, per plan scope guard"
  - "CheckmkClient.activate_changes()'s signature and False default left untouched; bootstrap_automation_user()'s own eager self-activation still sends force_foreign_changes: False since cmkadmin activates its own change there"

patterns-established: []

requirements-completed: [QF-01]

# Metrics
duration: 15min
completed: 2026-09-07
---

# Phase quick-260907-mp2: Fix Phase 6/7 activation 401 Summary

**`_activate_pending_changes()` now passes `force_foreign_changes=True` to `CheckmkClient.activate_changes()`, unblocking Phase 6/7 activation when cmkadmin's Phase 1 bootstrap changes are still pending.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-09-07T08:10:00Z
- **Completed:** 2026-09-07T08:25:45Z
- **Tasks:** 2 completed
- **Files modified:** 3

## Accomplishments
- Fixed the live-verified 401 "There are changes from other users and foreign changes are not allowed in this API call" that aborted activation in both Phase 6 and Phase 7 whenever cmkadmin's Phase 1 user-bootstrap changes were still pending when the `automation` REST user tried to activate.
- Brought the stale comment in `bootstrap_automation_user()` (`api.py`) back in line with the new behavior, without touching its actual logic.
- Added a regression test that pins `force_foreign_changes` to `True` in the actual JSON request body sent by `_activate_pending_changes()`, and confirmed by hand that it fails if the flag is removed.

## Task Commits

Each task was committed atomically:

1. **Task 1: Force foreign changes at the wizard's activation call site** - `1c5e375` (fix)
2. **Task 2: Regression test pinning force_foreign_changes=True** - `ec4a55a` (test)

**Plan metadata:** committed separately by the orchestrator (docs commit not part of this executor's scope).

## Files Created/Modified
- `src/checkmk_wizard/wizard.py` - `_activate_pending_changes()` now calls `client.activate_changes([connection.site], etag, force_foreign_changes=True)`, with an added why-comment naming the live-verified 401 and explaining that cmkadmin and `automation` represent one operator within a single wizard run.
- `src/checkmk_wizard/api.py` - Updated the now-stale comment block inside `bootstrap_automation_user()` that previously claimed the later activation ran with `force_foreign_changes` "left at its safe default of False" (no longer true); the rest of the rationale (why the eager cmkadmin self-activation is still worth doing) is preserved. No signature, default, or behavior change to `activate_changes()` or `bootstrap_automation_user()`.
- `tests/test_wizard.py` - `_mock_activation_routes()` now returns the activate-changes POST route object (existing callers unaffected, since none previously used the return value). Added `test_activate_pending_changes_forces_foreign_changes`, asserting `json.loads(request.content)["force_foreign_changes"] is True` and that `If-Match` is still sent, placed next to the existing activation tests.

## Decisions Made
- Kept the fix to a single keyword argument at the one call site the plan named, per its explicit scope guard: no CLI flag, config option, env var, or interactive prompt was added to make this conditional — it's unconditional, matching the "same operator, two accounts" rationale in the plan's threat model (T-QF-01, accepted).
- Did not touch `CheckmkClient.activate_changes()`'s signature/default or `bootstrap_automation_user()`'s own eager cmkadmin self-activation (`force_foreign_changes: False` on line ~472 of `api.py`) — that call activates cmkadmin's own change and correctly stays `False`.
- Did not modify `tests/test_api.py:319`, which asserts the bootstrap self-activation still sends `force_foreign_changes: False` — confirmed via `git diff main..HEAD -- tests/test_api.py` that it is untouched.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. To confirm the new regression test actually guards the fix (not just exercises code that always passes), I temporarily reverted the `force_foreign_changes=True` argument in `wizard.py`, re-ran `uv run pytest tests/test_wizard.py -q -k activate`, and observed `test_activate_pending_changes_forces_foreign_changes` fail with `assert False is True`, then restored the fix and re-ran the full suite (304 passed) before committing. This was a local verification step only — no extra commit was made for the intentional revert/restore.

## Verification Performed

- `grep -n 'activate_changes(\[connection.site\], etag, force_foreign_changes=True)' src/checkmk_wizard/wizard.py` — matches the single call site.
- `grep -n 'force_foreign_changes: bool = False' src/checkmk_wizard/api.py` — still matches; API default unchanged.
- `uv run pytest tests/ -q` — **304 passed** (was 303 before Task 2's new test).
- `git diff main..HEAD --stat` — only `src/checkmk_wizard/api.py`, `src/checkmk_wizard/wizard.py`, `tests/test_wizard.py` changed; `tests/test_api.py` confirmed untouched.
- Manually reverted then restored the fix to confirm the new test is a real regression guard (see Issues Encountered).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- The fix and its regression test are self-contained; no follow-on work identified by this task.
- Phase 9 (poller-core) execution, already in progress per STATE.md, is unaffected by this change.

---
*Phase: quick-260907-mp2*
*Completed: 2026-09-07*

## Self-Check: PASSED

- Commit `1c5e375` (Task 1): FOUND in `git log --all`
- Commit `ec4a55a` (Task 2): FOUND in `git log --all`
- `src/checkmk_wizard/wizard.py`: FOUND
- `src/checkmk_wizard/api.py`: FOUND
- `tests/test_wizard.py`: FOUND
- `.planning/quick/260907-mp2-fix-phase-6-7-activation-failing-with-40/260907-mp2-SUMMARY.md`: FOUND
