---
phase: 16
plan: 08
status: complete
type: live-uat
gaps: 4
---
# Plan 16-08 Summary: live verification of admin mode

Deploy host, site `dmc_test`, wizard `--demo` hosts. The plan's own done condition ("approved, or every failure captured as a gap") is met: the failures are in `16-UAT-GAPS.md` and are being fixed in gap-closure plans.

## Task 1: automated gate
Python 792 passed; dashboard 610 passed, typecheck, lint (0 errors) and build OK; `bash -n deploy/init-env.sh` OK; wsadmin ACL has one write grant (admin/cmd). `ruff` reports 7 errors, all in tests/test_site.py and tests/test_wizard.py and identical at the pre-phase commit 6ada1ee (not caused by this phase).

## Task 2: live UAT (user-run)
| Step | Result |
|---|---|
| 2 `--check-columns` (A1) | PASS: `active_checks_enabled` present for hosts and services |
| 3 `smoke_test_broker.py --skip-restart` | PASS: 7/7 (poller_publish, ws_subscribe, ws_publish_denied, wsadmin_publish_admin_cmd, wsadmin_publish_lan_denied, wsadmin_reads_lan, wsreader_cannot_read_admin); restart check skipped |
| 4 `/admin-config.json`, `/config.json` | PASS |
| 5 admin chrome only with `?admin=1`; Edit topology disabled | PASS |
| 6 ctrl+click selects, no navigation; plain click opens details (A2) | PASS |
| 7 Set DOWN / Set UP, one and several hosts, dialog lists only selected, FAKED badge | PASS (Checkmk GUI text and banner count not explicitly confirmed) |
| 8 managed switch cascade (A4) | PASS |
| 9 unmanaged switch children, combined inferred card, split on restore (D-03) | PASS |
| 10 folder selection (OQ3) | PASS |
| 11 persistence across full down/up (D-10) | PASS |
| 12 Restore all | FAIL: hosts go CRITICAL (gap 3) |
| 13 demo hosts not counted as faked | SKIPPED by user |
| 14 poller-down timeout | SKIPPED by user |

OQ1 (wsadmin reads lan/#): confirmed by smoke check. OQ2 (unmanaged switch UNREACH in a cascade): confirmed by step 8/9 behavior. OQ3: confirmed by step 10.

## Gaps found (details in 16-UAT-GAPS.md)
1. Plain click should select in admin mode (ctrl+click adds); no host details.
2. Add Select all.
3. Restore (and the reverse cascade after Set UP on a switch) must return demo hosts to the demo baseline: host UP, PING OK, PING left disabled. Today it re-enables the PING check, which pings a non-existent IP and goes CRITICAL.
4. Faked hosts go stale after about 3 minutes (live: checks-disabled hosts staleness 2.9 to 11.2, checks-enabled 0.83). The poller must re-inject faked state at least every 60 s.

## Deploy findings (outside Phase 16)
- Fresh `podman compose up -d` left clickhouse and grafana in Created ("depends on container ... not found in input list"); fixed in quick task 261002-liq (removed minio-init depends_on), not yet confirmed on the host.
- The minio_data volume written by the old root-run image needed `podman unshare chown` or recreation.
- `.venv` in the deploy checkout was unreadable by uv; the smoke test ran with `uv run --no-project` from outside the repo.
