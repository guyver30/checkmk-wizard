# Quick 261001-tpy Summary

`deploy/reset-site.sh` now detects the site in the `checkmk_data` volume, asks the operator to confirm it by typed name, asks for a new name, writes it to `deploy/.env` before `compose up`, and aborts on Esc, Ctrl+C or EOF with nothing changed.

## Commits
- 0f69663: feat(261001-tpy): reset-site.sh detect/confirm/rename (script + test harness)
- docs commit: docs(261001-tpy): reset-site.sh flow in README and three docs

## Verification (run)
- `bash -n deploy/reset-site.sh`: clean
- shellcheck (uvx shellcheck-py) on script and harness: clean (two justified disables, SC2154 and SC2059)
- `test-reset-site.sh`: 16 cases, all PASS (Esc at both prompts, wrong confirm, EOF, keep, rename ordering, invalid then valid, backspace, uncomment, mismatch, --yes, --yes --site, bad --site, preflight failure, missing volume)
- `--help` shows `--site`; `deploy/compose.yaml` untouched
- Docs grep checks pass
- Not verified: real podman / live checkmk stack (all podman/curl calls were stubbed)

## Deviations
- Worktree was based on 8961412; reset to the specified 8037b9f per the branch check.
- Wrote the script with the Write tool rather than a heredoc (tooling restriction); no behavior difference.
