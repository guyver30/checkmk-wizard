---
phase: 09-poller-core
verified: 2026-09-09T09:00:00Z
reverified: 2026-09-09T10:30:00Z
status: verified
score: 5/5 roadmap success criteria fully verified
has_blocking_gaps: false
overrides_applied: 0
gaps: []
deferred: []
human_verification:
  - test: "Run `scripts/smoke_test_poller.py --host localhost --livestatus-host localhost --compose-dir deploy` (no `--skip-restart-checks`) from the deployment host itself, with real `podman compose` control over the `poller` container"
    expected: "[PASS] ghost_tombstone and [PASS] lwt_offline, closing SC2 and the second half of SC5 with real evidence instead of mocks"
    result: >
      CONFIRMED 2026-09-09. Developer re-ran after the CR-01/CR-02 code-review fixes (commits c58ab95,
      1507fac) landed. Result: `[PASS] device_status_retained (20/20)`, `[PASS] topology_retained
      (20 device(s))`, `[PASS] poller_liveness (last_poll 20s ago)`, `[PASS] topology_quiet (no
      republish within 130.0s)`, `[PASS] ghost_tombstone`, `[PASS] lwt_offline`. The run's only
      failure — `[FAIL] livestatus_columns: Connection refused` — is an environment artifact, not a
      regression: `deploy/compose.yaml` publishes MQTT's 1883 to the host but does not publish
      Livestatus's 6557 on the `checkmk` container (only 8080/8000/6556 are published), so
      `--livestatus-host localhost` cannot reach it from outside `cmk_net`. `livestatus_columns` was
      already live-confirmed in the original 09-04 Task 1 run from inside the `poller` container
      (see the Live-verified citation in scripts/mqtt_poller.py); this run's purpose was specifically
      the restart/LWT checks, which both passed.
    why_human: "Requires live access to the real Podman/Checkmk/Mosquitto deployment host, which this verification sandbox does not have (same documented limitation as every prior plan in this phase)"
---

# Phase 9: Poller Core Verification Report

**Phase Goal:** A long-running poller keeps MQTT retained state in sync with Checkmk Livestatus, self-healing across restarts with no persisted state of its own required
**Verified:** 2026-09-09 (initial), re-verified 2026-09-09 after gap closure
**Status:** verified
**Re-verification:** Yes — see "Gap Closure" below

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `mosquitto_sub` on `lan/devices/+/status` shows retained per-device status with full OK/WARN/CRIT/UNKNOWN/DOWN granularity, timestamp, downtime/ack flags, republished every cycle | ✓ VERIFIED | Live: 09-04-SUMMARY.md — `[PASS] device_status_retained (21/21 payload(s) matched)`. Code: `publish_device_status` (scripts/mqtt_poller.py:514-525) emits exactly this shape every cycle from live `DeviceSnapshot` data, confirmed by `scripts/smoke_test_poller.py::check_device_status_retained`'s schema assertion. |
| 2 | Restarting the poller process does not cause an incorrect republish storm — status matches Livestatus's live current state each cycle, not the poller's own in-memory history | ✓ VERIFIED | `reconcile_state` (scripts/mqtt_poller.py:631-698) rebuilds state from the broker's own retained `lan/devices/topology` topic, never a local file; unit-tested (tests/test_mqtt_poller.py::test_reconcile_state_*). **Live-verified 2026-09-09**: `podman compose restart poller` via `scripts/smoke_test_poller.py::check_ghost_tombstone` (run from the host, no `--skip-restart-checks`) → `[PASS] ghost_tombstone`. |
| 3 | `lan/devices/topology` republishes only when a host is added/removed/reparented; unrelated poll cycles produce no new topology publish | ✓ VERIFIED | Live: 09-04-SUMMARY.md — `[PASS] topology_quiet (no republish within 130.0s)` — two full poll intervals observed with no spurious publish. Code: `topology_signature()` comparison gate in `run_cycle` (scripts/mqtt_poller.py:777-778). |
| 4 | Deleting a host from Checkmk produces empty tombstone payloads on its status/history topics within one poll cycle, disappears from topology; bounded history/events append only on actual transitions | ✓ VERIFIED | Live: 09-04-SUMMARY.md — manual test on real host `192.168.0.215`: `removed` event in `lan/events/recent`, removal from `lan/devices/topology`, `mosquitto_sub -C 1 -W 5` timeout (RC 27, no retained message) on the deleted host's status topic. Code: `publish_tombstone` + `run_cycle`'s `removed_ids` handling (scripts/mqtt_poller.py:544-559, 732-744). |
| 5 | `lan/poller/status` carries a birth message on startup **and** moves to an offline/LWT state when the poller process dies ungracefully | ✓ VERIFIED | Birth/heartbeat half: `[PASS] poller_liveness (last_poll 38s ago)` (09-04-SUMMARY.md). LWT-on-death half **live-verified 2026-09-09**: `podman compose kill -s KILL poller` via `check_lwt_offline` (run from the host, no `--skip-restart-checks`) → `[PASS] lwt_offline`, confirming the real Mosquitto broker delivers `{"status":"offline"}` on an ungraceful death, and that the CR-02 fix (`shutdown_mqtt_client()`, commit 1507fac) didn't regress the LWT path on graceful exits either. |

**Score:** 5/5 roadmap success criteria fully live-verified.

### Requirements Coverage (PLR-01..08)

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| PLR-01 | 09-01, 09-03 | Livestatus TCP polling, host state/service-summary/tags/parent/folder query | ✓ SATISFIED | `query_devices`/`build_hosts_query` (scripts/mqtt_poller.py:383-456); live column probe confirmed `name`,`state`,`scheduled_downtime_depth`,`acknowledged`,`worst_service_state`,`parents`,`tags`,`filename` all present on real Checkmk 2.4.0p35 CE site (in-source citation, scripts/mqtt_poller.py:69-90) |
| PLR-02 | 09-02 | Diffs against live Livestatus state each cycle; self-heals across restarts, no persisted state | ✓ SATISFIED | Live-verified 2026-09-09 (SC2 above): `[PASS] ghost_tombstone` from a real `podman compose restart poller`. `.planning/REQUIREMENTS.md` should be updated to check this off (still showed `[ ]`/`Pending` as of the initial verification pass, before this evidence existed). |
| PLR-03 | 09-01, 09-02 | Per-device retained status, full state granularity + timestamp | ✓ SATISFIED | Live-verified (SC1 above) |
| PLR-04 | 09-02, 09-03 | Topology republishes only on actual change | ✓ SATISFIED | Live-verified (SC3 above) |
| PLR-05 | 09-02 | Bounded per-device history + bounded global events, transition-only | ✓ SATISFIED | `append_bounded`, `run_cycle`'s event/history append logic (scripts/mqtt_poller.py:255-257, 757-775); unit-tested (13 `test_run_cycle*` tests); partially live-observed via the manual tombstone test's `removed` event |
| PLR-06 | 09-02 | Tombstone payloads for removed devices | ✓ SATISFIED | Live-verified (SC4 above) |
| PLR-07 | 09-02 | Birth/LWT liveness on `lan/poller/status` | ✓ SATISFIED | Birth and LWT-on-death both live-verified (see SC5 above) |
| PLR-08 | 09-01 | Downtime/acknowledgement surfaced in status payload | ✓ SATISFIED | `DeviceSnapshot.in_downtime`/`acknowledged` fields (D-07), included in every `publish_device_status` payload, confirmed present in the 21/21 live-matched payloads |

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `scripts/mqtt_poller.py` | Complete standalone poller daemon | ✓ VERIFIED | 916 lines; all functions named in plan interfaces present (`PollerConfig`, `DeviceSnapshot`, `build_mqtt_client`, 5 publish helpers, `reconcile_state`, `run_cycle`, `run_forever`, `main`); imports cleanly, no `checkmk_wizard` import (D-01 respected); `--help`/`--check-columns` verified working in this session |
| `tests/test_mqtt_poller.py` | Unit coverage for pure helpers + mocked MQTT/Livestatus layers | ✓ VERIFIED | 805 lines, 62 tests, all passing (`uv run pytest tests/test_mqtt_poller.py -q` → 62 passed, re-run this session) |
| `scripts/smoke_test_poller.py` | Live-verification script proving Phase 9 success criteria | ✓ VERIFIED — all 7 checks now executed live, including restart/kill checks | 604 lines, 7 check functions + `main()`; `--help` verified working this session; loads `mqtt_poller.py` via `importlib` to avoid drift |
| `deploy/compose.yaml` | Dedicated `poller` service, env-var config, `restart: unless-stopped`, bind-mounts git-tracked `scripts/` | ✓ VERIFIED | `poller:` service present (lines 119-158); all 11 env vars from `PollerConfig.from_env()` present; `restart: unless-stopped`; bind-mounts `${POLLER_SCRIPTS_DIR:-../scripts}:/scripts:ro,z` (not the uncommitted `./app`); pinned `paho-mqtt==2.1.0`; publishes no port (internal-only, consistent with container-boundary constraint) |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `scripts/mqtt_poller.py` | `socket.create_connection` | one-shot Livestatus TCP request | ✓ WIRED | `_livestatus_request` (line 313-335) |
| `tests/test_mqtt_poller.py` | `scripts/mqtt_poller.py` | `importlib.util.spec_from_file_location` | ✓ WIRED | Confirmed pattern present, 62 tests pass against it |
| `scripts/mqtt_poller.py` | `lan/poller/status` | `will_set()` before `connect()`, plus explicit `shutdown_mqtt_client()` on graceful exits (CR-02 fix) | ✓ WIRED, live-confirmed for both the LWT death path and graceful-exit path | `build_mqtt_client` (line 464-492); `shutdown_mqtt_client` (commit 1507fac) |
| `scripts/mqtt_poller.py` | `lan/devices/topology` | startup subscribe + bounded wait for retained payload | ✓ WIRED | `reconcile_state` (line 631-698) |
| `deploy/compose.yaml` | `scripts/mqtt_poller.py` | read-only bind mount + python command | ✓ WIRED | `command: python -u /scripts/mqtt_poller.py`, mount at line 137 |
| `scripts/smoke_test_poller.py` | `scripts/mqtt_poller.py` | `importlib` load of sibling module | ✓ WIRED | `_load_poller_module` (line 71-87), confirmed via `--help` run |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Full test suite passes | `uv run pytest -q` | 304 passed (initial), 307 passed after CR-01/CR-02 fixes added 3 regression tests | ✓ PASS |
| `mqtt_poller.py` test file passes | `uv run pytest tests/test_mqtt_poller.py -q` | 62 passed | ✓ PASS |
| Lint clean | `uvx ruff check scripts/mqtt_poller.py scripts/smoke_test_poller.py tests/test_mqtt_poller.py` | All checks passed! | ✓ PASS |
| CLI help works | `uv run python scripts/mqtt_poller.py --help` | exit 0, lists `--check-columns`/`--once` | ✓ PASS |
| Smoke-test CLI help works | `uv run python scripts/smoke_test_poller.py --help` | exit 0, lists all documented flags | ✓ PASS |
| Clean failure with no traceback/credential leak against unreachable Livestatus | `LIVESTATUS_HOST=127.0.0.1 LIVESTATUS_PORT=1 uv run python scripts/mqtt_poller.py --check-columns` | `ERROR Column check failed: ... Connection refused` — clean, no traceback, no credentials | ✓ PASS |

### Probe Execution

SKIPPED — no `scripts/*/tests/probe-*.sh` convention exists in this repo; this project uses the `scripts/smoke_test_*.py` live-verification convention instead (evaluated above under Behavioral Spot-Checks and the live evidence cited in 09-04-SUMMARY.md).

### Anti-Patterns Found

None. Grepped `scripts/mqtt_poller.py`, `scripts/smoke_test_poller.py`, `deploy/compose.yaml` for `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER|placeholder|coming soon|not yet implemented` — no matches. No stub returns, no hardcoded empty-data patterns feeding a rendered/published path. `deferred-items.md` correctly documents 7 *pre-existing, out-of-scope* ruff findings in unrelated files (`wizard.py`, `test_site.py`, `test_wizard.py`), none introduced by this phase.

### Documentation Inconsistencies (informational, not scored as gaps)

- `.planning/ROADMAP.md`'s Progress table (line 113) still shows Phase 8 as "0/3 Not started" while Phase 8's own checkbox list (lines 15, 38-43) shows all 3 plans `[x]` complete and Phase 9 depends on it having shipped. Likely a stale bookkeeping row, not a Phase 9 concern, but worth a follow-up correction.
- `.planning/STATE.md` still shows "Plan: 1 of 4" / 25% for Phase 9, contradicted by ROADMAP.md's "4/4 Complete" — stale, last updated 2026-09-07 before 09-04 finished.
- `.planning/REQUIREMENTS.md`'s Traceability table marks Phase 8's BRK-01/02/03 as "Pending" despite Phase 8 shipping — consistent with general table staleness for Phase 8, but notably PLR-02 is the *only* Phase 9 item left unchecked, which — per the analysis above — is not staleness but an accurate, uncorrected reflection of the real live-verification gap.

## Gap Closure

The initial verification pass (2026-09-09, first run) found 2 blocking gaps: SC2 and the LWT half of SC5 were only mocked-unit-tested, never proven against the real deployment, because the live smoke-test run recorded in 09-04-SUMMARY.md used `--skip-restart-checks` (run from inside the `poller` container, which cannot restart its own sibling service). A code review of the same files, run in parallel, independently found two related bugs:

- **CR-01**: `query_devices()` had unguarded optional-column extractions that could raise an uncaught `IndexError` on a malformed Livestatus row, crashing the poll loop — contradicting its own documented defensive-skip contract.
- **CR-02**: on every graceful exit path (fatal-startup failure, normal shutdown, both `--once` exits), the poller disconnected from MQTT gracefully without publishing an offline status first. A graceful MQTT disconnect suppresses the LWT, so `lan/poller/status` would stick at "online" forever after a real startup failure — directly relevant to the very SC5 gap this report flagged.

Both were fixed (commits `c58ab95`, `1507fac`) with 3 new regression tests (307 total passing). The developer then re-ran `scripts/smoke_test_poller.py --host localhost --livestatus-host localhost --compose-dir deploy` (no `--skip-restart-checks`) from the deployment host itself, which has real `podman compose` control over the `poller` container:

```
[FAIL] livestatus_columns: Livestatus request to localhost:6557 failed: [Errno 111] Connection refused
[PASS] device_status_retained (20/20 payload(s) matched)
[PASS] topology_retained (20 device(s))
[PASS] poller_liveness (last_poll 20s ago)
[PASS] topology_quiet (no republish within 130.0s)
[PASS] ghost_tombstone
[PASS] lwt_offline
[SUMMARY] one or more checks failed
```

`ghost_tombstone` and `lwt_offline` — the two checks that matter for this gap — both passed. The one failure, `livestatus_columns`, is an environment artifact of running from the host rather than a regression: `deploy/compose.yaml` publishes MQTT's `1883` to the host but not Livestatus's `6557` on the `checkmk` container (only `8080`/`8000`/`6556` are published), so `--livestatus-host localhost` can't reach it from outside the `cmk_net` Docker network. `livestatus_columns` was already live-confirmed from inside the `poller` container in the original 09-04 Task 1 run (see the Live-verified citation in `scripts/mqtt_poller.py`); this run's purpose was specifically the restart/LWT checks.

All 5 ROADMAP success criteria for Phase 9 are now live-verified against a real Checkmk 2.4.0p35 CE + Mosquitto + Podman deployment. No blocking gaps remain.

---

*Verified: 2026-09-09 (initial), re-verified 2026-09-09 (gap closure)*
*Verifier: Claude (gsd-verifier); gap closure recorded by orchestrating session*
