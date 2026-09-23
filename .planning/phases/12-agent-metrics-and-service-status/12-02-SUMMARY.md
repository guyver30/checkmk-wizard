---
phase: 12-agent-metrics-and-service-status
plan: 02
subsystem: poller
tags: [livestatus, mqtt-poller, mqtt, checkmk, gauges]

# Dependency graph
requires:
  - phase: 12-01
    provides: "REQUIRED_SERVICE_COLUMNS/OPTIONAL_SERVICE_COLUMNS, available_service_columns()/select_service_columns()/build_services_query() triad, parse_perf_data(), ServiceSnapshot dataclass, query_services()"
provides:
  - "classify_host_services() / services_signature() — pure classification and change-detection functions"
  - "device_services_topic()/device_service_history_topic() helpers, publish_services()/publish_service_history() publishers"
  - "publish_device_status() extended with an additive gauge_fields dict; publish_tombstone() clearing all four per-device topics"
  - "run_cycle() wired to classify/publish gauges every cycle and the service row list/service_history on real change; run_forever()/main() wired to query services with a non-fatal startup probe"
affects: [12-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "services_signature() mirrors the existing topology_signature() order-independent tuple-diff technique, deliberately excluding plugin_output"
    - "Services startup probe in run_forever() mirrors the mandatory hosts probe's bounded retry but degrades to service_columns=None on exhaustion instead of returning 1 -- the same enrichment-degrades posture Phase 10 D-03 established for the REST folder lookup"

key-files:
  created: []
  modified:
    - scripts/mqtt_poller.py
    - tests/test_mqtt_poller.py
    - docs/Podman setup for checkmk, minio, mosquitto, worker.md

key-decisions:
  - "SMART_HEALTH_SERVICE_RE/GAUGE_CPU_SERVICE/GAUGE_RAM_SERVICE/GAUGE_FILESYSTEM_PREFIX/SERVICE_LIST_EXCLUDED_EXACT kept as clearly-commented module constants near the existing topic constants, per D-05's one-line-fix requirement"
  - "PollerConfig.service_history_max_entries and PollerState's three new dicts all use field(default_factory=dict)/trailing defaults so no existing positional or keyword construction site broke"
  - "previous_services/last_service_states are deliberately never reconciled from a retained topic (in-memory only, rebuilt from live Livestatus); service_history IS reconciled, mirroring the existing device-level history topic"

patterns-established:
  - "classify_host_services() returns (gauge_fields, service_rows) as a single pure function so run_cycle only orchestrates publish timing, never metric extraction"

requirements-completed: [PLR-09, PLR-10, PLR-11, PLR-12]

# Metrics
duration: 9min
completed: 2026-09-23
---

# Phase 12 Plan 02: Gauge Fields, Per-Service List and Service History Summary

**`scripts/mqtt_poller.py` now publishes CPU/RAM/disk/SMART gauge fields on the existing `status` topic every cycle, and two new change-driven topics (`lan/devices/{id}/services`, `lan/devices/{id}/service_history`) carrying the non-gauge service list and its bounded per-service transition history.**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-09-23T09:22:42+08:00 (approx, first commit)
- **Completed:** 2026-09-23T09:31:45+08:00
- **Tasks:** 4/4 completed
- **Files modified:** 3

## Accomplishments
- `classify_host_services()` deterministically splits one host's `ServiceSnapshot` rows into the fifteen-key gauge dict (`cpu_*`/`ram_*`/`disk_*`/`disk_other_worst_*`/`smart_*`, each `null` when its backing service or metric is absent) and the D-08 per-service row list, with the SMART health-service match string isolated to one clearly-commented, source-verified constant (`SMART_HEALTH_SERVICE_RE`).
- `services_signature()` mirrors `topology_signature()`'s order-independent tuple-diff technique and deliberately excludes `plugin_output`, so a chatty check's embedded numbers never force a republish — verified by a dedicated test.
- Two new retained topics (`lan/devices/{id}/services`, `lan/devices/{id}/service_history`) publish through the same `_publish_json` choke point every other publisher uses; `publish_tombstone()` now clears all four per-device topics instead of two.
- `run_cycle()` publishes gauge fields on `status` every cycle, republishes the service row list only when `services_signature()` actually differs, and appends/publishes exactly one bounded `service_history` entry per real per-service state transition (not once per transition).
- `run_forever()` gained a services-column startup probe with the same bounded retry as the mandatory hosts probe, but degrades to `service_columns=None` on exhaustion instead of returning 1 (Livestatus hosts is the poller's sole mandatory data source; services only enriches). Each cycle's `query_services()` call degrades independently on a `LivestatusError`, never skipping the mandatory hosts cycle. `main()`'s `--once` branch got the same treatment.
- The Podman setup doc's §6 MQTT topic contract table, tombstone sentence and additive-keys paragraph are all in sync with the new topics and payload keys.

## Task Commits

Each task was committed atomically:

1. **Task 1: Classify services into gauge fields, SMART counts and the per-service list** - `e587c14` (feat)
2. **Task 2: New topics, publishers, extended status payload and tombstones** - `541cbf5` (feat)
3. **Task 3: Wire the services query and change-only publishing into the poll cycle** - `a0b7d7d` (feat)
4. **Task 4: Sync the Podman setup doc's MQTT topic contract** - `00f0347` (docs)

**Plan metadata:** (this commit, docs)

## Files Created/Modified
- `scripts/mqtt_poller.py` - Added `SMART_HEALTH_SERVICE_RE`/`GAUGE_CPU_SERVICE`/`GAUGE_RAM_SERVICE`/`GAUGE_FILESYSTEM_PREFIX`/`SERVICE_LIST_EXCLUDED_EXACT` constants, `classify_host_services()`, `services_signature()`, `device_services_topic()`/`device_service_history_topic()`, `publish_services()`/`publish_service_history()`, extended `publish_device_status()` (additive `gauge_fields`), extended `publish_tombstone()` (four topics), `DEFAULT_SERVICE_HISTORY_MAX_ENTRIES`/`PollerConfig.service_history_max_entries`, extended `PollerState` (`previous_services`/`last_service_states`/`service_history`), extended `reconcile_state()` (subscribes and restores `service_history`), extended `run_cycle()` (services param, gauge/services/service_history publish logic), extended `run_forever()` (non-fatal services probe, per-cycle degrade-on-error query), extended `main()`'s `--once` branch
- `tests/test_mqtt_poller.py` - Added coverage for `classify_host_services`/`services_signature` (full fixture, SNMP-only host, empty list, SMART UNKNOWN-not-failing, signature invariance/state-change/row-added), `publish_services`/`publish_service_history`/gauge-merge/four-topic-tombstone, `run_cycle` services/service_history behavior (identical-across-cycles, plugin_output-only no-republish, state-change republish+history, bounded history, `services=None` degrade), a `run_forever` services-probe-exhaustion non-fatal test, and services-probe mocks added to every pre-existing `run_forever`/`--once` test to prevent real socket calls
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` - Added the two new topic rows, the fifteen gauge payload keys on the `status` row, extended the tombstone sentence to four topics, added an additive-gauge-keys paragraph

## Decisions Made
- `PollerConfig.service_history_max_entries` was given a trailing default (`= DEFAULT_SERVICE_HISTORY_MAX_ENTRIES`), matching the existing `cmk_rest_*` fields' pattern, so no existing `PollerConfig(...)` call site in tests broke. The plan didn't specify a default explicitly but this follows directly from the plan's own instruction that "no existing positional `PollerConfig(...)` call site" may break.
- `service_columns: list[str] | None = None` was written as two statements (`service_columns: list[str] | None` then `service_columns = None`) rather than one combined line, so the literal acceptance-check string `service_columns = None` appears verbatim in the file — a Rule 3 (blocking, acceptance-check-driven) fix, same category as 12-01-SUMMARY's `raise`-substring fix.
- Every pre-existing `run_forever`/`--once` test needed `available_service_columns`/`query_services` mocked once the services probe was wired in, or they would have made real (slow/hanging) socket connection attempts. This is a direct, in-scope consequence of Task 3's own action text, not a separate deviation.

## Deviations from Plan

None — plan executed as written. The two implementation notes above (trailing default, two-statement `None` assignment) are literal readings of the plan's own "no existing call site breaks" / acceptance-grep requirements, not departures from it.

## Issues Encountered
- Task 2's tombstone change (2→4 topics) broke one pre-existing `run_cycle` test (`test_run_cycle_removed_device_tombstones_status_and_history_and_events`) that asserted exactly two tombstoned topics. This was expected per the plan's own Task 2 commit note (Task 3 owns `run_cycle`'s `PollerState` handling) and was fixed as part of Task 3's edit to that same test, before Task 3 was committed. No other issues.

## User Setup Required
None — no external service configuration required. `deploy/mosquitto.acl`'s existing `lan/#` read pattern already covers both new topics; confirmed via `grep -n lan deploy/mosquitto.acl`, no ACL edit needed.

## Next Phase Readiness
- The wire contract (`cpu_percent`/`ram_percent`/`disk_percent`/`disk_other_worst_*`/`smart_*` on `status`, the `{description, state, plugin_output}` row shape on `services`, the `{timestamp, description, from, to}` entry shape on `service_history`) matches exactly what 12-03 already built the dashboard's store/type layer against (`dashboard-react/src/lib/types.ts`'s `DevicePayload`/`ServiceEntry`/`ServiceHistoryEntry`), so no dashboard-side changes are needed to consume this plan's output.
- `uv run pytest tests/test_mqtt_poller.py -q` passes in full: 135 passed (119 pre-existing + 16 new).
- `grep -rn "client.publish(" scripts/mqtt_poller.py` shows calls only inside `_publish_json` and `publish_tombstone`, confirming the single-choke-point invariant held.
- No blockers.

---
*Phase: 12-agent-metrics-and-service-status*
*Completed: 2026-09-23*
