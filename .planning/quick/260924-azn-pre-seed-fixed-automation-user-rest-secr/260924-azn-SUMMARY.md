---
phase: quick-260924-azn
plan: 01
subsystem: wizard-credentials
tags: [checkmk, rest, automation-user, deploy]
requirements: [TODO-2026-09-21-pre-seed-rest-secret]
key-files:
  modified:
    - src/checkmk_wizard/api.py
    - src/checkmk_wizard/wizard.py
    - tests/test_api.py
    - tests/test_wizard.py
    - deploy/compose.yaml
    - deploy/.env.example
    - README.md
    - docs/WIZARD-OPERATION.md
    - docs/Podman setup for checkmk, minio, mosquitto, worker.md
metrics:
  completed: 2026-09-24
---

# Quick 260924-azn: Pre-seed fixed automation-user REST secret Summary

`CMK_REST_SECRET` from the worker env is pushed into Checkmk as the `automation` user's secret (created if missing, PUT-updated if present) and never printed; unset/empty keeps the generate-and-print fallback.

## Commits

- 6e27bf5: `bootstrap_automation_user(..., secret=None)` with GET-probe create-vs-update, plus 4 tests
- d88ffd4: wizard passes `os.environ CMK_REST_SECRET` at both call sites; `_print_automation_secret_created(secret, from_env)` omits the value when env-sourced; 3 tests
- ee760d0: compose comments, `.env.example` (`CMK_REST_SECRET=` empty, no `REPLACE_ME`), Podman doc, WIZARD-OPERATION.md, README

## Verification (actually run)

- `uv run pytest -q`: 480 passed.
- Task 1 verify: 12 bootstrap_automation_user tests pass (4 new were RED first: TypeError on `secret=`).
- Task 3 shell verify: printed OK.
- `grep os.environ src/checkmk_wizard/api.py`: 0 matches.
- `uvx ruff check src tests`: 7 findings, all pre-existing in code not touched by this plan (tests/test_site.py x4, wizard.py:1468 B023, tests/test_wizard.py:254 RET501/PLR1711). Changed files' new code introduces none (`uvx ruff check src/checkmk_wizard/api.py tests/test_api.py` is clean).

## Not verified (no live site used, per constraints)

- `PUT /objects/user_config/automation` with `auth_type: automation` + `store_automation_secret` on update, and whether Checkmk enforces a minimum length / password policy on automation secrets. Marked UNVERIFIED in the `bootstrap_automation_user` docstring and WIZARD-OPERATION.md; the OpenAPI-spec check was not done. Behaviour is covered only by respx mocks.
- Status code of GET on a missing user is assumed 404 (per plan).

## Deviations from Plan

1. **[Setup]** Worktree base differed from the expected commit; reset to 2bcb3ed per the branch check before starting.
2. **[Rule 3 - test robustness]** rich wraps console output at terminal width, so the env-secret test collapses whitespace before matching the confirmation text.
3. Added `monkeypatch.delenv("CMK_REST_SECRET")` only to the one existing container-mode test that could be sensitive to a shell env; other existing tests use `**kwargs` and were unaffected.
4. WIZARD-OPERATION.md security bullet at ~1531 claimed the secret is "never printed"; corrected to describe both paths (stale before this change).

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model (T-azn-01/02 mitigated: env secret not printed and asserted in test; `.env.example` placeholder removed).

## Self-Check: PASSED

Commits 6e27bf5, d88ffd4, ee760d0 exist on the worktree branch; all modified files present.
