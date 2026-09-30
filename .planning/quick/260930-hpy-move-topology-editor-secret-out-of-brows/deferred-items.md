# Deferred Items — quick 260930-hpy

Out-of-scope findings noticed during execution, not fixed per the scope
boundary rule (only auto-fix issues directly caused by this task's changes).

## B023 loop-variable binding warning in `src/checkmk_wizard/wizard.py:1595`

`uvx ruff check src/checkmk_wizard/wizard.py` reports:

```
B023 Function definition does not bind loop variable `task`
  --> src/checkmk_wizard/wizard.py:1595:33
```

This is pre-existing (confirmed present at commit `a548b45`, before this
quick task's changes) inside Phase 3's `phase3_discovery`/network-scan
progress-reporting closure, an area this plan's tasks never touch. Not
fixed here because it is unrelated to the topology_editor secret work.
Task 1's `<verify>` automated command chains `uvx ruff check` across
`api.py`/`wizard.py`/`provision_topology_editor.py` together, so this
pre-existing warning causes that combined command to exit 1 even though
every line this plan added or modified is ruff-clean on its own (verified
by running ruff against the diff hunks individually — see the plan's
SUMMARY.md for the exact commands run).
