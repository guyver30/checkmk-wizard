---
phase: 10-checkmk-tag-group-onboarding-integration
plan: 02
subsystem: checkmk-tag-group-provisioning
tags: [checkmk, rest-api, host-tag-group, device-type, idempotent-provisioning]

# Dependency graph
requires:
  - phase: 10-01
    provides: "device_types.json, live-verified tag-group POST body shape (`id`, not `ident`), and the finding that a tag group's implicit default does not materialise as an explicit per-host attribute"
provides:
  - "CheckmkClient.create_host_tag_group() / get_host_tag_group(), both routed through _request()"
  - "wizard._load_device_types() — fail-loud config loader for device_types.json"
  - "wizard._ensure_device_type_tag_group() — idempotent create-once provisioning wired into phase2_folders, before the use_folders confirm"
  - "DEVICE_TYPE_TAG_GROUP_ID constant (single source of truth for the tag_device_type attribute key)"
affects:
  - "10-04 (derives tag_device_type attribute key from DEVICE_TYPE_TAG_GROUP_ID for OnboardedHost/_onboard_hosts)"
  - "10-06 (re-runs the Livestatus tags probe once a real device_type tag exists on a host)"

tech-stack:
  added: []
  patterns:
    - "Idempotent-create-with-status-report (get-then-create, print a summary line) mirroring phase2_folders's existing folder-creation pattern"

key-files:
  created: []
  modified:
    - src/checkmk_wizard/api.py
    - src/checkmk_wizard/wizard.py
    - tests/test_api.py
    - tests/test_wizard.py

key-decisions:
  - "Backfill count implemented as 'hosts lacking an explicit tag_device_type attribute' rather than 'hosts equal to other', per plan 10-01's live probe finding — see Deviations below"

patterns-established:
  - "Idempotent-create-with-status-report: check-then-create, console.print a summary line, wrap in try/except CheckmkAPIError and warn rather than abort"

requirements-completed: [TAG-01]

# Metrics
duration: 35min
completed: 2026-09-11
---

# Phase 10 Plan 02: Checkmk Tag-Group Provisioning Summary

**Wizard now creates the `device_type` host tag group exactly once (with `other` first) and reports how many pre-existing hosts the implicit default silently covered, counted by absence of an explicit `tag_device_type` attribute rather than by matching the default value.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-09-11T04:00:00Z (approx, worktree base reset)
- **Completed:** 2026-09-11T04:20:00Z
- **Tasks:** 2 completed
- **Files modified:** 4

## Accomplishments
- `CheckmkClient.create_host_tag_group()` / `get_host_tag_group()` added, both routed through `_request()`, using the live-verified `id`-keyed POST body shape confirmed by plan 10-01's probe run
- `_load_device_types()` validates `device_types.json` and fails loud (naming the file path) when the first entry isn't `other`
- `_ensure_device_type_tag_group()` idempotently provisions the tag group and prints a summary count of pre-existing hosts the default touched, wired into `phase2_folders` before the `use_folders` confirm and before Phase 3 stages any placeholder host

## Task Commits

Each task was committed atomically:

1. **Task 1: Add create_host_tag_group() and get_host_tag_group() to CheckmkClient** - `e13d30c` (feat)
2. **Task 2: Add the device_types loader and the idempotent tag-group provisioning step** - `9195205` (feat)

_No TDD RED/GREEN split was used — tests were written alongside each task's implementation and run together, per this codebase's existing test-per-behavior convention rather than a strict red-green cycle; all tests passed on first run once implementation matched behavior specs._

## Files Created/Modified
- `src/checkmk_wizard/api.py` - `get_host_tag_group()` (GET with `expect=(200, 404)`, no tilde-encoding), `create_host_tag_group()` (POST with `id`-keyed body, both routed through `_request()`)
- `src/checkmk_wizard/wizard.py` - `DEVICE_TYPE_TAG_GROUP_ID` constant, `_DEVICE_TYPES_PATH`, `_load_device_types()`, `_ensure_device_type_tag_group()`, wired into `phase2_folders` before the `use_folders` confirm
- `tests/test_api.py` - 6 new tests covering `get_host_tag_group`/`create_host_tag_group` idempotency, body shape, and error handling
- `tests/test_wizard.py` - 9 new tests covering `_load_device_types` validation, `_ensure_device_type_tag_group`'s no-op/create/backfill-count/failure paths, and `phase2_folders`'s wiring when folders are declined; the 3 pre-existing `test_phase2_folders_*` tests were updated to mock the new tag-group GET route (200, already-present) so they remain no-ops for the new provisioning step

## Decisions Made
- Backfill count counts hosts *lacking* an explicit `tag_device_type` attribute, not hosts whose attribute equals `other` — see Deviations below for why.
- The `# -- Phase 2: host tag groups --` section comment in `api.py` follows this codebase's existing convention of labeling `CheckmkClient` methods by which wizard phase (`phase1_site_bringup`..`phase7_activation`) calls them, since `_ensure_device_type_tag_group` is called from `phase2_folders` — this is a domain reference to the wizard's own phase numbering, not planning/GSD phase numbering.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug, prevented by live-verified finding] Backfill count uses "lacking explicit attribute" instead of "equals other"**
- **Found during:** Task 2 (writing `_ensure_device_type_tag_group`)
- **Issue:** The plan's own worked-example code (in 10-PATTERNS.md, mirroring 10-RESEARCH.md's prediction) counted hosts whose `extensions.attributes["tag_device_type"]` equals `choices[0]`. Plan 10-01's live probe against a real Checkmk 2.4.0p35 CE site confirmed a tag group's implicit first-tag default does NOT materialise as an explicit per-host attribute at all — that counting query always returns zero on every real site.
- **Fix:** Implemented the count as `sum(1 for h in hosts if "tag_device_type" not in h.get("extensions", {}).get("attributes", {}))` — counting hosts that have no explicit value for the group, which is the same set the implicit default silently covers.
- **Files modified:** `src/checkmk_wizard/wizard.py`
- **Verification:** `test_ensure_device_type_tag_group_prints_backfill_count` asserts a mocked 3-host `list_hosts()` response (2 without the attribute, 1 with an explicit `tag_device_type=ACS`) reports a count of 2.
- **Committed in:** `9195205` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — correctness fix mandated by live-verified evidence explicitly called out in this plan's prompt)
**Impact on plan:** Necessary correction; without it, D-08's backfill count would silently and permanently report zero on every real site. No scope creep — same function, same call site, only the counting predicate changed.

## Issues Encountered

The worktree's starting HEAD had diverged from the expected wave-1 completion commit (`446a870150a8afeff90be8c072cf0b3a5f8d691e`) — the branch's merge-base with that commit was an ancestor, not the commit itself, because the worktree had been created before wave-1's docs commits landed. Resolved per the `<worktree_branch_check>` protocol: verified the working tree was clean, then `git reset --hard` to the expected base commit before starting any task work. No uncommitted work was lost.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `DEVICE_TYPE_TAG_GROUP_ID` is available for plan 10-04 to derive the `tag_device_type` attribute key without repeating the literal string.
- The tag group is provisioned before any host onboarding happens in a fresh wizard run, so plan 10-04's per-host `device_type` prompt (Phase 4) and `create_host`/`update_host_attributes` calls (Phase 5) can rely on the group already existing.
- A3 (Livestatus `tags` key shape for `device_type` specifically) remains open per 10-01's findings — deferred to plan 10-06, unaffected by this plan.

## Self-Check

- `[ -f src/checkmk_wizard/api.py ]` and it contains `create_host_tag_group`/`get_host_tag_group` — checked below
- `[ -f src/checkmk_wizard/wizard.py ]` and it contains `_ensure_device_type_tag_group`/`_load_device_types` — checked below
- `git log --oneline --all | grep -q e13d30c` — checked below
- `git log --oneline --all | grep -q 9195205` — checked below
- `uv run pytest -q` exits 0 (322 passed) — checked below
- `uvx ruff check src/checkmk_wizard/api.py tests/test_api.py` exits 0 — checked below
- `uvx ruff check src/checkmk_wizard/wizard.py tests/test_wizard.py` shows only 3 pre-existing errors at lines this plan did not touch (verified via `git diff` hunk ranges) — not introduced by this plan, out of scope per the deviation rules' scope boundary

## Self-Check: PASSED

---
*Phase: 10-checkmk-tag-group-onboarding-integration*
*Completed: 2026-09-11*
