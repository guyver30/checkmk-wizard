---
phase: 16-dashboard-admin-mode-fake-host-up-down-for-live-demos-admin-
plan: 07
subsystem: docs
tags: [docs, admin-mode, runbook]
requires: ["16-02", "16-03", "16-05", "16-06"]
key-files:
  modified:
    - docs/Incident demo with fake check results.md
    - dashboard-react/README.md
    - docs/DEPLOY-NEW-MACHINE.md
    - docs/Podman setup for checkmk, minio, mosquitto, worker.md
    - README.md
    - CLAUDE.md
    - .planning/PROJECT.md
requirements-completed: [D-06, D-07, D-10, D-11, D-13, D-14]
completed: 2026-10-02
---

# Phase 16 Plan 07: Admin mode documentation Summary

Documented admin mode: a runbook section reproducing Scenarios A, B and C from the dashboard, the dashboard README contract (section 5e and the `/admin-config.json` note), the `ADMIN_WS_PASSWORD` env rows and upgrade procedure, the `wsadmin` broker user, a README pointer, and the dated constraint amendment in CLAUDE.md and PROJECT.md.

## Commits
- 9ee6391: runbook admin section and dashboard README
- a949071: deploy docs, Podman doc, top-level README, constraint amendment

## Verification (actually run)
- All plan grep checks: `?admin=1` present in both Task 1 files, "notification" 2 and "ClickHouse" 1 in the runbook, `ADMIN_WS_PASSWORD` 3 in each deploy doc, `wsadmin` 3 in the Podman doc, "Amended 2026-10-02, Phase 16" 1 in each of CLAUDE.md and PROJECT.md, `ADMIN MODE - ` exists in AdminBar.tsx, `admin=1` in README.md.
- `git diff --stat` for CLAUDE.md and PROJECT.md: exactly one changed line each.
- Not verified: the documented live checks (smoke test, `--check-columns`) were not run, since there is no live stack here; Plan 08 covers them.

## Deviations from Plan
- Docs state the payload shapes from the implemented `adminMode.ts` parsers and `publish_admin_faked`.
- The runbook describes Scenarios A and B as short click steps rather than exact card text.

## Known Stubs
None.

## Self-Check: PASSED
