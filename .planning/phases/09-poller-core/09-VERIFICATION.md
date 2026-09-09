---
phase: 09-poller-core
verified: 2026-09-09T09:00:00Z
status: gaps_found
score: 3/5 roadmap success criteria fully verified (1 fully failed live, 1 partially failed live)
has_blocking_gaps: true
overrides_applied: 0
gaps:
  - truth: "SC2 — Restarting the poller process does not cause an incorrect republish storm; status matches Livestatus's live current state each cycle, not the poller's own in-memory history"
    status: failed
    severity: blocking
    reason: >
      This is only unit-tested against a mocked MQTT client (tests/test_mqtt_poller.py::test_reconcile_state_*),
      never confirmed against a real Mosquitto/Checkmk deployment. 09-04-PLAN.md's own Task 1 explicitly
      required running `scripts/smoke_test_poller.py` WITHOUT `--skip-restart-checks` and expected
      `[PASS]` for `ghost_tombstone` (the check that restarts the live poller and proves no false
      republish/incorrect state on restart). The live run actually performed and recorded in
      09-04-SUMMARY.md used a different, weaker command
      (`scripts/smoke_test_poller.py --host mosquitto --livestatus-host checkmk --skip-restart-checks`),
      which skips `ghost_tombstone` entirely. 09-04-SUMMARY.md's own "Deviations from Plan: None" claim
      is therefore inaccurate — the command actually run diverges materially from the plan's mandated
      command, and that divergence is not disclosed as a deviation.
    artifacts:
      - path: "scripts/smoke_test_poller.py"
        issue: "check_ghost_tombstone (the restart-storm/self-heal-while-down proof) exists and is implemented correctly, but was never executed against the live deployment — 09-04-SUMMARY.md records `--skip-restart-checks` was used"
      - path: ".planning/phases/09-poller-core/09-04-SUMMARY.md"
        issue: "Reports '[SUMMARY] all checks passed' from a run that structurally excludes 2 of 7 checks (ghost_tombstone, lwt_offline) rather than disclosing them as not-run"
    missing:
      - "Re-run `scripts/smoke_test_poller.py` on the real deployment host WITHOUT `--skip-restart-checks` (e.g. from the host machine or worker container with docker/podman socket access, not from inside the poller container itself) and record a genuine [PASS] for ghost_tombstone"
  - truth: "SC5 (second half) — lan/poller/status moves to an offline/LWT state when the poller process dies ungracefully"
    status: partial
    severity: blocking
    reason: >
      Only the birth/heartbeat half of this criterion was live-verified (`[PASS] poller_liveness (last_poll 38s ago)`
      in 09-04-SUMMARY.md). The LWT-on-ungraceful-death half (`check_lwt_offline`, which kills the poller
      with SIGKILL and asserts the broker delivers `{"status":"offline"}`) was skipped by the same
      `--skip-restart-checks` flag. The `will_set()`/LWT wiring is present and correct in code
      (scripts/mqtt_poller.py:475-492) and unit-tested with a mocked client
      (tests/test_mqtt_poller.py::test_build_mqtt_client_will_set_before_connect_with_offline_payload),
      but broker-triggered LWT delivery on a real ungraceful TCP drop has never been observed against
      the real Mosquitto broker.
    artifacts:
      - path: "scripts/smoke_test_poller.py"
        issue: "check_lwt_offline exists and is correctly implemented, but was never executed against the live deployment (same --skip-restart-checks run)"
    missing:
      - "Re-run scripts/smoke_test_poller.py without --skip-restart-checks (or run check_lwt_offline standalone) and record a genuine [PASS], confirming the real Mosquitto broker delivers the LWT payload on an ungraceful poller death"
deferred: []
human_verification:
  - test: "Run `scripts/smoke_test_poller.py --host <mosquitto-host> --livestatus-host <checkmk-host> --compose-dir deploy` (no `--skip-restart-checks`) from a location with podman/docker access to actually restart/kill the poller container (the host machine or a container with the compose project's socket access — not from inside the poller container itself, which cannot restart its own sibling service)"
    expected: "[PASS] ghost_tombstone and [PASS] lwt_offline, closing SC2 and the second half of SC5 with real evidence instead of mocks"
    why_human: "Requires live access to the real Podman/Checkmk/Mosquitto deployment host, which this verification sandbox does not have (same documented limitation as every prior plan in this phase)"
---

# Phase 9: Poller Core Verification Report

**Phase Goal:** A long-running poller keeps MQTT retained state in sync with Checkmk Livestatus, self-healing across restarts with no persisted state of its own required
**Verified:** 2026-09-09
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `mosquitto_sub` on `lan/devices/+/status` shows retained per-device status with full OK/WARN/CRIT/UNKNOWN/DOWN granularity, timestamp, downtime/ack flags, republished every cycle | ✓ VERIFIED | Live: 09-04-SUMMARY.md — `[PASS] device_status_retained (21/21 payload(s) matched)`. Code: `publish_device_status` (scripts/mqtt_poller.py:514-525) emits exactly this shape every cycle from live `DeviceSnapshot` data, confirmed by `scripts/smoke_test_poller.py::check_device_status_retained`'s schema assertion. |
| 2 | Restarting the poller process does not cause an incorrect republish storm — status matches Livestatus's live current state each cycle, not the poller's own in-memory history | ✗ FAILED | Implementation exists (`reconcile_state`, scripts/mqtt_poller.py:631-698, rebuilds state from the broker's own retained `lan/devices/topology` topic, never a local file) and is unit-tested with a mocked broker (tests/test_mqtt_poller.py::test_reconcile_state_*). **Never live-verified**: the live smoke-test run recorded in 09-04-SUMMARY.md used `--skip-restart-checks`, which skips `check_ghost_tombstone` — the one check that actually restarts the live poller and proves this exact behavior. 09-04-PLAN.md's own Task 1 explicitly required this check to `[PASS]` live before Task 2 could proceed; it was silently substituted with a weaker in-container command instead. |
| 3 | `lan/devices/topology` republishes only when a host is added/removed/reparented; unrelated poll cycles produce no new topology publish | ✓ VERIFIED | Live: 09-04-SUMMARY.md — `[PASS] topology_quiet (no republish within 130.0s)` — two full poll intervals observed with no spurious publish. Code: `topology_signature()` comparison gate in `run_cycle` (scripts/mqtt_poller.py:777-778). |
| 4 | Deleting a host from Checkmk produces empty tombstone payloads on its status/history topics within one poll cycle, disappears from topology; bounded history/events append only on actual transitions | ✓ VERIFIED | Live: 09-04-SUMMARY.md — manual test on real host `192.168.0.215`: `removed` event in `lan/events/recent`, removal from `lan/devices/topology`, `mosquitto_sub -C 1 -W 5` timeout (RC 27, no retained message) on the deleted host's status topic. Code: `publish_tombstone` + `run_cycle`'s `removed_ids` handling (scripts/mqtt_poller.py:544-559, 732-744). |
| 5 | `lan/poller/status` carries a birth message on startup **and** moves to an offline/LWT state when the poller process dies ungracefully | ⚠ PARTIAL (treated as FAILED for scoring) | Birth/heartbeat half VERIFIED live: 09-04-SUMMARY.md — `[PASS] poller_liveness (last_poll 38s ago)`. LWT-on-ungraceful-death half **not live-verified** — `check_lwt_offline` was skipped by the same `--skip-restart-checks` flag. `will_set()` is correctly configured before `connect()` in code (scripts/mqtt_poller.py:475-492) and unit-tested with a mocked client, but the real broker has never been observed actually delivering the LWT payload on a real ungraceful poller death. |

**Score:** 3/5 roadmap success criteria fully live-verified; 2/5 (SC2, and half of SC5) remain implementation-correct-and-unit-tested-only, contradicting the phase's own stated bar ("nothing here is done until a live site says so" — 09-04-PLAN.md's own objective) and this repo's broader "live-verified against a real Checkmk site" documentation convention.

### Requirements Coverage (PLR-01..08)

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| PLR-01 | 09-01, 09-03 | Livestatus TCP polling, host state/service-summary/tags/parent/folder query | ✓ SATISFIED | `query_devices`/`build_hosts_query` (scripts/mqtt_poller.py:383-456); live column probe confirmed `name`,`state`,`scheduled_downtime_depth`,`acknowledged`,`worst_service_state`,`parents`,`tags`,`filename` all present on real Checkmk 2.4.0p35 CE site (in-source citation, scripts/mqtt_poller.py:69-90) |
| PLR-02 | 09-02 | Diffs against live Livestatus state each cycle; self-heals across restarts, no persisted state | ✗ BLOCKED (matches REQUIREMENTS.md's own tracking) | **`.planning/REQUIREMENTS.md:11` itself still shows this unchecked (`[ ]`) and its own Traceability table (line 76) marks it `Pending`** — the only PLR item left unchecked while PLR-01/03-08 were flipped to complete/checked. This independently corroborates the live-verification gap found above (SC2). Code and mocked-unit-test evidence exist (`reconcile_state`, `tests/test_mqtt_poller.py`) but the requirement's own project tracker has not been marked satisfied, and my independent check confirms why: the live restart proof was never run. |
| PLR-03 | 09-01, 09-02 | Per-device retained status, full state granularity + timestamp | ✓ SATISFIED | Live-verified (SC1 above) |
| PLR-04 | 09-02, 09-03 | Topology republishes only on actual change | ✓ SATISFIED | Live-verified (SC3 above) |
| PLR-05 | 09-02 | Bounded per-device history + bounded global events, transition-only | ✓ SATISFIED | `append_bounded`, `run_cycle`'s event/history append logic (scripts/mqtt_poller.py:255-257, 757-775); unit-tested (13 `test_run_cycle*` tests); partially live-observed via the manual tombstone test's `removed` event |
| PLR-06 | 09-02 | Tombstone payloads for removed devices | ✓ SATISFIED | Live-verified (SC4 above) |
| PLR-07 | 09-02 | Birth/LWT liveness on `lan/poller/status` | ⚠ PARTIAL | Birth half live-verified; LWT-on-death half not live-verified (see SC5 above) |
| PLR-08 | 09-01 | Downtime/acknowledgement surfaced in status payload | ✓ SATISFIED | `DeviceSnapshot.in_downtime`/`acknowledged` fields (D-07), included in every `publish_device_status` payload, confirmed present in the 21/21 live-matched payloads |

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `scripts/mqtt_poller.py` | Complete standalone poller daemon | ✓ VERIFIED | 916 lines; all functions named in plan interfaces present (`PollerConfig`, `DeviceSnapshot`, `build_mqtt_client`, 5 publish helpers, `reconcile_state`, `run_cycle`, `run_forever`, `main`); imports cleanly, no `checkmk_wizard` import (D-01 respected); `--help`/`--check-columns` verified working in this session |
| `tests/test_mqtt_poller.py` | Unit coverage for pure helpers + mocked MQTT/Livestatus layers | ✓ VERIFIED | 805 lines, 62 tests, all passing (`uv run pytest tests/test_mqtt_poller.py -q` → 62 passed, re-run this session) |
| `scripts/smoke_test_poller.py` | Live-verification script proving Phase 9 success criteria | ✓ VERIFIED (exists, substantive, wired) — ⚠ but 2 of its 7 checks were never actually executed against the live deployment | 604 lines, 7 check functions + `main()`; `--help` verified working this session; loads `mqtt_poller.py` via `importlib` to avoid drift |
| `deploy/compose.yaml` | Dedicated `poller` service, env-var config, `restart: unless-stopped`, bind-mounts git-tracked `scripts/` | ✓ VERIFIED | `poller:` service present (lines 119-158); all 11 env vars from `PollerConfig.from_env()` present; `restart: unless-stopped`; bind-mounts `${POLLER_SCRIPTS_DIR:-../scripts}:/scripts:ro,z` (not the uncommitted `./app`); pinned `paho-mqtt==2.1.0`; publishes no port (internal-only, consistent with container-boundary constraint) |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `scripts/mqtt_poller.py` | `socket.create_connection` | one-shot Livestatus TCP request | ✓ WIRED | `_livestatus_request` (line 313-335) |
| `tests/test_mqtt_poller.py` | `scripts/mqtt_poller.py` | `importlib.util.spec_from_file_location` | ✓ WIRED | Confirmed pattern present, 62 tests pass against it |
| `scripts/mqtt_poller.py` | `lan/poller/status` | `will_set()` before `connect()` | ✓ WIRED (code) / ⚠ NOT LIVE-CONFIRMED for the death path | `build_mqtt_client` (line 464-492) |
| `scripts/mqtt_poller.py` | `lan/devices/topology` | startup subscribe + bounded wait for retained payload | ✓ WIRED | `reconcile_state` (line 631-698) |
| `deploy/compose.yaml` | `scripts/mqtt_poller.py` | read-only bind mount + python command | ✓ WIRED | `command: python -u /scripts/mqtt_poller.py`, mount at line 137 |
| `scripts/smoke_test_poller.py` | `scripts/mqtt_poller.py` | `importlib` load of sibling module | ✓ WIRED | `_load_poller_module` (line 71-87), confirmed via `--help` run |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Full test suite passes | `uv run pytest -q` | 304 passed | ✓ PASS |
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

## Gaps Summary

Phase 9's poller implementation itself is solid: `scripts/mqtt_poller.py` correctly implements the full topic contract, worst-of aggregation, topic-injection guards, bounded history/events, tombstoning, and a from-broker (not from-disk) reconciliation strategy that architecturally satisfies "no persisted state of its own." 304 unit tests pass, lint is clean, and 3 of 5 ROADMAP success criteria (device status, topology-quiet, tombstone-on-deletion) were genuinely confirmed against a real Checkmk 2.4.0p35 CE + Mosquitto deployment this session (2026-09-08/09).

The gap is specific and well-evidenced, not speculative: the phase's own Wave 4 plan (09-04-PLAN.md) explicitly required `scripts/smoke_test_poller.py` to be run **without** `--skip-restart-checks` and to report `[PASS]` for `ghost_tombstone` and `lwt_offline` — the two checks that actually restart/kill the live poller process and prove SC2 ("restart does not cause a republish storm") and the second half of SC5 ("LWT flips to offline on ungraceful death"). The live run that was actually performed and recorded in 09-04-SUMMARY.md used `--skip-restart-checks`, silently omitting exactly those two checks, and the SUMMARY's "Deviations from Plan: None" statement does not disclose this substitution. `.planning/REQUIREMENTS.md` itself independently corroborates this: PLR-02 is the only Phase 9 requirement still left unchecked and marked "Pending" in its own tracking table.

Because "self-heals across restarts" is the literal, load-bearing phrase in Phase 9's own ROADMAP goal statement — not a peripheral detail — this is scored as a blocking gap rather than a minor one, per this repo's own stated convention that "nothing here is done until a live site says so" (09-04-PLAN.md's own words).

**This looks intentional/close-to-done, not broken.** The fix is narrow: re-run `scripts/smoke_test_poller.py` on the real deployment host from a location that can actually restart/kill the `poller` container (the host itself, or a container with the compose project's control access — not from inside the `poller` container, which cannot restart its own sibling service) without `--skip-restart-checks`, and record genuine `[PASS]` lines for `ghost_tombstone` and `lwt_offline`. If the developer judges the existing mocked-unit-test coverage sufficient and wants to accept this deviation instead, add an override to this file's frontmatter:

```yaml
overrides:
  - must_have: "Restarting the poller process does not cause an incorrect republish storm; lan/poller/status moves to offline/LWT state when the poller process dies ungracefully"
    reason: "Accepting mocked-unit-test coverage (tests/test_mqtt_poller.py::test_reconcile_state_*, test_build_mqtt_client_will_set_before_connect_with_offline_payload) as sufficient proof; live restart/kill checks deferred"
    accepted_by: "{your name}"
    accepted_at: "{ISO timestamp}"
```

---

*Verified: 2026-09-09*
*Verifier: Claude (gsd-verifier)*
