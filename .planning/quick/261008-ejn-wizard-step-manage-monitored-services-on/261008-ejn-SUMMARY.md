# Quick 261008-ejn: Manage monitored services on existing hosts Summary

Opt-in wizard step after Phase 4 that edits each existing Linux agent host's `discovery_systemd_units_services` rule via new REST methods (`get_rule`, `update_rule`, `delete_rule`), with its hosts rediscovered in Phase 6.

## Tasks

| Task | Commit |
|------|--------|
| 1. REST methods get_rule / update_rule / delete_rule + 4 tests | 1ac405d |
| 2. `manage_existing_host_services`, helpers, run() wiring, tests | acc1c09 |
| 3. Docs (WIZARD-OPERATION.md, README Esc paragraph) | see git log (docs commit) |

## Verification actually run

- `uv run pytest -q`: 1179 passed.
- `uv run pytest tests/test_api.py -q`: 75 passed (ruff clean on api.py and test_api.py).
- ruff on wizard.py and tests/test_wizard.py: 4 findings (B023 at wizard.py:1993, I001, RET501, PLR1711 in tests). All four exist unchanged on base commit 9ab7caa (checked by running ruff on the base files); none introduced here.
- Docs grep checks: section title, `manage_existing_host_services` and "Systemd single services discovery" all present in docs/WIZARD-OPERATION.md.

## NOT live-verified

Nothing was run against a real Checkmk 2.4.0p35 site or a real SSH host; all tests use respx and mocked prompts. Unverified REST shapes (read from the 2.4.0 source only): GET/PUT/DELETE `/objects/rule/{id}`, whether GET returns an `ETag` (fallback `If-Match: *`), and that PUT accepts the echoed `properties`. TDD note: RED for Task 2 was the import error at collection (the names did not exist yet); behavior tests were then green on first run.

## Deviations

- Plan said `_prompt_host_services` and others as described; implemented as specified. The duplicate-rules test was split in two (unchanged union selection writes nothing; changed selection updates the first and deletes the second) because the union semantics make the plan's single scenario a no-op.
- Windows is out of scope by design (no OS signal on existing host records; wizard never connects to Windows).
- README has no phase list; only its Esc paragraph got one added mention of the step.

## Operator checklist (needs a live stack)

1. Run the wizard, answer Yes, add a service to an existing host, apply; after Phase 6/7 the "Systemd Service <name>" service appears.
2. Rerun, untick that service, apply; it vanishes after discovery/activation and the rule no longer lists it.
3. Rerun, untick everything; the host's "Systemd single services discovery" rule is gone.
4. Check in Setup that each host has at most one such rule and its host_name condition is intact.
