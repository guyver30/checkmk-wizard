---
phase: quick
plan: 260907-lwe
subsystem: cli
tags: [questionary, wizard, container-mode, ux]

# Dependency graph
requires: []
provides:
  - "_default_checkmk_host() helper picking 'checkmk' vs 'localhost' by container mode"
  - "CMK_PASSWORD-prefilled cmkadmin prompt in phase1_site_bringup()"
  - "worker service CMK_PASSWORD in deploy/compose.yaml so the new default has a value"
affects: [poller-core, container-mode-onboarding, operator-docs]

# Tech tracking
tech-stack:
  added: []
  patterns: ["container-mode-aware prompt defaults via a named helper, mirroring the existing CMK_SITE_ID pre-fill pattern"]

key-files:
  created: []
  modified:
    - src/checkmk_wizard/wizard.py
    - tests/test_wizard.py
    - deploy/compose.yaml
    - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
    - docs/WIZARD-OPERATION.md

key-decisions:
  - "Named _default_checkmk_host(container_mode) helper instead of an inline ternary, so both branches are unit-testable without a full host-native Phase 1 test harness"
  - "cmkadmin prompt message gets a conditional suffix (mentions CMK_PASSWORD only when it's actually set) rather than restructuring the prompt"

patterns-established:
  - "Container-mode env-var pre-fill pattern: os.environ.get(\"CMK_PASSWORD\", \"\") as default=, same as the existing CMK_SITE_ID pre-fill"

requirements-completed: [QUICK-260907-lwe]

# Metrics
duration: 3min
completed: 2026-09-07
---

# Phase quick Plan 260907-lwe: Fix container-mode UX in wizard.py defaults Summary

**Container-mode Phase 1 now pre-fills the Checkmk-host prompt with `checkmk` (was `localhost`, unreachable from the sibling worker container) and the cmkadmin prompt with `$CMK_PASSWORD` when set, closing the loop the compose stack already provides.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-09-07T07:55:37Z
- **Completed:** 2026-09-07T07:58:56Z
- **Tasks:** 2 completed
- **Files modified:** 5

## Accomplishments
- Added `_default_checkmk_host(container_mode)` returning `"checkmk"` in container mode and `"localhost"` in host-native mode, wired into the host prompt's `default=`.
- The cmkadmin `questionary.password` prompt now defaults to `os.environ.get("CMK_PASSWORD", "")`, masked as before, with a conditional message noting the pre-fill source; blank-means-skip still works when unset.
- Added `CMK_PASSWORD=cmkadmin` to the `worker` service in `deploy/compose.yaml` so the new default actually has a value in the documented stack.
- Synced `docs/Podman setup for checkmk, minio, mosquitto, worker.md` §8.3 and `docs/WIZARD-OPERATION.md` (container-mode walkthrough + Phase 1 step-by-step) to describe the new pre-filled behavior instead of "type this in manually."

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire container-mode defaults into the Phase 1 host and cmkadmin prompts** - `fe710b3` (feat)
2. **Task 2: Give the worker service CMK_PASSWORD and resync the operator docs** - `a6a4628` (docs)

**Plan metadata:** committed separately by the orchestrator (docs: complete plan)

## Files Created/Modified
- `src/checkmk_wizard/wizard.py` - new `_CONTAINER_MODE_CHECKMK_HOST` constant, `_default_checkmk_host()` helper, host-prompt default wired to it, cmkadmin prompt defaulted from `CMK_PASSWORD`
- `tests/test_wizard.py` - two unit tests for `_default_checkmk_host()` (both branches) and two container-mode `phase1_site_bringup()` tests asserting the recorded `default=` values with `CMK_PASSWORD` set/unset
- `deploy/compose.yaml` - `worker` service gains `CMK_PASSWORD=cmkadmin`, matching the `checkmk` service's value
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` - §8.3 Checkmk-host and cmkadmin bullets rewritten to describe pre-filled defaults
- `docs/WIZARD-OPERATION.md` - container-mode walkthrough and Phase 1 step 3 updated to document `_default_checkmk_host()` and the `CMK_PASSWORD` pre-fill

## Decisions Made
- Kept the change strictly inside the container-mode branch of `phase1_site_bringup()` plus the new constant/helper — no new env vars, no CLI flags, no config layer, matching the plan's explicit constraint.
- Left the Phase 5 `_resolve_agent_registration_server()` `localhost` discussion in `docs/WIZARD-OPERATION.md` (around the agent-registration section) untouched, per the plan — unrelated logic.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. Operators using the documented compose stack get the new default automatically once they redeploy with the updated `deploy/compose.yaml` (or set `CMK_PASSWORD` manually on their existing `worker` container).

## Next Phase Readiness

- No blockers. This was a standalone UX fix found during Phase 9 (poller-core) live verification; Phase 9 execution can resume independently.

---
*Phase: quick*
*Completed: 2026-09-07*

## Self-Check: PASSED

All files referenced in this summary exist on disk; commits `fe710b3` and `a6a4628` are present in git history. `uv run pytest -q` ran green (288 passed) after both task commits.
