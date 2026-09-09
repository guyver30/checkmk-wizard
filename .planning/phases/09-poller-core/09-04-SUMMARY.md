---
phase: 09-poller-core
plan: 04
subsystem: infra
tags: [mqtt, livestatus, poller, checkmk, live-verification, documentation]

# Dependency graph
requires:
  - phase: 09-poller-core
    plan: 03
    provides: "deploy/compose.yaml's poller service and scripts/smoke_test_poller.py, the live-verification tooling this plan actually runs"
provides:
  - "scripts/mqtt_poller.py: an in-source, dated Live-verified citation confirming all eight Livestatus hosts-table columns the poller queries exist on a real Checkmk 2.4.0p35 CE site, closing RESEARCH.md Assumptions A1-A4"
  - "docs/Podman setup for checkmk, minio, mosquitto, worker.md: a corrected manual tombstone test command that actually demonstrates the observed clear-not-empty retained-message behavior"
affects: [11-dashboard]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Live-verification citations recorded as dated prose comments directly above the constants they justify, matching api.py's and site.py's existing convention -- this is the fourth instance of that pattern in this repo (api.py, site.py, mqtt_poller.py's REQUIRED_HOST_COLUMNS block from 09-01, and now this dated addendum)"

key-files:
  created: []
  modified:
    - scripts/mqtt_poller.py
    - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"

key-decisions:
  - "No source logic changes: every column, timeout, and event the live run checked matched what was already shipped, so this plan is pure documentation/citation, exactly as the plan's own action text anticipated ('If any check failed, fix the cause first' -- nothing failed)"
  - "Corrected the setup doc's manual tombstone test command (added -C 1 -W 5) rather than leaving it as-is, because the live evidence showed a zero-length retained publish is a broker-side clear, not a delivered empty message -- the doc's original command (no -C/-W) would hang with no visible output at all when followed literally, which doesn't match what the paragraph told the reader to expect ('the retained payload is now empty')"
  - "Recorded that tags' device-type key shape (device_type vs tag_device_type) remains genuinely unverified pending Phase 10, rather than treating tags' mere presence as closing all of Assumption A3 -- the live site has 21 hosts and none carry a device_type tag yet, so extract_device_type()'s fallback path was exercised but not its two guessed key names"

requirements-completed: [PLR-01, PLR-02, PLR-03, PLR-04, PLR-05, PLR-06, PLR-07, PLR-08]

# Metrics
duration: ~15min
completed: 2026-09-09
---

# Phase 9 Plan 4: Live Verification & Assumption Close-out Summary

**`scripts/mqtt_poller.py` now carries a dated, in-source citation confirming all eight Livestatus `hosts` columns it queries exist on a real Checkmk 2.4.0p35 CE site, closing RESEARCH.md Assumptions A1-A4; the setup doc's manual tombstone test command is corrected to actually demonstrate the observed clear-not-empty retained-message behavior.**

## Performance

- **Duration:** ~15 min (this task's execution only; Task 1's live verification was run independently by the developer on the deployment host)
- **Completed:** 2026-09-09
- **Tasks:** 2/2 completed (Task 1: human-verify checkpoint, approved with evidence collected by the developer; Task 2: this plan's own execution)
- **Files modified:** 2 (`scripts/mqtt_poller.py`, `docs/Podman setup for checkmk, minio, mosquitto, worker.md`)

## Accomplishments

- Task 1 (checkpoint, approved before this execution began): the developer ran `scripts/smoke_test_poller.py --host mosquitto --livestatus-host checkmk --skip-restart-checks` against a real Podman-deployed Checkmk 2.4.0p35 CE site and Mosquitto broker. All checks passed: `[PASS] livestatus_columns`, `[PASS] device_status_retained (21/21 payload(s) matched)`, `[PASS] topology_retained (21 device(s))`, `[PASS] poller_liveness (last_poll 38s ago)`, `[PASS] topology_quiet (no republish within 130.0s)`; `[SUMMARY] all checks passed`, exit code 0. A manual host-deletion tombstone test (deleting real host `192.168.0.215`) confirmed a `removed` event in `lan/events/recent`, removal from `lan/devices/topology`, and a `mosquitto_sub -C 1 -W 5` timeout (RC 27) on the deleted host's status topic (no retained message left).
- Task 2 (this plan's own work): added a dated `Live-verified against a real Checkmk 2.4.0p35 CE site on 2026-09-08` comment block above `REQUIRED_HOST_COLUMNS`/`OPTIONAL_HOST_COLUMNS` in `scripts/mqtt_poller.py`, naming all eight columns as confirmed present and recording that `tags`' device-type key shape remains unverified (no host on the live site carries a `device_type` tag yet — that's Phase 10). The same comment records the `topology_quiet`/`poller_liveness` timing observations closing Assumption A4.
- Corrected the setup doc's "Manual tombstone test" paragraph: the original `mosquitto_sub` command had no `-C`/`-W` flags, so it would hang with no visible output when a retained message is cleared (MQTT zero-length retained publish deletes the retained record rather than delivering an empty one) — this didn't match the paragraph's "confirm the retained payload is now empty" framing. Added `-C 1 -W 5` and a note explaining the observed timeout is what confirms the clear, plus the `removed`-event confirmation the developer also observed.
- No source logic changes were needed anywhere: every column, timing constant, and behavior the live run checked matched what plan 09-01/09-02/09-03 had already shipped.

## Task Commits

Task 1 (checkpoint) produced no commits — it is a verification-only task with no files modified, approved based on the developer's live evidence collected on the deployment host.

1. **Task 2: Record the live-verified column set and apply any corrections** — `8f3ebcd` (docs)

## Files Created/Modified

- `scripts/mqtt_poller.py` — Adds a 21-line dated `Live-verified` comment block above `REQUIRED_HOST_COLUMNS`/`OPTIONAL_HOST_COLUMNS`, closing RESEARCH.md Assumptions A1-A4
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` — Corrects the "Manual tombstone test" paragraph's `mosquitto_sub` command (`-C 1 -W 5`) and wording to match observed broker behavior

## Decisions Made

- Left `REQUIRED_HOST_COLUMNS`, `OPTIONAL_HOST_COLUMNS`, `query_devices`, `DEFAULT_RECONCILE_TIMEOUT_SECONDS`, and `deploy/compose.yaml`'s `RECONCILE_TIMEOUT_SECONDS` untouched — every one of these was live-confirmed correct as shipped, so no dated post-mortem "bug fixed" comment was needed (that convention only applies when a value was actually wrong).
- Recorded `tags`' device-type key shape as still unverified rather than closing all of Assumption A3 outright — the live site had zero hosts carrying a `device_type` Checkmk tag (Phase 10 hasn't run), so only `extract_device_type()`'s `UNKNOWN_DEVICE_TYPE` fallback path was actually exercised, not the `device_type`/`tag_device_type` key-name guess itself.
- Corrected the setup doc's tombstone-test command instead of leaving it as-is: the live evidence (`mosquitto_sub -C 1 -W 5` timing out with RC 27, no message) showed the original wording ("confirm... the retained payload is now empty") doesn't match what actually happens on the wire — a cleared retained topic delivers nothing, it doesn't deliver an empty payload — so a reader following the original command verbatim (no `-C`/`-W`) would see no output and have no way to know whether that means "cleared" or "still hanging."

## Deviations from Plan

None — plan executed exactly as written. Task 1's live checkpoint was collected by the developer directly on the deployment host (not simulated or re-run by this executor, per explicit instruction); Task 2 consumed that evidence and made no corrections to source logic since every check passed.

## Issues Encountered

- `uv run ruff check` fails to spawn in this environment (`ruff` is not declared in `pyproject.toml`'s `dependency-groups.dev`) — same known gap plans 09-01/09-02/09-03 already documented. Used `uvx ruff check scripts/ src/ tests/` instead, this repo's own established substitution. Result: 7 findings, all in `src/checkmk_wizard/wizard.py:676` (B023), `tests/test_site.py` (SIM117 x4), and `tests/test_wizard.py:236` (RET501/PLR1711) — identical to the pre-existing set already logged in `.planning/phases/09-poller-core/deferred-items.md` by plan 09-01, none in the two files this plan touched (`uvx ruff check scripts/mqtt_poller.py` → `All checks passed!`). Not fixed, per the deviation rules' scope boundary; `deferred-items.md` unchanged since the findings are identical to what's already recorded there.

## User Setup Required

None — this plan's changes are documentation/comments only; no new configuration, credentials, or deployment steps introduced.

## Next Phase Readiness

- Phase 9's Livestatus column contract is now live-verified end to end, not assumed: `scripts/mqtt_poller.py` cites the exact date and site version, matching this repo's `api.py`/`site.py` citation convention.
- RESEARCH.md Assumptions A1-A4 are all closed: A1 (`parents`), A2 (`filename`), and A3's existence claim (`tags` present) confirmed; A3's key-shape claim is explicitly flagged as still open pending Phase 10 (recorded in-source, not silently assumed); A4 (reconciliation timing) confirmed via the observed 130s-quiet/38s-heartbeat window.
- Phase 11 (dashboard) inherits a poller whose live behavior — not just its unit-tested behavior — is now documented and proven against a real Checkmk 2.4.0p35 site and real Mosquitto broker.
- One open item carried forward for Phase 10: once a `device_type` Checkmk tag is actually assigned to a live host, re-confirm which key (`device_type` or `tag_device_type`) Livestatus's `tags` column actually uses, since `extract_device_type()` currently guesses both defensively but neither guess has been exercised against real tagged data.

## Self-Check: PASSED

- FOUND: `scripts/mqtt_poller.py` (Live-verified comment present)
- FOUND: `docs/Podman setup for checkmk, minio, mosquitto, worker.md` (Manual tombstone test corrected)
- FOUND commit: `8f3ebcd`
- Verified: `grep -q 'Live-verified' scripts/mqtt_poller.py` → match found
- Verified: `uv run pytest -q` → 304 passed
- Verified: `uvx ruff check scripts/ src/ tests/` → 7 pre-existing findings, none in files this plan touched (`uvx ruff check scripts/mqtt_poller.py` → All checks passed!); `uv run ruff check` itself is not runnable in this environment (documented, not a new gap)
- Verified: `git status --short` before commit showed only the two files this plan's `<files>` list names

---
*Phase: 09-poller-core*
*Completed: 2026-09-09*
