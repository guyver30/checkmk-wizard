---
phase: 13-wizard-parents-support-and-topology-map
plan: 01
subsystem: infra
tags: [checkmk-rest, live-verification, probe]

# Dependency graph
requires: []
provides:
  - "scripts/probe_topology_rest.py: a stdlib-only, lint-clean probe covering P1-P6 (openapi-doc.yaml capability scan, built-in tag groups, unmanaged-switch attribute shape, parents/labels round-trip + collection visibility, CORS preflight, admin role permissions)"
affects: [13-04, 13-05, 13-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Live-verification probe scripts (stdlib-only urllib, env-var config, throwaway host create/delete in finally, never activates changes) — same convention as scripts/probe_host_attribute_merge.py and scripts/probe_checkmk_rest_shapes.py"

key-files:
  created: [scripts/probe_topology_rest.py]
  modified: []

key-decisions:
  - "Task 2's live probe run could not happen in this environment (no podman, no reachable Checkmk site) — execution is paused at the checkpoint, not skipped or simulated"

patterns-established:
  - "Pattern: OpenAPI paths/methods scanned via indentation-based regex (no YAML library) — see parse_openapi_paths()"

requirements-completed: []  # DASH-12/DASH-13/PLR-13 NOT complete — Task 2 (live run) and Task 3 (findings) remain

# Metrics
duration: ~15min (Task 1 only; plan paused before Tasks 2-3)
completed: 2026-09-23 (Task 1 only — plan NOT complete)
---

# Phase 13 Plan 01: Live REST Capability Probe Script (PAUSED)

**Status: PAUSED at Task 2's blocking human-verify checkpoint — resume required.**

`scripts/probe_topology_rest.py` (Task 1) is written, lint-clean, stdlib-only, and covers
P1-P6, but it has NOT been run against the real Checkmk deployment. Task 2 requires the
developer to run it on the live deployment host and paste back the complete stdout; Task 3
(recording findings in the docstring) cannot start until that output exists.

## Performance

- **Tasks attempted:** 1 of 3 (Task 1 complete; Task 2 blocking; Task 3 not started)
- **Files created:** 1

## Accomplishments

- `scripts/probe_topology_rest.py` created: a stdlib-only (`urllib.request`, `urllib.error`,
  `json`, `os`, `re`, `sys`) diagnostic probe that creates two throwaway hosts
  (`gsd-probe-topo-parent`, `gsd-probe-topo-child`), answers six REST-capability questions
  (P1-P6), and deletes both hosts in a `finally` block. It never calls Checkmk's
  changes-activation endpoint.
- All Task 1 acceptance criteria verified by actually running the commands (not inspected):
  - `uvx ruff check scripts/probe_topology_rest.py` → `All checks passed!`
  - `uv run python -c "import ast,sys; ast.parse(...)"` → parses cleanly
  - `grep -c "VERDICT V-" scripts/probe_topology_rest.py` → `13`
  - `grep -nE "^import (httpx|requests)|^from checkmk_wizard" ...` → no matches (stdlib-only confirmed)
  - All required literal strings present: `PROBE_PARENT = "gsd-probe-topo-parent"`,
    `PROBE_CHILD = "gsd-probe-topo-child"`, `openapi-doc.yaml`, `OPTIONS`, `unmanaged_switch`,
    `map_position`, `tag_address_family`
  - All required print-statement substrings present: `VERDICT V-SWITCH`, `VERDICT V-PARENTS`,
    `VERDICT V-LABELS`, `VERDICT V-LABELS-IN-COLLECTION`, `VERDICT V-CORS`, `user_role create:`,
    `user_role edit:`, `custom host attribute definition:`, `host_tag_group update:`
  - `grep -n "activate-changes/invoke" scripts/probe_topology_rest.py` → no matches (never activates)
  - Host deletion confirmed inside a `finally:` block (line 612 in the committed file)
  - `CMK_REST_SECRET= uv run python scripts/probe_topology_rest.py` → exited 1, printed
    `[FAIL] CMK_REST_SECRET is not set`, no traceback

## Task Commits

1. **Task 1: Write scripts/probe_topology_rest.py (P1-P6)** - `4cf9f24` (feat)

Task 2 (checkpoint:human-verify, gate="blocking") and Task 3 (record findings) were NOT
executed — see "Why paused" below.

## Files Created/Modified

- `scripts/probe_topology_rest.py` - stdlib-only live REST capability probe covering
  P1 (openapi-doc.yaml capability scan for user_role/custom-attribute/host_tag_group
  endpoints), P2 (built-in tag group contents), P3 (unmanaged-switch attribute shape),
  P4 (parents + label round-trip, labels-in-collection visibility), P5 (CORS preflight),
  P6 (admin role permissions), plus a final pending-changes count. No findings block yet —
  that is Task 3's job, once real output exists.

## Decisions Made

- Followed the plan's interface precedent (`scripts/probe_host_attribute_merge.py`) closely:
  single `_rest()` choke point, `ProbeError` for connection-level failures only, redacted
  `Authorization` header (`Bearer <username> ***`), throwaway-host cleanup in `finally`.
- P4's `VERDICT V-LABELS` combines two independently-tested label values across the run
  (P3's `map_position="120,-40"`, which has both a comma and a minus sign, and P4's own
  `map_position="0,0"`, which has only a comma) rather than relying on P4's PUT alone, since
  the plan's literal P4 label value (`"0,0"`) does not itself contain a minus sign. This is
  made explicit in the printed VERDICT line so a human reader can see exactly which value
  backs which half of the claim.
- P6's admin-permissions extraction tries three candidate `extensions` key names
  (`permissions`, `enabled_permissions`, `permission_list`) since the exact key Checkmk 2.4
  uses for a role's permission-id list was not confirmed by RESEARCH.md; if none match, the
  full `extensions` dict is printed so a human can locate the real key from the live output.

## Deviations from Plan

None - Task 1 executed exactly as written. No Rule 1/2/3 auto-fixes were needed.

## Why Paused (blocking checkpoint, not a deviation)

Task 2 is `type="checkpoint:human-verify" gate="blocking"`. Per its own text: "This development
machine has no podman and no reachable Checkmk site (confirmed during research). Do not run,
simulate or infer the probe's results." This worktree/execution environment has no `podman`,
no `docker`, and no reachable Checkmk site — confirmed again here (13-RESEARCH.md's own
Environment Availability table already recorded this same finding: `curl` to `localhost:8080`
timed out, no `docker`/`podman` present).

**No attempt was made to run, simulate, or fabricate probe output.** Task 3 (recording findings
in the docstring) was NOT started, because it depends entirely on the verbatim Task 2 output,
which does not exist yet.

## Issues Encountered

None beyond the expected environment gap (no live Checkmk site reachable), which is the
checkpoint's whole reason for existing.

## Resume Instructions

To complete this plan, the developer must:

1. On the deployment host (with podman and the live Checkmk site), pull commit `4cf9f24`
   (or later) into the repo checkout the `automation-worker` container mounts.
2. Run:
   ```
   podman exec -it automation-worker bash -c "cd /app/checkmk-wizard && python3 scripts/probe_topology_rest.py"
   ```
   (The worker container already carries `CMK_REST_HOST`/`CMK_REST_PORT`/`CMK_REST_USERNAME`/
   `CMK_REST_SECRET` and `CMK_SITE_ID` from compose.)
3. Paste the COMPLETE output back verbatim, including every `P1`..`P6` block and every
   `VERDICT` line, and the `=== Cleanup ===` section confirming both probe hosts were deleted
   (DELETE status 204 or 404 for each).
4. A continuation agent (or the same executor, re-invoked) then runs Task 3: append a dated
   `Live-verified against a real Checkmk <version> CE site on <date>:` findings block to the
   module docstring, with one `VERDICT V-<ID>:` line per id (`ROLE`, `PERMS`, `SWITCH`,
   `PARENTS`, `LABELS`, `LABELS-IN-COLLECTION`, `CORS`, `CUSTOMATTR`, `TAGPUT`), copied
   verbatim from the pasted output — never inferred or softened — plus a closing
   `Consequences for plans 13-04/13-05/13-06:` paragraph, per the plan's Task 3 `<action>`.
5. Only after Task 3 lands should STATE.md/ROADMAP.md be advanced past plan 13-01 and
   downstream plans 13-04/13-05/13-06 be planned/executed against its VERDICT lines.

## User Setup Required

None beyond the resume step above (running the script on the deployment host is itself the
required manual step, per Task 2's own design — this is not a new/separate setup requirement).

## Next Phase Readiness

**NOT ready.** Plans 13-04, 13-05, and 13-06 are documented (13-RESEARCH.md, this plan's
frontmatter `key_links`) as depending on this probe's `VERDICT` lines. Those lines do not
exist yet. Do not start 13-04/13-05/13-06 until this plan's Task 3 is complete with real,
live-sourced findings.

---
*Phase: 13-wizard-parents-support-and-topology-map*
*Completed: NOT COMPLETE — paused at Task 2 of 3, 2026-09-23*
