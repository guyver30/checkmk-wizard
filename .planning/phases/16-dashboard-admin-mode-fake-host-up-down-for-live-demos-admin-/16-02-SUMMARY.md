---
phase: 16-dashboard-admin-mode-fake-host-up-down-for-live-demos-admin-
plan: 02
subsystem: poller
tags: [mqtt, livestatus, admin, worker-thread]
requires: [16-01]
provides:
  - AdminCommandWorker, AdminContext, query_faked_hosts, refresh_admin_faked, publish_admin_ack, publish_admin_faked, parse_admin_faked_payload, admin wiring in build_mqtt_client/reconcile_state/run_forever
affects: [16-04, 16-05, 16-08]
key-files:
  modified: [scripts/mqtt_poller.py, tests/test_mqtt_poller.py]
key-decisions:
  - "Faked signal (assumption A1): host active checks disabled AND (PING active checks disabled OR no PING service); ledger fallback when active_checks_enabled column is absent on hosts or services."
requirements-completed: [D-01, D-05, D-08, D-09, D-10, D-11, D-12]
completed: 2026-10-02
---

# Phase 16 Plan 02: Poller admin wiring Summary

The running poller now subscribes to `admin/cmd` on every connect, executes commands in a single daemon worker thread (bounded queue of 8, id dedupe over 64, retained deliveries dropped, Livestatus retries 3/5/10 s), acks each correlatable command on `admin/ack` (QoS 1, not retained), and keeps a retained, change-only `admin/faked` map current after every successful poll cycle.

## Commit
- feat(16-02): single commit for both tasks (same two files, tests written alongside) - hash recorded by the orchestrator merge.

## Verification (observed)
- `uv run pytest -q` (full suite): 792 passed.
- `uvx ruff check --no-cache scripts/mqtt_poller.py tests/test_mqtt_poller.py`: All checks passed.
- `uv run python scripts/mqtt_poller.py --help`: prints usage.
- `retain=True` count in scripts/mqtt_poller.py: 12 at HEAD -> 13 (only admin/faked added).
- NOT verified: behavior against a live Checkmk/Mosquitto (all I/O mocked).

## Deviations from Plan
- [Rule 3 - Blocking] Existing `test_run_forever_*` tests patch `threading.Event` globally, which breaks `threading.Thread()` construction once `run_forever` starts the admin worker. Added an autouse fixture in tests/test_mqtt_poller.py that no-ops `AdminCommandWorker.start/stop` for tests named `test_run_forever*`. Existing tests otherwise unchanged.
- [Process] Both tasks committed in one commit (same files); red-first not run separately.
- `parse_admin_faked_payload` validates host ids with `_HOST_ID_RE` (the same pattern commands accept) rather than `is_publishable_device_id`, which allows spaces/`!`. Also added extra tests (all-hosts-unknown, empty-body faked query, ledger-mode worker).

## Assumption for the Plan 08 live probe (A1)
The `active_checks_enabled` column on both `hosts` and `services` tables, and the faked signal (host check disabled AND PING disabled/absent), are unverified against a live site. `--check-columns` now prints `active_checks_enabled (admin, optional)` and `(admin, optional, services)`. If missing, the poller logs a warning and uses the ledger (source "ledger").

## Known Stubs
None.

## Self-Check: PASSED
