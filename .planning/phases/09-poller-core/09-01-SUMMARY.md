---
phase: 09-poller-core
plan: 01
subsystem: infra
tags: [livestatus, mqtt, poller, checkmk, dataclasses, python]

# Dependency graph
requires:
  - phase: 08-broker-infrastructure-hardening
    provides: Mosquitto broker with persistence, `poller` user credentials, retained-message semantics proven live
provides:
  - "scripts/mqtt_poller.py: PollerConfig (env-driven config), DeviceSnapshot record type"
  - "Pure helpers: compute_overall_state, is_publishable_device_id, append_bounded, topology_nodes, topology_signature, derive_folder, extract_device_type"
  - "Livestatus query layer: LivestatusError, available_host_columns, select_host_columns, build_hosts_query, query_devices — one GET hosts round trip -> typed DeviceSnapshot list"
affects: [09-02-mqtt-publisher, 09-03, 09-04, 11-dashboard]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Standalone scripts/ module with no checkmk_wizard import (D-01 portability)"
    - "One choke-point network function (_livestatus_request) normalizing all Livestatus failures into a single typed exception, mirroring CheckmkClient._request"
    - "Module-level `_logger = logging.getLogger(__name__)` instead of root-logger `logging.warning(...)` calls (ruff LOG015)"
    - "importlib spec_from_file_location + sys.modules registration to unit-test a scripts/*.py module that isn't part of an importable package"

key-files:
  created:
    - scripts/mqtt_poller.py
    - tests/test_mqtt_poller.py
    - .planning/phases/09-poller-core/deferred-items.md
  modified: []

key-decisions:
  - "Used `uvx ruff check` instead of the plan's literal `uv run ruff check` — ruff is not a project dependency in this repo (not in pyproject.toml dependency-groups), only available as an ephemeral uv tool, consistent with this environment's own CLAUDE.md guidance for one-off tools"
  - "Did not import `datetime`, `sys`, or `paho.mqtt.client` in this plan's module even though the plan's action text lists them as forward-looking imports for Plan 09-02 — those imports were unused in this plan's code and would fail the plan's own `ruff check` acceptance criterion (F401 unused-import); they will be added in 09-02 when actually used"
  - "Added `sys.modules['mqtt_poller'] = poller` before `exec_module()` in the test file — required to avoid a genuine CPython 3.11 `dataclasses` + `from __future__ import annotations` crash when loading a `@dataclass`-containing module via `importlib.util.spec_from_file_location` without registering it first"

patterns-established:
  - "Livestatus column availability is verified live via GET columns before building the hosts query, degrading missing optional columns to a logged safe default rather than a hard failure"
  - "Every device id crossing into an MQTT topic string is validated by is_publishable_device_id first (T-09-01)"

requirements-completed: [PLR-01, PLR-03, PLR-08]

# Metrics
duration: ~35min
completed: 2026-09-06
---

# Phase 9 Plan 1: Poller Core Foundation Summary

**Standalone `scripts/mqtt_poller.py` with env-driven `PollerConfig`, worst-of status aggregation, topic-injection guards, and a Livestatus `GET hosts` query layer that parses one JSON round trip into typed `DeviceSnapshot` records — 28 unit tests, no live broker or Checkmk site required.**

## Performance

- **Duration:** ~35 min (start time not captured at session start; estimated from session context)
- **Completed:** 2026-09-06T10:18:45Z
- **Tasks:** 2/2 completed
- **Files modified:** 2 created (`scripts/mqtt_poller.py`, `tests/test_mqtt_poller.py`), plus 1 deviation-tracking file (`deferred-items.md`)

## Accomplishments
- `PollerConfig.from_env()` reads every poller runtime setting from environment variables per D-04, with numeric env-var parsing that falls back to documented defaults (with a warning) instead of crash-looping on a typo, and a `__repr__` that never renders the raw MQTT password (T-09-02)
- `compute_overall_state` implements the D-08 worst-of aggregation exactly: host DOWN/UNREACHABLE wins outright, otherwise the worst service state maps to OK/WARN/CRIT/UNKNOWN
- `is_publishable_device_id` closes the T-09-01 MQTT topic-injection gap — any host name containing `+`, `#`, `/`, or ASCII control characters is rejected before it can be interpolated into a topic string
- A single `GET hosts` Livestatus round trip (`query_devices`, `build_hosts_query`) parses into `DeviceSnapshot` records carrying `in_downtime`/`acknowledged` (D-07), `parents`, `device_type`, and `folder` — with `available_host_columns`/`select_host_columns` resolving which optional columns the live site actually exposes and degrading gracefully when one is missing
- 28 unit tests cover every pure helper and the mocked-socket Livestatus layer; the module imports cleanly with no live broker, Checkmk site, or environment variables present

## Task Commits

Each task was committed atomically:

1. **Task 1: Poller module foundation — config, topic guards, state/topology/bounded-log helpers** - `d636c06` (feat)
2. **Task 2: Livestatus query layer — column probe, single GET hosts round trip, DeviceSnapshot parsing** - `6c41882` (feat)

## Files Created/Modified
- `scripts/mqtt_poller.py` - Standalone poller module: `PollerConfig`, `DeviceSnapshot`, pure state/topology/bounded-log helpers, and the Livestatus query layer (`LivestatusError`, `_livestatus_request`, `available_host_columns`, `select_host_columns`, `build_hosts_query`, `query_devices`)
- `tests/test_mqtt_poller.py` - 28 unit tests covering every pure helper and the Livestatus layer against a mocked `socket.create_connection`
- `.planning/phases/09-poller-core/deferred-items.md` - Logs 7 pre-existing, out-of-scope ruff findings discovered in unrelated files while running the plan's repo-wide lint check

## Decisions Made
- Ran lint via `uvx ruff check` rather than the plan's literal `uv run ruff check`: ruff is not declared in `pyproject.toml`'s `dependency-groups.dev`, so `uv run ruff` fails to spawn in this environment (`Failed to spawn: ruff`). `uvx ruff check` is this repo's own documented convention for one-off tools (per this environment's CLAUDE.md: "Run a one-off tool without adding it to the project: `uvx ruff check`") and is what actually produces a meaningful, comparable lint result here. Verified the exact same result would occur for the plan's own literal command by confirming `ruff` is absent from `uv.lock`.
- Deferred importing `datetime`, `sys`, and `paho.mqtt.client` in this plan even though the plan's `<action>` text names them as forward-looking imports for Plan 09-02's use: with this repo's actual effective ruff rule set (verified empirically — see Issues Encountered), an unused import is a hard `F401` failure, which would make the plan's own `ruff check` acceptance criterion fail. Only imports this plan's code actually uses (`json`, `logging`, `os`, `socket`, `dataclasses`) are present; the three forward-looking imports will be added in 09-02 when the MQTT client and timestamp formatting are actually wired up.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `uv run ruff check` does not work in this environment; used `uvx ruff check` instead**
- **Found during:** Task 1 verification
- **Issue:** The plan's `<verify>` command is `uv run pytest ... && uv run ruff check ...`. `ruff` is not listed in `pyproject.toml`'s `dependency-groups`, so `uv run ruff` fails with `Failed to spawn: ruff` — this is an environment/tooling gap, not a code defect.
- **Fix:** Ran `uvx ruff check scripts/mqtt_poller.py tests/test_mqtt_poller.py` instead, which is this environment's own documented pattern for one-off tools and produces the equivalent lint result against the same ruff version this repo's `.ruff_cache` evidence already confirms is in use.
- **Files modified:** None (verification-only change)
- **Verification:** `uvx ruff check scripts/mqtt_poller.py tests/test_mqtt_poller.py` → `All checks passed!`
- **Committed in:** N/A (verification step, no code change)

**2. [Rule 1 - Bug] Fixed two real ruff findings the plan's literal import list would have produced (LOG015, SIM103)**
- **Found during:** Task 1 verification, after first draft of `scripts/mqtt_poller.py`
- **Issue:** `logging.warning(...)` calls used the root logger directly (LOG015: "Use own logger instead"), and `is_publishable_device_id` had two sequential `if ...: return False` blocks that could collapse into one `return` (SIM103) — this repo's actual effective ruff rule set (verified empirically: `uvx ruff check` against 0.16.6, matching a `.ruff_cache` entry this task's own run created) flags both.
- **Fix:** Added `_logger = logging.getLogger(__name__)` and routed every warning through it; simplified `is_publishable_device_id`'s final two checks into a single `return not any(...)`.
- **Files modified:** `scripts/mqtt_poller.py`
- **Verification:** `uvx ruff check scripts/mqtt_poller.py tests/test_mqtt_poller.py` → `All checks passed!`; `uv run pytest tests/test_mqtt_poller.py -q` → 28 passed
- **Committed in:** `d636c06` (Task 1 commit; the logger/simplification were folded into the initial implementation before committing)

**3. [Rule 3 - Blocking] `sys.modules` registration required before `exec_module()` for a `@dataclass` module loaded via `importlib`**
- **Found during:** Task 1, first test run
- **Issue:** Loading `scripts/mqtt_poller.py` via `importlib.util.spec_from_file_location` + `module_from_spec` + `exec_module` (exactly as the plan's `<action>` and the plan's own `<acceptance_criteria>` verification snippet both specify) crashes with `AttributeError: 'NoneType' object has no attribute '__dict__'` inside CPython 3.11's `dataclasses._is_type`, because `@dataclass` combined with `from __future__ import annotations` looks up `sys.modules[cls.__module__]` while processing fields, and that lookup returns `None` if the module was never registered in `sys.modules`. Reproduced with a minimal 2-field dataclass file, confirming this is a genuine CPython 3.11 stdlib interaction, not a defect in this plan's code.
- **Fix:** Added `sys.modules["mqtt_poller"] = poller` immediately before `_SPEC.loader.exec_module(poller)` in `tests/test_mqtt_poller.py`. This is the standard, minimal fix for this well-known Python limitation.
- **Files modified:** `tests/test_mqtt_poller.py`
- **Verification:** `uv run pytest tests/test_mqtt_poller.py -q` → 28 passed (previously errored at collection)
- **Committed in:** `d636c06` (Task 1 commit)

---

**Total deviations:** 3 auto-fixed (2 blocking/tooling, 1 bug/lint)
**Impact on plan:** All three are tooling/environment corrections needed to make the plan's own verification steps actually run; no scope creep, no behavior changes beyond what the plan specified. See "Issues Encountered" for the one acceptance-criterion the plan's literal wording cannot satisfy in this environment regardless of implementation.

## Issues Encountered

- The plan's `<acceptance_criteria>` for Task 1 includes a literal command: `uv run python -c "...spec_from_file_location(...); s.loader.exec_module(m); print(repr(m.PollerConfig.from_env()))"`. Run exactly as written, this fails with the same CPython 3.11 `dataclasses`/`sys.modules` AttributeError described in Deviation 3 above, because that literal command does not register the module in `sys.modules` before `exec_module()`. This is not fixable from inside `scripts/mqtt_poller.py` — the crash reproduces with any `@dataclass` + `from __future__ import annotations` module loaded this way, confirmed with a minimal unrelated reproduction file. I verified the *intended* behavior (module imports cleanly with no live broker/site/env vars, and `repr(PollerConfig)` masks the password) using the corrected loading pattern (registering `sys.modules` first, exactly as `tests/test_mqtt_poller.py` does), which passed. The plan's own test file loading approach (which I implemented) is unaffected since it does the registration.
- The repo-wide `uvx ruff check scripts/ src/ tests/` command (from the plan's overall `<verification>` block) surfaces 7 pre-existing findings in `src/checkmk_wizard/wizard.py`, `tests/test_site.py`, and `tests/test_wizard.py` — none in files this plan created or touched (confirmed via `git status --short` before any of my commits, showing only the two new `mqtt_poller` files). Logged to `.planning/phases/09-poller-core/deferred-items.md` per the deviation rules' scope boundary; not fixed.

## User Setup Required

None - no external service configuration required. This plan has no live-network dependency; MQTT publishing and the compose service wiring are deferred to Plan 09-02.

## Next Phase Readiness

- `scripts/mqtt_poller.py` exports the exact interface Plan 09-02 depends on verbatim (per this plan's `<interfaces>` contract): `PollerConfig`, `DeviceSnapshot`, all topic/state/topology/bounded-log helpers, and the full Livestatus query layer (`LivestatusError`, `available_host_columns`, `select_host_columns`, `build_hosts_query`, `query_devices`).
- Plan 09-02 will add the `datetime`, `paho.mqtt.client` (and likely `sys` for a `main()`/CLI entry point) imports this plan intentionally deferred, plus the MQTT publisher, startup topology reconciliation, and the poll loop itself.
- No blockers. The Livestatus column names (`parents`, `tags`, `filename`) used by `query_devices` remain unverified against a live Checkmk site per RESEARCH.md Open Question 1 — recommend a live `GET columns` check against the real deployment host before or during Plan 09-02/09-03's live smoke testing, consistent with this project's established "live-verify against a real Checkmk site" convention.

## Self-Check: PASSED

- FOUND: `scripts/mqtt_poller.py`
- FOUND: `tests/test_mqtt_poller.py`
- FOUND: `.planning/phases/09-poller-core/09-01-SUMMARY.md`
- FOUND commit: `d636c06`
- FOUND commit: `6c41882`
- FOUND commit: `0b9b2d2`

---
*Phase: 09-poller-core*
*Completed: 2026-09-06*
