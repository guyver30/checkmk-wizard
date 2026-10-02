---
phase: quick-261002-bkk
plan: 01
subsystem: wizard-demo-mode
tags: [demo, livestatus, host_check_commands]
key-files:
  modified:
    - src/checkmk_wizard/livestatus.py
    - src/checkmk_wizard/wizard.py
    - tests/test_livestatus.py
    - tests/test_wizard.py
    - README.md
    - docs/WIZARD-OPERATION.md
    - docs/Incident demo with fake check results.md
completed: 2026-10-02
---

# Quick 261002-bkk: Demo mode pre-select, always-up host check rule, PENDING label

Demo mode now pre-checks all generated hosts in Phase 4, keeps promoted hosts fresh with an "Always assume host to be up" `host_check_commands` rule created before activation, injects check_icmp-style plugin output, and the post-activation table shows PENDING for never-checked hosts.

## Commits
- 7e82c60: livestatus `has_been_checked` / `HOST_STATE_PENDING`
- 30205b7: pre-select, rule, fake output, PENDING label in table, tests
- ab17ac2: docs

## Deviations from Plan (orchestrator-directed)
- Host UP result still injected when the rule was created (`PROCESS_HOST_CHECK_RESULT`, no `DISABLE_HOST_CHECK`), so promoted hosts show UP immediately; `DISABLE_HOST_CHECK` only in the rule-failure fallback. Docs carry no "PENDING after activation" wording for promoted hosts.
- Plugin output is `OK - <ip> rta 0.412ms lost 0%` instead of `faked up` (no `;`). `_fake_demo_hosts_up` now takes `list[OnboardedHost]` (needs the IP) plus `fake_host_checks`. `docs/Incident demo with fake check results.md` updated (`CRITICAL - <ip>: rta nan, lost 100%` for down).
- Base commit: worktree started at a28bd79 and was reset to the expected 9f71527.

## Verification
- `uv run pytest -q`: 719 passed.
- `uvx ruff check src tests`: 8 errors, all pre-existing (B023 wizard.py scan progress, I001/RET501/PLR1711 in tests, test_site); none in changed lines.
- Not verified: `value_raw="'ok'"` against a live Checkmk 2.4.0p35 (from GUI source knowledge; documented in code and docs with the GUI/REST cross-check).

## Known Stubs
None.

## Self-Check: PASSED
