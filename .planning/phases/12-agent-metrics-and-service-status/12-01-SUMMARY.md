---
phase: 12-agent-metrics-and-service-status
plan: 01
subsystem: poller
tags: [livestatus, mqtt-poller, nagios-perfdata, checkmk]

# Dependency graph
requires:
  - phase: 09-poller-core
    provides: "_livestatus_request choke point, available_host_columns/select_host_columns/build_hosts_query triad, query_devices row-parsing pattern to mirror"
provides:
  - "REQUIRED_SERVICE_COLUMNS/OPTIONAL_SERVICE_COLUMNS module constants"
  - "available_service_columns() / select_service_columns() / build_services_query() triad"
  - "parse_perf_data() — defensive Nagios perf_data string parser, never raises"
  - "ServiceSnapshot dataclass and query_services() — typed GET services round trip"
  - "--dump-service-names CLI flag for live SMART service-name confirmation"
affects: [12-02, 12-03, 12-04, 12-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Services column-availability triad mirrors the existing hosts triad exactly (available_*_columns/select_*_columns/build_*_query)"
    - "query_services() reuses query_devices()'s per-field try/except skip-the-row posture, never a second exception type"
    - "parse_perf_data() tokenizes on whitespace except inside a single-quoted label, via a small regex rather than raw.split()"

key-files:
  created: []
  modified:
    - scripts/mqtt_poller.py
    - tests/test_mqtt_poller.py

key-decisions:
  - "perf_data kept OPTIONAL (never REQUIRED) in the services column split, per 12-RESEARCH.md Pitfall 4"
  - "parse_perf_data tokenizes with a small regex, not str.split(), so a single-quoted label containing a space parses as one token instead of two"

patterns-established:
  - "Services query pipeline (available_service_columns -> select_service_columns -> build_services_query -> query_services) is a literal parallel of the existing hosts pipeline, same LivestatusError type, same _livestatus_request choke point"

requirements-completed: [PLR-09]

# Metrics
duration: 20min
completed: 2026-09-23
---

# Phase 12 Plan 01: Services Query Foundation Summary

**`scripts/mqtt_poller.py` gains a `GET services` Livestatus pipeline (column probe, defensive row parser, typed `ServiceSnapshot`) and a hand-rolled Nagios `perf_data` parser — the data foundation every later Phase 12 plan (gauges, SMART badge, per-service list) consumes.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-09-23T09:05:00+08:00 (approx, first commit 09:07:13+08:00)
- **Completed:** 2026-09-23T09:10:57+08:00
- **Tasks:** 3/3 completed
- **Files modified:** 2

## Accomplishments
- The poller can now probe which `services` table columns a live Checkmk site actually exposes, and only refuses to run the query when a truly required column (`host_name`/`description`/`state`) is missing — `plugin_output`/`perf_data` degrade gracefully with a logged warning.
- A defensive, never-raising Nagios `perf_data` parser turns Livestatus's raw performance-data strings into per-metric `{value, warn, crit, min, max}` dicts, in Python only (never shipped to the browser).
- `query_services()` runs one `GET services` round trip through the existing `_livestatus_request` choke point and returns typed `ServiceSnapshot` records, with the same per-row/per-field skip-not-fatal posture `query_devices()` already established.
- `--dump-service-names` lets an operator confirm the live site's actual SMART service naming (flagged as contradicted/unverified by 12-RESEARCH.md's Critical Finding) with zero code changes.

## Task Commits

Each task was committed atomically:

1. **Task 1: Services column-availability triad and CLI diagnostics** - `04558a4` (feat)
2. **Task 2: Nagios perf_data parser** - `90ea30e` (feat)
3. **Task 3: ServiceSnapshot dataclass and query_services** - `b2639e5` (feat)

**Plan metadata:** (this commit, docs)

## Files Created/Modified
- `scripts/mqtt_poller.py` - Added `REQUIRED_SERVICE_COLUMNS`/`OPTIONAL_SERVICE_COLUMNS`, `available_service_columns()`, `select_service_columns()`, `build_services_query()`, `--dump-service-names` CLI flag, extended `--check-columns` to also probe the services table, `_strip_uom()`, `parse_perf_data()`, `ServiceSnapshot` dataclass, `query_services()`
- `tests/test_mqtt_poller.py` - Unit coverage for the services column triad, the perfdata parser (fs/CPU/percent/quoted-label/garbage-token/empty/non-string shapes), and `query_services()` row parsing (full row, malformed-row skip, required-only-columns degradation, empty body, malformed JSON, topic-unsafe host skip)

## Decisions Made
- `perf_data` stays strictly optional in `REQUIRED_SERVICE_COLUMNS`/`OPTIONAL_SERVICE_COLUMNS` — confirmed no test or code path treats it as required, per 12-RESEARCH.md Pitfall 4's explicit warning about blast radius.
- `parse_perf_data()`'s tokenizer uses a small regex (`'[^']*'=\S*|\S+`) instead of the plan's literal `raw.split()` draft, because the draft breaks a single-quoted label containing a space (`'total used'=5;;;;`) into two tokens. This is a Rule 1 (bug) auto-fix, not a deviation from intent — the plan's own acceptance criteria requires the quoted-label case to parse correctly.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `raw.split()` breaks a quoted label containing a space into two tokens**
- **Found during:** Task 2 (Nagios perf_data parser) — the plan's own acceptance criteria requires `'total used'=5;;;;` to parse to label `total used`, but a first implementation following the plan's literal `raw.split()` draft split it into `"'total"` and `"used'=5;;;;"`, neither of which parses correctly.
- **Issue:** `str.split()` breaks on every whitespace character, including the one inside a single-quoted label — the perfdata format explicitly allows spaces inside a quoted label (nagios-plugins.org/doc/guidelines.html).
- **Fix:** Replaced `raw.split()` with a small compiled regex (`_PERF_DATA_TOKEN_RE = re.compile(r"'[^']*'=\S*|\S+")`) that tries a quoted-label-then-value token first, falling back to a plain non-space token — `re.findall()` over this pattern tokenizes correctly for both shapes.
- **Files modified:** `scripts/mqtt_poller.py`
- **Verification:** `test_parse_perf_data_quoted_label_with_space` passes; full test suite (119 tests) still passes with no regression to the other perfdata shapes.
- **Committed in:** `90ea30e` (Task 2 commit — the fix was made before the task was marked complete, not as a follow-up)

**2. [Rule 1 - Bug] Docstring's literal "raise" substring broke the task's own grep-based acceptance check**
- **Found during:** Task 2 — the plan's acceptance criterion `grep -A 30 'def parse_perf_data' scripts/mqtt_poller.py | grep -c raise` must return `0`, but the initial docstring phrase "Never raises" contains the substring "raise", making the grep match the docstring itself, not an actual `raise` statement.
- **Issue:** No functional bug (the function genuinely never raises), but the acceptance check as specified would fail against the initial wording.
- **Fix:** Reworded the docstring to "No exception ever escapes this function" — same contract stated explicitly, no `raise` substring.
- **Files modified:** `scripts/mqtt_poller.py`
- **Verification:** `grep -A 30 'def parse_perf_data' scripts/mqtt_poller.py | grep -c raise` now returns `0`.
- **Committed in:** `90ea30e` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 — bugs found and fixed before task completion, not scope changes)
**Impact on plan:** Both fixes were required for the plan's own stated acceptance criteria to pass; no scope creep, no architectural change.

## Issues Encountered
None beyond the two auto-fixed items above.

## User Setup Required
None - no external service configuration required. This plan adds pure Python functions with unit test coverage; nothing is wired into the live poll loop yet (that is plan 12-02's job per the plan's own `<objective>`).

## Next Phase Readiness
- `query_services()`, `ServiceSnapshot`, and `parse_perf_data()` are ready for plan 12-02 to wire into `run_cycle()`/`run_forever()` and the new publish topics.
- `--dump-service-names` is ready to run against the live agent-test host to resolve 12-RESEARCH.md's flagged SMART service-name conflict before any filter regex is hardcoded in a later plan.
- No blockers. All verification commands in the plan (`uv run pytest tests/test_mqtt_poller.py -q`, `uv run python scripts/mqtt_poller.py --help`, the no-third-party-import grep) pass as specified.

---
*Phase: 12-agent-metrics-and-service-status*
*Completed: 2026-09-23*

## Self-Check: PASSED
- FOUND: `.planning/phases/12-agent-metrics-and-service-status/12-01-SUMMARY.md`
- FOUND: `04558a4` (Task 1 commit)
- FOUND: `90ea30e` (Task 2 commit)
- FOUND: `b2639e5` (Task 3 commit)
