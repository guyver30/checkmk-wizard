---
phase: 13-wizard-parents-support-and-topology-map
plan: 04
subsystem: infra
tags: [poller, python, checkmk-rest, credentials, mqtt]

# Dependency graph
requires:
  - phase: 13-wizard-parents-support-and-topology-map (plan 01)
    provides: "scripts/probe_topology_rest.py's live-verified VERDICT lines (V-ROLE, V-PERMS, V-LABELS, V-LABELS-IN-COLLECTION) that this plan's REST body shapes and label parsing depend on"
provides:
  - "scripts/mqtt_poller.py: fetch_host_config() (single host_config REST GET) carries map_position/unmanaged from Checkmk host labels into DeviceSnapshot, topology_nodes(), and topology_signature(); fetch_host_folders() is now a thin wrapper; _normalise_restored_node() backfills/type-checks both new keys for cross-version retained payloads"
  - "scripts/provision_topology_editor.py: idempotent, stdlib-only provisioning of a scoped topology_editor Checkmk role + automation user, so the dashboard's future write path (plan 13-05) never embeds the wizard's admin automation credential"
affects: [13-05, 13-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Reading a REST endpoint's real request-body schema directly from the installed Checkmk source tree (/opt/omd/versions/2.4.0p35.cre/lib/python3/cmk/gui/openapi/endpoints/...) when a live site is unreachable and a prior probe only confirmed endpoint availability, not body shape -- a stronger source than a live HTTP round trip since it is the literal server code that executes the request"

key-files:
  created: [scripts/provision_topology_editor.py, tests/test_provision_topology_editor.py]
  modified: [scripts/mqtt_poller.py, tests/test_mqtt_poller.py, .planning/REQUIREMENTS.md]

key-decisions:
  - "Role-clone/edit REST body shapes (CreateUserRole: role_id/new_role_id/new_alias; EditUserRole: new_permissions dict of id->yes/no/default, no ETag required) were read directly from the live Checkmk 2.4.0p35 install's own endpoint source on this machine, since 13-01's probe confirmed the endpoints exist but never captured their body schema and no live site was reachable from this execution environment to re-probe"
  - "topology_signature() reads map_position/unmanaged via .get() with defaults, not direct indexing like the five pre-existing fields, so the ~25 pre-existing hand-built node-dict test fixtures elsewhere in the suite (previous_nodes fixtures for run_cycle/reconcile_state tests) did not need updating -- only the few tests that assert exact equality against a function's live output (parse_topology_payload, reconcile_state.previous_nodes) needed the two new keys added"
  - "PLR-13 marked complete in REQUIREMENTS.md; DASH-12 intentionally left Pending -- this plan only provisions the write-capable credential DASH-12 needs, sibling plan 13-05 delivers the actual edit-mode UI/write path DASH-12 describes and owns marking it complete"

patterns-established:
  - "Pattern: fetch_host_config() single-GET-covers-multiple-fields, thin-wrapper-for-backward-compatibility (fetch_host_folders()) -- avoids a second REST call per cycle when a new field piggybacks on an already-polled collection endpoint"

requirements-completed: [PLR-13]

# Metrics
duration: ~45min (resumed mid-session after a rate-limit interruption; wall-clock before resume not tracked)
completed: 2026-09-23
---

# Phase 13 Plan 04: Poller map_position/unmanaged + topology_editor Provisioning Summary

Poller's `host_config` REST lookup now carries each host's saved map position and unmanaged-switch marker into the MQTT topology payload from one GET (no second REST call), and a new stdlib-only script provisions a permission-scoped `topology_editor` Checkmk role/user for the dashboard's upcoming direct-write path.

## Performance

- **Tasks:** 2 of 2 completed
- **Files created:** 2 (`scripts/provision_topology_editor.py`, `tests/test_provision_topology_editor.py`)
- **Files modified:** 3 (`scripts/mqtt_poller.py`, `tests/test_mqtt_poller.py`, `.planning/REQUIREMENTS.md`)

## Accomplishments

- `fetch_host_config()` replaces the poller's per-cycle `fetch_host_folders()` REST call as the single `host_config` collection GET, reading `extensions.attributes.labels` for `map_position` (regex-validated `^-?\d{1,6},-?\d{1,6}$`, matching `dashboard-react/src/lib/topologyLayout.ts`'s `MAP_POSITION_RE` exactly) and `unmanaged_switch` (strict `== "yes"`), per 13-01 VERDICT V-LABELS-IN-COLLECTION -- confirmed no extra REST call is needed.
- `DeviceSnapshot`, `topology_nodes()`, and `topology_signature()` carry the two new fields end to end into the `lan/devices/topology` MQTT payload; a position or unmanaged-marker change now triggers exactly one topology republish (an unchanged cycle republishes nothing), verified by two new `topology_signature` difference tests.
- `_normalise_restored_node()` backfills/type-checks `map_position`/`unmanaged` for a retained payload written by an older poller (missing keys, or wrong types), extending the existing crash-loop prevention pattern -- verified never to raise and never to compute a spurious signature.
- `scripts/provision_topology_editor.py`: a one-shot, idempotent, stdlib-only script that clones the built-in `user` role into `topology_editor`, grants exactly the 13-01 VERDICT V-PERMS six `wato.*` ids (never `wato.activateforeign`, never any `wato.users`/`wato.global`/`wato.rulesets` id), creates the `topology_editor` automation user (`roles: ["topology_editor"]`, never `["admin"]`), prints the generated secret exactly once, and activates its own pending change without forcing another operator's foreign changes through.

## Verification (actually run, not inspected)

- `uv run pytest tests/test_mqtt_poller.py -q` -> `152 passed`
- `uv run pytest tests/test_provision_topology_editor.py -q` -> `10 passed`
- `uv run pytest -q` (full suite) -> `473 passed`
- `RUFF_CACHE_DIR=/tmp/ruff-cache-gate uvx ruff check scripts/mqtt_poller.py tests/test_mqtt_poller.py scripts/provision_topology_editor.py tests/test_provision_topology_editor.py` -> `All checks passed!`
- `RUFF_CACHE_DIR=/tmp/ruff-cache-gate uvx ruff check scripts/ src/ tests/` -> `Found 7 errors` -- confirmed pre-existing (identical count reproduced on the clean base commit via a temporary `git stash`), all in `tests/test_site.py`/`tests/test_wizard.py`, files this plan never touched (SIM117/RET501/PLR1711 style nits, out of scope per the Scope Boundary rule)
- `CMK_REST_SECRET= uv run python scripts/provision_topology_editor.py` -> exit code 1, stderr `[FAIL] CMK_REST_SECRET is not set`
- `grep -c "fetch_host_config(" scripts/mqtt_poller.py` -> `10` (>= 3 required: definition + docstring refs + main loop + `--once` path)
- `grep -n '"map_position": snapshot.map_position'` / `'"unmanaged": snapshot.unmanaged'` in `scripts/mqtt_poller.py` -> both match
- `grep -n '_MAP_POSITION_RE = re.compile'` -> `re.compile(r"^-?\d{1,6},-?\d{1,6}$")`, identical to the browser-side regex
- `git diff -- tests/test_mqtt_poller.py` inspected line-by-line: the five original `test_fetch_host_folders_*` test bodies appear only as diff-hunk context, never as changed lines
- `grep -v '^\s*#' scripts/provision_topology_editor.py | grep -c '"roles": \["admin"\]'` -> `0`
- `grep -n "wato.activateforeign" scripts/provision_topology_editor.py` -> both occurrences are inside comments
- `grep -n 'force_foreign_changes": False' scripts/provision_topology_editor.py` -> matches
- `grep -E "^import (httpx|requests)" scripts/provision_topology_editor.py` -> no output
- Post-commit deletion check (`git diff --diff-filter=D --name-only HEAD~1 HEAD`) after both task commits -> no output, no unexpected deletions

## Task Commits

1. **Task 1: Poller carries map_position + unmanaged in the topology payload (PLR-13)** - `ce7ccbd` (feat)
2. **Task 2: scripts/provision_topology_editor.py (scoped role + automation user)** - `3414c66` (test, RED: module import fails, no implementation yet), `65ec813` (feat, GREEN: implementation + all 10 tests pass)

## Files Created/Modified

- `scripts/mqtt_poller.py` - `HostConfigInfo` dataclass; `fetch_host_config()` (single REST GET reading folder + labels); `fetch_host_folders()` reduced to a thin wrapper; `DeviceSnapshot.map_position`/`.unmanaged` fields; `topology_nodes()`/`topology_signature()` extended; `_normalise_restored_node()` backfill; `query_devices(host_config=...)`; `run_forever()`/`main() --once` both call `fetch_host_config()` once per cycle
- `tests/test_mqtt_poller.py` - new `fetch_host_config`/`topology_nodes`/`topology_signature` map_position+unmanaged tests; updated the handful of tests that assert exact equality against a changed function's output; four stub-only `fetch_host_folders` patches repointed to `fetch_host_config`
- `scripts/provision_topology_editor.py` - new stdlib-only provisioning script (role clone/edit, user create, best-effort own-change activation)
- `tests/test_provision_topology_editor.py` - new test file covering all four pure helpers plus the `CMK_REST_SECRET` fail-fast gate
- `.planning/REQUIREMENTS.md` - PLR-13 marked complete (checkbox + traceability table); DASH-12 left Pending (owned by plan 13-05)

## Decisions Made

- **Role clone/edit REST body shapes were source-verified, not probe-verified.** 13-01's `scripts/probe_topology_rest.py` confirmed via `parse_openapi_paths()` that `POST /domain-types/user_role/collections/all` and `PUT /objects/user_role/{role_id}` exist (VERDICT V-ROLE: REST), but that scan checks path/method availability only, never request-body schemas -- there was no pasted OpenAPI excerpt anywhere in this repo's history naming the actual field names, and this execution environment has no reachable Checkmk site to re-probe (`getent`/`/dev/tcp` to `checkmk:5000` fails). The plan's own action text says "read the OpenAPI excerpt the probe printed; do not guess the body" -- since that excerpt doesn't exist, guessing was the one option explicitly ruled out. Instead, the actual Checkmk 2.4.0p35 install present on this machine (`/opt/omd/versions/2.4.0p35.cre/`) was read directly: `cmk/gui/openapi/endpoints/user_role/request_schemas.py` gives the exact `CreateUserRole`/`EditUserRole` marshmallow schemas, and `cmk/gui/openapi/endpoints/user_role/__init__.py` confirms the edit endpoint's `@Endpoint(...)` registration passes no `etag=` argument (so no `If-Match` header is needed on the PUT, unlike `host_config`). This is the literal server code that will execute the request -- stronger evidence than a live HTTP round trip, and consistent with this codebase's own "Checkmk's live behaviour, not its docs, is the source of truth" rule. If a future Checkmk version changes this shape, the script prints the full rejection body on a 4xx rather than silently believing it succeeded.
- **`topology_signature()` uses `.get()` for the two new fields, not direct indexing.** The five pre-existing fields (`id`, `parents`, `device_type`, `folder`, `alias`) are read via `node["..."]`, and the codebase's established convention (seen in the `alias` field's own addition history) is to keep every test's hand-built node dict in sync with the full current shape. Doing that for `map_position`/`unmanaged` would have required editing roughly 25 unrelated node-dict fixtures scattered across `run_cycle`/`reconcile_state` tests that have nothing to do with this plan's scope. `.get()` with the same None/False defaults `_normalise_restored_node()` already backfills keeps those ~25 fixtures passing unmodified while still correctly extending the signature tuple for every node dict that does carry the new keys (which is every node `topology_nodes()`/`_normalise_restored_node()` produces in production). A dedicated regression test (`test_topology_signature_tolerates_nodes_missing_map_position_and_unmanaged_keys`) documents this choice.
- **PLR-13 marked complete; DASH-12 deliberately not marked**, even though the plan's own frontmatter lists both. DASH-12 describes the full edit-mode dashboard experience (draw/reconnect/delete links, drag positions, batched Apply) which plan 13-05 delivers; this plan only supplies one dependency of it (the scoped write credential). Marking it complete here would be inaccurate and would race the sibling worktree executing 13-05, which also lists DASH-12 in its own frontmatter and is the plan that actually finishes it.

## Deviations from Plan

**1. [Rule 3 - Blocking, informational-gap variant] Role-clone REST body shape not available from the cited source**
- **Found during:** Task 2 (`scripts/provision_topology_editor.py`)
- **Issue:** The plan's action text directs reading "the OpenAPI excerpt the probe printed" for the `user_role` create/edit body shape, but `scripts/probe_topology_rest.py`'s P1 step only ever printed AVAILABLE/ABSENT + matched path lists (via `parse_openapi_paths()`), never the actual `openapi-doc.yaml` body-schema text -- there is nothing to read. This execution environment also has no reachable Checkmk site to probe live (confirmed: DNS resolution for `checkmk` fails).
- **Fix:** Read the real request-body schema directly from the Checkmk 2.4.0p35 source tree installed on this machine (`/opt/omd/versions/2.4.0p35.cre/lib/python3/cmk/gui/openapi/endpoints/user_role/{__init__,request_schemas}.py`) -- the literal server-side code that validates and handles the request. This is a strictly stronger source than the missing OpenAPI excerpt would have been (it is the ground truth the OpenAPI spec is itself generated from), and is documented at length in the script's module docstring with the exact file paths and read date, following this codebase's live/source-verification citation convention.
- **Files modified:** `scripts/provision_topology_editor.py` (module docstring + `ensure_role()`/`build_role_permissions()` implementation)
- **Verification:** All 10 `tests/test_provision_topology_editor.py` tests pass; the acceptance-criteria greps (no `roles: ["admin"]`, `wato.activateforeign` only in comments, `force_foreign_changes: False` present, no `httpx`/`requests` import) all confirmed. The actual live POST/PUT round trip against a real Checkmk site was NOT exercised in this environment (no reachable site) -- if the source-read schema is somehow stale on a future Checkmk patch version, the script's `_print_rejection()` diagnostic prints the full 4xx body rather than silently reporting success, so a real deployment run will surface any mismatch loudly rather than corrupt state silently.

---

**Total deviations:** 1 auto-fixed (1 blocking/informational-gap, resolved via a stronger source than the plan anticipated)
**Impact on plan:** No scope creep; the role-clone/edit implementation is exactly what the plan asked for, sourced more rigorously than the plan's own suggested method could have provided in this environment.

## Issues Encountered

None beyond the deviation above. The worktree's base commit had drifted behind `main` (this worktree branched before 13-01's live-verified VERDICT findings and 13-03's TopologyMap component were merged); this was corrected with a non-destructive `git merge --ff-only` to the orchestrator-specified base commit before any task work began, per the plan's own `<worktree_branch_check>` step.

## User Setup Required

None for this plan's own code. `scripts/provision_topology_editor.py` is itself the one-time setup step plan 13-05's dashboard will depend on (run once against the real deployment, `CMK_REST_SECRET` set to the wizard's admin automation secret) -- not run in this execution since no live Checkmk site was reachable from this environment. Running it, and pasting the printed `TOPOLOGY_EDITOR_SECRET` into `dashboard-react/src/lib/config.ts`, remains an operator action for whenever plan 13-05's write path is ready to use it.

## Next Phase Readiness

**Ready.** Plan 13-05 (dashboard edit-mode UI) can now:
- Read `map_position`/`unmanaged` straight off `lan/devices/topology`'s MQTT payload (no direct Checkmk REST read needed for the read path, resolving the CONTEXT.md open question).
- Run `scripts/provision_topology_editor.py` once per deployment to obtain the scoped `TOPOLOGY_EDITOR_SECRET`, then embed it in `dashboard-react/src/lib/config.ts` alongside the existing `WS_USERNAME`/`WS_PASSWORD` convention.

Plan 13-06 (whatever it covers) was not investigated as part of this plan; no blockers identified against it from this plan's changes.

## Self-Check

- `scripts/mqtt_poller.py` modified and contains `def fetch_host_config`: `FOUND`
- `scripts/provision_topology_editor.py` exists: `FOUND`
- `tests/test_provision_topology_editor.py` exists: `FOUND`
- Commit `ce7ccbd` (Task 1) exists in history: `FOUND`
- Commit `3414c66` (Task 2 RED) exists in history: `FOUND`
- Commit `65ec813` (Task 2 GREEN) exists in history: `FOUND`

## Self-Check: PASSED

---
*Phase: 13-wizard-parents-support-and-topology-map*
*Completed: 2026-09-23*
