---
phase: quick-261008-d0w
plan: 01
completed: 2026-10-08
commits: [d44199c, 10520ab, 839342a]
---

# Quick 261008-d0w: CPU load end to end

Wizard default CPU load levels 1.5/2.0 per core, poller `cpu_load*` gauge keys, CPU load counted towards agent host state, analytics need on WARN (urgent) / CRIT (immediate), dashboard Load gauge.

## Commits
- d44199c Task A: wizard default, docstring on non-idempotent `_create_threshold_rules`, test, docs "Existing sites"
- 10520ab Task B: poller gauge + visible state, analytics rule, tests, MQTT docs
- 839342a Task C: dashboard types, helpers, gauge, tests, README, 12-UI-SPEC amendment

## Verification (actually run)
- `uv run pytest -q`: 1144 passed
- `cd dashboard-react && npm test`: 60 files, 840 tests passed; `npx tsc --noEmit -p .`: exit 0
- ruff on changed files: 4 findings, all pre-existing and outside lines touched (wizard.py:1777 B023; tests/test_wizard.py I001, RET501, PLR1711). `ruff check` on scripts/mqtt_poller.py, analytics/rules.py and the changed poller/analytics tests: clean.

## Perf-data verification
Context7 query tool was not exposed in this session (`query-docs` unavailable), so I read the Checkmk 2.4.0 source on GitHub instead: `cmk/plugins/lib/cpu_load.py`. It confirms metric names `load1`/`load5`/`load15` (`metric_name=f"load{avg}"`) and that warn/crit are absolute (rule levels are per core, `levels_upper = (levels[0]*num_cpus, levels[1]*num_cpus)`). Cited in the poller comment. Not checked against a live site's actual perf data.

## Deviations
- Task A: the existing wizard tests already used `_DEFAULT_CPU_LOAD_LEVELS` symbolically; I changed the default-path assertion to literal (1.5, 2.0) plus an explicit constant assertion.
- Task B: the existing `test_no_failure_need_for_unchosen_service` was parametrized "CPU load" CRIT (the bug); replaced with "Systemd Timesyncd Time" and both WARN and CRIT states. Also added a "CPU load" row to no services-topic example (not needed).
- Setup: worktree HEAD was not at the expected base; reset to e590782 as instructed.

## Not live-verified
No live Checkmk/podman stack was available: the real `CPU load` perf-data on a live host, the gauge on the running dashboard, the host going WARN, and the urgent need appearing in a live analytics container are all unverified; only unit/component tests ran. Existing sites must edit the existing CPU load rule (documented) for 1.5/2.0 to take effect.

## Known stubs
None.

## Self-Check: PASSED (commits d44199c, 10520ab, 839342a present; full Python and dashboard suites green)
