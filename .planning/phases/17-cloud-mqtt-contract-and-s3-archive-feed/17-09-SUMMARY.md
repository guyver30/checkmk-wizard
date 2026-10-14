---
phase: 17-cloud-mqtt-contract-and-s3-archive-feed
plan: 09
subsystem: analytics
tags: [mqtt-v5, event_id, analytics, archive]
requires: ["17-03", "17-06"]
provides:
  - Analytics MQTT v5 client with deterministic event_id user property on every discrete publish
key-files:
  modified:
    - analytics/publish.py
    - analytics/service.py
    - tests/test_analytics_publish.py
    - tests/test_analytics_service.py
requirements: [CLOUD-EVENTID]
metrics:
  completed: 2026-10-14
---

# Phase 17 Plan 09: Analytics v5 and event_id Summary

The analytics client now connects with MQTT v5 and every need status, forecast, narration and their tombstones carries a deterministic `event_id` user property in the poller's format.

## Accomplishments
- `analytics/publish.py`: `content_event_id` (same algorithm as the poller, pinned by a parity test), `_event_properties`, keyword-only `event_id` on `publish_retained_json` and `publish_tombstone`.
- `analytics/service.py`: `build_client` uses `protocol=mqtt.MQTTv5`; event ids at all publish sites: need `<need.id>-<hash>`, forecast `<host>-forecast-<hash>`, narration `<incident>-narration-<hash>`; tombstones `<need>-cleared-<epoch>`, `<host>-forecast-cleared-<epoch>`, `<incident>-narration-closed-<epoch>` (FA-17, epoch from the deciding cycle's `now`).
- Topics, payloads, QoS and retain unchanged; `analytics/ingest.py` untouched and has no `.publish(`.

## Commits
- db301ca feat(17-09): event_id user property support in analytics publish helpers
- e175a49 feat(17-09): MQTT v5 analytics client and event ids on every analytics publish

## Verification (observed)
- `uv run pytest tests/test_analytics_publish.py -q`: 11 passed
- `uv run pytest tests -q -k analytics`: 368 passed
- `uvx ruff check analytics tests/...`: all checks passed

## Deviations from Plan

**[Rule 3 - Blocking] Two existing triage tests wrapped `client.publish` with a 4-arg signature** that rejected the new `properties` kwarg. Updated `publish_and_drop` / `publish_and_change` in tests/test_analytics_service.py to accept and forward `properties`. No assertion changed.

**Worktree base:** the worktree HEAD was at 881dfb4; reset to the required base a968681 per the branch check before starting.

## Known Stubs
None.

## Self-Check: PASSED
