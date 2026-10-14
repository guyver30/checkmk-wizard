---
phase: 17-cloud-mqtt-contract-and-s3-archive-feed
plan: 04
subsystem: poller
tags: [throttle, heartbeat, status, staleness]
requires: ["17-03", "17-05"]
provides:
  - StatusMark, gauge_band, status_bands, status_discrete_signature, should_publish_status
  - PollerConfig.metrics_heartbeat_seconds (CLOUD_METRICS_HEARTBEAT_S, default 300, 0 = every cycle)
  - heartbeat_s key in lan/devices/{id}/status payload
key-files:
  modified:
    - scripts/mqtt_poller.py
    - tests/test_mqtt_poller.py
key-decisions:
  - "Checkmk staleness >= 3.0 is part of the discrete signature, so a frozen retained staleness cannot hide a stale host"
  - "A services outage (bands None) keeps the previous bands in the mark so band tracking survives it"
requirements-completed: [CLOUD-THROTTLE]
completed: 2026-10-14
---

# Phase 17 Plan 04: Status throttle Summary

Device status now publishes only on a discrete change, a gauge ok/warn/crit band crossing, or every `CLOUD_METRICS_HEARTBEAT_S` seconds (default 300); payloads carry `heartbeat_s`, and `lan/poller/status` still publishes every cycle.

## What changed

- Pure functions `gauge_band`, `status_bands`, `status_discrete_signature`, `should_publish_status` and frozen `StatusMark`; constants `DEFAULT_METRICS_HEARTBEAT_SECONDS`, `STATUS_STALE_THRESHOLD = 3.0` (mirrors dashboard STALENESS_FACTOR), `_STATUS_BAND_KEYS`.
- `PollerConfig.metrics_heartbeat_seconds` from `CLOUD_METRICS_HEARTBEAT_S` via `_env_int`; negatives clamped to 0 with a warning; in `__repr__`.
- `run_cycle` gains `monotonic_now`, gates `publish_device_status` per snapshot, stores marks in `PollerState.status_marks`, drops them in the removed loop and stale sweep. Services diffing is unchanged and unconditional.
- FA-11 consequence (accepted, D-09): on-prem gauges refresh every 5 minutes except on band crossings.

## Verification (observed)

- `uv run pytest tests/test_mqtt_poller.py -q`: 410 passed (17 new).
- `uvx ruff check scripts/mqtt_poller.py tests/test_mqtt_poller.py`: all checks passed.
- Not verified: live broker or dashboard behaviour with a throttled poller.

## Deviations from Plan

1. [Rule 3] Worktree HEAD was behind the expected base; reset to a968681 per the branch check.
2. Both tasks edit the same two files and were developed together; one atomic commit (3eb77b7) instead of two.
3. No existing tests needed changing: they run a single cycle or use fresh state, so the first-publish rule kept them green.
4. The removal test counts only non-empty status publishes because the tombstone is an empty payload on the same topic.

## Known Stubs

None.

## Self-Check: PASSED
