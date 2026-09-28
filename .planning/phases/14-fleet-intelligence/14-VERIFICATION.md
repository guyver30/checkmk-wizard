---
phase: 14-fleet-intelligence
verified: 2026-09-28T06:27:40Z
status: human_needed
score: 26/26 in-scope must-haves verified (4 kiosk truths descoped by the operator, not counted)
has_blocking_gaps: false
overrides_applied: 0
accepted_scope_changes:
  - item: "DASH-17 kiosk/wall mode (plan 14-06 truths 1-4, plan 14-09 kiosk docs and kiosk live step)"
    decision: "Descoped by the operator at the 2026-09-28 live UAT. Code and docs removed in 9f9bbe8; REQUIREMENTS.md marks DASH-17 [~] descoped; ROADMAP marks 14-06 removed."
  - item: "D-15 dependent-weighting / criticality model (14-09 live step 6)"
    decision: "Live-exercised, behaves as coded, but operator finds the model unclear. Redesign parked in .planning/todos/pending/2026-09-28-revisit-criticality-and-dependency-model.md, along with deferred review findings WR-01, WR-02, WR-03, WR-05 and IN-02."
  - item: "14-REVIEW IN-01, IN-03, IN-04, IN-05, IN-06"
    decision: "Minor, left as is per 14-REVIEW.md Fix Status."
gaps: []
deferred: []
human_verification:
  - test: "Post-UAT regression smoke of the incident engine: force a 3-level DOWN chain (e.g. switch DOWN, child switch DOWN, leaf DOWN) with the Livestatus external-command recipe in docs/Incident demo with fake check results.md"
    expected: "Exactly one incident card, rooted at the top DOWN host; the lower DOWN hosts are listed as confirmed down and are dimmed in tree and map"
    why_human: "CR-01 changed compute_incidents() nesting (24b22f5) AFTER the 14-05 live gate of 2026-09-26. Unit tests cover it; the live site has not seen the changed code."
  - test: "Reconnect and deep-link smoke: open the dashboard, let an incident open, disconnect the browser (or stop the broker) while the incident closes, reconnect; then load /?incident=<id> fresh in a new tab while an incident is open"
    expected: "The closed incident's card is gone after reconnect (no ghost card); the fresh deep-link load scrolls to and rings the matching card"
    why_human: "CR-02 (resetIncidents on connect) and WR-04 (scroll after retained replay) were fixed in a1a73cf after the live gates; real MQTT reconnect timing and browser scroll are not exercised by jsdom tests."
---

# Phase 14: Fleet Intelligence Verification Report

**Phase Goal:** The dashboard stops reporting device status and starts reporting service impact, cause, and forecast. Phase 14's share (14-CONTEXT D-01): root-cause collapse into incidents, incident cards, consequence dimming, and operator-set criticality and dependency labels. History/prediction are Phases 14.1/14.2 and out of scope.
**Verified:** 2026-09-28T06:27:40Z
**Status:** human_needed (no gaps; two post-UAT regression smoke checks requested)
**Re-verification:** No, initial verification

## Goal Achievement

### Observable Truths

ROADMAP Phase 14 has no `success_criteria` array (scope list only), so the contract is the union of the PLAN `must_haves` plus the REQUIREMENTS.md text for PLR-14/15/16 and DASH-14/15/16.

| # | Truth (source) | Status | Evidence |
|---|---|---|---|
| 1 | Poller groups every DOWN/UNREACH host into one incident per root cause from `parents` + `host_state_raw` only (14-01, PLR-14) | VERIFIED | `compute_incidents()` scripts/mqtt_poller.py:766-926; pure, no I/O; own probe run: managed switch DOWN + 2 UNREACH children produced one incident `incident-sw` with both under `not_observable` |
| 2 | DOWN host under unmanaged switch with >=1 non-OK sibling makes the switch an inferred root (14-01, PLR-15) | VERIFIED | inferred_roots loop :822-830 (>=2 non-OK children, >=1 DOWN); probe: `incident-um` `inferred: True`, children in `not_observable` |
| 3 | Lone DOWN host under unmanaged switch is its own non-inferred incident (14-01, PLR-15) | VERIFIED | probe: `incident-e` root `e`, `inferred: False` |
| 4 | Retained publish on change only, zero-length retained tombstone on close (14-01, PLR-16) | VERIFIED | run_cycle :2387-2397 compares `incident_signature()`; `publish_incident` qos=1 retain=True :1777; `publish_incident_tombstone` payload=None retain=True :1786 |
| 5 | Restart self-heal, no incident state on disk (14-01, PLR-14) | VERIFIED | reconcile_state subscribes `lan/incidents/+/status` before TOPIC_TOPOLOGY :2181, seeds `previous_incidents` with `None` signatures :2205 so first cycle republishes or tombstones; no file writes. Live-verified 14-05 (restart survival) |
| 6 | worst_criticality = max over root, consequences, transitive dependents; UP dependent counts one tier lower (14-01, PLR-16, D-15) | VERIFIED | `_dependents_closure` :749, `_effective_criticality_index` :735; probe: critical UP dependent `scr` gave `worst_criticality: high`. Model redesign parked by operator (accepted) |
| 7 | Dashboard subscribes `lan/incidents/+/status` (14-02) | VERIFIED | mqttClient.ts:37 SUBSCRIBE_TOPICS |
| 8 | Tombstone removes incident from store (14-02) | VERIFIED | useAppStore.ts:131-143 |
| 9 | Malformed payload dropped without throwing (14-02) | VERIFIED | parsePayload not-ok / non-object return early :133-146; `normalizeIncident` returns null without id/root |
| 10 | Incidents ordered by worst criticality then longest-open (14-02, DASH-14) | VERIFIED | `sortIncidents` lib/incidents.ts:91-110 |
| 11 | Host-id lookup gives root/consequence/none + incident id (14-02, D-12) | VERIFIED | `buildIncidentLookup` :141-164; dependents excluded per D-15 |
| 12 | Tree: consequence visible, dimmed, "See incident" badge -> /?incident=, name still links /details (14-03, DASH-15) | VERIFIED | TreeNode.tsx:92-127 (opacity-50, Link to /details, badge replaces StateBadge) |
| 13 | Map: consequence at reduced opacity, flat neutral border, click -> /?incident= (14-03, DASH-15) | VERIFIED | mapIcons.ts:117-137 (opacity 0.4, NEUTRAL_400, no dashes; opacity reset to 1 on recovery, fix 51d50df); TopologyMap.tsx:368 navigate |
| 14 | Only root keeps alarm styling; inferred root marked in tree and dashed warning border on map (14-03, DASH-15) | VERIFIED | TreeNode "Inferred, not confirmed" badge :128; mapIcons `inferred-root` dashes [6,3] WARN_HEX. See advisory A-1 on folder rollup |
| 15 | No incident lookup -> tree/map unchanged (14-03) | VERIFIED | `incidentLookup` optional / default `new Map()`; full suite green |
| 16 | Card list above stats strip: root + duration, inferred marker, confirmed down / not observable split, worst criticality (14-04, DASH-14) | VERIFIED | IndexRoute.tsx:246-252 IncidentList before StatsStrip; IncidentCard.tsx title/inferred Badge/consequenceSummary/criticality Badge/expandable grouped lists |
| 17 | Card order by criticality then duration (14-04) | VERIFIED | IndexRoute uses `selectOpenIncidents` (sorted); IncidentList never re-sorts |
| 18 | Empty state "No open incidents" + "Every device the poller can reach is reporting normally." (14-04) | VERIFIED | IncidentList.tsx:41-47 (IN-04 wording concern accepted as minor) |
| 19 | No card text claims "not operating" (14-04, D-04) | VERIFIED | grep: no occurrence in rendered strings; test IncidentList.test.tsx:201 |
| 20 | Live store incidents dim tree and map end to end (14-04) | VERIFIED | IndexRoute.tsx:68-76 store -> selectOpenIncidents -> buildIncidentLookup -> buildTree option and TopologyMap prop :287; TopologyMap useMemo `buildMapModel(topologyDevices, statuses, nowMs, incidentLookup)` :165 |
| 21 | /?incident={id} highlights and scrolls to the card (14-04) | VERIFIED | IndexRoute reads `searchParams.get("incident")`; IncidentList ring + scrollIntoView, re-runs on `hasTarget` (WR-04 fix a1a73cf, regression test :183). Live re-check requested (human item 2) |
| 22 | Deploy doc lists incident topic contract; README 5c; last_state_change live result recorded (14-05) | VERIFIED | docs row :392 + paragraph :402; README `## 5c. Incidents` :188; OPTIONAL_HOST_COLUMNS comment dated 2026-09-26 |
| 23 | Live D-06 evidence-framing gate passed before criticality work (14-05) | VERIFIED | 14-05-SUMMARY: operator approval 2026-09-26 (single-host, managed collapse, inferred root, split, restart survival) |
| 24 | Poller reads criticality / service_criticality / depends_on from the existing REST host_config lookup, no new call; bad values degrade safely (14-07, PLR-16) | VERIFIED | `fetch_host_config` :1285-1287 with never-raising `_parse_*` :401-467; `query_devices` :1508-1510 copies via `host_info.criticality` |
| 25 | Every viewer receives the labels on lan/devices/topology; label change triggers republish; older retained topology backfilled (14-07) | VERIFIED | `topology_nodes` :650-653, `topology_signature` :687-689, `_normalise_restored_node` :2016; test `test_run_cycle_republishes_topology_on_criticality_change`; live 14-09 step 5 pass |
| 26 | Edit mode panel sets host tier, per-service tier, add/remove depends_on (confirm on remove), writes labels via serialized GET->merge->PUT(If-Match) with the scoped credential, counts toward the single Apply; failed write shows snackbar (14-08, DASH-16) | VERIFIED | CriticalityEditor.tsx:124-174 calls `setCriticality`/`setServiceCriticality`/`updateDependsOn`, `window.confirm("Remove this dependency?...")`; checkmkWrite.ts `updateLabels` -> `updateHostAttributes` with If-Match inside `serialize()`; IndexRoute mounts panel gated on `editMode && isTopologyEditingConfigured()` with `onSaved={onEditSaved}` (same counter as map). Live 14-09 steps 2-4 pass. Whether labels are visible to the poller before Apply (WR-05) is deferred to the operator's redesign todo |
| - | 14-06 kiosk truths (4) and 14-09 kiosk docs / kiosk live step | DESCOPED (accepted) | Removed in 9f9bbe8; no KioskView.tsx / useKioskRotation.ts / `?kiosk` branch remain; REQUIREMENTS.md DASH-17 `[~]` descoped |
| - | 14-09 "operator saw worst criticality rise to high from a still-UP critical dependent" | ACCEPTED (parked) | Step 6 live run exercised D-15 with a critical-on-critical pair; operator parked the model. The one-tier-down behaviour is confirmed by unit tests and by this verifier's own probe (`scr` critical UP -> `high`) |

**Score:** 26/26 in-scope truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `scripts/mqtt_poller.py` | incident engine, publish/tombstone, label parsing | VERIFIED | substantive, wired into run_cycle/reconcile_state/fetch_host_config |
| `tests/test_mqtt_poller.py` | incident + label tests | VERIFIED | 28 incident tests pass (`-k incident`), incl. CR-01 3-level chain and DOWN parent cycle |
| `dashboard-react/src/lib/incidents.ts` | tiers, normalize, sort, lookup, duration, status, summary | VERIFIED | all 9 planned exports present |
| `dashboard-react/src/store/useAppStore.ts` | incidents slice + resetIncidents | VERIFIED | wired from mqttClient.ts:96 on every connect |
| `dashboard-react/src/store/mqttClient.ts` | incident subscription | VERIFIED | |
| `dashboard-react/src/lib/treeModel.ts`, `components/TreeNode.tsx` | dimming/inferred fields and rendering | VERIFIED | |
| `dashboard-react/src/lib/topologyLayout.ts`, `lib/mapIcons.ts`, `components/TopologyMap.tsx` | map dimming, inferred-root emphasis, incident click | VERIFIED | |
| `dashboard-react/src/components/IncidentCard.tsx`, `IncidentList.tsx` | cards and list | VERIFIED | `fill` kiosk variant removed with DASH-17 (accepted) |
| `dashboard-react/src/routes/IndexRoute.tsx` | list mount + lookup + editor wiring | VERIFIED | |
| `dashboard-react/src/lib/checkmkWrite.ts` | label writers/codecs | VERIFIED | |
| `dashboard-react/src/components/CriticalityEditor.tsx` | edit-mode panel | VERIFIED | |
| `docs/Podman setup for checkmk, minio, mosquitto, worker.md` | incident + topology rows, label section | VERIFIED | kiosk section removed (accepted) |
| `dashboard-react/README.md` | 5c Incidents, 5d Criticality & dependencies | VERIFIED | 5e Kiosk removed (accepted) |
| `routes/KioskView.tsx`, `hooks/useKioskRotation.ts` | kiosk | DESCOPED | intentionally absent |

### Key Link Verification

| From | To | Via | Status |
|---|---|---|---|
| run_cycle | compute_incidents | `compute_incidents(snapshots)` :2387 | WIRED |
| reconcile_state | lan/incidents/+/status | subscribe :2181, seeded previous_incidents :2205 | WIRED |
| mqttClient.ts | useAppStore.handleMessage | SUBSCRIBE_TOPICS entry | WIRED |
| incidents.ts tiers | mqtt_poller.py CRITICALITY_TIERS | identical `low, medium, high, critical` | WIRED |
| TreeNode | /?incident= | Link around "See incident" badge | WIRED |
| TopologyMap | buildMapModel(..., incidentLookup) | useMemo | WIRED |
| IndexRoute | incidents slice | `useAppStore((s) => s.incidents)` -> selectOpenIncidents -> buildIncidentLookup | WIRED |
| fetch_host_config | DeviceSnapshot labels | `host_info.criticality` | WIRED |
| topology_signature | publish_topology | includes criticality/depends_on/service_criticality | WIRED |
| CriticalityEditor | checkmkWrite writers | onChange handlers | WIRED |
| IndexRoute | CriticalityEditor onSaved | `onSaved={onEditSaved}` | WIRED |
| checkmkWrite.updateLabels | updateHostAttributes | inside serialize() | WIRED |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| IncidentList / IncidentCard | `incidents` | store slice <- retained `lan/incidents/+/status` <- `compute_incidents()` over live Livestatus snapshots | Yes (live gate 14-05) | FLOWING |
| Tree / Map dimming | `incidentLookup` | derived from same slice in IndexRoute | Yes | FLOWING |
| CriticalityEditor current values | `node` (topology payload) | `lan/devices/topology` <- REST host_config labels | Yes (live 14-09 step 5) | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Python suite | `uv run pytest -q` | 559 passed | PASS |
| Dashboard suite | `npm --prefix dashboard-react test` | 39 files, 457 tests passed | PASS |
| Typecheck | `npm --prefix dashboard-react run typecheck` | exit 0 | PASS |
| Incident tests | `uv run pytest -q tests/test_mqtt_poller.py -k incident` | 28 passed | PASS |
| Root-cause collapse, inferred root, lone host, D-15 weighting | scratchpad probe calling `compute_incidents()` on 9 synthetic snapshots | 3 incidents exactly as specified; UP critical dependent -> `high` | PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh` declared or present for this phase. SKIPPED.

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
|---|---|---|---|
| PLR-14 | 14-01, 14-05 | SATISFIED | truths 1, 4, 5; live 14-05 |
| PLR-15 | 14-01, 14-05 | SATISFIED | truths 2, 3; live 14-05 |
| PLR-16 | 14-01, 14-05, 14-07, 14-09 | SATISFIED | truths 4, 6, 24, 25; live 14-09 step 5. D-15 model redesign parked (accepted) |
| DASH-14 | 14-02, 14-04, 14-05 | SATISFIED | truths 10, 16-19, 21 |
| DASH-15 | 14-02, 14-03, 14-04, 14-05 | SATISFIED | truths 11-15, 20; advisory A-1 |
| DASH-16 | 14-08, 14-09 | SATISFIED | truth 26; live 14-09 steps 2-4 |
| DASH-17 | 14-06, 14-09 | DESCOPED (accepted) | operator decision 2026-09-28; REQUIREMENTS.md `[~]`; code removed 9f9bbe8 |

All seven IDs are claimed by at least one plan; REQUIREMENTS.md maps no further IDs to Phase 14. No orphans. Note: the REQUIREMENTS.md checkboxes and traceability table still read `[ ]` / `Pending` for PLR-14..16 and DASH-14..16; the orchestrator may want to flip them on phase completion.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| (phase-modified files) | - | TBD/FIXME/XXX | none found | - |
| dashboard-react/src/lib/config.ts | 52-72 | `*_PLACEHOLDER` constants | Info | Intentional deploy-time placeholders, pre-existing pattern |
| dashboard-react/src/lib/grouping.ts / treeModel.ts | grouping.ts:82, treeModel.ts:74 | Advisory A-1: folder group rollup (`rollUpGroup`) ignores incident membership, so a folder containing only consequence hosts still shows a DOWN/UNREACH header badge and counts toward severity ordering; StatsStrip counts likewise | Warning (advisory) | Host rows themselves comply with DASH-15; the aggregate header can still "raise an alarm" on a consequence's behalf. Not in any plan must-have and the 14-05 live gate was approved with it; worth folding into the parked criticality/dependency redesign or backlog |
| 14-REVIEW WR-01/02/03/05, IN-02 | - | editor rollback, TS/Python parser mismatch, unwritable service rows, pre-Apply visibility, unused service_criticality | Warning (accepted, deferred) | Parked by operator in the redesign todo |

### Human Verification Required

### 1. Multi-level DOWN chain after CR-01 fix

**Test:** Using the Livestatus external-command recipe (docs/Incident demo with fake check results.md), force a 3-level DOWN chain.
**Expected:** One incident card rooted at the top DOWN host; lower DOWN hosts listed as confirmed down and dimmed in tree and map.
**Why human:** `compute_incidents()` nesting changed in 24b22f5 after the 2026-09-26 live gate. Unit-tested only.

### 2. Reconnect and deep-link after CR-02/WR-04 fixes

**Test:** Let an incident open, disconnect the browser from the broker while it closes, reconnect. Then load `/?incident=<id>` fresh while an incident is open.
**Expected:** No ghost card after reconnect; fresh deep-link load scrolls to and rings the matching card.
**Why human:** Fixed in a1a73cf after the live gates; real MQTT reconnect timing and browser scrolling are not exercised by jsdom.

### Gaps Summary

No gaps. Every in-scope must-have from plans 14-01..14-05, 14-07 and 14-08 is present, substantive, wired and carrying live data; the 14-09 label read/write path was live-verified. Kiosk mode (DASH-17) and the D-15 model redesign are recorded as operator-accepted scope changes, not gaps. Status is human_needed only because the incident engine and the store's reconnect/deep-link behaviour changed after the last live gate; both checks are short smoke tests of already unit-tested fixes.

---

_Verified: 2026-09-28T06:27:40Z_
_Verifier: Claude (bm-verifier)_
