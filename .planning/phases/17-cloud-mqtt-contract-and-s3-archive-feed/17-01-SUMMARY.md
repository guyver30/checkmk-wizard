---
phase: 17-cloud-mqtt-contract-and-s3-archive-feed
plan: 01
subsystem: infra
tags: [mosquitto, mqtt, bridge, smoke-test]
requires: []
provides:
  - Live verdicts for bridge assumptions A1-A6, A8 (all required ones PASS)
  - scripts/smoke_test_bridge.py, a re-runnable two-broker bridge gate
affects: [17-02, 17-03, 17-08]
tech-stack:
  added: []
  patterns: [throwaway-container live smoke test, pure config builders unit-tested]
key-files:
  created:
    - scripts/smoke_test_bridge.py
    - tests/test_smoke_test_bridge.py
  modified:
    - .planning/phases/17-cloud-mqtt-contract-and-s3-archive-feed/17-RESEARCH.md
key-decisions:
  - "Phase gate passed: A1 and A2 verified live, later plans may rely on event_id user-property pass-through and tombstone forwarding"
requirements-completed: [CLOUD-BRIDGE, CLOUD-EVENTID, CLOUD-ACL]
duration: 25min
completed: 2026-10-14
---

# Phase 17 Plan 01: Bridge smoke test Summary

Two-broker Mosquitto 2.1.2 bridge smoke test proving prefix remap, event_id user-property pass-through, tombstones, include_dir, outage queueing and per-SEN ACLs live.

## Results (run 2026-10-14, docker, image digest sha256:38c0da4f2ef8...)

| Check | Verdict |
|-------|---------|
| REMAP (`sites/s1/x` -> `app/123/s1/x`) | PASS |
| A1 event_id user property unchanged | PASS |
| A2 retain flag carried + tombstone clears cloud copy | PASS |
| A4 include_dir loads bridge / empty dir tolerated | PASS / PASS |
| A5 paho 2.1 v5 API names | PASS |
| A6 5/5 QoS 1 messages delivered after WAN outage | PASS |
| A8 ACL-OWN / ACL-OTHER / SCOPE | PASS / PASS / PASS |
| A3 retained re-send on reconnect (informational) | Not re-sent (0 times) |

Not covered: TLS (`bridge_cafile`) was not exercised (plaintext on a throwaway network); A7 (ClickHouse dedup) is out of scope for this test.

## Task commits

1. Task 1, smoke test + unit tests: 9dceff4 (6 tests pass, ruff clean)
2. Task 2, live run and RESEARCH verdicts: committed as `docs(17-01)` (hash in git log; also includes a verdict-label tweak to the script)

## Deviations from Plan

- [Rule 3 - Blocking] Worktree HEAD base differed from the expected base commit; reset to 5da354f per the worktree branch check before starting.
- Minor: A3 verdict label prints "re-sent"/"not re-sent" instead of PASS/FAIL, since it is informational.

## Known Stubs

None.

## Self-Check: PASSED
