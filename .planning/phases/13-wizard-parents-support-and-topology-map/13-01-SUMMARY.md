---
phase: 13-wizard-parents-support-and-topology-map
plan: 01
subsystem: infra
tags: [checkmk-rest, live-verification, probe]

# Dependency graph
requires: []
provides:
  - "scripts/probe_topology_rest.py: a stdlib-only, lint-clean probe covering P1-P6 (openapi-doc.yaml capability scan, built-in tag groups, unmanaged-switch attribute shape, parents/labels round-trip + collection visibility, CORS preflight, admin role permissions), with a dated Live-verified findings block recording one VERDICT per question"
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
  - "V-ROLE: role creation/edit is available over REST (POST /domain-types/user_role/collections/all, PUT /objects/user_role/{role_id}) — plan 13-04 provisions topology_editor over REST, not a manual GUI step"
  - "V-PERMS: topology_editor needs exactly wato.use, wato.edit, wato.all_folders, wato.edit_hosts, wato.manage_hosts, wato.activate; wato.activateforeign is deliberately excluded even though present on the admin role"
  - "V-SWITCH: the unmanaged-switch attribute dict is {'tag_address_family': 'no-ip', 'tag_agent': 'no-agent', 'tag_snmp_ds': 'no-snmp', 'tag_device_type': 'NetworkDevice'}, accepted on the first attempt with no fallback variant needed"
  - "V-CORS: NOT ALLOWED (OPTIONS preflight returned 405, no Access-Control-* headers) — plan 13-05's browser dashboard cannot call Checkmk cross-origin and needs a same-origin proxy"
  - "V-LABELS-IN-COLLECTION: YES — plan 13-04's poller can read map_position and other labels straight from the host_config collection response it already polls, no extra per-host GET"
  - "V-CUSTOMATTR: custom host attribute definitions are not creatable over REST; map_position stays a host label, meeting D-07's Checkmk-owned-storage intent identically"
  - "V-TAGPUT: host_tag_group update is available over REST, but unmanaged switches reuse the existing device_type NetworkDevice tag rather than a new tag group value"

patterns-established:
  - "Pattern: OpenAPI paths/methods scanned via indentation-based regex (no YAML library) — see parse_openapi_paths()"
  - "Pattern: a probe's module docstring carries its own dated Live-verified findings block with one VERDICT line per question, read directly by downstream plans instead of a separate findings doc"

requirements-completed: [DASH-12, DASH-13, PLR-13]

# Metrics
duration: ~25min total (Task 1 ~15min in a prior session; Task 3 ~10min in this session; Task 2 was a human-run checkpoint, not executor time)
completed: 2026-09-23
---

# Phase 13 Plan 01: Live REST Capability Probe Script Summary

Stdlib-only probe script that answers six live REST-capability questions (role creation, tag-group values, unmanaged-switch attribute shape, parents/labels round-trip, CORS, permission ids) against the real Checkmk site, with its findings recorded as dated VERDICT lines in its own module docstring.

## Performance

- **Tasks completed:** 3 of 3
- **Files created:** 1
- **Files modified:** 1 (same file, Task 3 docstring-only update)

## Accomplishments

- `scripts/probe_topology_rest.py` created (Task 1): a stdlib-only (`urllib.request`, `urllib.error`, `json`, `os`, `re`, `sys`) diagnostic probe that creates two throwaway hosts (`gsd-probe-topo-parent`, `gsd-probe-topo-child`), answers six REST-capability questions (P1-P6), and deletes both hosts in a `finally` block. It never calls Checkmk's changes-activation endpoint.
- The probe was run on the real deployment host (Task 2, human-verify checkpoint) via `podman exec -it automation-worker bash -c "cd /app/checkmk-wizard && python3 scripts/probe_topology_rest.py"`. Complete verbatim stdout was pasted back and used as the sole source for Task 3 — no value was inferred or simulated.
- Task 3 appended a dated `Live-verified against a real Checkmk 2.4.0p35/p36 CE site on 2026-09-23:` findings block to the module docstring, with one `VERDICT V-<ID>:` line for each of `ROLE`, `PERMS`, `SWITCH`, `PARENTS`, `LABELS`, `LABELS-IN-COLLECTION`, `CORS`, `CUSTOMATTR`, `TAGPUT`, plus a closing `Consequences for plans 13-04/13-05/13-06:` paragraph. No executable code was changed.

## Verification (actually run, not inspected)

- `RUFF_CACHE_DIR=/tmp/ruff-cache-gate uvx ruff check scripts/probe_topology_rest.py` → `All checks passed!`
- `uv run python -c "import ast; ast.parse(open('scripts/probe_topology_rest.py').read())"` → parsed cleanly, no exception
- `grep -c "VERDICT V-\(ROLE\|PERMS\|SWITCH\|PARENTS\|LABELS\|LABELS-IN-COLLECTION\|CORS\|CUSTOMATTR\|TAGPUT\):" scripts/probe_topology_rest.py` → `22` (well above the minimum of 9; both the docstring findings and the executable print statements contribute matching lines)
- `grep -n "Live-verified against a real Checkmk" scripts/probe_topology_rest.py` → line 59, followed by a date
- `grep -n "Consequences for plans 13-04/13-05/13-06:" scripts/probe_topology_rest.py` → line 109, present
- `git diff scripts/probe_topology_rest.py` for the Task 3 commit touches only lines inside the module docstring (verified by inspecting the full diff — every changed `+`/`-` line falls between the opening `"""` and the closing `"""` at the top of the file)
- `grep -n "activate-changes/invoke" scripts/probe_topology_rest.py` → no match (exit 1), confirming the probe still never activates changes
- Post-commit deletion check (`git diff --diff-filter=D --name-only HEAD~1 HEAD`) → no output, no unexpected file deletions

## Task Commits

1. **Task 1: Write scripts/probe_topology_rest.py (P1-P6)** — `4cf9f24` (feat, merged to main from prior worktree)
2. **Task 2: Run the probe on the deployment host** — checkpoint resolved by the developer's pasted verbatim stdout (no commit of its own; documented in this SUMMARY's Accomplishments/Findings sections)
3. **Task 3: Record the live findings in the probe's docstring** — `1a3e661` (docs)

## Files Created/Modified

- `scripts/probe_topology_rest.py` — stdlib-only live REST capability probe covering P1 (openapi-doc.yaml capability scan for user_role/custom-attribute/host_tag_group endpoints), P2 (built-in tag group contents), P3 (unmanaged-switch attribute shape), P4 (parents + label round-trip, labels-in-collection visibility), P5 (CORS preflight), P6 (admin role permissions), plus a final pending-changes count. Now carries a dated `Live-verified` findings block in its module docstring, the single source of truth for plans 13-04/13-05/13-06.

## Live Findings (from the real deployment run, 2026-09-23)

- **V-ROLE: REST.** `user_role create` and `user_role edit` are both available over REST — plan 13-04 provisions `topology_editor` via REST, no manual GUI step.
- **V-PERMS:** `wato.use`, `wato.edit`, `wato.all_folders`, `wato.edit_hosts`, `wato.manage_hosts`, `wato.activate` are all confirmed present on the admin role and are exactly what `topology_editor` needs. `wato.activateforeign` is present on admin but deliberately excluded from the scoped role.
- **V-SWITCH:** `{'tag_address_family': 'no-ip', 'tag_agent': 'no-agent', 'tag_snmp_ds': 'no-snmp', 'tag_device_type': 'NetworkDevice'}` — accepted on the first attempt.
- **V-PARENTS:** parents round-trip OK.
- **V-LABELS:** label values containing a comma and a minus sign are both accepted and echoed back unchanged.
- **V-LABELS-IN-COLLECTION: YES** — the `host_config` collection GET already includes `extensions.attributes.labels` per entry.
- **V-CORS: NOT ALLOWED** — the OPTIONS preflight returned 405 with no `Access-Control-*` headers; the browser dashboard needs a same-origin proxy.
- **V-CUSTOMATTR:** custom host attribute definitions are not creatable over REST (`ABSENT`, no matching paths); `map_position` stays a host label.
- **V-TAGPUT:** `host_tag_group update` is available over REST, but unmanaged switches reuse the existing `device_type` `NetworkDevice` tag rather than a new tag-group value.

## Decisions Made

- Followed the plan's interface precedent (`scripts/probe_host_attribute_merge.py`) closely: single `_rest()` choke point, `ProbeError` for connection-level failures only, redacted `Authorization` header (`Bearer <username> ***`), throwaway-host cleanup in `finally`.
- P4's `VERDICT V-LABELS` combines two independently-tested label values across the run (P3's `map_position="120,-40"`, which has both a comma and a minus sign, and P4's own `map_position="0,0"`, which has only a comma) rather than relying on P4's PUT alone.
- P6's admin-permissions extraction tries three candidate `extensions` key names (`permissions`, `enabled_permissions`, `permission_list`); the live run confirmed `permissions` is the correct key (`[P6] admin permissions found under extensions['permissions']`).
- Task 3's Checkmk version string (`2.4.0p35/p36`) is carried over from the docstring's own targeting statement rather than a printed version banner, since the probe does not print one — this is noted explicitly inside the findings block itself so it is never mistaken for a live-read value.
- Every value recorded in Task 3's findings block was copied verbatim from the developer's pasted stdout; none was inferred, softened, or filled in from the plan's candidate lists.

## Deviations from Plan

None — Tasks 1 and 3 executed exactly as written. No Rule 1/2/3 auto-fixes were needed. Task 2 (human-verify checkpoint) was resolved by the developer running the probe on the real deployment host and pasting back complete verbatim output, per its own design.

## Issues Encountered

None. The prior session's environment gap (no podman, no reachable Checkmk site) was the checkpoint's expected blocking condition, not an issue — it resolved once the developer ran the probe on the actual deployment host.

## User Setup Required

None. The probe run itself (Task 2) was the one required manual step, and it is complete.

## Next Phase Readiness

**Ready.** Plans 13-04, 13-05, and 13-06 can now read their REST-capability inputs directly from `scripts/probe_topology_rest.py`'s docstring `VERDICT` lines and `Consequences for plans 13-04/13-05/13-06:` paragraph — no further probing needed before those plans proceed.

## Self-Check

- `scripts/probe_topology_rest.py` exists: `FOUND`
- Commit `4cf9f24` (Task 1) exists in history: `FOUND`
- Commit `1a3e661` (Task 3) exists in history: `FOUND`

## Self-Check: PASSED

---
*Phase: 13-wizard-parents-support-and-topology-map*
*Completed: 2026-09-23*
