---
phase: 09-poller-core
plan: 03
subsystem: infra
tags: [mqtt, livestatus, poller, checkmk, paho-mqtt, podman-compose, python]

# Dependency graph
requires:
  - phase: 09-poller-core
    plan: 02
    provides: "scripts/mqtt_poller.py's complete, runnable poller daemon (build_mqtt_client, publish helpers, reconcile_state, run_cycle, run_forever, main) and its fixed MQTT topic/payload contract"
provides:
  - "deploy/compose.yaml: a fifth `poller` service that runs scripts/mqtt_poller.py unattended, restart: unless-stopped, entirely configured via environment variables, bind-mounting the git-tracked scripts/ directory read-only"
  - "scripts/smoke_test_poller.py: standalone live-verification script proving the live Livestatus column set and four of the five Phase 9 success criteria against a running stack"
  - "Operator documentation for the poller service, its MQTT topic contract, and its smoke test in docs/Podman setup for checkmk, minio, mosquitto, worker.md"
affects: [11-dashboard]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "importlib.util.spec_from_file_location to load a sibling scripts/*.py module by path, with the loaded module registered in sys.modules[spec.name] BEFORE exec_module -- required for @dataclass decorators in the loaded module to resolve string annotations (from __future__ import annotations) via sys.modules[cls.__module__] without an AttributeError"
    - "Live smoke-test scripts prove behavior a mocked pytest suite structurally cannot: scripts/smoke_test_poller.py is the Phase 9 counterpart to scripts/smoke_test_broker.py (Phase 8), same standalone/not-pytest-collected/PASS-FAIL-line convention"
    - "Compose service bind-mounts the git-tracked scripts/ directory read-only rather than the uncommitted ./app dir the worker service uses, so a fresh checkout deploys the poller without a manual copy step"

key-files:
  created:
    - scripts/smoke_test_poller.py
  modified:
    - deploy/compose.yaml
    - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"

key-decisions:
  - "Registered the dynamically-loaded mqtt_poller module in sys.modules[spec.name] before calling spec.loader.exec_module() -- without this, mqtt_poller.py's @dataclass decorators raise AttributeError: 'NoneType' object has no attribute '__dict__' when Python's dataclasses machinery tries to resolve string type annotations via sys.modules[cls.__module__], since the module isn't registered under that name yet at class-definition time. This is a general importlib.util.spec_from_file_location pitfall for any target module using `from __future__ import annotations` with dataclasses, not specific to this script."
  - "check_device_status_retained asserts that AT LEAST ONE retained lan/devices/{id}/status payload matches the fixed contract (not that every payload does), matching the plan's literal wording -- a single malformed/legacy payload among many devices doesn't fail the whole check"
  - "check_lwt_offline always issues --start-cmd once the offline assertion has been checked, regardless of whether that assertion passed, so a failed check never leaves the poller killed and down for the next operator"
  - "Restructured docs §2's directory tree so deploy/ is shown living inside the checkout (checkmk-stack/app/checkmk-wizard/deploy/) rather than a separate copy/symlink at checkmk-stack/deploy/, since the poller's ../scripts bind mount only resolves against the repo's own git-tracked scripts/ directory when deploy/ is the checkout's own directory"

requirements-completed: [PLR-01, PLR-04, PLR-05, PLR-06, PLR-07]

# Metrics
duration: ~45min
completed: 2026-09-06
---

# Phase 9 Plan 3: Poller Deployment & Live Verification Summary

**A fifth `poller` compose service runs `scripts/mqtt_poller.py` unattended with `restart: unless-stopped`, `scripts/smoke_test_poller.py` proves four of the five Phase 9 success criteria against a live stack in one command, and the setup doc documents both plus the full MQTT topic contract.**

## Performance

- **Duration:** ~45 min
- **Completed:** 2026-09-06
- **Tasks:** 3/3 completed
- **Files modified:** 3 (`deploy/compose.yaml`, `docs/Podman setup for checkmk, minio, mosquitto, worker.md` modified; `scripts/smoke_test_poller.py` created)

## Accomplishments

- `deploy/compose.yaml` gains a `poller` service (`container_name: mqtt-poller`, `restart: unless-stopped`) that bind-mounts the git-tracked `scripts/` directory read-only (`${POLLER_SCRIPTS_DIR:-../scripts}:/scripts:ro,z`) instead of the uncommitted `./app` dir the `worker` service uses, installs a pinned `paho-mqtt==2.1.0`, and configures all eleven `PollerConfig.from_env()` settings plus `PYTHONUNBUFFERED=1` via environment variables — no config file, no published port, no new top-level volume
- `scripts/smoke_test_poller.py` (604 lines) is a standalone, manually-invoked live-verification script that loads `scripts/mqtt_poller.py` via `importlib.util.spec_from_file_location` so it can never drift from the poller's own column/topic contract, then runs seven checks: `check_livestatus_columns` (live column presence, RESEARCH.md Open Question 1), `check_device_status_retained` (Success Criterion 1), `check_topology_retained` (payload half of PLR-01/PLR-04), `check_poller_liveness` (positive half of Success Criterion 5), `check_topology_quiet` (Success Criterion 3, `--skip-slow`), `check_ghost_tombstone` (Success Criterion 4, `--skip-restart-checks`), and `check_lwt_offline` (LWT half of Success Criterion 5, `--skip-restart-checks`)
- The setup doc's §2 now states the repo checkout must exist before `podman compose up` and that `podman compose` runs from the checkout's own `deploy/` directory (not a copy placed loose in `checkmk-stack/`), §3 names all five services and explains why the poller is its own service, §4 adds the working-directory command and `podman compose logs -f poller`, §6 adds a full MQTT topic contract table, and §7 adds a "Poller smoke test" subsection plus a "Manual tombstone test" paragraph for the one success criterion (real Checkmk host deletion) that isn't automated

## Task Commits

Each task was committed atomically:

1. **Task 1: Add the dedicated poller service to deploy/compose.yaml** — `b4b0da8` (feat)
2. **Task 2: Live verification script scripts/smoke_test_poller.py** — `1b99b03` (feat)
3. **Task 3: Document the poller service, its topic contract, and its smoke test** — `711651a` (docs)

## Files Created/Modified

- `deploy/compose.yaml` — Adds the `poller` service block (env vars, restart policy, bind mount, pinned dependency install)
- `scripts/smoke_test_poller.py` — New standalone live-verification script; 7 check functions plus `main()`, `_load_poller_module`, `_wait_for_retained_payload`, `_collect_retained`
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` — §2 (directory structure/working directory), §3 (five services), §4 (deployment commands), §6 (MQTT topic contract table), §7 (poller smoke test + manual tombstone test)

## Decisions Made

- Registered the dynamically-loaded `mqtt_poller` module into `sys.modules[spec.name]` before `spec.loader.exec_module()` — discovered this was required (not optional) when `--help` crashed with `AttributeError: 'NoneType' object has no attribute '__dict__'` from `mqtt_poller.py`'s `@dataclass` decorators trying to resolve `from __future__ import annotations` string type hints via `sys.modules[cls.__module__]`, which is `None` until the module is registered. Documented inline as a general `importlib.util.spec_from_file_location` + dataclasses pitfall.
- `check_device_status_retained` requires only one matching payload among all collected `lan/devices/+/status` retained messages, per the plan's literal "assert at least one payload... matches" wording, rather than failing on any single malformed payload.
- `check_lwt_offline` always runs `--start-cmd` after checking the offline assertion (pass or fail), so a failed check never leaves the poller down for the next operator to discover.
- Restructured the setup doc's §2 directory tree to show `deploy/` living inside the checkout (`checkmk-stack/app/checkmk-wizard/deploy/`) instead of a separate copy/symlink at `checkmk-stack/deploy/`, since the poller's `../scripts` bind mount only resolves against this repo's own git-tracked `scripts/` directory when `deploy/` is the checkout's own directory — not a documentation nicety, a correctness requirement for the new service to have a script to run.

## Deviations from Plan

None — plan executed exactly as written. The `sys.modules[spec.name]` registration fix falls under Rule 3 (auto-fix blocking issue): `--help` could not run at all without it, discovered during the plan's own `<verify>` step for Task 2, fixed inline, re-verified, and folded into the Task 2 commit before it was made (no separate fix commit needed since the bug was caught before the initial commit, not after).

## Issues Encountered

- Ran lint via `uvx ruff check` rather than the plan's literal `uv run ruff check`, for the same environment reason plans 09-01 and 09-02 already documented: `ruff` is not declared in `pyproject.toml`'s `dependency-groups.dev`, so `uv run ruff` fails to spawn (`Failed to spawn: ruff`). `uvx ruff check` is this repo's own documented convention for one-off tools and reproduces the identical result — `uvx ruff check scripts/` reports "All checks passed!".
- No podman/docker/mosquitto_sub/live Checkmk site available in this execution sandbox (same documented limitation as 09-RESEARCH.md's Environment Availability table) — `scripts/smoke_test_poller.py` was verified structurally (imports cleanly, `--help` exits 0 and lists all required flags, all seven check functions/`main() -> int` are present, no `except Exception`/`shell=True`, `spec_from_file_location` used) and functionally against unreachable endpoints (`--host 127.0.0.1 --tcp-port 1 --livestatus-host 127.0.0.1 --livestatus-port 1`), which produced clean `[FAIL] ...: [Errno 111] Connection refused` lines for every network-dependent check and a correct `[SUMMARY] one or more checks failed` / exit 1 — no traceback, no credential leakage. It was **not** run against a real broker or Checkmk site; that remains a deployment-host verification step, consistent with `scripts/smoke_test_broker.py`'s own established precedent (Phase 8).

## User Setup Required

None — no external service configuration required for this plan's own changes. Running `scripts/smoke_test_poller.py` for real (proving the five requirements it targets) requires a live deployment host with the full compose stack up, per the doc's own new "Poller smoke test" section — this is expected live verification, not a setup gap.

## Next Phase Readiness

- The poller is now fully deployable: `podman compose up -d poller` from the repo checkout's `deploy/` directory starts it with everything it needs (committed script, pinned dependency, Phase 8 broker credentials, all settings as env vars).
- `scripts/smoke_test_poller.py` gives an operator a single command to prove the live Livestatus column set and four of five Phase 9 success criteria; the fifth (real Checkmk host deletion) is a documented manual step.
- Live verification against a real deployment host (all seven smoke-test checks passing against real Mosquitto/Checkmk/poller containers) is the one item this plan could not execute in this sandbox and remains outstanding before Phase 9 is considered fully proven end-to-end — this mirrors the same gap 09-02's summary already flagged for its own unit-tested-only daemon.
- Phase 11 (dashboard) can now treat the MQTT topic/payload contract as both implemented (09-02) and operator-documented (this plan's §6 table) — no remaining ambiguity about what the poller publishes or how to verify it.

## Self-Check: PASSED

- FOUND: `deploy/compose.yaml` (poller service present)
- FOUND: `scripts/smoke_test_poller.py`
- FOUND: `docs/Podman setup for checkmk, minio, mosquitto, worker.md` (updated)
- FOUND commit: `b4b0da8`
- FOUND commit: `1b99b03`
- FOUND commit: `711651a`
- Verified: `uvx ruff check scripts/` → All checks passed!
- Verified: `uv run pytest -q` → 284 passed, nothing collected from `scripts/`
- Verified: `uv run python scripts/smoke_test_poller.py --help` → exit 0, lists `--skip-slow`, `--skip-restart-checks`, `--livestatus-host`, `--compose-dir`
- Verified: `deploy/compose.yaml` contains all eleven `<interfaces>` env vars, `paho-mqtt==2.1.0` (pinned), `POLLER_SCRIPTS_DIR`; `grep -c 'app:/app'` → 1 (worker's mount untouched); `grep -c 'ports:'` → 3 (poller publishes none)
- Verified: setup doc contains `MQTT topic contract`, `Poller smoke test`, `Manual tombstone test`, `POLLER_SCRIPTS_DIR`, `check-columns`; section heading count unchanged at 9

---
*Phase: 09-poller-core*
*Completed: 2026-09-06*
