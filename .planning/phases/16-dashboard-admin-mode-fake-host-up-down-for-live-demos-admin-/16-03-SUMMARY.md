---
phase: 16-dashboard-admin-mode-fake-host-up-down-for-live-demos-admin-
plan: 03
subsystem: infra
tags: [mosquitto, acl, nginx, compose, smoke-test]
requires: []
provides:
  - wsadmin broker user (write admin/cmd only; read lan/#, admin/ack, admin/faked)
  - ADMIN_WS_PASSWORD generation and compose wiring
  - open /admin-config.json nginx location
  - live smoke checks for the wsadmin ACL
key-files:
  modified:
    - deploy/mosquitto.acl
    - deploy/compose.yaml
    - deploy/dashboard-nginx.conf
    - deploy/init-env.sh
    - deploy/.env.example
    - scripts/smoke_test_broker.py
decisions:
  - "D-06 amended (user-confirmed 2026-10-02): wsadmin also reads lan/# so the admin page uses one connection; it still cannot write under lan/"
  - "D-07: /admin-config.json is deliberately open on the demo network; ADMIN_ALLOW_CIDR deferred"
requirements: [D-06, D-07, D-09]
metrics:
  tasks: 2
  files: 6
completed: 2026-10-02
---

# Phase 16 Plan 03: wsadmin broker credential and delivery path Summary

Provisioned the `wsadmin` broker user (publish limited to `admin/cmd`), generated its password via init-env.sh, wired it through compose into mosquitto and the dashboard, exposed it on an exact-match open `/admin-config.json`, and added four live ACL smoke checks.

## Commits
- d82199b: wsadmin ACL, password generation, compose wiring, /admin-config.json (Task 1)
- bd32eb6: smoke checks in scripts/smoke_test_broker.py (Task 2)

## Verification actually run
- Task 1 verify script (pyyaml compose parse; every `${VAR}` in dashboard-nginx.conf is defined in dashboard env): printed `ok`.
- `bash -n deploy/init-env.sh`: exit 0; `ADMIN_WS_PASSWORD` occurrences in init-env.sh: 4; `readwrite` lines in the ACL: 1 (poller only); removed lines mentioning `config.json` in the nginx diff: 0.
- Task 2: `py_compile` OK, `--help` lists `--admin-ws-user`/`--admin-ws-password`, 4 new check functions, 0 `def test_`, `uvx ruff check` passed.
- NOT verified: the live smoke checks were not run against a broker (no live stack in this worktree); Plan 08 runs them.

## Deviations from Plan
None to behavior. Implementation note: the four checks share a private `_delivered()` helper (independent subscriber, bounded wait, SUBACK awaited before publishing) instead of four copies of the same code; the public check signatures match the plan.

## Threat Flags
None beyond the plan's register (T-16-10 accepted: open endpoint serves a write-capable login).

## Self-Check: PASSED
