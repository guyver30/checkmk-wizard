---
phase: 16-dashboard-admin-mode-fake-host-up-down-for-live-demos-admin-
plan: 01
subsystem: poller
tags: [mqtt, livestatus, admin, cascade]
requires: []
provides:
  - admin topic constants, AdminCommand/AdminAction, parse_admin_command, plan_admin_actions, build_admin_commands, send_livestatus_commands
affects: [16-02]
key-files:
  modified: [scripts/mqtt_poller.py, tests/test_mqtt_poller.py]
key-decisions:
  - "D-02 clarified 2026-10-02 (user-confirmed): on DOWN of a managed host the unmanaged switch itself becomes UNREACH, but the cascade walk stops there and its children are untouched."
requirements-completed: [D-01, D-02, D-03, D-04, D-05, D-09, D-11, D-13]
duration: ~15min
completed: 2026-10-02
---

# Phase 16 Plan 01: Admin command core Summary

Pure admin core in the poller: validated command parsing, DOWN/UP cascade planner that stops at unmanaged switches, injection-safe Livestatus command builder (host + PING, disable-then-inject) and a one-connection-per-command sender.

## Tasks
Both tasks touch the same two files and were committed together as one commit (`git log` hash recorded by the orchestrator merge): feat(16-01). Not wired into run_forever (Plan 02).

## Verification (observed)
- `uv run pytest tests/test_mqtt_poller.py -q`: 341 passed.
- `uvx ruff check --no-cache scripts/mqtt_poller.py tests/test_mqtt_poller.py`: All checks passed.
- compute_incidents untouched; D-03 covered by three new tests (inferred card with two faked children, single child stays plain root, faked managed parent keeps children listed).

## Deviations from Plan
- [Process] Tasks 1 and 2 committed in a single commit rather than two, as both edit the same files and tests were written together. Red-first run was not performed separately; tests were written alongside the implementation and then run green.
- [Lint] Restructured the cascade loop condition and combined nested `with` statements to satisfy ruff (SIM114/SIM117).
- `parse_admin_command` returns `hosts=[]` for restore_all regardless of input (hosts ignored per contract), though a non-list truthy hosts still errors.

## Known Stubs
None.

## Self-Check: PASSED
