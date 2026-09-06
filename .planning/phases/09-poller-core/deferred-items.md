# Deferred Items — Phase 09 (poller-core)

Out-of-scope lint findings discovered while running `uvx ruff check scripts/ src/ tests/`
during 09-01 execution. All are pre-existing (predate this plan's changes —
confirmed via `git status --short` showing only `scripts/mqtt_poller.py` and
`tests/test_mqtt_poller.py` as new files) and none are in files this plan
touched. Not fixed, per the deviation rules' scope boundary.

| File | Rule | Description |
|------|------|-------------|
| `src/checkmk_wizard/wizard.py:676` | B023 | `on_progress` closure does not bind the `task` loop variable |
| `tests/test_site.py:45,67,89,175` | SIM117 | Nested `with` statements could be combined into one |
| `tests/test_wizard.py:236` | RET501 / PLR1711 | Explicit `return None` / useless `return` at end of function |
