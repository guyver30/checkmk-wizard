---
phase: quick-260906-jm0
plan: 01
subsystem: docs
tags: [podman, registries.conf, unqualified-search-registries, short-name-resolution]

# Dependency graph
requires:
  - phase: quick-260906-iwo
    provides: "Podman installation instructions for a fresh Linux machine (§1.1/§1.2 of the same doc)"
provides:
  - "Short-name registry-resolution fix documented as the final sub-topic of §1.1 Install Podman"
affects: [docs/Podman setup for checkmk, minio, mosquitto, worker.md, phase-08 readers following the Podman setup doc]

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"

key-decisions:
  - "Followed the doc's existing bold-lead-in convention (`**Short-name image resolution:**`) rather than adding a new heading level, per doc_conventions"

patterns-established: []

requirements-completed: [QUICK-260906-jm0]

# Metrics
duration: ~10min
completed: 2026-09-06
---

# Phase quick-260906-jm0: Add unqualified-search-registries fix to §1.1 Install Podman Summary

**Documented the fresh-Podman short-name image resolution failure and its `~/.config/containers/registries.conf` fix as the final bold-lead-in sub-topic of §1.1, so a reader following the doc doesn't hit a dead end at §4's `podman compose up -d`.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-09-06T06:00:00Z (approx)
- **Completed:** 2026-09-06T06:11:07Z
- **Tasks:** 1 completed
- **Files modified:** 1

## Accomplishments
- Added a `**Short-name image resolution:**` sub-topic to §1.1, immediately before `### 1.2.`, matching the existing `**Rootless UID/GID ranges:**` bold-lead-in pattern
- Documented the verbatim short-name resolution error (greppable via a ```text fence) and named which of the stack's four images fail (`checkmk/check-mk-raw`, `eclipse-mosquitto`, `minio/minio`) vs. which succeeds (`python:3.12-slim`, via Podman's built-in `shortnames.conf` alias) and why
- Explained the *why*: Podman's anti-typosquatting default refuses to guess a registry for an unqualified short name, and §1.1's own verify step passes anyway because it already uses the fully-qualified `docker.io/library/hello-world`
- Documented the fix (`~/.config/containers/registries.conf` rootless per-user override) with a security clause noting it declares a single intended registry rather than disabling Podman's protection
- Documented the recovery path: re-run `podman compose up -d`, no cleanup needed, because the three failed services never created a container object (failed at `podman run`, exit 125) and existing volumes/network are reused

## Task Commits

Each task was committed atomically:

1. **Task 1: Add short-name registry fix as the final sub-topic of §1.1** - `1e636aa` (docs)

_No plan-metadata commit yet — orchestrator handles the docs commit (SUMMARY.md/STATE.md) separately per constraints._

## Files Created/Modified
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` - Added the short-name registry-resolution fix as the last sub-topic of §1.1, immediately before `### 1.2.`; purely additive (24 insertions, 0 deletions)

## Decisions Made
- Used the existing bold-lead-in convention (`**Short-name image resolution:**`) instead of inventing a new heading level, per the plan's `doc_conventions` — no `### 1.1.1.` or `####` heading exists anywhere else in the file, so none was added here.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Doc change is self-contained and complete. §1.1 now warns a fresh-install reader about short-name resolution before they reach §4, closing the gap the plan identified. No blockers for subsequent work; Phase 08 (broker-infrastructure-hardening) execution is unaffected by this quick task.

---
*Phase: quick-260906-jm0*
*Completed: 2026-09-06*

## Self-Check: PASSED

- FOUND: `docs/Podman setup for checkmk, minio, mosquitto, worker.md`
- FOUND: commit `1e636aa`
- FOUND: `.planning/quick/260906-jm0-add-unqualified-search-registries-fix-to/260906-jm0-SUMMARY.md`
