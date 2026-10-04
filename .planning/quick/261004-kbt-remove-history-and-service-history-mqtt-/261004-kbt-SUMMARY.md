---
phase: quick-261004-kbt
plan: 01
subsystem: poller, dashboard, docs
tags: [mqtt, poller, cleanup]
requirements: [PLR-05, PLR-06, PLR-12]
key-files:
  modified:
    - scripts/mqtt_poller.py
    - tests/test_mqtt_poller.py
    - scripts/smoke_test_poller.py
    - deploy/compose.yaml
    - dashboard-react/src/lib/topics.ts
    - dashboard-react/src/lib/types.ts
    - dashboard-react/src/lib/config.ts
    - dashboard-react/src/store/useAppStore.ts
    - docs/MQTT-CONTRACT-WALKTHROUGH.md
    - .planning/PROJECT.md
metrics:
  completed: 2026-10-04
---

# Quick 261004-kbt: Remove history and service_history MQTT topics

The poller no longer publishes per-device `history` / `service_history`; ClickHouse is the only transition history. Retained copies are cleared once through the existing legacy sweep, and the dashboard drops the dead subscriptions and store slices.

## Commits

- 77b99bb: poller, tests, smoke test, compose
- ad8bf59: dashboard
- fc2d27d: docs and PROJECT.md

## What changed

- Poller: removed the publishers, topic helpers, `append_bounded`, the two `PollerConfig` fields and env vars, and the `history` / `last_service_states` / `service_history` state slices. `lan/events/recent`, `status`, `services` and ClickHouse writes are unchanged.
- `reconcile_state` still subscribes the two wildcards and records retained non-empty history/service_history topics into `legacy_retained_topics`; the existing `allow_stale_sweep` loop clears them once. `publish_raw_tombstone` accepts only this site's 4-segment `history|service_history` topics under `sites/`. `publish_tombstone` still clears the four topics for one release.
- Dashboard: removed the two subscriptions, `HistoryEntry` / `ServiceHistoryEntry`, `HISTORY_MAX_ENTRIES`, and the `history` / `serviceHistory` slices. A status tombstone still removes the device and its services.
- Docs: removal note and updated tables in the walkthrough, Podman doc, dashboard README and PROJECT.md.

## Verification (actually run)

- `uv run pytest -q`: 864 passed.
- `uvx ruff check --no-cache scripts`: all checks passed.
- Dashboard `npm test`: 634 passed (45 files); `npm run typecheck`: clean; `npm run lint`: only pre-existing warnings, no errors.
- Task 1 and 2 grep checks: no remaining references outside the intentional legacy lines. Task 3 doc grep passed (261004-kbt present in walkthrough and PROJECT.md).
- Not run: live broker redeploy (out of scope; use full `podman compose down && up -d` if redeployed).

## Deviations from Plan

**1. [Rule 1 - Bug] Updated `dashboard-react/src/lib/topics.test.ts`**
- Not in the plan's file list; it asserted 8 and 10 subscribe topics and failed after the two were removed. Changed to 6 and 8. Included in commit ad8bf59.

**2. Walkthrough leftovers (minor)**
- Part 4 sizing lines (per-device `history` / `service_history` in the retained-topic count and the size table) were left as the plan only listed specific line ranges; they describe the earlier sizing analysis.

## Self-Check: PASSED

Commits 77b99bb, ad8bf59, fc2d27d exist on the worktree branch.
