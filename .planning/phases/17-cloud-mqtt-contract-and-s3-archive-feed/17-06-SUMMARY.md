---
phase: 17-cloud-mqtt-contract-and-s3-archive-feed
plan: 06
subsystem: analytics
tags: [mqtt-v5, clickhouse, cloud-ingest, dedupe]
requires: [17-01]
provides:
  - "ANALYTICS_MODE=cloud-ingest history writer (analytics/ingest.py)"
  - "HISTORY_INGEST_TABLES allow-listed insert_history_rows"
affects: [17-09]
key-files:
  created: [analytics/ingest.py]
  modified: [analytics/config.py, analytics/history.py, analytics/service.py, tests/test_analytics_config.py, tests/test_analytics_ingest.py]
decisions:
  - "Dedupe is in-process only: bounded OrderedDict of 4096 (topic, event_id) pairs (FA-15)"
  - "Insert failure is logged, event_id not remembered, chunk still acked (FA-16)"
metrics:
  completed: 2026-10-14
---

# Phase 17 Plan 06: Cloud history ingest Summary

A `cloud-ingest` mode of the analytics container subscribes to one site's `app/<SEN>/<site>/history/+` chunks over MQTT v5 (persistent session, manual ack), validates rows against the poller's exact column schemas, dedupes by event_id and inserts into ClickHouse through a separate table allow-list.

## Tasks

| Task | Commit | Result |
|------|--------|--------|
| 1 Config + allow-listed insert | d5b46dc | config fields, `valid_sen`, `HISTORY_INGEST_TABLES`, `insert_history_rows`; `insert_rows` still refuses poller tables |
| 2 HistoryIngest + dispatch | 12c9780 | `analytics/ingest.py`, `main()` dispatch, exit 2 without valid SITE_SEN |

## Verification (observed)

- `uv run pytest tests -q -k analytics`: 354 passed.
- `uvx ruff check analytics`: clean after `--fix` (2 import-order/style fixes in ingest.py).
- `analytics/topics.py` unchanged; no `.publish(` in ingest.py; full-mode `INPUT_FILTERS` contain no history topic (tested).
- Not verified: a live broker/ClickHouse round trip (no live cloud broker available); the real paho client callbacks were exercised with a stubbed `connect`/`subscribe`/`ack`.

## Deviations from Plan

- Base reset: worktree started on an older commit than the required base; reset to a69d2bd per the branch check before work.
- [Rule 3] `tests/test_analytics_config.py` `ENV_NAMES` extended with the four new env names (the existing test asserts the exact set of env names read).
- `run_ingest` is imported as `from analytics import ingest` inside `_run_cloud_ingest` (lazy, keeps paho-free import path for full mode and allows monkeypatching).

## Known Stubs

None.

## Self-Check: PASSED
