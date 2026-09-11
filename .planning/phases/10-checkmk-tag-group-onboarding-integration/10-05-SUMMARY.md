---
phase: 10-checkmk-tag-group-onboarding-integration
plan: 05
subsystem: infra
tags: [podman, compose, mqtt, checkmk-rest-api, smoke-test, docs]

# Dependency graph
requires:
  - phase: 10-checkmk-tag-group-onboarding-integration
    provides: "10-03's mqtt_poller.py REST folder lookup (fetch_host_folders, PollerConfig.cmk_rest_* fields, alias in DeviceSnapshot/payloads)"
provides:
  - "deploy/compose.yaml poller service now declares every CMK_REST_* variable PollerConfig.from_env reads"
  - "scripts/smoke_test_poller.py check_device_enrichment, distinguishing stale-poller-code, missing-CMK_REST_SECRET, and WR-07 filesystem-path regressions"
  - "operator-facing documentation for provisioning the poller's automation secret and the updated MQTT payload contract"
affects: [11-dashboard-topology-visualization]

# Tech tracking
tech-stack:
  added: []
  patterns: ["compose env-var indirection with a checked-in obvious placeholder for a secret that must be provisioned out-of-band, mirroring the existing CMK_PASSWORD/MQTT_PASSWORD/minioadmin trust model"]

key-files:
  created: []
  modified:
    - deploy/compose.yaml
    - scripts/smoke_test_poller.py
    - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"

key-decisions:
  - "CMK_REST_SECRET ships as the literal placeholder REPLACE_ME in deploy/compose.yaml rather than a separate secrets file or .env, matching this stack's existing checked-in-placeholder pattern for CMK_PASSWORD/MQTT_PASSWORD/minioadmin (IN-02) — no .gitignore change needed since no new file was introduced"
  - "Fixed a pre-existing bug in scripts/smoke_test_poller.py's _DEVICE_STATUS_KEYS/_TOPOLOGY_NODE_KEYS (Rule 1): they didn't include the alias key plan 10-03 added to the live payload, so the existing check_device_status_retained's strict set-equality check would fail-loud on any real 10-03 deployment"

requirements-completed: [TAG-03]

# Metrics
duration: 25min
completed: 2026-09-11
---

# Phase 10 Plan 05: Poller REST Credential Wiring Summary

**Wired the poller's CMK_REST_* credentials into deploy/compose.yaml, added a smoke-test check proving the alias/folder enrichment reached the broker, and documented how to provision the automation secret.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-09-11T04:08:00Z
- **Completed:** 2026-09-11T04:33:19Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- `deploy/compose.yaml`'s `poller` service now declares `CMK_REST_HOST`, `CMK_REST_PORT`, `CMK_SITE_ID`, `CMK_REST_USERNAME`, and `CMK_REST_SECRET` (the last an obvious `REPLACE_ME` placeholder), closing the gap that made plan 10-03's folder lookup silently return empty folders in the deployed stack.
- Added `check_device_enrichment` to `scripts/smoke_test_poller.py`, which fails loudly and with an actionable message for three distinct failure modes (stale poller code, missing/wrong `CMK_REST_SECRET`, and the WR-07 filesystem-path regression) instead of all three looking like a generic empty field.
- Documented the poller's REST credential provisioning path and the updated MQTT topic contract (`alias` added to `lan/devices/{id}/status` and `lan/devices/topology`) in the Podman setup doc, with the new smoke-test check routed back to the credential setup section.

## Task Commits

Each task was committed atomically:

1. **Task 1: Declare the poller's REST credentials in deploy/compose.yaml** - `375c501` (feat)
2. **Task 2: Add a smoke-test check proving the location and alias enrichment reached the broker** - `8b8c8a4` (feat)
3. **Task 3: Document the poller REST credential and the updated topic contract** - `ab1ba43` (docs)

_Note: no plan-metadata commit is created by this executor — the orchestrator owns STATE.md/ROADMAP.md writes per this plan's execution instructions._

## Files Created/Modified
- `deploy/compose.yaml` - poller service gains a `CMK_REST_*` environment block with a comment explaining the placeholder, the silent-degradation failure mode, and where to get the real secret
- `scripts/smoke_test_poller.py` - new `check_device_enrichment` check registered in `main()`; `_DEVICE_STATUS_KEYS`/`_TOPOLOGY_NODE_KEYS` widened to include `alias`; module docstring's per-check list extended
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` - new "Note on `CMK_REST_SECRET` (poller)" credential-setup paragraph, `alias` added to the topic contract table plus a `folder`/`alias` explanation paragraph, and a new bullet for `check_device_enrichment` in the "What each check proves" list

## Decisions Made
- Ship `CMK_REST_SECRET=REPLACE_ME` as a checked-in placeholder rather than introducing a new secrets file/`.env` mechanism — this matches the trust model this stack already uses for `CMK_PASSWORD`, `MQTT_PASSWORD`, and `minioadmin` (T-10-19/T-10-20 in the plan's threat model), and needed no `.gitignore` change since no new file was added.
- Left the poller's `command:` line untouched (`pip install --no-cache-dir paho-mqtt==2.1.0`) — the plan explicitly calls this out as a decision already made by 10-03 (stdlib `urllib.request` over adding an HTTP library), and an acceptance criterion enforces it.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Widened `_DEVICE_STATUS_KEYS`/`_TOPOLOGY_NODE_KEYS` to include `alias`**
- **Found during:** Task 2 (writing `check_device_enrichment`)
- **Issue:** `scripts/smoke_test_poller.py`'s existing `check_device_status_retained` asserts `set(data) != _DEVICE_STATUS_KEYS` (strict equality) against the retained `lan/devices/{id}/status` payload, but plan 10-03 added an `alias` key to that payload (`mqtt_poller.py:publish_device_status`) without updating this constant. Against any real post-10-03 deployment, this existing check would fail-loud on every retained payload — a pre-existing bug directly in the smoke-test file this plan owns and is extending.
- **Fix:** Added `alias` to `_DEVICE_STATUS_KEYS` and `_TOPOLOGY_NODE_KEYS` so both existing checks and the new `check_device_enrichment` agree on the live payload shape.
- **Files modified:** `scripts/smoke_test_poller.py`
- **Verification:** `uv run pytest -q` (337 passed) and `uvx ruff check scripts/` (clean) after the change; the mocked test suite doesn't exercise these live-only constants directly, so this was verified by inspection against `mqtt_poller.py`'s actual payload-building code (`publish_device_status`, `topology_nodes`) plus the file's own `check_device_status_retained`/`check_topology_retained` logic.
- **Committed in:** `8b8c8a4` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix)
**Impact on plan:** Necessary for the plan's own stated goal — without this fix, the pre-existing key-equality check would have failed on the very live payload this plan's new check is designed to validate, making the smoke test itself an obstacle rather than a proof. No scope creep beyond `scripts/smoke_test_poller.py`, a file this plan already owns.

## Issues Encountered
- `uv run ruff` is not available in this environment (`ruff` binary not on PATH inside the project's own venv); used `uvx ruff check scripts/` instead, which resolves and runs ruff standalone without modifying the project's dependencies. Result: all checks passed.
- The plan's Task 1 verify command (`uv run python -c "import yaml, ..."`) needs PyYAML, which is not a project dependency (correctly — this repo has no YAML-parsing runtime need). Ran the verification via `uv run --with pyyaml python -c "..."` (an ephemeral, one-off environment, not a `uv add`) rather than adding `pyyaml` to `pyproject.toml`. This is a one-off verification tool per this repo's own tooling conventions (`uvx`/`--with` for standalone checks), not a project dependency change.

## User Setup Required

**External service requires manual configuration.** The poller's `CMK_REST_SECRET` placeholder (`REPLACE_ME` in `deploy/compose.yaml`) must be replaced with the real Checkmk automation-user secret before the folder enrichment will work:
- Run the checkmk-wizard's Phase 1 bootstrap once (creates the `automation` user and its secret).
- Get the secret from the Checkmk UI (Setup -> Users -> `automation` -> Automation secret), or read `/omd/sites/dmc/var/check_mk/web/automation/automation.secret` inside the `checkmk` container.
- Edit the real value into `deploy/compose.yaml`'s `CMK_REST_SECRET` line (or supply it via an environment override), then run `podman compose up -d poller` to pick it up.
- Verify with `uv run python scripts/smoke_test_poller.py` (or, from inside `worker`, `--host mosquitto --livestatus-host checkmk --skip-restart-checks`) — the new `check_device_enrichment` check will report `[PASS]` once at least one device has a non-empty `folder`.

Full instructions: "Note on `CMK_REST_SECRET` (poller)" in `docs/Podman setup for checkmk, minio, mosquitto, worker.md` §3.

## Verification Status

The following were actually run and observed in this worktree (not a live deployment host):
- `uv run --with pyyaml python -c "..."` (Task 1's YAML-parse check) — passed, `missing: set()`.
- `grep -c 'paho-mqtt==2.1.0' deploy/compose.yaml` — returned `1`; poller `command:` line unchanged.
- `uv run python scripts/smoke_test_poller.py --help` — exited 0.
- `uvx ruff check scripts/` — "All checks passed!".
- `uv run pytest -q` — `337 passed`, matching the baseline (no regression).
- Doc string-presence checks (`CMK_REST_SECRET`, `CMK_REST_USERNAME`, `alias` count, no stray `vlan` payload key, heading levels unchanged) — verified via direct file inspection.

**Not verified** (needs a live deployed stack, which this worktree does not have): that `check_device_enrichment` actually connects to a running broker and correctly distinguishes the three failure modes against real retained payloads, and that a `podman compose up -d poller` with a real `CMK_REST_SECRET` produces non-empty `folder` values end-to-end. These require the operator's own deployment host per the "User Setup Required" section above.

## Next Phase Readiness
- TAG-03's end-to-end half is now closed: the poller has every credential it needs declared (pending the operator supplying the real secret), and a smoke-test check exists to prove or diagnose the enrichment on a live stack.
- Phase 11 (dashboard) can rely on `alias` and `folder` being present in the live MQTT payload contract once the operator completes the one-time secret provisioning step documented here.

---
*Phase: 10-checkmk-tag-group-onboarding-integration*
*Completed: 2026-09-11*
