---
phase: quick-261012-j6d
plan: 01
subsystem: wizard demo mode, demo tooling
tags: [demo, wizard, clickhouse, forecast, trend-need]
requires: []
provides:
  - "wizard --demo can create a Linux agent demo host with no network step"
  - "scripts/seed_fake_history.py: synthetic metric history seed / delete / dry-run"
affects: [src/checkmk_wizard/wizard.py, scripts/seed_fake_history.py]
key-files:
  created:
    - scripts/seed_fake_history.py
    - tests/test_seed_fake_history.py
  modified:
    - src/checkmk_wizard/wizard.py
    - tests/test_wizard.py
    - docs/WIZARD-OPERATION.md
    - "docs/Incident demo with fake check results.md"
key-decisions:
  - "phase6_discovery gets an extra demo_hostnames kwarg so run() does not skip discovery for real Linux hosts handed over by the services step"
  - "Seed timestamps are anchored on the last point (exactly now), so the first row can be later than now - days when days*24 is not a multiple of step"
metrics:
  tasks: 3
  completed: 2026-10-12
---

# Quick 261012-j6d: Demo Linux agent host and seeded metric history Summary

Wizard `--demo` can create a Linux agent demo host with no SSH/agent/discovery step and fakes it UP via Check_MK / Check_MK Discovery; `scripts/seed_fake_history.py` backfills a synthetic ClickHouse metric series so the forecast chart and trend need fire on demand.

## Commits

- 5bba7a2 feat(quick-261012-j6d): demo mode can create Linux agent demo hosts without network steps
- a238263 feat(quick-261012-j6d): add seed_fake_history.py for forecast and trend-need demos
- c880d98 docs(quick-261012-j6d): runbook for demo Linux host and seeded metric history

## What changed

1. Wizard (`wizard.py`): Phase 4 demo label for the linux method; `_onboard_hosts`/`phase5_onboarding(demo=)` create demo linux hosts as `cmk-agent`/`no-snmp` hosts and skip every prompt and remote call; `phase6_discovery(demo=, demo_hostnames=)` skips discovery for them; `_fake_demo_hosts_up` sends DISABLE_SVC_CHECK + PROCESS_SERVICE_CHECK_RESULT for `Check_MK` and `Check_MK Discovery` instead of PING for linux hosts; `run()` passes `demo` through. Ping demo hosts and non-demo runs unchanged.
2. `scripts/seed_fake_history.py` (stdlib only, imports fit/rules/config from `analytics/`): `--dry-run` preview, insert as poller_writer in batches of 5000, `--delete` as ch_admin with `mutations_sync=1`, strict argument validation, `--env-file`/`deploy/.env` loading.
3. Docs: WIZARD-OPERATION.md (entry point, Phases 4-7) and a new runbook section in `Incident demo with fake check results.md`.

## Verification actually run

- `uv run pytest -q`: 1251 passed (tests/test_wizard.py 334, tests/test_seed_fake_history.py 47).
- `uv run python scripts/seed_fake_history.py --host demo-lnx1 --dry-run`: trending, slope 0.399/day, r2 0.999, 15.5 days to crit (date), tier urgent, confidence medium, no network. Also checked `--end 89` gives immediate, `--start 30 --end 60` standard, `--days 75 --noise 0.2` confidence high (the runbook's steering table).
- `uvx ruff check` on the new script/test files: clean. wizard.py and test_wizard.py keep their pre-existing ruff findings (same counts as HEAD, none new).

## NOT live-verified

Nothing here was run against a live Checkmk or ClickHouse (no site on this machine). Open live-verification points:

1. What an agent host (tag_agent cmk-agent) with no reachable agent looks like in Livestatus/Checkmk 2.4.0p35 CE: that it has a `Check_MK` service from activation even without discovery, that `Check_MK Discovery` exists by default (periodic discovery rule) and when it first runs, and whether other services appear.
2. Whether DISABLE_SVC_CHECK + PROCESS_SERVICE_CHECK_RESULT on `Check_MK` / `Check_MK Discovery` sticks under the CE Nagios core (the Check_MK service is the agent fetcher; a disabled active check should not reschedule).
3. Whether the "Always assume host to be up" host_check_commands rule (value_raw "'ok'", itself not yet live-verified) is enough to keep an agent host UP and fresh (no STALE) when the agent never answers; and that the dashboard poller then treats the host as a non-agent host (no `Check_MK Agent` service, so `apply_visible_service_state` keeps the Livestatus host state) and lists Check_MK / Check_MK Discovery in its service table.
4. That ClickHouse accepts the backdated JSONEachRow insert into partitions older than 31 days (TTL move to the s3 volume) without error, and that ALTER TABLE ... DELETE with mutations_sync=1 over HTTP as ch_admin completes.
5. That the dashboard shows the forecast and trend need for a host with no live Filesystem service (forecast list comes from the retained lan/forecasts/{host} topic, so it should).

Also unverified: the script's request shapes were checked only against a faked `urlopen`; the dry-run predicts analytics from code defaults and cannot see the analytics container's env overrides.

## Deviations from Plan

**1. [Rule 1 - Bug] `phase6_discovery` extra `demo_hostnames` kwarg**
- **Found during:** Task 1
- **Issue:** `run()` hands `onboarded + service_hosts` to phase 6, and service hosts (existing real hosts from the services step) are `os_family="linux"`; a plain `demo=True` skip would have skipped discovery for real hosts.
- **Fix:** optional `demo_hostnames` set; `run()` passes the names of the hosts onboarded this run. Without it all linux hosts are treated as demo (the plan's literal behaviour). Test added.
- **Files:** src/checkmk_wizard/wizard.py, tests/test_wizard.py (commit 5bba7a2)

**2. [Detail] Phase 5 still calls `_resolve_agent_registration_server`**, but with the list excluding demo linux hosts, so it never prompts (it only prompts for a non-loopback linux/windows host). The test asserts it receives an empty list.

**3. [Detail] Sawtooth first point:** the first generated row falls on a period boundary and so sits at the tooth top; with 30 days / period 10 there are three drops, not two. Harmless for the fit (only the last tooth is kept).

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model (T-j6d-01..05 mitigations implemented: input regex/charset validation before SQL, password only in header and never printed, delete pinned to host AND service AND metric, constant `;`-free Livestatus texts; tests assert these).

## Self-Check: PASSED

- scripts/seed_fake_history.py, tests/test_seed_fake_history.py, this SUMMARY exist.
- Commits 5bba7a2, a238263, c880d98 present in `git log`.
