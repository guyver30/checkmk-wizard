# Quick 261004-lyz Summary

Removed the temporary pre-14.3 legacy namespace support: the poller's `lan/#` and `admin/#` ACL grants, its un-namespaced subscriptions/recording/admin_faked seed, the legacy smoke checks and the matching doc text. The kbt retired history/service_history sweep is kept.

## Commits
- 45a0a60 chore: drop legacy poller ACL grants and legacy smoke checks (ACL template, test_mosquitto_acl.py, smoke_test_broker.py)
- 90cc1db docs: fix wsreader grant comment in dashboard-react/src/lib/config.ts (orchestrator-approved addition, comment only)
- 748a6c9 refactor: remove pre-14.3 sweep and admin_faked seed from poller (mqtt_poller.py, test_mqtt_poller.py)
- 31bd5e4 docs: Podman doc describes the removal and the manual path for pre-14.3 stacks

## Changes
- ACL: poller has exactly `readwrite sites/@SITE_ID@/#`; header comment no longer contains the placeholder token (6 non-comment placeholder lines, 0 in comments).
- Poller: `legacy_retained_topics` renamed `retired_history_topics`; un-prefixed messages ignored; no `lan/#` / `admin/faked` subscriptions; admin_faked comes only from the site topic; `publish_raw_tombstone` refuses everything except this site's retired history/service_history topics.
- Smoke: `check_poller_legacy_write` and `check_wsreader_cannot_read_legacy` deleted; `_cleanup` no longer takes `seed`.
- Tests: nine legacy tests and `_LEGACY_SET` removed; ignore-unprefixed and refusal tests extended; subscriptions-all-site-prefixed assertion added.

## Verification (observed)
- `uv run pytest -q`: 856 passed.
- `tests/test_mosquitto_acl.py`: 15 passed; `sh -n deploy/render-mosquitto-acl.sh` ok.
- Rendered ACL for dmc_test: poller block prints exactly `topic readwrite sites/dmc_test/#`; `grep -c dmc_test` = 6.
- Repo grep for legacy references returns only the intended dated removal notes (Podman doc line 325, mqtt_poller.py comments at 3661 and 3804).
- Ruff: clean on changed files except one pre-existing PIE810 at tests/test_mqtt_poller.py:3500 (from quick kbt, not touched here; left alone).
- Not run: live broker smoke test and deployment (needs dmc-server).

## Deviations
- Worktree base was 49cfd94, not the required f40c65c; hard-reset to f40c65c per the branch check.
- Added the approved config.ts comment fix as its own commit.
- Rule 3: used `python` scripts via the scratchpad to apply multi-site edits; no behavior impact.

## Deployment notes (not performed)
On dmc-server: pull, then full `podman compose down && podman compose up -d` (never a single container), then re-run `scripts/smoke_test_broker.py --skip-restart ...` and expect no legacy checks.
