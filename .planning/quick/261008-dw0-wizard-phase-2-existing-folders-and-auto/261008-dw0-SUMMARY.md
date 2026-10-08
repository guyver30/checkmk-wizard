---
phase: quick-261008-dw0
plan: 01
subsystem: wizard
tags: [phase2, folders, network-scan]
key-files:
  modified:
    - src/checkmk_wizard/wizard.py
    - tests/test_wizard.py
    - docs/WIZARD-OPERATION.md
completed: 2026-10-08
---

# Quick 261008-dw0: Phase 2 existing folders and monitored scan hosts

Phase 2 now lists and reuses a site's existing top-level folders (keep/replace scan, offline to prod upgrade), and Checkmk's per-folder network scan uses criticality "prod" so found hosts are monitored at once as device type "other".

## Commits
- 5d23280 feat: scan hosts as prod, `_top_level_folder_names`, `_network_scan_summary`, message text
- 93cb820 feat: Phase 2 existing-folder flow (`_prompt_folder_subnet`, `_configure_existing_folder`, reworked `phase2_folders`)
- docs commit: docs/WIZARD-OPERATION.md Phase 2/3 text

## Verification (actually run)
- `uv run pytest -q`: 1158 passed.
- `uvx ruff check src tests`: 8 findings, all pre-existing (B023 in wizard.py `task` loop variable, SIM117 x4 in tests/test_site.py, I001/RET501/PLR1711 in tests/test_wizard.py; the latter three confirmed identical on the base commit). No new findings.
- Every `update_folder_attributes` call in wizard.py carries only `network_scan` for existing folders.
- Docs checks: "prod" present, no "unmonitored, for manual review", exclusion-range caveat present.

## Deviations
- Minor: typing a folder name already handled in this run prints a dim "already set up" note and skips it (previously a duplicate name would attempt another create).
- Minor: IPv4-only skip for a given subnet on an existing folder falls through to the offline-to-prod offer rather than returning.
- Context7 was not queried again; the plan's interface notes (docs hosts_setup "Productive system" = immediate monitoring) were used as given.

## Unverified on this machine — operator checklist
1. Does Checkmk's network scan activate changes by itself for non-offline hosts? (docs say "immediate monitoring"; not confirmed) If not, activate pending changes after the first scan run.
2. Scan-found hosts appear on the dashboard as device type "other".
3. Caveat: anything answering ping becomes a monitored host; use Checkmk's network-scan exclusion ranges in the folder properties if needed (not set by the wizard).
4. The folder list/GET shape (`extensions.path`, `extensions.attributes.network_scan`) and Checkmk's duplicate-folder error response were coded defensively, not live-verified; the offline-to-prod PUT round-trips the GET shape, also not live-verified.

Nothing here was run against a live Checkmk; all REST behaviour is mocked with respx.
