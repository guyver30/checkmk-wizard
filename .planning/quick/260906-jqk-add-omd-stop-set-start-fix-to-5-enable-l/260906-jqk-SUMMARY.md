---
phase: quick-260906-jqk
plan: 01
subsystem: docs
tags: [checkmk, omd, livestatus, podman, documentation]

# Dependency graph
requires:
  - phase: quick-260906-iwo
    provides: docs/Podman setup for checkmk, minio, mosquitto, worker.md (base doc)
  - phase: quick-260906-jm0
    provides: §1.1/§1.2 unqualified-search-registries fix (prior quick task, untouched by this one)
provides:
  - §5's Livestatus-over-TCP enable sequence corrected from config/restart to stop/set/start
  - Rationale prose explaining omd's running-site config refusal and the no-data-loss guarantee
affects: [phase-08-broker-infrastructure-hardening, docs]

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"

key-decisions:
  - "Replaced the two-command config/restart sequence with a three-command stop/set/start sequence, confirmed working against a real Checkmk 2.4.0p35 CE site"

patterns-established: []

requirements-completed: [QUICK-260906-JQK]

# Metrics
duration: ~10min
completed: 2026-09-06
---

# Phase quick-260906-jqk: Fix §5 Livestatus-over-TCP enable sequence Summary

**§5's `omd config`/`omd restart` sequence, which fails on a freshly-started site with "Cannot change config variables while site is running.", replaced with a confirmed-working `omd stop`/`omd config`/`omd start` sequence plus rationale prose.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-09-06T06:07:57Z (approx)
- **Completed:** 2026-09-06T06:18:07Z
- **Tasks:** 1 completed
- **Files modified:** 1

## Accomplishments
- §5's bash fence now reads `omd stop dmc` / `omd config dmc set LIVESTATUS_TCP on` / `omd start dmc`, in that order — the sequence confirmed working on a real deployment host.
- Added a rationale paragraph explaining that `omd config ... set` refuses to change config on a running site (citing the exact error text) and that the stop/start loses no monitoring data (config change, not a data wipe; data lives in the `checkmk_data` volume).
- Updated the line-263 parenthetical aside so it names the new command trio instead of the stale `omd config`/`omd restart` reference.

## Task Commits

Each task was committed atomically:

1. **Task 1: Replace §5's command sequence with stop/set/start and add rationale prose** - `0753107` (fix)

**Plan metadata:** (handled by orchestrator's docs commit, not included here)

## Files Created/Modified
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` - §5's enable-Livestatus-TCP command sequence fixed and rationale prose added; §1.1, §1.2, §2, §3, §4, §6, §7, §8, §9 untouched

## Decisions Made
- Kept the new rationale paragraph as a single unwrapped line (matching the doc's existing per-paragraph style, e.g. lines 252/264/271), rather than hard-wrapping at ~100 chars — this was a minor style self-correction after the first pass, applied before committing, not a deviation from the plan's substance.

## Deviations from Plan

None - plan executed exactly as written. (One in-flight style adjustment — un-hard-wrapping the new paragraph to match the doc's existing single-line-per-paragraph convention — was made before the task commit and does not change the paragraph's content or the plan's success criteria.)

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required. This is a documentation-only fix; no code, dependencies, or runtime behavior changed.

## Next Phase Readiness
§5 now matches the confirmed-working command sequence for any reader following the doc after a fresh `podman compose up -d`. No blockers for phase-08 (broker-infrastructure-hardening) or future quick tasks touching this doc — §5 is now internally consistent (fence, rationale, and aside all agree on stop/set/start).

## Self-Check: PASSED

- FOUND: `docs/Podman setup for checkmk, minio, mosquitto, worker.md`
- FOUND: commit `0753107`

---
*Phase: quick-260906-jqk*
*Completed: 2026-09-06*
