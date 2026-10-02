---
phase: 16-dashboard-admin-mode-fake-host-up-down-for-live-demos-admin-
plan: 09
subsystem: poller
tags: [admin, livestatus, gap-closure]
requires: []
provides:
  - Demo-baseline restore (ENABLE_HOST_CHECK + host UP + PING OK, PING left disabled)
  - Faked-host keepalive every 30 s on the admin worker thread
key-files:
  modified:
    - scripts/mqtt_poller.py
    - tests/test_mqtt_poller.py
decisions:
  - "Restore never sends ENABLE_SVC_CHECK (user decision: always demo baseline)"
  - "Keepalive sends only PROCESS_* commands, never DISABLE/ENABLE"
metrics:
  completed: 2026-10-02
---

# Phase 16 Plan 09: Restore baseline and fake keepalive Summary

Restore now returns hosts to the wizard --demo baseline (UAT gaps 3/3b), and the admin worker re-injects faked hosts' state every 30 s so they no longer go STALE (gap 4).

## What changed
- `build_admin_commands` restore: `ENABLE_HOST_CHECK`, then `PROCESS_HOST_CHECK_RESULT` 0 and `PROCESS_SERVICE_CHECK_RESULT` PING 0 with one shared OK text; no `ENABLE_SVC_CHECK`, no forced/scheduled checks. Shared helpers `_admin_up_output`, `_admin_fake_result`, `_admin_guard`. The reverse cascade needed no change (it already emits `restore`).
- `query_faked_hosts` skips rows whose host check is enabled (row[2] != 0).
- `ADMIN_FAKE_KEEPALIVE_INTERVAL_SECONDS = 30`, `build_admin_keepalive_commands`, `AdminCommandWorker.maybe_keepalive` (new `clock_fn`/`query_fn` kwargs), invoked from `_run` each iteration via a broad-catch wrapper. No I/O when nothing is faked; non-ledger mode re-queries the faked set before sending; single send, no retries.

## Verification (observed)
- `uv run pytest tests/test_mqtt_poller.py -q`: 386 passed.
- `uvx ruff check scripts/mqtt_poller.py`: All checks passed.
- `grep 'f"ENABLE_SVC_CHECK' scripts/mqtt_poller.py`: no matches.
- Not verified: live Checkmk behaviour (needs the live site); only unit-level.

## Deviations from Plan
- Tasks 1 and 2 touch the same functions and test file and share helpers, so they were committed together in one commit rather than two. Otherwise executed as written.
- Worktree HEAD was not at the expected base at start; reset to ce74c83 per the branch check.

## Known Stubs
None.

## Self-Check: PASSED
