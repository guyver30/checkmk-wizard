# Quick 261001-ts1: wizard Esc abort Summary

Esc/Ctrl+C at any prompt in Phases 1-4 aborts through one `WizardAborted`, then the wizard shows pending changes and offers Apply / Revert (GUI revert_changes action) / Leave; Esc is off from Phase 5.

## Commits
- 1301cfe feat: `api.revert_pending_changes()` + `RevertChangesResult` (7 respx tests)
- f4e8204 feat: `WizardAborted`, `_AbortState`, `_abortable_ask_async` (installed in `main()`), retag-screen Esc, Phase 5 disables Esc with a note, Ctrl+C exits 130 (9 tests)
- e33f171 feat: `_handle_abort()` (table, apply/revert/leave), `run()` wiring, cmkadmin password recorded for revert (11 tests)
- 31acab0 docs: WIZARD-OPERATION.md "Leaving the wizard early (Esc)" + Phase 5 sentence, README "Leaving early (Esc)"

## Verification (observed)
- `uv run pytest -q`: 712 passed.
- `uvx ruff check --no-cache` on the four touched Python files: "Found 4 errors." (same 4 pre-existing, none new).
- Greps: `Question.ask_async = _abortable_ask_async` appears once (main()); "Not yet live-verified on 2.4.0p35" present in the api.py docstring; no reset-site lines in the docs diff.

## Not verified
- `revert_pending_changes` against a real Checkmk 2.4.0p35 (only respx mocks); transid/csrf parsing is based on reading Checkmk source.
- Esc behaviour in a real terminal (tested with prompt_toolkit pipe input only).

## Deviations
- [Rule 3] The worktree was based on 8961412, not the expected 38dac86; reset --hard to 38dac86 per the branch check, before any work.
- Default select choice is "leave" when other users' changes exist, else "revert" (per plan, Claude's discretion).
- Test note: a KeyboardInterrupt escaping an asyncio task kills the test runner, so the Ctrl+C-with-Esc-disabled test catches it inside the task.

## Known Stubs
None.

## Self-Check: PASSED
