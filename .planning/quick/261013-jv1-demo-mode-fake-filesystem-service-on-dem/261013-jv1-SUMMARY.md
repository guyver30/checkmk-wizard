---
phase: quick-261013-jv1
plan: 01
subsystem: wizard demo mode, scripts
tags: [demo, livestatus, custom_checks, seeder]
key-files:
  modified:
    - src/checkmk_wizard/wizard.py
    - tests/test_wizard.py
    - scripts/seed_fake_history.py
    - tests/test_seed_fake_history.py
    - docs/WIZARD-OPERATION.md
    - "docs/Incident demo with fake check results.md"
metrics:
  completed: 2026-10-13
---

# Quick 261013-jv1: Demo-mode passive "Filesystem /" service and seeder-driven state

`checkmk-wizard --demo` gives each demo Linux host a passive `Filesystem /` service
(an "Integrate Nagios plugins" / `custom_checks` rule created before activation, initial OK
result with no perf data), and `scripts/seed_fake_history.py` sets that service's state and
`fs_used_percent` value from `--end/--warn/--crit` via Livestatus after the history insert.

## Commits

- f09caf6 feat(quick-261013-jv1): demo Linux hosts get a passive Filesystem / service
- 59262ef feat(quick-261013-jv1): seeder sets the faked service state and value from the seeded end value
- 3ffd8f1 docs(quick-261013-jv1): faked Filesystem / service in demo mode

## What changed

- wizard.py: `_DEMO_FILESYSTEM_SERVICE`, `_DEMO_FILESYSTEM_OUTPUT`, `_create_demo_filesystem_rule`
  (ruleset `custom_checks`, folder `/`, `host_name` one_of demo Linux hosts, value_raw
  `repr({"service_description": "Filesystem /", "has_perfdata": True})`), created in
  `phase7_activation` after the host_check_commands rule and before activation.
  `_fake_demo_hosts_up(..., fake_filesystem=...)` appends `DISABLE_SVC_CHECK` and an OK
  `PROCESS_SERVICE_CHECK_RESULT` (no `|`, no `;`) for Linux hosts only. Rule failure: yellow
  warning, no Filesystem commands, rest of demo flow unchanged.
- seed_fake_history.py: `check_state`, `perf_data`, `check_output`, `check_result_command`,
  `reset_command`; `--no-check-result`, `--livestatus-host`, `--livestatus-port` (env
  LIVESTATUS_HOST / LIVESTATUS_PORT, else `checkmk:6557`); `--service` rejects `;`; history is
  inserted first, then the result is sent; `--delete` resets to OK without perf data BEFORE the
  ClickHouse delete; `--dry-run` prints `Check result (not sent): ...`; Livestatus OSError prints
  the manual `lq` command and returns 1. It imports `checkmk_wizard.livestatus` via a
  `sys.path` insert of `<repo>/src` (stdlib only).
- No poller or dashboard code changed.

## Freshness reasoning

The host stays fresh through the existing always-up `host_check_commands` rule. The service is
passive (no command line: active checks off, no freshness), so its injected result is not
replaced by the core; the poller reads staleness only from the hosts table. A WARN/CRIT
`Filesystem /` raises the host's overall state through the poller's existing
`compute_overall_state` path for hosts without a `Check_MK Agent` service (by code reading, not
observed live).

## Verification actually run

- `uv run pytest -q` (full suite): 1278 passed.
- `uv run pytest tests/test_wizard.py -q -k "phase7 or demo"`: passed (31, at task 1).
- `uv run pytest tests/test_seed_fake_history.py -q`: 68 passed.
- Dry run defaults: prints `...;Filesystem /;1;WARN - ... 84.0% used ...|fs_used_percent=84.0;80;90;0;100`;
  `--end 92` prints state 2 (CRIT); `--end 70` prints state 0 (OK).
- `uvx ruff check` on the four touched Python files: 6 findings remain, all outside my changes
  (wizard.py B023 at ~1999 and two RUF100 noqa, tests/test_wizard.py I001 and RET501/PLR1711);
  the two findings my code introduced (import order/noqa in the seeder, ISC004 in wizard.py)
  were fixed before commit.

## NOT live-verified (mock/unit tested only)

1. `custom_checks` ruleset name and `value_raw` Python-literal dict shape on Checkmk 2.4.0p35
   (the REST rule POST is mocked in tests). The wizard prints a warning if the POST is rejected.
2. Whether adding the custom check removes Checkmk's implicit PING service (PING commands are
   then harmless no-ops, host stays UP via the host_check_commands rule).
3. That `PROCESS_SERVICE_CHECK_RESULT` splits `text|perfdata` on the pipe so the perf data lands
   in the service's perf_data (the poller's `parse_perf_data` then yields `fs_used_percent`).
4. That the dashboard disk gauge shows for a host with no agent and that a WARN/CRIT
   `Filesystem /` colours host, tree and map.
5. That the passive service stays put (does not go stale/UNKNOWN) over time.

## Operator verification steps

1. Run `deploy/run-wizard.sh --demo` (or `uv run checkmk-wizard --demo`), pick the demo Linux
   method for one host (e.g. `demo-lnx1`). In Checkmk check Setup > Services > Other services >
   Integrate Nagios plugins for the rule, and `Filesystem /` appears on the host as OK with
   the "no value seeded yet" text and no metric (also confirms PING state).
2. Optionally `GET /objects/rule/{id}` for the rule and compare `extensions.value_raw`.
3. Preview: `podman exec -it automation-worker bash -c "cd /app/checkmk-wizard && python3 scripts/seed_fake_history.py --host demo-lnx1 --dry-run"`.
4. Seed: same without `--dry-run`. Expect "Set Filesystem / on demo-lnx1 to WARN (84%) via Livestatus checkmk:6557."
5. Look for: in Checkmk the service `Filesystem /` WARN with a `fs_used_percent` metric of 84 and
   the 80/90 levels (checks item 3); in the dashboard the host WARN in tree/map, the disk gauge at
   84 % (item 4), and after a few poll cycles flat-tail history rows at 84.
6. Try `--end 92` (CRIT) and `--delete` (service back to OK without a value, history rows gone).
7. If the service does not exist, Checkmk ignores the result silently: re-check step 1.

## Deviations from Plan

None of substance. One note: the `ISC004` fix in wizard.py (parenthesised string pair) landed in
the Task 2 commit rather than Task 1.

## Known Stubs

None.

## Self-Check: PASSED

Commits f09caf6, 59262ef, 3ffd8f1 exist; modified files exist; full suite green.
