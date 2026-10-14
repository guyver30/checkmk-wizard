---
phase: 17-cloud-mqtt-contract-and-s3-archive-feed
plan: 03
subsystem: poller
tags: [mqtt-v5, event_id, history, site_sen]
requires: ["17-01"]
provides:
  - Poller MQTT v5 clients with deterministic event_id user property on discrete publishes
  - PollerConfig.site_sen with startup validation (exit 2)
  - publish_history(): chunked QoS 1 history messages on sites/<site_id>/history/<table>
affects: [17-04, 17-06]
key-files:
  modified:
    - scripts/mqtt_poller.py
    - tests/test_mqtt_poller.py
key-decisions:
  - "event_id derives only from message identity (content hash, cycle epoch, command id), never publish-time clock"
  - "History publishing is on iff SITE_SEN is non-empty; MQTT publish runs before the ClickHouse write"
requirements-completed: [CLOUD-EVENTID, CLOUD-HISTORY, CLOUD-SEN]
completed: 2026-10-14
---

# Phase 17 Plan 03: Poller v5, event_id and history feed Summary

The poller now speaks MQTT v5, tags every discrete publish with a retry-stable `event_id` user property, validates `SITE_SEN` at startup, and publishes each cycle's history rows as 500-row QoS 1 chunks.

## What changed

- Both MQTT clients (`build_mqtt_client`, `reconcile_state`) use `protocol=mqtt.MQTTv5`.
- New helpers `_event_properties`, `content_event_id`, `history_event_id`, `_cycle_epoch`; `_publish_json` takes `event_id`.
- event_id on topology, services, events, incident status, admin faked, admin ack (`<id>-ack`), device tombstones (`<id>-removed-<epoch>`, including the stale sweep) and incident tombstones (`<id>-closed-<epoch>`). Device status, poller status, shutdown and raw legacy tombstones carry none.
- `PollerConfig.site_sen` (env `SITE_SEN`, stripped, in `__repr__`); `main()` returns 2 for values not matching `[1-9][0-9]{0,17}` and logs whether the cloud feed is on.
- `publish_history()` with `HISTORY_CHUNK_ROWS = 500`, called in `run_forever` and `--once` with the same timestamp and batch passed to `build_history_rows` and `write_history`.

## Verification (observed)

- `uv run pytest tests/test_mqtt_poller.py -q`: 393 passed.
- `uvx ruff check scripts/mqtt_poller.py tests/test_mqtt_poller.py`: all checks passed.
- grep: `protocol=mqtt.MQTTv5` x2, old constructor x0.
- Not verified: live broker round trip of the new publishes (covered for pass-through by 17-01 A1; no live poller run here).

## Deviations from Plan

1. [Rule 3 - Blocking] Worktree base differed from the expected base; reset to a69d2bd per the branch check.
2. Both tasks edit the same two files and were developed together; committed as a single atomic commit rather than two.
3. `publish_history` is defined just before `write_history` instead of after it (no behavioral difference).
4. An accidental `git stash` was run once; the entry was applied by SHA and dropped immediately, no work lost.

## Known Stubs

None.

## Self-Check: PASSED
