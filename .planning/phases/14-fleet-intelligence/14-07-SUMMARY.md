---
phase: 14-fleet-intelligence
plan: 07
subsystem: poller
tags: [mqtt, checkmk-labels, criticality, dependencies, python]

# Dependency graph
requires:
  - phase: 14-fleet-intelligence (plan 14-01)
    provides: "compute_incidents()/incident_signature() consuming DeviceSnapshot.criticality/depends_on with safe defaults; CRITICALITY_TIERS/DEFAULT_CRITICALITY"
  - phase: 14-fleet-intelligence (plan 14-05)
    provides: "D-06 gate passed -- live evidence the incident engine this plan feeds works on a real site"
provides:
  - "CRITICALITY_LABEL/SERVICE_CRITICALITY_LABEL/DEPENDS_ON_LABEL constants and _HOST_ID_RE, the exact strings/delimiters plan 14-08's browser-side twin must reuse"
  - "_parse_criticality()/_parse_service_criticality()/_parse_depends_on(): strict, never-raising parsers with fixed vocabulary, delimiter validation, and 200/50 entry caps"
  - "HostConfigInfo/DeviceSnapshot carry criticality/service_criticality/depends_on end to end: fetch_host_config() -> query_devices() -> topology_nodes()/topology_signature() -> every dashboard viewer"
  - "_normalise_restored_node() backfills and type-checks the three new fields so an older or malformed retained topology payload never crashes the poller"
affects: [14-08-criticality-and-dependency-label-editing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Checkmk host label read path (fetch_host_config -> HostConfigInfo -> query_devices -> DeviceSnapshot), following the exact map_position/unmanaged precedent from Phase 13 -- one REST GET, no new call"
    - "Change-only topology republish via topology_signature()'s tuple, extended with three more .get()-defaulted fields so a label edit is indistinguishable from a map-position/unmanaged edit in the republish decision"
    - "_normalise_restored_node()'s backfill-and-type-check contract extended to a third generation of fields (map_position/unmanaged in Phase 13, criticality/service_criticality/depends_on here), confirming the pattern generalizes"

key-files:
  created: []
  modified:
    - scripts/mqtt_poller.py
    - tests/test_mqtt_poller.py

key-decisions:
  - "Label vocabulary and delimiters implemented exactly as 14-RESEARCH.md's Label Design proposed (D-09 Claude's discretion, tagged ASSUMED there): criticality:<tier> (low/medium/high/critical), service_criticality:<name>=<tier>;... , depends_on:<host>,<host>,... -- no changes made during implementation"
  - "Entry caps (200 service_criticality entries, 50 depends_on entries) count validated/kept entries, not raw split segments, so a label with many malformed entries interleaved with valid ones still yields exactly the documented cap of good data"

patterns-established: []

requirements-completed: [PLR-16]

# Metrics
duration: ~35min
completed: 2026-09-26
---

# Phase 14 Plan 07: Criticality and Dependency Label Read Path Summary

**Poller reads operator-set `criticality`, `service_criticality`, and `depends_on` Checkmk host labels from the existing per-cycle REST lookup (no new REST call) and carries them to every dashboard viewer via `lan/devices/topology`, closing the label half of PLR-16 that plan 14-01's incident engine already consumes.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 2 completed
- **Files modified:** 2

## Accomplishments

- `CRITICALITY_LABEL`/`SERVICE_CRITICALITY_LABEL`/`DEPENDS_ON_LABEL` constants and `_HOST_ID_RE` added to the Phase 13 label block, with the exact vocabulary/delimiters 14-RESEARCH.md's "Label Design" section proposed (`low`/`medium`/`high`/`critical`; `;`/`=` for per-service entries; `,` for dependency lists) -- all colon-free per the live-verified Checkmk label constraint.
- `_parse_criticality()`, `_parse_service_criticality()`, `_parse_depends_on()`: strict, never-raising parsers. Out-of-vocabulary tiers, malformed entries (missing `=`, empty name, a name containing `:`), invalid host ids, self-references, and duplicates are all silently dropped/degraded rather than raising or propagating garbage. Both multi-value labels are capped (200 service entries, 50 depends-on ids) against a hostile or runaway label value.
- `HostConfigInfo`/`fetch_host_config()` extended to parse these three labels off the exact same `host_config` collection GET Phase 13 already makes -- confirmed by `grep -c urlopen` staying at 1 occurrence in the file.
- `DeviceSnapshot` gained `service_criticality`; `query_devices()` now populates all three fields from `host_config`, with the same graceful-degradation-to-default posture as `map_position`/`unmanaged` when a host is missing from the mapping.
- `topology_nodes()` emits the three fields on every node; `topology_signature()` folds them into its change-detection tuple, so editing a host's criticality or dependency links triggers exactly one topology republish, and an unrelated cycle with unchanged labels republishes nothing.
- `_normalise_restored_node()` backfills and type-checks all three fields for a pre-14-07 retained payload (missing keys) or a malformed one (wrong types), so an upgrade republishes topology exactly once and the poller never crash-loops on old or hand-edited retained state.
- End-to-end test (`test_run_cycle_incident_worst_criticality_counts_dependents_from_labels`) confirms the full chain: a `DOWN` host under an `UNREACH` chain, with a still-`UP` dependent carrying an operator-set `critical` label, produces a published incident with `worst_criticality: "high"` (D-15's one-tier reduction) -- proving the label read path this plan built actually reaches plan 14-01's already-shipped incident engine.

## Task Commits

Each task was committed atomically:

1. **Task 1: Label constants, strict parsers and fetch_host_config extension** - `76fd002` (feat)
2. **Task 2: Carry labels through DeviceSnapshot, topology payload, signature and restore** - `88a6935` (feat)

**Plan metadata:** (this commit, docs: complete plan)

_Note: both tasks were `tdd="true"`; tests were written alongside each task's implementation in the same commit (flat `def test_*` functions, no `class Test...` groupings), matching this test file's own established convention from prior Phase 14 plans._

## Files Created/Modified

- `scripts/mqtt_poller.py` -- `CRITICALITY_LABEL`/`SERVICE_CRITICALITY_LABEL`/`DEPENDS_ON_LABEL`/`_HOST_ID_RE`/`_MAX_SERVICE_CRITICALITY_ENTRIES`/`_MAX_DEPENDS_ON_ENTRIES` constants; `_parse_criticality()`/`_parse_service_criticality()`/`_parse_depends_on()`; `HostConfigInfo.criticality`/`service_criticality`/`depends_on`; `fetch_host_config()` extended to populate them; `DeviceSnapshot.service_criticality`; `query_devices()` extended to populate `criticality`/`depends_on`/`service_criticality` from `host_config`; `topology_nodes()`/`topology_signature()` extended with the three fields; `_normalise_restored_node()` extended to backfill/type-check them
- `tests/test_mqtt_poller.py` -- 7 new `fetch_host_config`/parser tests (Task 1); `test_query_devices_carries_phase14_labels_from_host_config` + defaults counterpart, `test_topology_nodes_include_criticality_service_criticality_and_depends_on`, `test_run_cycle_republishes_topology_on_criticality_change`/`_depends_on_change`, `test_run_cycle_skips_topology_publish_when_phase14_labels_unchanged`, `test_normalise_restored_node_backfills_phase14_fields`/`_rejects_wrong_typed_phase14_fields`/`_upgrade_republishes_topology_once_and_never_raises`, `test_run_cycle_incident_worst_criticality_counts_dependents_from_labels` (Task 2); `_snapshot()` helper extended with `service_criticality`; three pre-existing exact-equality tests (`test_topology_nodes_emits_map_position_and_unmanaged`, `test_parse_topology_payload_coerces_string_parents_to_empty_list`, `test_parse_topology_payload_parses_devices_keyed_by_id`, `test_reconcile_state_seeds_previous_nodes_from_retained_topology`) updated to include the three new keys their exact dict/tuple comparisons now produce

## Decisions Made

None beyond what CONTEXT.md/14-RESEARCH.md's Label Design already locked (D-07/D-08/D-09) -- implemented the proposed vocabulary/delimiters exactly as written, since the plan explicitly adopted 14-RESEARCH.md's "Label Design" section as-is.

## Deviations from Plan

**1. [Rule 1 - Bug] Updated four pre-existing exact-equality tests broken by the new topology fields**
- **Found during:** Task 2, first full-suite run after extending `topology_nodes()`/`topology_signature()`/`_normalise_restored_node()`
- **Issue:** `test_topology_nodes_emits_map_position_and_unmanaged`, `test_parse_topology_payload_coerces_string_parents_to_empty_list`, `test_parse_topology_payload_parses_devices_keyed_by_id`, and `test_reconcile_state_seeds_previous_nodes_from_retained_topology` all asserted exact dict/tuple equality against `topology_nodes()`/`topology_signature()`/`_normalise_restored_node()` output that predated this plan's three new keys -- these are direct, expected consequences of the plan's own action (extending those three functions), not a design change
- **Fix:** Added the three new keys/tuple positions (`criticality`, `service_criticality`, `depends_on`, defaulting to `"low"`/`{}`/`[]`) to each assertion's expected value
- **Files modified:** tests/test_mqtt_poller.py
- **Verification:** `uv run pytest tests/test_mqtt_poller.py -q` -- 209 passed (was failing 2/209 before this fix)
- **Committed in:** `88a6935` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1, test-only, no product-code change)
**Impact on plan:** None on scope -- purely fixing test assertions that hard-coded the pre-plan field set, an unavoidable side effect of the plan's own Task 2 action.

## Issues Encountered

None.

## User Setup Required

None -- no external service configuration required. This plan only reads labels an operator would set via Checkmk's own UI or the plan 14-08 dashboard editor (not yet built); no live label was written or verified against a real site in this plan (that verification belongs to 14-08's write path and/or a future live-UAT pass).

## Next Phase Readiness

- The label read path is complete and stable: `CRITICALITY_LABEL`/`SERVICE_CRITICALITY_LABEL`/`DEPENDS_ON_LABEL` and their exact delimiter scheme are now load-bearing (consumed by `fetch_host_config()`) -- plan 14-08's browser-side `checkmkWrite.ts` write path must use these exact same key strings and delimiters, as the module comment states.
- `service_criticality` is parsed and carried to every viewer via topology but is not yet consulted by `compute_incidents()` (per-service criticality feeding incident severity was explicitly out of scope for plan 14-01, per its own Open Question 3 note) -- this remains stored-but-unused until a future plan decides to wire it in, which is expected, not a gap in this plan.
- No blockers for 14-08 (dashboard criticality/dependency editing) or 14-09.

---
*Phase: 14-fleet-intelligence*
*Completed: 2026-09-26*

## Self-Check: PASSED

- FOUND: scripts/mqtt_poller.py
- FOUND: tests/test_mqtt_poller.py
- FOUND: .planning/phases/14-fleet-intelligence/14-07-SUMMARY.md
- FOUND commit: 76fd002 (Task 1)
- FOUND commit: 88a6935 (Task 2)
