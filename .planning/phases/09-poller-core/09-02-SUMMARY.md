---
phase: 09-poller-core
plan: 02
subsystem: infra
tags: [mqtt, livestatus, poller, checkmk, paho-mqtt, python]

# Dependency graph
requires:
  - phase: 09-poller-core
    plan: 01
    provides: "scripts/mqtt_poller.py's PollerConfig, DeviceSnapshot, pure state/topology helpers, and the Livestatus query layer"
provides:
  - "scripts/mqtt_poller.py: complete, runnable poller daemon (build_mqtt_client, five publish helpers, reconcile_state, run_cycle, run_forever, main, CLI entry point)"
  - "Fixed MQTT topic/payload contract for lan/devices/{id}/status, lan/devices/topology, lan/devices/{id}/history, lan/events/recent, lan/poller/status"
affects: [09-03, 09-04, 11-dashboard]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single-topic startup reconciliation: subscribe once to lan/devices/topology (not a per-device wildcard) so exactly one retained message (or none) arrives deterministically after SUBACK"
    - "Will-less short-lived reconciliation client, distinct from the long-lived publisher client, so the reconciliation client's own disconnect can never publish a false offline poller status (T-09-06)"
    - "Every publish funnels through one _publish_json choke point (mirrors CheckmkClient._request), degrading a broker hiccup to one dropped publish instead of killing the poll loop"
    - "No 'first cycle' suppression flag: state.last_status starts empty on both cold start and warm restart, so a false transition on cycle 1 is structurally impossible rather than guarded by a flag"

key-files:
  created: []
  modified:
    - scripts/mqtt_poller.py
    - tests/test_mqtt_poller.py

key-decisions:
  - "Reused parse_events_payload (generic 'parse a bounded JSON array, degrade to [] on empty/malformed' parser) for per-device history payloads during reconciliation too, rather than adding a third near-identical parser -- both retained topics share the exact same bounded-array-of-dicts shape"
  - "Added a DEFAULT_LIVESTATUS_TIMEOUT_SECONDS=10.0 module constant (matching src/checkmk_wizard/livestatus.py's existing hardcoded default) for the poller's own Livestatus socket calls in run_forever/main, since D-04 scopes env-var configuration to the settings it explicitly names and this wasn't one of them"
  - "Left MQTT connect() failures at startup (in both build_mqtt_client and reconcile_state) unhandled/propagating, rather than adding a narrow except around them: the new poller compose service is provisioned with restart: unless-stopped (D-02) specifically for automatic crash recovery, so a total broker-unavailable-at-startup condition crash-restarting is the sanctioned recovery path, not a bug -- narrow exception handling in this module is reserved for the per-cycle Livestatus/publish failures the phase's own success criteria call out (T-09-03, T-09-05), not for total-outage-at-startup scenarios"

requirements-completed: [PLR-02, PLR-03, PLR-04, PLR-05, PLR-06, PLR-07]

# Metrics
duration: ~50min
completed: 2026-09-06
---

# Phase 9 Plan 2: Poller MQTT Wiring Summary

**`scripts/mqtt_poller.py` is now a complete, runnable poller daemon: birth/LWT liveness on `lan/poller/status`, five publish helpers at the QoS/retain levels the fixed payload contract specifies, single-topic startup reconciliation from Mosquitto's own retained store (no poller-owned state file), and a poll cycle that tombstones removed devices and republishes topology/history/events only on genuine change — 62 new unit tests against a mocked MQTT client, no live broker required.**

## Performance

- **Duration:** ~50 min
- **Completed:** 2026-09-06
- **Tasks:** 2/2 completed
- **Files modified:** 2 (`scripts/mqtt_poller.py`, `tests/test_mqtt_poller.py`) — no new files

## Accomplishments

- `build_mqtt_client` configures the LWT before connecting (paho-mqtt documents this ordering as load-bearing), publishes a birth message from `on_connect` (VERSION2 five-arg signature), and delegates reconnect/backoff entirely to `reconnect_delay_set(min_delay=1, max_delay=120)` + `loop_start()` — no hand-rolled retry loop
- Five publish helpers (`publish_device_status`, `publish_topology`, `publish_history`, `publish_events`, `publish_tombstone`) plus `publish_poller_status`, all funneled through one `_publish_json` choke point that catches `(TimeoutError, OSError)` so a transient broker hiccup degrades exactly one publish rather than the whole poll loop (T-09-03)
- `publish_device_status` uses QoS 0 (self-correcting every cycle); every change-triggered topic uses QoS 1 — matches RESEARCH.md's resolved "continuous = QoS 0, change-triggered = QoS 1" rule, documented in-line so future edits don't drift
- `publish_tombstone` clears both a removed device's status and history topics with `payload=None, retain=True, qos=1` and `wait_for_publish(timeout=5)`, the same mechanism `scripts/smoke_test_broker.py::_cleanup` already proved against the real deployed broker
- `reconcile_state` rebuilds `PollerState.previous_nodes` from the broker's single retained `lan/devices/topology` topic (not a wildcard subscription, not a local file) using a will-less short-lived client, satisfying PLR-02's "no persisted state of its own" with Mosquitto's own `persistence true` as the durable store
- `run_cycle` republishes every device's status every cycle from live data, tombstones ids that vanished from Livestatus (with a `removed` event carrying the device's last known state), appends `added`/`state_change` events and bounded history entries only on genuine change, and republishes `lan/devices/topology` only when `topology_signature` differs from the previous cycle
- `run_forever` installs `SIGTERM`/`SIGINT` handlers for a graceful stop that publishes the same `{"status": "offline"}` value the LWT would have left, so a `podman compose stop poller` and a `kill -9` look identical to a consuming dashboard; a per-cycle `LivestatusError` is caught, logged, and skipped — the poll interval itself is the retry backoff
- `main()` adds `--check-columns` (probe the live site, print present/missing for every required/optional column) and `--once` (run exactly one cycle) as operator diagnostics; runtime configuration stays env-var-only per D-04

## Task Commits

Each task was committed atomically:

1. **Task 1: MQTT client lifecycle and the five publish helpers** — `6da4389` (feat)
2. **Task 2: Startup reconciliation, poll cycle, and main entry point** — `c101642` (feat)

## Files Created/Modified

- `scripts/mqtt_poller.py` — Adds `utc_now_iso`, `build_mqtt_client`, `_publish_json`, `publish_device_status`, `publish_topology`, `publish_history`, `publish_events`, `publish_tombstone`, `publish_poller_status`, `PollerState`, `parse_topology_payload`, `parse_events_payload`, `reconcile_state`, `run_cycle`, `run_forever`, `main`; ends with `if __name__ == "__main__": sys.exit(main())`
- `tests/test_mqtt_poller.py` — Adds 34 tests covering the MQTT client lifecycle, all five publish helpers, reconciliation, `run_cycle`'s full diff/tombstone/history/events/topology logic, truncation bounds, and `run_forever`'s survival of a `LivestatusError` (62 tests total in the file, 284 in the full suite)

## Decisions Made

- Reused `parse_events_payload` (a generic "bounded JSON array of dicts, degrade to `[]` on empty/malformed" parser) for per-device history reconciliation as well as `lan/events/recent` — both retained topics share the exact same shape contract, so a third near-identical parser would have been pure duplication.
- Added `DEFAULT_LIVESTATUS_TIMEOUT_SECONDS = 10.0` as a module constant (matching `src/checkmk_wizard/livestatus.py`'s existing hardcoded `10`) for the poller's own per-cycle Livestatus socket calls in `run_forever`/`main`. D-04 scopes environment-variable configuration to the settings it explicitly names (poll interval, MQTT host/port/credentials, Livestatus host/port); this timeout wasn't one of them, so it stays a code constant rather than growing the env-var surface unprompted.
- Left `client.connect()` failures at startup (in both `build_mqtt_client` and `reconcile_state`) unhandled and propagating, rather than adding a narrow `except` around them. The new `poller` compose service carries `restart: unless-stopped` (D-02) specifically for automatic crash recovery — a total-broker-unavailable-at-startup condition crash-restarting via that policy is the sanctioned recovery path, not a bug. This module's narrow-exception-handling convention is reserved for the per-cycle failures the phase's own threat model calls out (`T-09-03` publish/Livestatus hiccups, `T-09-05` malformed retained payloads), not for "the broker was never up at all" at process start.

## Deviations from Plan

None — plan executed exactly as written. `run_cycle`'s event-list truncation uses a direct list-slice (`(state.events + events_this_cycle)[-config.events_max_entries:]`) rather than looping calls to `append_bounded` for multiple events in one cycle; this is the same bounded-list-replace semantic `append_bounded` implements, just applied to a batch rather than one entry at a time, and was left to Claude's discretion per the plan's own "exact JSON payload field layout... left to discretion" framing.

## Issues Encountered

- Ran lint via `uvx ruff check` rather than the plan's literal `uv run ruff check`, for the same environment reason plan 09-01 already documented: `ruff` is not declared in `pyproject.toml`'s `dependency-groups.dev`, so `uv run ruff` fails to spawn (`Failed to spawn: ruff`). `uvx ruff check` is this repo's own documented convention for one-off tools and reproduces the identical result.
- The repo-wide `uvx ruff check scripts/ src/ tests/` command (from the plan's overall `<verification>` block) surfaces the same 7 pre-existing findings already logged in `.planning/phases/09-poller-core/deferred-items.md` by plan 09-01 (`src/checkmk_wizard/wizard.py:676` B023, `tests/test_site.py` SIM117 x4, `tests/test_wizard.py:236` RET501/PLR1711) — confirmed none are in `scripts/mqtt_poller.py` or `tests/test_mqtt_poller.py`. Not fixed, per the deviation rules' scope boundary; no update to `deferred-items.md` needed since the findings are identical to what's already recorded.

## User Setup Required

None — no external service configuration required. This plan's verification runs entirely against a mocked `paho.mqtt.client.Client`; no live broker or Checkmk site was reachable or needed. Live smoke-testing of the full daemon against a real Mosquitto/Checkmk deployment (reconciliation timing, tombstone-on-restart, actual broker round-trip) is deferred to a later plan's live verification pass, consistent with this project's established "live-verify against a real deployment host" convention (`scripts/smoke_test_broker.py` precedent).

## Next Phase Readiness

- `scripts/mqtt_poller.py` is now a complete, standalone, runnable daemon satisfying PLR-02 through PLR-07: `uv run python scripts/mqtt_poller.py` starts the full reconcile-then-poll-forever loop; `--check-columns` and `--once` provide manual/CI-friendly diagnostics without needing to run the full loop.
- The MQTT topic/payload contract (topics, QoS, retain flags, and exact JSON field names for status/topology/history/events/poller-status) is now fixed in working, tested code — this is the interface Phase 11's dashboard will consume verbatim.
- Not yet done in this plan (explicitly out of scope, per the plan's own boundary): wiring a `poller` service into `deploy/compose.yaml`, and any live smoke-testing against a real Mosquitto/Checkmk deployment. Both remain for a subsequent plan in this phase.
- The Livestatus column names (`parents`, `tags`, `filename`) used by `query_devices` (built in 09-01) remain unverified against a live Checkmk site — RESEARCH.md Open Question 1 still recommends a live `GET columns` check before this phase is considered fully done end-to-end.

## Self-Check: PASSED

- FOUND: `scripts/mqtt_poller.py`
- FOUND: `tests/test_mqtt_poller.py`
- FOUND commit: `6da4389`
- FOUND commit: `c101642`
- Verified: `uv run pytest -q` → 284 passed
- Verified: `uvx ruff check scripts/mqtt_poller.py tests/test_mqtt_poller.py` → All checks passed!
- Verified: `uv run python scripts/mqtt_poller.py --help` → exit 0, lists `--check-columns` and `--once`
- Verified: `LIVESTATUS_HOST=127.0.0.1 LIVESTATUS_PORT=1 uv run python scripts/mqtt_poller.py --check-columns` → exit 1, clean connection-error message, no traceback, no credentials

---
*Phase: 09-poller-core*
*Completed: 2026-09-06*
