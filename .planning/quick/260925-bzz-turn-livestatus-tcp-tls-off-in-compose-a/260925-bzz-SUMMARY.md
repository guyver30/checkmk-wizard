---
phase: quick-260925-bzz
plan: 01
subsystem: livestatus-tcp
tags: [checkmk, livestatus, tls, compose, entrypoint-hook]
requirements: [QUICK-260925-bzz]
key-files:
  created:
    - deploy/checkmk-hooks/pre-start/10-livestatus-tcp-plaintext.sh
  modified:
    - deploy/compose.yaml
    - src/checkmk_wizard/site.py
    - src/checkmk_wizard/wizard.py
    - src/checkmk_wizard/livestatus.py
    - tests/test_site.py
    - tests/test_wizard.py
    - README.md
    - docs/Podman setup for checkmk, minio, mosquitto, worker.md
metrics:
  completed: 2026-09-25
---

# Quick 260925-bzz: Livestatus TCP TLS off Summary

A compose-deployed Checkmk site now gets `LIVESTATUS_TCP_TLS=off` via a read-only pre-start entrypoint hook; host-mode wizard sets TCP on and TLS off (stop, set, start); container mode detects a TLS-only port 6557 and prints the exact fix.

## Commits

- 9a66de4: feat - pre-start hook + compose mount (script committed as git mode 100755, verified with `git ls-files -s`)
- dc8b9a5: feat - `livestatus_tcp_tls_enabled()`, reworked `enable_livestatus_tcp()`, `_livestatus_answers_plaintext()` and container-mode warning, tests
- 4cf357d: docs - README and Podman doc (sections 5, 8.3, 8.5)

## Verification actually run

- `bash -n` on the hook, executable bit, `git ls-files -s` shows 100755, compose mount line present outside comments: passed.
- `uv run pytest -q`: 500 passed.
- `uvx ruff check --no-cache src tests`: 7 findings, equal to the pre-existing baseline (one new SIM117 in my test was fixed).
- Task 3 grep checks: passed.

## Not verified (record)

- (a) Whether the image ships its own files in /docker-entrypoint.d/pre-start/ (mitigated: single-file mount).
- (b) Whether the entrypoint runs under `set -e` (mitigated: hook always exits 0, no `set -e`).
- (c) That the `2.4.0-latest` tag's entrypoint matches branch 2.4.0.
- The optional podman confirmation was NOT run: `podman` is not installed on this machine. The hook was never executed against a real container, and the live operator check in the plan (`podman compose up -d --force-recreate checkmk`, then `omd config dmc show LIVESTATUS_TCP_TLS` prints `off`) is still outstanding.

## Deviations from Plan

- Worktree HEAD started at 18d7fe1 (not the expected base); reset to a80fe89 per the startup instructions.
- `_omd_config_set()` private helper added in site.py to avoid duplicating the set/raise logic for the two variables (minor, within Task 2 scope).
- `enable_livestatus_tcp` also raises SiteBootstrapError if `omd stop` fails with "failed" in stdout (not specified in plan; mirrors the start_site convention).
- Tests used the plan's design; one pre-existing test (`..._restarts_when_already_running`) was replaced by the stop/set/set/start ordering test as planned.

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model (hook mounted `:ro`, always exits 0, try/finally restart).
