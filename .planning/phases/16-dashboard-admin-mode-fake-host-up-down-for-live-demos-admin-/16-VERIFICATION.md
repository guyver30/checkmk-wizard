---
phase: 16-dashboard-admin-mode-fake-host-up-down-for-live-demos-admin-
verified: 2026-10-02T00:00:00Z
status: passed
score: 14/14 decisions verified; the 5 gap-closure behaviors and the banner count were confirmed live by the user on 2026-10-02
has_blocking_gaps: false
human_verification:
  - test: "Restore selected / Restore all on faked demo hosts"
    expected: "Hosts return to UP with PING OK (not CRITICAL); not counted as faked afterwards"
    why_human: "Needs the live Checkmk core (16-09 was unit-tested only)"
  - test: "Set UP on a managed switch whose children were cascaded UNREACHABLE"
    expected: "Children return to UP/OK, not CRITICAL"
    why_human: "Live core behavior"
  - test: "Leave faked hosts (DOWN/UNREACH/UP) for more than 5 minutes"
    expected: "No STALE; staleness stays near 0 (30 s keepalive)"
    why_human: "Time-based live behavior"
  - test: "Plain click on map node and tree row in ?admin=1; ctrl/cmd+click toggles; no host details"
    expected: "Selection only, no navigation"
    why_human: "Browser interaction (unit tested only)"
  - test: "Select all button"
    expected: "Selects exactly the listed hosts"
    why_human: "Browser interaction on the live stack"
  - test: "UAT step 13 (demo hosts not counted as faked) and step 14 (poller-down ack timeout)"
    expected: "Per 16-08-PLAN"
    why_human: "Skipped by user in UAT"
---

# Phase 16 Verification Report

**Goal:** Admin mode (`?admin=1`) lets an operator multi-select hosts (map, tree, folder) and send fake UP/DOWN/UNREACHABLE results via MQTT to the poller, which injects Livestatus commands so non-admin dashboards show them live.

**Status:** human_needed (no failures found; live re-verification of gap fixes outstanding)

## Evidence

| Check | Result |
|---|---|
| `uv run pytest -q` | 809 passed |
| dashboard-react `npm run test` | 43 files, 619 tests passed |
| dashboard-react typecheck | clean |
| Debt markers (TODO/FIXME/XXX/TBD) in poller, adminStore, AdminBar | none |

## Truths

| Truth | Status | Evidence |
|---|---|---|
| Core flow: ctrl+click select, Set DOWN/UP, confirm dialog, FAKED badge, wsadmin ACL, /admin-config.json, admin chrome only with ?admin=1 (D-06..D-09, D-12, D-13) | VERIFIED (live UAT) | 16-08 steps 2-7, smoke test 7/7 |
| D-01/D-02 managed cascade, UNREACHABLE stops at unmanaged switch | VERIFIED (live UAT) | steps 8, 9 |
| D-03 combined inferred switch card with faked children | VERIFIED (live UAT + tests) | step 9 |
| Folder selection incl. subfolders (D-17) | VERIFIED (live UAT) | step 10 |
| Persistence via Livestatus-derived faked set (D-10) | VERIFIED (live UAT) | step 11 |
| D-05 amended: restore = ENABLE_HOST_CHECK + UP + PING OK, no ENABLE_SVC_CHECK | VERIFIED in code, live pending | `build_admin_commands` (mqtt_poller.py:1269-1291); grep finds no `f"ENABLE_SVC_CHECK`; 386 poller tests; faked-set derivation skips enabled host checks |
| D-11 keepalive every 30 s, PROCESS_* only, runs on admin worker | VERIFIED in code, live pending | `ADMIN_FAKE_KEEPALIVE_INTERVAL_SECONDS=30` (1374), `build_admin_keepalive_commands` (1309), `maybe_keepalive` called from `_run` (1740) |
| Plain click selects, no details, ctrl/cmd toggles (admin only) | VERIFIED in code, live pending | `replaceSelection` wired in TopologyMap:504, TreeNode:172; store action; IndexRoute suppresses details; tests |
| Select all selects listed hosts only | VERIFIED in code, live pending | AdminBar:339 with `visibleHostIds` from IndexRoute tree model |
| Docs/CONTEXT amendments (16-11) | VERIFIED | commits 5672a58, 8c6767d |
| D-14 banner count | UNCERTAIN (unverifiable_runtime) | not explicitly confirmed in UAT |
| UAT 13 (demo hosts not counted as faked) and 14 (no-answer timeout) | UNCERTAIN (unverifiable_runtime) | skipped by user |

## Anti-patterns / notes
- ruff reports 7 pre-existing errors in tests/test_site.py and tests/test_wizard.py, identical at the pre-phase commit (not caused by this phase).
- Security note (D-07): /admin-config.json is open by design for a closed demo network.

## Gaps
None blocking. Outstanding items are the human verification entries in the frontmatter.

## Live re-verification (2026-10-02, user on the deploy host)
User reported "passed all items" for the human checks: Restore selected / Restore all return to UP with PING OK, Set UP on a managed switch restores its children, faked hosts stay fresh, plain click selects and ctrl/cmd+click toggles with no host details, Select all, and the banner count. UAT steps 13 and 14 were skipped by the user. Not tried live: Select all / commands with more than 200 hosts (the 200-host limit now fails with an error message instead of a hung dialog, unit-tested only).
