---
phase: 17-cloud-mqtt-contract-and-s3-archive-feed
plan: 07
subsystem: wizard
tags: [wizard, sen, deploy-env]
requires: [17-01]
provides:
  - Wizard prompts for the site equipment number and persists SITE_SEN to deploy/.env
affects: [17-02, 17-03, 17-04, 17-05, 17-06]
key-files:
  modified:
    - src/checkmk_wizard/wizard.py
    - tests/test_wizard.py
requirements-completed: [CLOUD-SEN]
completed: 2026-10-14
---

# Phase 17 Plan 07: Wizard SEN prompt Summary

After Phase 1 the wizard validates or asks for the site equipment number (positive integer, no leading zeros) and writes `SITE_SEN=<n>` to deploy/.env atomically, keeping the file mode.

## What was built

- `_SEN_RE` (fullmatch), `_DEPLOY_ENV_FILE`, `_read_env_value`, `_write_env_value` (temp file + os.replace, mode preserved, refuses values outside `[A-Za-z0-9_.:-]`, returns False on OSError with no temp left behind).
- `_configure_site_sen()`: existing valid file value is shown without prompting; else valid `os.environ["SITE_SEN"]` is written without prompting; else a questionary prompt with validator. Unwritable file prints the literal `SITE_SEN=<n>` line; both paths explain `podman compose down && up -d`.
- `run()` awaits it right after `phase1_site_bringup()` inside the WizardAborted try.
- Tests: autouse fixture redirects `_DEPLOY_ENV_FILE` and stubs the step for all run() tests; 24 new tests.

## Verification (observed)

- `uv run pytest tests -q`: 1311 passed.
- `uvx ruff check`: 6 findings, all pre-existing (none on the new code).

## Deviations from Plan

- [Process] Both tasks share the same two files with interleaved tests, so they were committed together in one commit (hash in git log) instead of two.
- [Rule 3] Worktree base differed from expected; reset to a69d2bd per the branch check.

## Known Stubs

None.

## Self-Check: PASSED
