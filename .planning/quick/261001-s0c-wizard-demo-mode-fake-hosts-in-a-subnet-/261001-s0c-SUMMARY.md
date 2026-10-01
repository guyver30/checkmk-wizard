# Quick Task 261001-s0c: wizard --demo mode Summary

`checkmk-wizard --demo` generates N fake hosts per subnet folder instead of scanning, defaults Phase 4 to ping, and fakes the hosts UP via Livestatus external commands after Phase 7 activation.

## Commits
- 489b508 feat: livestatus.send_commands (one connection per command, CR/LF rejected)
- 8d31f04 feat: --demo argparse flag, `_demo_host_ips`, demo Phase 3 path, `demo` kwarg threaded through phases 3/4/7
- 8e37959 feat: Phase 4 ping default, `_fake_demo_hosts_up` (retry, warn with manual lq commands), run-wizard.sh arg passthrough
- 99096e2 docs: README and docs/WIZARD-OPERATION.md

## Verification (actually run)
- `uv run pytest -q`: 686 passed
- `uv run checkmk-wizard --help` lists `--demo`
- `bash -n deploy/run-wizard.sh` OK; `grep -c -- --demo`: README 3, WIZARD-OPERATION 5
- `uvx ruff check`: only 8 pre-existing errors (test_site.py, old lines in wizard.py/test_wizard.py); none from this work
- Not verified: live run against a real Checkmk/Livestatus, and `deploy/run-wizard.sh --demo` in the container.

## Deviations
- Worktree base was a07b023, reset to expected 54545af per the branch check.
- Rule 1: the rich warning uses `rich.markup.escape` for the manual command list so `[$(date +%s)]` is not parsed as markup.

## Self-Check: PASSED
