# Quick 261008-f5e: Wizard main menu and --manage Summary

Main menu after Phase 1 ("Onboard new hosts" default / "Manage existing hosts only") plus a `--manage` flag, reusing the retag screen, services step, Phase 6 and Phase 7.

## Commits
- 6880a0a feat: menu, `--manage`, `_manage_existing_hosts`, `default_yes`, tests
- 3eeb543 docs: docs/WIZARD-OPERATION.md and README.md

## What changed
- `src/checkmk_wizard/wizard.py`: `_prompt_main_menu`, `_manage_existing_hosts`, `run(demo, manage)`, `main --manage` (`--demo --manage` is an argparse error, exit 2). Amended docstrings of `_retag_existing_hosts` and `manage_existing_host_services`.
- `tests/test_wizard.py`: 14 new tests (menu choices/default, manage flow, no tag group, no service hosts, no hosts, flags, Esc at menu and in retag, both default_yes defaults, argparse conflict); existing run() tests mock the menu; `fake_run` accepts `manage`.
- Docs: new "Main menu" section, `--manage`, control-flow diagram, Esc, README subsection.

## Deviations
**Operator amendment (replaces the plan's "leave both defaults as No").** In option 2 and with `--manage`, the retag screen's first question and the services step's opt-in confirm default to Yes. Implemented as a keyword `default_yes: bool = False` on `_retag_existing_hosts` (`default=bool(promoting) or default_yes`) and `manage_existing_host_services`; `_manage_existing_hosts` passes `default_yes=True`; the onboarding flow keeps No. Tested for both values; documented.

Otherwise the plan was executed as written. The worktree started at bd3f266 and was reset to fa58b87 per the branch check.

## Verification (observed)
- `uv run pytest -q`: 1194 passed.
- `uvx ruff check` on wizard.py and tests/test_wizard.py: 4 findings (3 auto-fixable), identical count on the base commit fa58b87 files; none introduced here.
- Doc greps: `--manage` appears in both docs; "## Main menu" and both function names present.
- NOT live-verified: nothing was run against a real Checkmk site or terminal; the prompt UI itself (questionary select rendering) is untested beyond mocks.

## Operator checklist
1. Run `deploy/run-wizard.sh` (or `uv run checkmk-wizard`); after Phase 1 the "What do you want to do?" menu appears.
2. Press Enter: Phase 2 starts as before (old flow unchanged; retag and services prompts still default No).
3. Re-run and pick "Manage existing hosts only" (or `--manage`): no folder/scan prompts; the "Hosts to tag" table lists existing hosts; the "Do that now?" and services opt-in questions default to Yes.
4. Retag one host, then change a service on an agent host; Phase 6 rediscovers that host, Phase 7 activates and shows the full-site table; no pending changes remain in Setup > Activate changes.
5. Press Esc at the menu and inside the manage flow: the pending-changes Apply/Revert/Leave prompt behaves as in Phases 2-4.
6. `deploy/run-wizard.sh --demo --manage` prints the argparse error and exits.

## Self-Check: PASSED
Both commits exist; wizard.py, tests, both docs modified.
