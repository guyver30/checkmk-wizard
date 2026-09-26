# Phase 14: Fleet Intelligence - Research

**Researched:** 2026-09-26
**Domain:** Root-cause incident grouping over existing Livestatus/parents data (Python poller), Checkmk host-label read/write for a business-knowledge overlay (criticality/dependencies), React/TS incident presentation and kiosk mode
**Confidence:** MEDIUM-HIGH (architecture integration points are HIGH — read directly from this repo's source; the incident-grouping algorithm and label-encoding scheme are Claude's-discretion designs per D-09/D-13, tagged ASSUMED and meant to be checked, not novel unverified library claims)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Three phases: 14 (impact, root-cause, kiosk), 14.1 (history + availability + Grafana), 14.2 (prediction + AI narration). Numbered as decimals; Phase 15 (location) is not renumbered.
- **D-02:** Availability reporting on MinIO (roadmap feature 4) belongs to 14.1, with the TSDB, because both share the poller-writes-history plumbing and the retention decision.
- **D-03:** The four blocking decisions from ROADMAP.md are resolved here (D-20, D-21, D-22, D-23) so no phase is blocked on them.
- **D-04:** Impact is NOT derived from `device_type`. An UNREACHABLE device behind a dead unmanaged switch may still be operating (only unobservable); a genuinely DOWN device is more serious. The UI must distinguish "not observable (upstream cause)" from "confirmed down" and never assert "lift not operating" from monitoring data alone.
- **D-05:** Criticality is business knowledge that Checkmk does not have. It is entered by an operator, never inferred.
- **D-06:** Scope is the largest option: evidence framing **plus** per-host criticality **plus** dependency links ("depends on"). Deliberately large; the planner should wave it so evidence framing (root-cause collapse) ships and is verifiable before criticality/dependency editing.
- **D-07:** Criticality tier and dependency links are stored as **Checkmk host labels** written via REST from the dashboard's edit mode, carried to every viewer by the poller — the Phase 13 pattern (`MAP_POSITION_LABEL` / `UNMANAGED_SWITCH_LABEL` in `scripts/mqtt_poller.py`). No new store, survives dashboard redeploy.
- **D-08:** Per-service criticality (e.g. a systemd service on a Linux host) is a label on the host keyed by service name.
- **D-09:** Exact tier vocabulary (names and count of tiers), label key names and the dependency label encoding are Claude's discretion, subject to Checkmk label constraints (research must verify label value length/charset against the live 2.4.0p36 site).
- **D-10:** Root-cause collapse uses Phase 13's `parents` plus the DOWN vs UNREACHABLE distinction already in `host_state_raw` (Phase 11 D-17).
- **D-11:** When a device is DOWN and its parent is an **unmanaged** switch (unobservable), treat the unmanaged parent as the **inferred** root cause, labelled "inferred, not confirmed". If several siblings under it go down together it is one incident; a single device down alone with no sibling evidence is its own incident.
- **D-12:** Rendering: a top-of-dashboard **incident card list** (one card per root cause: duration, consequences grouped into "not observable" vs "confirmed down", worst criticality affected). In the device tree and map, consequence devices stay visible but are dimmed and point to the incident instead of raising their own alarm.
- **D-13:** Incident detection/grouping happens in the poller and is published to retained MQTT topics so the dashboard stays a pure MQTT consumer for this feature. Topic names are Claude's discretion; follow the `lan/devices/...` per-topic, change-only publishing conventions (PLR-04).
- **D-14:** Kiosk/wall mode: full-screen, chrome-free, auto-rotating for a lobby/boardroom screen. Details (rotation content, interval, URL switch such as `?kiosk`) are Claude's discretion, keeping to the KONE design system.
- **D-20..D-24 (locked inputs for 14.1, not this phase's work):** Raw edition fixed, poller writes history; 3-year downsampled retention; Grafana alongside for analysts; TSDB-on-MinIO container; dashboard reads history read-only over HTTP (amends "no new backend").
- **D-30..D-32 (locked inputs for 14.2, not this phase's work):** no monitoring data leaves the network; simple regression with confidence tags; separate analytics container publishing to MQTT.

### Claude's Discretion

- Tier names/count, label key and dependency encoding (D-09)
- MQTT topic names and payload shapes (D-13)
- Kiosk details (D-14)
- Incident card visual design within the KONE design system

### Deferred Ideas (OUT OF SCOPE)

- Location-aware incident wording (tower/room) — arrives with Phase 15 location tags.
- Operator-acknowledged root cause per incident (manual choice of cause) — rejected for now in favour of inference (D-11).
- Local LLM for narration — optional later upgrade over templates (D-30, Phase 14.2).
- Checkmk-native metric export if the site ever moves off Raw — explicitly not designed for (D-20).
- History/TSDB/Grafana (Phase 14.1) and prediction/narration (Phase 14.2) — entirely out of this phase.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PLR-14 | Poller groups non-OK hosts into incidents each cycle, one incident per root cause, using `parents` and DOWN-vs-UNREACHABLE. Re-derives every cycle from Livestatus, no persisted state | "Root-Cause Grouping Algorithm" and "Incident Identity Without Persisted State" below give the exact grouping rule, the `last_state_change`-based duration source, and the self-heal-via-reconcile pattern that satisfies "no persisted state" |
| PLR-15 | Unmanaged-parent inference: DOWN host under an unmanaged switch + a non-OK sibling promotes the switch to inferred root; a lone DOWN host under an unmanaged switch is its own incident | Algorithm's Step 3 (unmanaged-parent inference) codifies this exactly, reusing Phase 13's `UNMANAGED_SWITCH_LABEL`/`unmanaged` field already carried on every topology node |
| PLR-16 | Poller publishes open incidents to retained MQTT topics, change-only, tombstones on close; carries operator-set criticality/per-service criticality/depends-on labels to every viewer; worst-affected criticality counts root + consequences + dependents | Topic design (`lan/incidents/{id}/status`) with a diff/tombstone pattern identical to `publish_device_status`/`publish_tombstone`; label carriage via `topology_nodes()` extension (same precedent as `map_position`/`unmanaged` in Phase 13); "Worst-Affected Criticality" section gives the reverse-dependency-closure algorithm |
| DASH-14 | Incident card list above the primary view: root, duration, inferred marker, consequence hosts split into confirmed-down/not-observable, worst criticality, ordered by worst criticality then duration | "Dashboard Architecture" section: new Zustand slice + `IncidentList`/`IncidentCard` components above `ThreePaneLayout`, ordering via tier ordinal + `since` timestamp |
| DASH-15 | Tree and map: consequence hosts stay visible but dimmed, link to their incident instead of alarming; only the root shows alarm styling | Extension points identified in `treeModel.ts` (`TreeDeviceNode`) and `topologyLayout.ts` (`MapNode`) — both already take device-state input as a plain parameter, ready for an `incidentConsequenceIds` set |
| DASH-16 | Edit mode: set host criticality tier, per-service criticality, add/remove depends-on links, written via the same scoped REST credential + single Apply flow as DASH-12 | `checkmkWrite.ts`'s `updateHostAttributes`/`setMapPosition` pattern generalizes directly; label encoding designed in "Label Design" section |
| DASH-17 | Kiosk/wall mode via URL, full-screen, no nav/edit chrome, auto-rotates between incident list and topology map | "Kiosk Mode" section: recommended `?kiosk=1` query param on the existing `/` route, Fullscreen API gesture caveat, rotation via a small interval hook |

</phase_requirements>

## Summary

Phase 14 is almost entirely new logic layered on data the poller already reads (`parents`, `host_state_raw`, `worst_service_state`) and a write path the dashboard already has (Phase 13's REST-via-`topology_editor`-credential + single Apply flow). Nothing here needs a new library, container, or credential. The two genuinely new technical questions — "what can a Checkmk host label hold" and "how do we compute an incident's duration with zero persisted poller state" — both have satisfying answers: labels tolerate any character except a colon in either key or value (confirmed against Checkmk's own docs), and Livestatus's per-host `last_state_change` timestamp (a standard Nagios-lineage column, present across every Livestatus implementation checked, though not yet live-probed on THIS 2.4.0p36 site — recommend the same `GET columns` defensive probe the poller already runs for other optional columns) gives a duration for free without inventing any incident-state tracking.

The root-cause grouping algorithm itself (PLR-14/PLR-15) is new design work, not a documented Checkmk feature — Checkmk's own "Fix problems in your network" / "aggregations" functionality is a Checkmk-side concept the poller does not use; this phase reimplements a purpose-built version of it directly against Livestatus's `parents` and `host_state_raw` fields. The design in this document (root selection, unmanaged inference, consequence collapse, and the worst-criticality dependency-closure rule PLR-16 requires) is Claude's-discretion work product per D-09/D-13 — it should be treated as a strong starting proposal for the planner and discuss-phase to validate against edge cases (nested failures, nested dependency chains), not as verified fact.

**Primary recommendation:** Extend the poller's existing per-cycle snapshot/diff loop (`run_cycle`) with an incident-computation step fed by data it already has (no new Livestatus columns except an optional `last_state_change` probe), publish incidents on new per-incident retained topics mirroring `lan/devices/{id}/status`'s shape and tombstone convention, and carry criticality/dependency labels as new fields on the existing `lan/devices/topology` node shape — the same place Phase 13 added `map_position`/`unmanaged`. On the dashboard, add one new Zustand slice, two new small pure-logic modules (`incidents.ts`, extending `topologyLayout.ts`/`treeModel.ts`), and reuse every existing edit-mode/Apply/idle-timeout/design-system pattern verbatim for the new criticality/dependency editing UI.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Incident detection/grouping (root-cause collapse) | Backend (poller) | — | Must be computed once, consistently, for every viewer (D-13); browser has no Livestatus access |
| Incident duration/identity | Backend (poller) | — | Derived from Livestatus `last_state_change`, self-heals across poller restarts with no persisted state (PLR-14) |
| Criticality/dependency storage | Database (Checkmk WATO config, via host labels) | Backend (poller reads, dashboard writes) | D-07 locks this to Checkmk labels; no new store |
| Criticality/dependency editing | Browser (dashboard edit mode) | API/Backend (Checkmk REST, direct browser-to-Checkmk per Phase 13's reversal of the read-only posture) | Same architecture Phase 13 already established for `parents`/`map_position` |
| Incident card rendering, dimming, ordering | Browser (React dashboard) | — | Pure presentation over poller-published MQTT data |
| Kiosk/wall mode | Browser (React dashboard, routing + Fullscreen API) | — | No server involvement; a URL-driven rendering mode of the existing SPA |

## Standard Stack

No new external packages. This phase is new logic in two existing components:

### Core (already in place, reused verbatim)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (`urllib`, `json`, `dataclasses`) | 3.11 (project-pinned) | Poller's REST/Livestatus/MQTT glue | Existing project convention (`scripts/mqtt_poller.py` is stdlib-only for `httpx`-free operation in the automation-worker container) |
| `mqtt.js` | ^5.16.0 (already a dependency, `dashboard-react/package.json`) | Incident topic subscription | Already the app's only MQTT client |
| `zustand` | ^5.0.15 (already a dependency) | New `incidents` slice | Same wholesale-replace-slice convention as `devices`/`topology` |
| `kone-design-system` | file: tarball (already a dependency) | `Card`/`Badge`/`Switch`/`Select` primitives for incident cards and the criticality/dependency editor | Locked project convention (11.1 D-40) |
| Browser Fullscreen API (`Element.requestFullscreen()`) | Web platform, no package | Kiosk true-fullscreen | Native API; verified requires a user gesture — see Kiosk Mode pitfall below |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Poller-computed incidents | Checkmk's own "BI" (Business Intelligence) aggregation rules | Checkmk BI is a CE-available feature that could express parent/child aggregation server-side, but it changes Checkmk's own configuration (new rule sets, another thing the wizard/dashboard would need to keep in sync) and does not solve the "operator-entered criticality/dependency" half of this phase at all (D-05 requires business knowledge Checkmk structurally cannot have) — not investigated further, out of scope per this phase's minimal-new-surface posture and D-07's explicit label-based storage choice |
| Per-incident label encoding designed here | A JSON blob in a single label value | Rejected: harder to grep/debug in the Checkmk UI (labels display as flat text), and a JSON blob crossing the "any character except colon" constraint would need escaping discipline the flat `key=val;key=val` scheme avoids |

**Installation:** none — no `uv add`/`npm install` needed for this phase.

## Package Legitimacy Audit

**Not applicable.** This phase introduces zero new third-party packages in either the Python poller or the React dashboard — every dependency listed under Standard Stack above is already installed and used by prior phases. No `slopcheck`/registry verification is required. If the planner's task breakdown ends up needing a package this research did not anticipate (e.g. a date/duration formatting helper), run the Package Legitimacy Gate at that point rather than skipping it.

## Verified: Checkmk Host Label Constraints

**Confidence: HIGH** — `[CITED: docs.checkmk.com/latest/en/labels.html]`, cross-checked against `[CITED: forum.checkmk.com]` community confirmation.

- Format is `key:value`; **both the key and the value may contain any character except the colon (`:`)**. This is more permissive than host tags.
- A host may have any number of labels, but **only one value per key** (a host cannot carry both `foo:bar` and `foo:bar2` simultaneously — setting a new value for an existing key replaces it).
- Newer Checkmk versions validate that imported/auto-generated labels never contain a colon in the key or value, replacing one with an underscore if the source data has one — confirms the colon restriction is enforced server-side, not just a UI convention.
- Three label origins exist (explicit/WATO, rule-based, auto-generated from special agents); **explicit labels — the kind this phase writes via REST — take priority over the other two**, so nothing else on this site can silently override an operator's criticality/dependency label.
- No documented length limit was found; this phase's values (short host-id lists, single-word tier tokens) are far below anything likely to be a practical concern, but this was not stress-tested against a live site and should be spot-checked once real hosts exist (a live REST PUT with a deliberately long value, mirroring how Phase 13's `probe_topology_rest.py`/`probe_host_attribute_merge.py` did their own live verification).
- **This directly confirms D-09's ask**: the label scheme below (comma/`=`-delimited values) is safe because neither host names (`_HOST_NAME_RE`: letters/digits/underscore/hyphen/dot) nor the tier vocabulary tokens this phase mints ever need a colon.

## Label Design (D-09, Claude's discretion — tagged ASSUMED, needs planner/discuss confirmation)

Following the exact precedent of `MAP_POSITION_LABEL`/`UNMANAGED_SWITCH_LABEL` in `scripts/mqtt_poller.py` (module-level string constants, shared byte-for-byte between the poller's Python and the dashboard's `topologyLayout.ts`/`checkmkWrite.ts` TypeScript):

```python
# Proposed additions to scripts/mqtt_poller.py, same section as MAP_POSITION_LABEL
CRITICALITY_LABEL = "criticality"                    # host-level tier
SERVICE_CRITICALITY_LABEL = "service_criticality"    # one label, multi-entry value
DEPENDS_ON_LABEL = "depends_on"                      # one label, multi-entry value

CRITICALITY_TIERS = ("low", "medium", "high", "critical")  # ordinal, index = rank
```

- **Host criticality tier** (D-05): `criticality:<tier>` where `<tier>` is one of a small fixed vocabulary. Proposed: **`low` / `medium` / `high` / `critical`** (4 tiers — matches the operator's own examples: "a multimedia server outranks a multimedia screen" is a 2-tier distinction in practice, but "some Linux services matter more than others" plus a top "this is the whole building" tier argues for 4, not 2, so ties don't collapse everything into one bucket). A host with no `criticality` label defaults to the lowest tier (`low`) for ordering purposes — never treated as "unset ⇒ excluded", since an incident's worst-criticality calculation (PLR-16) must still produce a sane answer for a fleet where the operator hasn't yet triaged every host.
- **Per-service criticality** (D-08): rather than one label key per service (which would force sanitizing arbitrary service-name strings like `"Filesystem /"` or `"Systemd Service cron"` into label-key-safe tokens, and Checkmk's "one value per key" rule means a naive `service_criticality:<name>` key-per-service scheme still needs a value, doubling the key count for no benefit), encode **all of a host's per-service overrides in the single `service_criticality` label's value**, as `;`-separated `name=tier` pairs: `service_criticality: cron=high;ModemManager=low`. Neither `;` nor `=` can legally appear in a Checkmk service name derived from this project's own check plugins (built-in check names are plain ASCII words/paths); the poller should still defensively reject/skip any service name containing either delimiter when writing, the same defensive posture `_MAP_POSITION_RE`/`isValidHostName` already apply elsewhere in this codebase, rather than assume it can never happen.
- **Depends-on links** (D-06): `depends_on:<host1>,<host2>,...` — comma-separated Checkmk host ids on the *dependent* host (the screen), pointing at what it depends on (the media server), matching the operator's own example wording ("screen -> media server"). Host ids are already constrained to `[-0-9a-zA-Z_.]+` (`HOST_NAME_RE`, `dashboard-react/src/lib/checkmkWrite.ts`), so a bare comma is an unambiguous, safe delimiter with no escaping needed.
- All three keys and values are colon-free by construction, satisfying the one hard constraint the docs actually impose.

**Assumption flagged (A1 in the Assumptions Log):** the 4-tier vocabulary, the `;`/`=`/`,` delimiter choices, and "one combined label per multi-value concept rather than one label per entry" are Claude's discretion per D-09 — reasonable and internally consistent, but not something the operator has seen or confirmed. Surface this explicitly in discuss-phase or plan review before the planner locks task acceptance criteria around these exact strings.

## Architecture Patterns

### System Architecture Diagram

```
Checkmk Livestatus (TCP)          Checkmk REST API (host_config)
        │                                    │
        │ parents, host_state_raw,           │ labels: map_position,
        │ worst_service_state,               │ unmanaged, criticality,
        │ last_state_change (NEW,            │ service_criticality,
        │  probe-gated)                      │ depends_on  (NEW)
        ▼                                    ▼
┌───────────────────────────────────────────────────────┐
│  scripts/mqtt_poller.py :: run_cycle()                 │
│                                                          │
│  1. existing per-device status/services/history publish │
│  2. NEW: compute_incidents(snapshots, host_config)       │
│       - build parent/child + unmanaged-aware graph       │
│       - group non-OK hosts into root + consequences       │
│       - diff against in-memory previous-incident set       │
│       - publish opened/changed, tombstone closed            │
│  3. topology_nodes() carries criticality/service_criticality/│
│     depends_on alongside existing map_position/unmanaged     │
└───────────────────────────────────────────────────────┘
        │                                    │
        │ lan/incidents/{id}/status (NEW)    │ lan/devices/topology
        │ retained, tombstoned on close      │ (existing topic, new fields)
        ▼                                    ▼
┌───────────────────────────────────────────────────────┐
│  Mosquitto (WebSockets, read-only ACL — unchanged)       │
└───────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────┐
│  dashboard-react (mqtt.js singleton, unchanged)          │
│                                                            │
│  useAppStore: NEW `incidents` slice (wholesale-replace,    │
│  same convention as `devices`)                              │
│                                                              │
│  IndexRoute                                                  │
│   ├─ NEW IncidentList (above ThreePaneLayout, like StatsStrip)│
│   ├─ Tree / TopologyMap: dimmed consequence hosts, link →      │
│   │   incident instead of own alarm (DASH-15)                  │
│   └─ Edit mode: criticality/service-criticality/depends-on      │
│       editor → checkmkWrite.ts (GET→merge labels→PUT→Apply,      │
│       same pattern as setMapPosition/updateParents)               │
│                                                                     │
│  NEW: ?kiosk=1 rendering mode — no NavBar/edit chrome, rotates      │
│  between IncidentList and TopologyMap on a timer                     │
└───────────────────────────────────────────────────────┘
```

### Recommended Project Structure

No new top-level directories. New files, following exact existing sibling-file conventions:

```
scripts/
└── mqtt_poller.py           # add: compute_incidents(), publish_incident(),
                              #      publish_incident_tombstone(), extend
                              #      HostConfigInfo/topology_nodes()/
                              #      fetch_host_config()

tests/
└── test_mqtt_poller.py      # add: TestComputeIncidents, TestUnmanagedInference,
                              #      TestIncidentPublishDiff (mirrors existing
                              #      TestServicesSignature-style test classes)

dashboard-react/src/
├── lib/
│   ├── incidents.ts          # NEW: pure logic — parse incident payload, sort
│   │                         #      by (worstCriticalityRank desc, sinceMs asc),
│   │                         #      worst-criticality dependency-closure calc
│   ├── incidents.test.ts     # NEW
│   ├── topologyLayout.ts     # extend: MapNode gains dimmed/incidentId/criticality
│   ├── treeModel.ts          # extend: TreeDeviceNode gains dimmed/incidentId
│   └── checkmkWrite.ts       # extend: setCriticality/setServiceCriticality/
│                             #         updateDependsOn (generalize
│                             #         updateHostAttributes's label-merge)
├── components/
│   ├── IncidentList.tsx      # NEW: renders IncidentCard[] above ThreePaneLayout
│   ├── IncidentCard.tsx      # NEW
│   └── CriticalityEditor.tsx # NEW: edit-mode panel (tier select, service list,
│                             #      depends-on link picker)
├── hooks/
│   └── useKioskRotation.ts   # NEW: small interval hook, same shape as useNowTick
└── store/
    └── useAppStore.ts        # extend: `incidents: Record<string, IncidentPayload>`
                              #         slice + handleMessage branch
```

### Pattern 1: Root-Cause Grouping Algorithm (PLR-14/PLR-15)

**What:** Per poll cycle, group every non-OK host into incidents, each keyed by a stable root.

**Precise rule** (Claude's-discretion design, `[ASSUMED]` — see Assumptions Log A2):

1. Build a `child -> parents` and `parent -> children` index from every snapshot's `parents` list (already fetched every cycle — no new Livestatus query).
2. A host is **non-OK** if `host_state_raw != "UP"` (i.e. `"DOWN"` or `"UNREACH"`, the same field Phase 11 D-17 introduced) — service-level WARN/CRIT does *not* trigger incident grouping; D-04/roadmap wording is about host-level DOWN/UNREACHABLE cascades, not individual failing checks.
3. **Root selection**, per host `H` in state DOWN (never UNREACH — an UNREACHABLE host is by definition not a root, its unreachability is explained by something upstream):
   - If `H`'s parent `P` is **not** marked `unmanaged` (or `H` has no parent), `H` is a root. Its consequence set is every descendant of `H` (in the parent→children graph) that is currently non-OK — normally these are `UNREACH` (Checkmk cannot reach anything behind a truly down device) but a descendant that is independently `DOWN` is included too, flagged as "confirmed down" like the root (see Pitfall below on this being a known false-attribution risk).
   - If `H`'s parent `P` **is** `unmanaged` (D-11): check every other child of `P`. If **any** sibling is also non-OK, `P` (the unmanaged switch) becomes the root instead of `H`, marked `inferred: true`. Every non-OK descendant of `P` (including `H`) becomes a consequence. If `H` is the *only* non-OK host under `P`, `H` remains its own single-host incident (root = `H`, `inferred: false`) — the sibling-evidence requirement is exactly D-11's wording.
4. Every UNREACH host that is not already claimed as a consequence by step 3 (e.g. its nearest non-OK ancestor was itself only UNREACH, not DOWN, because the true root is further up a multi-hop chain) walks its parent chain upward until it finds the nearest DOWN (or inferred-unmanaged) ancestor and joins that incident. A host with no DOWN ancestor anywhere in its chain (all ancestors UP, or the chain terminates without one — e.g. `parents` unset) has no incident to join and is left alone as a plain non-OK device (Checkmk data is simply inconsistent/incomplete for it — do not invent a root).
5. Consequence hosts are split, per D-12/DASH-14, into `confirmed_down` (their own `host_state_raw == "DOWN"`) and `not_observable` (`host_state_raw == "UNREACH"`).
6. Incident id: `f"incident-{root_id}"` — deterministic, stable across cycles and across a poller restart, requiring no persisted counter.

```python
# Illustrative shape, not final code — the planner's task breakdown should turn
# this into real functions with the project's existing dataclass/typing conventions.
def compute_incidents(
    snapshots: list[DeviceSnapshot],
    host_config: dict[str, HostConfigInfo],
) -> list[dict]:
    ...
```

**When to use:** Every poll cycle, after `topology_nodes()` is built (parents data is already in hand) and before the topology/events publish step in `run_cycle()`.

### Pattern 2: Incident Identity and Duration Without Persisted Poller State

**What:** PLR-14 requires the poller to "keep no incident state of its own" and self-heal from Livestatus every cycle — exactly the existing `reconcile_state()`/`state.previous_nodes` pattern already used for topology and service diffing, extended to incidents.

- **Duration source:** Livestatus's `last_state_change` column (a standard Nagios-lineage timestamp column — `[ASSUMED, community-sourced, not yet live-verified on this project's 2.4.0p36.cre site]`, see Assumptions Log A3) gives "when did this host's current state begin" for free, per host, every cycle — no incident-open-time bookkeeping needed. An incident's `since` = `min(last_state_change)` across the root and every current consequence. This is exactly why "no persisted state" is achievable: the *duration* is Checkmk's own already-tracked fact, not something the poller has to remember across a restart.
- **Add `last_state_change` to `OPTIONAL_HOST_COLUMNS`** (`scripts/mqtt_poller.py`) behind the exact same defensive `available_host_columns()`/`select_host_columns()` probe already gating `parents`/`tags`/`alias` — if the live column probe (`GET columns` query, the same live-verification method this codebase already uses, see `available_host_columns()`'s docstring) doesn't find it, degrade to `since = None` for every incident rather than failing the whole cycle, and flag this in a task's verification step as something to live-check against the real site before considering PLR-14 done.
- **Tombstoning closed incidents / self-heal on restart:** extend `reconcile_state()`'s startup subscribe list (`client.subscribe(...)` calls around line 1626-1631) to also subscribe to `lan/incidents/+/status`, collecting currently-retained incident ids into a new `state.retained_incident_ids` set — the exact same mechanism `retained_ids` already uses for devices (`allow_stale_sweep`). Then hold `state.previous_incident_ids: set[str]` in memory for the life of the process (not persisted to disk — resets on restart, which is fine because the retained-topic reconcile above already recovers what was open) and, each cycle, tombstone any id present in `previous_incident_ids` but absent from this cycle's freshly-computed incident set.

### Pattern 3: Carrying Criticality/Dependency Labels to Every Viewer (PLR-16 second half)

**What:** Extend the existing once-per-cycle REST `host_config` lookup (`fetch_host_config()`, already reads `map_position`/`unmanaged` off `extensions.attributes.labels`) to also read `criticality`, `service_criticality`, `depends_on`. Extend `HostConfigInfo`, `topology_nodes()`, and `topology_signature()` the same way Phase 13 extended them for `map_position`/`unmanaged` — this means a criticality/dependency change automatically triggers a `lan/devices/topology` republish through the existing change-detection signature, with zero new topics or new REST calls.

```python
# scripts/mqtt_poller.py, mirroring the existing 13-04 extension pattern
raw_criticality = labels.get(CRITICALITY_LABEL)
criticality = raw_criticality if raw_criticality in CRITICALITY_TIERS else "low"
depends_on = _parse_depends_on(labels.get(DEPENDS_ON_LABEL))  # comma-split, filter to known host ids
service_criticality = _parse_service_criticality(labels.get(SERVICE_CRITICALITY_LABEL))
```

**Why this tier, not a new topic:** criticality/dependency data changes rarely (operator edits it deliberately, like `map_position`), is read from the same REST call the poller already makes every cycle, and every dashboard viewer already subscribes to `lan/devices/topology` — adding a second topic for logically-the-same-cadence data would only fragment the contract PLR-13 just unified.

### Pattern 4: Worst-Affected Criticality (PLR-16's dependency-closure requirement)

**What:** "An incident's worst affected criticality counts the root, its consequences, and every host that depends on any of them" — this needs a **reverse** dependency index (`depends_on` points from dependent → depended-upon, e.g. screen → media server; the reverse index answers "who depends on media server?").

1. Build `dependents: dict[str, list[str]]` by inverting every host's `depends_on` list.
2. `affected = {root} | consequence_ids`.
3. **Transitive closure recommended** (`[ASSUMED — Claude's discretion, flag for confirmation]`): BFS/DFS outward from `affected` following `dependents` edges, since a two-hop chain (lift depends on media server, media server depends on the core switch that just failed) should plausibly still count — but this was not explicitly specified by the operator and could over-count in a densely-linked fleet; the planner should treat one-hop vs. transitive as an open question worth a quick discuss-phase confirmation rather than silently picking one.
4. `worst_criticality = max(CRITICALITY_TIERS.index(host_config[h].criticality) for h in affected | closure)`, defaulting absent-criticality hosts to `"low"` (index 0) per the Label Design section above.

### Anti-Patterns to Avoid

- **Inferring criticality or "is this actually broken" from `device_type` or any Checkmk-native signal.** D-04/D-05 explicitly forbid this — criticality is 100% operator input, and impact wording must stay in "not observable" vs "confirmed down" language, never "not operating," for any host whose only signal is UNREACH.
- **Persisting incident state to disk or treating `state.previous_incident_ids` as durable.** PLR-14 requires the poller to be restartable with zero incident memory; the in-memory set plus the retained-topic reconcile at startup is the *entire* durability story — do not add a JSON file or similar.
- **Adding a new REST call for criticality/dependency data.** It rides the existing `fetch_host_config()` call; a second REST round-trip per cycle would be needless load with no benefit (mirrors the reasoning that led Phase 13 to reuse one GET for map_position/unmanaged too, per `13-01 VERDICT V-LABELS-IN-COLLECTION`).
- **One label key per service** for per-service criticality — multiplies label count for no querying benefit this project needs, and forces sanitizing arbitrary service-name strings into label-key-safe tokens; the single-label multi-entry-value encoding avoids both problems (see Label Design).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| "Time since incident began" live-ticking display | A poller-side duration string that needs re-publishing every second | Publish `since` (ISO8601) once; let the browser compute elapsed time client-side | `dashboard-react/src/hooks/useNowTick.ts` already exists for exactly this ("badge staleness, stats-strip counts") — reuse it for incident-card duration, don't add a second periodic timer (its own header comment says "this is the app's only periodic timer") |
| REST GET→merge-labels→PUT boilerplate for 3 new label kinds | Three near-identical copy-pasted functions | Generalize `checkmkWrite.ts`'s existing `updateHostAttributes()` label-merge shape (already used once for `setMapPosition`) into a small shared `updateLabels(host, mutate)` helper, then `setCriticality`/`setServiceCriticality`/`updateDependsOn` become thin one-liners over it | The GET→drop-meta_data→merge→PUT-with-ETag dance is exactly what `updateHostAttributes` already does; duplicating it three more times is the kind of "don't hand-roll your own thing that already exists two files away" this table exists to prevent |
| Kiosk true fullscreen | A CSS-only "fake fullscreen" that claims to satisfy DASH-17 | Both: CSS chrome-free layout (works everywhere, no gesture needed) **and** an explicit "Enter fullscreen" affordance calling `Element.requestFullscreen()` (works once a human taps it, or when the browser itself is launched in OS/kiosk mode, e.g. `chromium --kiosk <url>`) | The Fullscreen API cannot be invoked automatically on page load or from a timer — browsers reject it outside a real user gesture (verified, see Kiosk Mode section) |

**Key insight:** every piece of new "infrastructure" this phase seems to need (a duration clock, a label-merge REST helper, a per-device diff/tombstone convention, a stale-topic reconcile-on-restart mechanism) already exists in this codebase in a form built for an adjacent problem. The work is almost entirely: extend the existing shape one more time, don't invent a parallel one.

## Common Pitfalls

### Pitfall 1: Grouping an independently-DOWN descendant under the wrong incident
**What goes wrong:** A host that is DOWN for its *own* unrelated reason, but happens to sit physically behind an unmanaged switch that also just died, gets folded into that switch's incident as a "confirmed down" consequence — implying a causal link that isn't real.
**Why it happens:** The grouping algorithm (Pattern 1) has no independent evidence to distinguish "down because the switch died" from "coincidentally also down." Livestatus's `parents`/`host_state_raw` alone cannot disambiguate this.
**How to avoid:** Accept this as a known, documented limitation (it matches D-04's "evidence framing, never invented certainty" spirit — the UI already hedges UNREACH as "not observable," and a coincidentally-DOWN host inside an incident is still, factually, DOWN, so the wording isn't false, just imprecise about cause). Do not attempt session-level correlation or timing heuristics to "fix" this in v1 — out of scope, not requested, and risks the exact overclaiming D-04 warns against.
**Warning signs:** An incident card whose "confirmed down" list is unexpectedly large relative to its "not observable" list may be worth a operator gut-check during UAT.

### Pitfall 2: Trusting `last_state_change` exists without a live probe
**What goes wrong:** Assuming the column is present and shipping incident duration against it; if the live Checkmk 2.4.0p36.cre site's Livestatus doesn't expose it (unlikely but unconfirmed — see Assumptions Log A3), every incident silently gets `since: null`.
**Why it happens:** This research could not reach a live Livestatus instance to run `GET columns` (the same limitation `09-RESEARCH.md`/`10-RESEARCH.md` flagged for their own optional-column assumptions, resolved there by a live probe during planning/execution).
**How to avoid:** Add `last_state_change` through the exact same `OPTIONAL_HOST_COLUMNS`/`available_host_columns()` defensive-probe machinery already in place — this makes the pitfall self-correcting by construction (degrade to `None`, log a warning, never crash) rather than something a task needs to special-case.
**Warning signs:** every incident's `since` reads `null` in a live smoke test.

### Pitfall 3: Forgetting the Fullscreen API's user-gesture requirement
**What goes wrong:** A kiosk URL that tries to call `requestFullscreen()` in a `useEffect` on mount silently fails (`[VERIFIED via WebSearch, cross-referenced MDN/W3C community sources]` — "Failed to execute 'requestFullscreen' on 'Element': API can only be initiated by a user gesture"), leaving a non-fullscreen page with no error visible to the operator setting up the signage.
**Why it happens:** Browsers deliberately block auto-triggered fullscreen for the same reason they block autoplay-with-sound — it would let any page hijack the whole screen unprompted.
**How to avoid:** Ship the chrome-free CSS layout unconditionally under `?kiosk=1` (this alone satisfies "no navigation or edit controls"), and offer an explicit "Enter fullscreen" button as a one-time affordance for the true edge-to-edge case; document that dedicated signage hardware should instead launch the browser itself in OS-level kiosk mode (`chromium --kiosk <url>`), which sidesteps the API restriction entirely.
**Warning signs:** UAT on real signage hardware shows browser chrome (address bar) still visible after clicking through — check whether the launch method is OS kiosk mode or just the URL.

### Pitfall 4: Re-deriving severity/sort logic instead of reusing existing rank tables
**What goes wrong:** A new incident-card sort ("worst criticality, then duration") gets its own ad-hoc comparator instead of reusing `grouping.ts`'s `SEVERITY_RANK` pattern (already imported by `treeModel.ts` for exactly this kind of "there is one canonical rank table" discipline, per that file's own header comment: "This module does not re-derive severity ordering... both already live in grouping.ts").
**How to avoid:** Define `CRITICALITY_RANK` (or reuse the tier array's `indexOf`) in one place (`incidents.ts`), import it everywhere a criticality comparison is needed (card sort, worst-affected calc, any future criticality badge color), matching this codebase's established "one source of truth per derived ordering" convention.

## Code Examples

### Existing label read/write pattern to extend (verified from this repo, not external docs)

```python
# scripts/mqtt_poller.py — the exact GET-labels pattern PLR-16 extends
attributes = extensions.get("attributes", {})
labels = attributes.get("labels", {}) if isinstance(attributes, dict) else {}
raw_map_position = labels.get(MAP_POSITION_LABEL)
map_position = (
    raw_map_position
    if isinstance(raw_map_position, str) and _MAP_POSITION_RE.match(raw_map_position)
    else None
)
```

```typescript
// dashboard-react/src/lib/checkmkWrite.ts — the exact label-write pattern
// setCriticality/setServiceCriticality/updateDependsOn should follow
export function setMapPosition(host: string, x: number, y: number): Promise<void> {
  return serialize(() =>
    updateHostAttributes(host, (attributes) => {
      const currentLabels =
        attributes.labels && typeof attributes.labels === "object"
          ? (attributes.labels as Record<string, unknown>)
          : {};
      return {
        ...attributes,
        labels: { ...currentLabels, [MAP_POSITION_LABEL]: formatMapPosition(x, y) },
      };
    }),
  );
}
```

```typescript
// dashboard-react/src/store/mqttClient.ts — extend for the new incident topic
export const SUBSCRIBE_TOPICS = [
  "lan/devices/+/status",
  "lan/devices/+/history",
  "lan/devices/+/services",
  "lan/devices/+/service_history",
  "lan/devices/topology",
  "lan/events/recent",
  "lan/poller/status",
  "lan/incidents/+/status", // NEW — retained delivery on SUBACK gives every open incident for free
];
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Dashboard shows per-device status only (Phase 11/12) | Dashboard groups impact by root cause and business criticality (Phase 14) | This phase | The unit operators reason about shifts from "device X is red" to "incident Y is affecting Z" |
| Read-only browser (Phase 11, D-01's safety argument) | Browser writes host attributes directly via a scoped credential (Phase 13 reversal, extended here to labels) | Phase 13, continued here | Already an accepted, deliberate architecture shift — Phase 14 does not reopen this decision, only extends what gets written |

**Deprecated/outdated:** nothing in this phase deprecates prior phases' work — DASH-14/15 are additive rendering on top of the existing tree/map/stats-strip, not a replacement.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|----------------|
| A1 | 4-tier criticality vocabulary (`low`/`medium`/`high`/`critical`), the `;`/`=`/`,` delimiter scheme, and "one combined label per multi-value concept" are the right encoding | Label Design | Low-medium: purely a naming/encoding choice, easy to rename before any real data is written, but a mid-flight rename after operators have tagged hosts would require a migration script |
| A2 | The root-cause grouping algorithm (root selection, unmanaged inference, multi-hop UNREACH chain walk, "independently-DOWN descendant" behavior) matches what the operator actually wants to see | Pattern 1 | Medium: a wrong grouping produces a misleading incident card (e.g. merging two unrelated failures, or splitting one real cascade into two cards) — should be checked against a few realistic Checkmk topologies during plan review/UAT, not just unit-tested against invented fixtures |
| A3 | `last_state_change` exists as a Livestatus `hosts` table column on this project's Checkmk 2.4.0p36.cre site | Pattern 2 | Low: the existing defensive-probe machinery degrades this gracefully to `since: null` rather than failing — but incident cards without a duration are a visibly worse UX, so this is worth an early live-probe task in Wave 0 rather than discovering it at UAT |
| A4 | Transitive (not just one-hop) closure over `depends_on` edges is the right scope for "worst affected criticality" | Pattern 4 | Low-medium: over-counting worst-criticality in a densely-linked fleet would make everything look critical; under-counting (one-hop only) would miss legitimate multi-hop impact — worth a one-line discuss-phase confirmation before locking |

## Open Questions

1. **One-hop vs. transitive `depends_on` closure for worst-affected criticality (PLR-16)?**
   - What we know: the requirement text says "every host that depends on any of them" — grammatically ambiguous between "any of them directly" and "any of them, including transitively."
   - What's unclear: whether the operator's mental model extends past one hop.
   - Recommendation: default to transitive (safer to over-surface a business-critical impact than under-surface it) but flag this explicitly for a one-question discuss-phase confirmation before the planner locks acceptance criteria.

2. **Does an incident's consequence set include hosts that are independently DOWN (Pitfall 1), or should the algorithm try to exclude them?**
   - What we know: Livestatus alone cannot distinguish "down because of the incident" from "down for an unrelated reason at the same time."
   - What's unclear: whether operators would find the current design's over-inclusion (folding coincidental failures into one card) confusing enough to warrant future work.
   - Recommendation: ship as designed (Pattern 1), document the limitation in the incident card's own UI copy if there's room (e.g. a small "cause inferred from topology, not confirmed" note — which D-11 already requires for the inferred-root case specifically), and treat any operator pushback as a future refinement, not a Phase 14 blocker.

3. **Do systemd/other per-service criticality overrides ever need to influence an incident's worst-affected criticality (PLR-16), or only host-level criticality?**
   - What we know: PLR-16's wording ("operator-set criticality tier") reads as host-level; per-service criticality (D-08) is stored but PLR-16 doesn't explicitly say it feeds incident severity.
   - What's unclear: whether a host with a WARN/CRIT on a `critical`-tier service, but whose own host-level tier is `low`, should visually stand out in an incident.
   - Recommendation: keep worst-affected criticality host-level-only for v1 (simpler, matches the literal requirement text); per-service criticality's only confirmed consumer in this phase is the per-service editor UI itself (DASH-16), not incident severity math.

## Environment Availability

Skipped — this phase has no new external tool/service/runtime dependency. Everything it touches (Checkmk Livestatus/REST, Mosquitto, the existing Python/Node toolchains) is already running and verified by prior phases.

## Validation Architecture

Skipped per `.planning/config.json`'s `workflow.nyquist_validation: false`.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | No new auth surface — reuses the existing scoped `topology_editor` credential |
| V3 Session Management | No | Stateless dashboard, unchanged |
| V4 Access Control | Yes | The `topology_editor` role must gain no new permissions beyond what Phase 13 already granted (`wato.edit_hosts`/`wato.manage_hosts`/etc.) — writing labels is already covered by the same host-edit permission that writes `parents`/`map_position`; verify no broader permission (e.g. `wato.users`, `wato.global`) is accidentally required |
| V5 Input Validation | Yes | Label values (criticality tier, service-criticality entries, depends-on host ids) must be validated against the fixed tier vocabulary / `HOST_NAME_RE` before writing — mirrors `_MAP_POSITION_RE`'s existing strict-validate-or-None posture; never trust a label value read back from Checkmk without the same validation (a hand-edited WATO label could contain garbage) |
| V6 Cryptography | No | No new secrets or crypto — reuses the existing `topology_editor` secret already embedded client-side per Phase 13's accepted trusted-LAN posture |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| A malformed/garbage `depends_on` label (e.g. containing a nonexistent host id, or a host referencing itself) causes an infinite loop in the reverse-dependency closure walk (Pattern 4) | Denial of Service | Track visited-host-ids during the BFS/DFS closure walk (standard cycle-guard), same defensive posture the codebase already applies to malformed/untrusted MQTT payloads in `useAppStore.ts` ("must never throw out of the message handler and blank the page") |
| An operator (or a compromised browser session using the embedded `topology_editor` secret) writes a criticality/dependency label that doesn't match the expected vocabulary, corrupting downstream sort/ranking logic | Tampering | Server-side (poller-read) validation exactly like `_MAP_POSITION_RE` — an out-of-vocabulary `criticality` value degrades to the default tier rather than crashing or silently sorting wrong |

## Sources

### Primary (HIGH confidence)
- `[CITED: docs.checkmk.com/latest/en/labels.html]` — host label format/character/quantity constraints (fetched directly this session)
- Direct source reads this session: `scripts/mqtt_poller.py`, `dashboard-react/src/lib/{checkmkWrite,topologyLayout,treeModel,display,types,mapIcons}.ts`, `dashboard-react/src/store/{useAppStore,mqttClient,selectors}.ts`, `dashboard-react/src/components/{TopologyToolbar,TreeNode}.tsx`, `dashboard-react/src/hooks/{useNowTick,useEditIdleTimeout}.ts`, `dashboard-react/src/App.tsx`, `dashboard-react/src/lib/config.ts`, `scripts/provision_topology_editor.py`, `.planning/ROADMAP.md` (Phase 14 entry), `.planning/config.json`, `docs/Podman setup for checkmk, minio, mosquitto, worker.md` (topic contract table)
- `[VERIFIED via WebSearch, cross-referenced multiple sources including MDN/GitHub issue threads]` — Fullscreen API's mandatory user-gesture requirement

### Secondary (MEDIUM confidence)
- `[CITED: forum.checkmk.com/t/creation-of-host-labels-format-of-section]` — corroborates the colon-only restriction and label priority ordering
- `last_state_change` Livestatus column existence — cross-referenced Icinga test fixtures, Checkmk werk references, and a DeepWiki Checkmk-repo summary; consistent across all sources but none is `docs.checkmk.com`'s own rendered column table (that page did not return machine-readable column data to WebFetch) — treat as MEDIUM, not HIGH, and gate behind the project's existing live-probe pattern

### Tertiary (LOW confidence)
- None retained as unverified — every WebSearch finding used above was cross-checked against at least one additional source or the project's own established verification pattern (defensive column probes)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; every reused pattern read directly from this repo's own source
- Architecture (label carriage via topology, incident topic design): MEDIUM-HIGH — topic/label placement decisions are consistent with strong precedent (Phase 13) but are new design, not documented fact
- Root-cause grouping algorithm: MEDIUM — logically sound against the stated requirements and D-11's example, but not validated against real Checkmk topology data or operator review
- Pitfalls: HIGH for the Fullscreen-API and defensive-probe items (both independently verifiable facts); MEDIUM for the "independently-DOWN descendant" grouping limitation (a design tradeoff, not a bug to fix)

**Research date:** 2026-09-26
**Valid until:** 30 days (stable domain — no fast-moving library versions involved; the Checkmk label-format finding is unlikely to change, and the algorithm design has no external expiry, only a "needs operator validation" flag already captured in the Assumptions Log)
