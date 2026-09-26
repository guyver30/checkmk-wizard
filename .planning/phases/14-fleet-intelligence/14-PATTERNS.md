# Phase 14: Fleet Intelligence - Pattern Map

**Mapped:** 2026-09-26
**Files analyzed:** 17 (2 modified backend, 2 backend tests areas, 13 dashboard files)
**Analogs found:** 17 / 17 (all have a strong same-repo precedent — this phase is explicitly "extend an existing shape," per RESEARCH.md's own framing)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `scripts/mqtt_poller.py` — `compute_incidents()` | service (poller cycle step) | transform (graph grouping over in-memory snapshots) | `topology_nodes()` / `topology_signature()` in same file (`scripts/mqtt_poller.py:500-539`) | role-match (new pure-transform function in the same module, same dataclass-in/dict-out shape) |
| `scripts/mqtt_poller.py` — `publish_incident()` / `publish_incident_tombstone()` | service (MQTT publish) | pub-sub, change-only, tombstone-on-close | `publish_device_status()` / `publish_tombstone()` (`scripts/mqtt_poller.py:1244-1330`) | exact (identical retained-topic + tombstone contract, same file) |
| `scripts/mqtt_poller.py` — extend `HostConfigInfo` / `fetch_host_config()` / `topology_nodes()` for criticality/service_criticality/depends_on | service (REST read + label parse) | CRUD (read-only side of label carriage) | `fetch_host_config()`'s existing `map_position`/`unmanaged` label read (`scripts/mqtt_poller.py:795-873`) | exact (same function, same REST GET, additive fields — Phase 13's own precedent) |
| `scripts/mqtt_poller.py` — extend `OPTIONAL_HOST_COLUMNS` for `last_state_change` | config (Livestatus column list) | request-response (defensive column probe) | `OPTIONAL_HOST_COLUMNS` tuple + `available_host_columns()`/`select_host_columns()` (`scripts/mqtt_poller.py:190-208`, `892-934`) | exact (append one more string; the probe/degrade machinery needs zero new code) |
| `scripts/mqtt_poller.py` — extend `run_cycle()`/`PollerState`/`reconcile_state()` for incident self-heal | service (orchestration) | event-driven, self-healing from retained state | `run_cycle()`'s removed/added/state-transition diff loop + `reconcile_state()`'s retained-topic-driven rebuild (`scripts/mqtt_poller.py:1535-1827`) | exact (same file, same "no persisted state, reconcile from broker" pattern extended one more time) |
| `tests/test_mqtt_poller.py` — new incident tests | test | — | Flat `def test_fetch_host_config_*` / `def test_topology_*` / `def test_run_cycle_*` functions (`tests/test_mqtt_poller.py:95-198, 438-519, 1620-1669`) | exact — **see note below: no `class Test...` convention exists in this file** |
| `dashboard-react/src/lib/incidents.ts` (new) | utility (pure logic) | transform (parse/sort/closure) | `dashboard-react/src/lib/grouping.ts` (rank table + roll-up) and `dashboard-react/src/lib/topologyLayout.ts` (parse/format a label-derived value) | role-match |
| `dashboard-react/src/lib/incidents.test.ts` (new) | test | — | `dashboard-react/src/lib/grouping.test.ts` | role-match |
| `dashboard-react/src/lib/topologyLayout.ts` (extend `MapNode`) | utility (pure transform) | transform | itself, existing `buildMapModel()`/`withGridPositions()` (`dashboard-react/src/lib/topologyLayout.ts:81-148`) | exact (additive fields on the same function) |
| `dashboard-react/src/lib/treeModel.ts` (extend `TreeDeviceNode`) | utility (pure transform) | transform | itself, existing `buildTree()` (`dashboard-react/src/lib/treeModel.ts:42-119`) | exact |
| `dashboard-react/src/lib/checkmkWrite.ts` (extend: `updateLabels`, `setCriticality`, `setServiceCriticality`, `updateDependsOn`) | service (REST write client) | request-response, CRUD | itself, existing `setMapPosition()`/`updateParents()` (`dashboard-react/src/lib/checkmkWrite.ts:135-191`) | exact |
| `dashboard-react/src/components/IncidentList.tsx` (new) | component | request-response (renders store state) | `dashboard-react/src/components/StatsStrip.tsx` (top-of-pane summary strip, reads store via props) | role-match |
| `dashboard-react/src/components/IncidentCard.tsx` (new) | component | request-response | `kone-design-system`'s `Message` component (`design-system/src/components/Message.tsx`) — no in-repo card consumer yet, so the library component itself is the analog | role-match (new UI atom, first use of `Message` in this app) |
| `dashboard-react/src/components/CriticalityEditor.tsx` (new) | component (edit-mode panel) | CRUD (form -> REST write) | `dashboard-react/src/components/TopologyToolbar.tsx` (edit-mode panel, pending-count, Apply wiring) | role-match |
| `dashboard-react/src/hooks/useKioskRotation.ts` (new) | hook | event-driven (timer) | `dashboard-react/src/hooks/useNowTick.ts` (the app's one sanctioned periodic timer) | exact |
| `dashboard-react/src/store/useAppStore.ts` (extend: `incidents` slice) | store | pub-sub (MQTT message -> wholesale-replace slice) | itself, existing `topology`/`devices` handling in `handleMessage()` (`dashboard-react/src/store/useAppStore.ts:111-237`) | exact |
| `dashboard-react/src/store/mqttClient.ts` (extend `SUBSCRIBE_TOPICS`) | config | pub-sub | itself (`dashboard-react/src/store/mqttClient.ts:29-37`) | exact |
| `dashboard-react/src/routes/IndexRoute.tsx` (extend: mount `IncidentList`, kiosk branch) | route/controller | request-response (page composition) | itself (`dashboard-react/src/routes/IndexRoute.tsx:165-227`) | exact |

---

## Pattern Assignments

### `scripts/mqtt_poller.py` — `compute_incidents()` (service, transform)

**Analog:** `topology_nodes()` / `topology_signature()`, same file (`scripts/mqtt_poller.py:500-539`)

**Core pattern to copy — plain-dict-out transform over a list of dataclasses, no I/O:**
```python
# scripts/mqtt_poller.py:500-513
def topology_nodes(snapshots: list[DeviceSnapshot]) -> list[dict]:
    return [
        {
            "id": snapshot.id,
            "parents": list(snapshot.parents),
            "device_type": snapshot.device_type,
            "folder": snapshot.folder,
            "alias": snapshot.alias,
            "map_position": snapshot.map_position,
            "unmanaged": snapshot.unmanaged,
        }
        for snapshot in snapshots
    ]
```
`compute_incidents(snapshots, host_config)` should follow the same shape: pure function, takes the already-fetched `list[DeviceSnapshot]` plus `dict[str, HostConfigInfo]` (both already in hand in `run_cycle()` before the topology publish step), returns `list[dict]` — no Livestatus/REST/MQTT call inside the function itself. Build the parent/child index from `snapshot.parents` exactly as `topologyLayout.ts`'s edge-building loop does client-side (see below), and reuse `snapshot.host_state_raw`/`snapshot.unmanaged` fields that already exist on `DeviceSnapshot` (`scripts/mqtt_poller.py:404,412`) — no new Livestatus column needed for the grouping algorithm itself, only for `last_state_change` (duration).

**Where to insert the call:** in `run_cycle()`, after `nodes = topology_nodes(snapshots)` (`scripts/mqtt_poller.py:1739`) and before the tombstone/added/removed diff block — RESEARCH.md's Pattern 1 "when to use" note.

**Naming convention to follow:** module-level pure functions named after their transform (`topology_nodes`, `classify_host_services`, `services_signature`) — so `compute_incidents`, not e.g. `IncidentComputer.compute()`. This codebase has zero classes for stateless transforms; only `PollerConfig`/`PollerState`/dataclasses use `class`.

---

### `scripts/mqtt_poller.py` — `publish_incident()` / `publish_incident_tombstone()` (service, pub-sub + tombstone)

**Analog:** `publish_device_status()` / `publish_tombstone()` (`scripts/mqtt_poller.py:1244-1330`)

**Change-only retained-publish pattern to copy:**
```python
# scripts/mqtt_poller.py:1244-1271 (publish_device_status, QoS 0 continuous-republish variant)
def publish_device_status(
    client: mqtt.Client,
    snapshot: DeviceSnapshot,
    timestamp: str,
    gauge_fields: dict | None = None,
) -> None:
    """Publish one device's current status. QoS 0: republished every cycle from live data."""
    payload = {
        "id": snapshot.id,
        "state": snapshot.state,
        ...
        "timestamp": timestamp,
    }
    payload.update(gauge_fields or {})
    _publish_json(client, device_status_topic(snapshot.id), payload, qos=0, retain=True)
```

**Tombstone pattern to copy exactly (zero-length retained payload = MQTT's own "clear" semantic):**
```python
# scripts/mqtt_poller.py:1306-1330
def publish_tombstone(client: mqtt.Client, device_id: str) -> None:
    for topic in (
        device_status_topic(device_id),
        device_history_topic(device_id),
        device_services_topic(device_id),
        device_service_history_topic(device_id),
    ):
        try:
            info = client.publish(topic, payload=None, retain=True, qos=1)
            info.wait_for_publish(timeout=5)
        except (TimeoutError, OSError) as exc:
            _logger.warning("Failed to publish tombstone to %s: %s", topic, exc)
```
Per RESEARCH.md D-13, incidents are QoS 1 change-triggered (like `publish_topology`/`publish_services`, not QoS 0 like `publish_device_status`) — publish only when an incident opens/changes, and tombstone (this exact `payload=None, retain=True, qos=1` + `wait_for_publish` pattern) when an incident closes. Route every publish through the existing single choke point `_publish_json()` (`scripts/mqtt_poller.py:1225-1241`) for the non-tombstone case, exactly as every other publish helper does.

**Topic naming convention to copy:** `device_status_topic()`/`device_history_topic()` etc. are one-line topic-builder functions (`scripts/mqtt_poller.py:440-453`) — add `incident_status_topic(incident_id)` the same way, returning `f"lan/incidents/{incident_id}/status"`.

---

### `scripts/mqtt_poller.py` — extend `HostConfigInfo`/`fetch_host_config()`/`topology_nodes()` for criticality/dependency labels (service, CRUD read side)

**Analog:** the exact same functions' existing `map_position`/`unmanaged` extension (Phase 13)

**Dataclass extension pattern:**
```python
# scripts/mqtt_poller.py:361-372
class HostConfigInfo:
    """One host's REST-sourced config: folder plus the two map-editing labels. ..."""
    folder: str = ""
    map_position: str | None = None
    unmanaged: bool = False
```
Add `criticality: str = "low"`, `service_criticality: dict[str, str] = field(default_factory=dict)`, `depends_on: list[str] = field(default_factory=list)` the same way — new fields, same class, all with safe defaults (never `None` for criticality per RESEARCH.md's Label Design "unset defaults to low" rule).

**Label read/validate pattern to copy verbatim (this IS the exact code RESEARCH.md's Code Examples section already quotes):**
```python
# scripts/mqtt_poller.py:859-870
attributes = extensions.get("attributes", {})
labels = attributes.get("labels", {}) if isinstance(attributes, dict) else {}
raw_map_position = labels.get(MAP_POSITION_LABEL)
map_position = (
    raw_map_position
    if isinstance(raw_map_position, str) and _MAP_POSITION_RE.match(raw_map_position)
    else None
)
unmanaged = labels.get(UNMANAGED_SWITCH_LABEL) == UNMANAGED_SWITCH_VALUE
```
Add analogous `raw_criticality = labels.get(CRITICALITY_LABEL); criticality = raw_criticality if raw_criticality in CRITICALITY_TIERS else "low"` plus `_parse_depends_on()`/`_parse_service_criticality()` helpers (small, `_`-prefixed module-private functions, matching `_MAP_POSITION_RE`'s naming convention) — never raise on a malformed label, always degrade to the safe default, per this file's established V5 input-validation posture.

**Constant placement convention:** new label constants (`CRITICALITY_LABEL`, `SERVICE_CRITICALITY_LABEL`, `DEPENDS_ON_LABEL`, `CRITICALITY_TIERS`) go in the same commented block as `MAP_POSITION_LABEL`/`UNMANAGED_SWITCH_LABEL` (`scripts/mqtt_poller.py:85-96`), with a dated comment explaining the Phase 14/D-07/D-09 provenance — this file's comment convention (see CLAUDE.md "Comments" section: cite what was verified and how, date bug-fixes/extensions).

**`topology_nodes()`/`topology_signature()` extension:** add the three new fields to both functions' dict/tuple output exactly as `map_position`/`unmanaged` were added (`scripts/mqtt_poller.py:500-539`) — this is what makes a criticality/dependency edit auto-trigger a `lan/devices/topology` republish through existing change detection, per RESEARCH.md Pattern 3. Use `.get()` with defaults in `topology_signature()`, matching its own documented rationale for tolerating older/hand-built node dicts (`scripts/mqtt_poller.py:518-525`).

---

### `scripts/mqtt_poller.py` — extend `OPTIONAL_HOST_COLUMNS` for `last_state_change` (config, defensive probe)

**Analog:** the existing `OPTIONAL_HOST_COLUMNS` tuple itself (`scripts/mqtt_poller.py:190-208`)

```python
OPTIONAL_HOST_COLUMNS = (
    "scheduled_downtime_depth",
    "acknowledged",
    "worst_service_state",
    "parents",
    "tags",
    "alias",
    "staleness",
)
```
Append `"last_state_change"` as one more tuple entry with a dated comment following this block's own convention (cites the live site/version, whether it's been probed, and what happens if absent — see the `staleness` entry's own comment at lines 200-206 as the template). No other code changes needed: `available_host_columns()`/`select_host_columns()` (`scripts/mqtt_poller.py:892-934`) already iterate `OPTIONAL_HOST_COLUMNS` generically and degrade any missing one to a logged warning, never a hard failure.

---

### `scripts/mqtt_poller.py` — incident self-heal in `run_cycle()`/`PollerState`/`reconcile_state()` (service, event-driven/self-healing)

**Analog:** the file's own removed/added/state-transition diff block plus `reconcile_state()`'s retained-topic rebuild

**`PollerState` extension pattern** (add `previous_incident_ids: set[str] = field(default_factory=set)`, in-memory only, not persisted — mirrors `retained_ids`'s own dated comment, `scripts/mqtt_poller.py:1402-1406`):
```python
# scripts/mqtt_poller.py:1371-1406 (PollerState, abbreviated)
class PollerState:
    previous_nodes: dict[str, dict]
    ...
    retained_ids: set[str] = field(default_factory=set)
```

**`reconcile_state()` subscribe-then-collect pattern to copy** (add `lan/incidents/+/status` to the same wildcard-subscribe list, collect ids into a new `retained_incident_ids` set the same way `retained_ids` is collected):
```python
# scripts/mqtt_poller.py:1626-1631
client.subscribe(TOPIC_EVENTS, qos=1)
client.subscribe("lan/devices/+/status", qos=1)
client.subscribe("lan/devices/+/history", qos=1)
client.subscribe("lan/devices/+/services", qos=1)
client.subscribe("lan/devices/+/service_history", qos=1)
client.subscribe(TOPIC_TOPOLOGY, qos=1)
```

**`run_cycle()` diff-and-tombstone pattern to copy** for closing incidents (mirrors the removed-hosts loop exactly):
```python
# scripts/mqtt_poller.py:1742-1766 (removed_ids loop, the template for "tombstone what disappeared")
previous_ids = set(state.previous_nodes)
removed_ids = previous_ids - current_ids
for device_id in removed_ids:
    publish_tombstone(client, device_id)
    ...
```
For incidents: compute `current_incident_ids = {incident["id"] for incident in incidents}`, tombstone `state.previous_incident_ids - current_incident_ids`, publish (or re-publish on change) every id in `current_incident_ids`, then `state.previous_incident_ids = current_incident_ids` at the end of the cycle — same shape as `state.previous_nodes = {...}` on line 1826.

---

### `tests/test_mqtt_poller.py` — new incident tests (test)

**Analog:** flat `def test_*` functions for `fetch_host_config`/`topology_nodes`/`run_cycle` (`tests/test_mqtt_poller.py:95-198, 438-519, 1620-1669`)

**Correction to RESEARCH.md's "Recommended Project Structure":** RESEARCH.md's Code Examples table names `TestComputeIncidents`, `TestUnmanagedInference`, `TestIncidentPublishDiff` as if this file uses `class Test...` groupings. **It does not** — the actual, sole convention in this 2442-line file is flat, descriptively-named `def test_<function>_<scenario>():` functions (verified: `grep -n "^class Test"` returns zero matches; the only `class` in the file is the unrelated `_OneShotEvent` test helper at line 1923). New tests should follow the same flat-function convention, named e.g. `test_compute_incidents_groups_down_host_and_unreachable_descendants`, `test_compute_incidents_unmanaged_switch_promoted_as_inferred_root_when_sibling_also_down`, `test_compute_incidents_lone_down_host_under_unmanaged_switch_is_its_own_incident`, `test_publish_incident_tombstone_clears_retained_status` — mirroring the existing naming style exactly (`test_fetch_host_config_invalid_map_position_degrades_to_none`, `test_run_cycle_removed_device_tombstones_status_and_history_and_events`).

---

### `dashboard-react/src/lib/incidents.ts` (utility, transform)

**Analog:** `dashboard-react/src/lib/grouping.ts` (rank table + roll-up) and `dashboard-react/src/lib/topologyLayout.ts` (label-derived value parse/format)

**Rank-table convention to copy exactly** (one source-of-truth table, imported everywhere a comparison is needed — RESEARCH.md Pitfall 4 names this file directly):
```typescript
// dashboard-react/src/lib/grouping.ts:14-26
// Mirrors compute_overall_state()'s worst-of ordering in scripts/mqtt_poller.py (host
// DOWN/UNREACHABLE always wins outright, then CRIT > UNKNOWN > WARN > OK). The two tables
// live in different languages and must be kept in step by hand -- there is no shared
// source of truth between Python and this file.
export const SEVERITY_RANK: Record<string, number> = {
  OK: 0,
  PEND: 0,
  WARN: 1,
  UNKNOWN: 2,
  CRIT: 3,
  UNREACH: 3,
  DOWN: 4,
};
```
`incidents.ts` should define `export const CRITICALITY_RANK: Record<string, number> = { low: 0, medium: 1, high: 2, critical: 3 }` the same way, with the same "must be kept in step by hand with `CRITICALITY_TIERS` in `scripts/mqtt_poller.py`" comment convention, and every criticality comparison (card sort, worst-affected calc) must import this table rather than re-deriving an order — exactly the discipline `treeModel.ts`'s own header comment states for `SEVERITY_RANK` (see below).

**Header-comment convention to copy** (this module's own "what it must not do" contract, stated up front):
```typescript
// dashboard-react/src/lib/treeModel.ts:1-9
// Group and device tree nodes derived from store state, shaping the results of
// grouping.ts's own primitives (buildGroupIndex/rollUpGroup/sortedGroupKeys) for rendering.
// This module does not re-derive severity ordering or group-key logic -- both already live
// in grouping.ts, and D-32/D-43 name reusing them verbatim as a binding constraint. ...
//
// No DOM access, no broker connection, no browser storage, no network calls -- pure
// functions only.
```

**Parse/format-a-label-derived-value pattern to copy** (from `topologyLayout.ts`, the closest analog for turning a `depends_on`/`service_criticality` string back into a structured value client-side):
```typescript
// dashboard-react/src/lib/topologyLayout.ts:25-37
const MAP_POSITION_RE = /^-?\d{1,6},-?\d{1,6}$/;

export function parseMapPosition(value: unknown): { x: number; y: number } | null {
  if (typeof value !== "string" || !MAP_POSITION_RE.test(value)) {
    return null;
  }
  const [xRaw, yRaw] = value.split(",");
  return { x: Number(xRaw), y: Number(yRaw) };
}

export function formatMapPosition(x: number, y: number): string {
  return `${Math.round(x)},${Math.round(y)}`;
}
```

---

### `dashboard-react/src/lib/topologyLayout.ts` — extend `MapNode` (utility, transform)

**Analog:** itself — `buildMapModel()`'s existing node-building loop

```typescript
// dashboard-react/src/lib/topologyLayout.ts:48-55, 103-115
export interface MapNode {
  id: string;
  label: string;
  deviceType: string | undefined;
  state: string;
  position: { x: number; y: number } | null;
  unmanaged: boolean;
}
...
const nodes: MapNode[] = validEntries.map((entry) => {
  const status = safeStatuses[entry.id];
  const state = isDeviceStale(status, nowMs) ? "STALE" : effectiveState(status);
  const label = status ? displayName(status) : displayName({ id: entry.id, alias: entry.alias });
  return {
    id: entry.id,
    label,
    deviceType: entry.device_type,
    state,
    position: parseMapPosition(entry.map_position),
    unmanaged: entry.unmanaged === true,
  };
});
```
Add `dimmed: boolean`, `incidentId: string | null`, `criticality: string` fields to `MapNode` and populate them the same way — a plain, additive field on the same map-literal, sourced from a new parameter (e.g. an `incidentConsequenceIds: Set<string>` / `incidentByHostId: Map<string,string>` argument to `buildMapModel()`), never from module/global state (this file's own D-11 forward-compat rule: "takes an already-filtered device list as a plain parameter and never reads the store").

---

### `dashboard-react/src/lib/treeModel.ts` — extend `TreeDeviceNode` (utility, transform)

**Analog:** itself — `buildTree()`'s existing device-mapping loop

```typescript
// dashboard-react/src/lib/treeModel.ts:16-24, 67-79
export interface TreeDeviceNode {
  kind: "device";
  id: string;
  label: string;
  state: string;
  stale: boolean;
  deviceType: string | null | undefined;
  tagGroupMissing: boolean;
}
...
const children: TreeDeviceNode[] = [...ids]
  .map((id) => {
    const device = devicesMap.get(id);
    return {
      kind: "device" as const,
      id,
      label: displayName(device),
      state: effectiveState(device),
      stale: isDeviceStale(device, nowMs),
      deviceType: device?.device_type,
      tagGroupMissing: isTagGroupMissing(device),
    };
  })
```
Same additive-field treatment: `dimmed: boolean`, `incidentId: string | null`. `buildTree()` gains a new optional parameter (an incident lookup), following the same "plain parameter, not store read" rule already stated in this file's own header comment.

---

### `dashboard-react/src/lib/checkmkWrite.ts` — `updateLabels`/`setCriticality`/`setServiceCriticality`/`updateDependsOn` (service, CRUD write)

**Analog:** itself — `setMapPosition()` and `updateHostAttributes()`

**The exact GET→merge→PUT pattern to generalize, not duplicate three times (per RESEARCH.md's Don't-Hand-Roll table):**
```typescript
// dashboard-react/src/lib/checkmkWrite.ts:178-191
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
// dashboard-react/src/lib/checkmkWrite.ts:135-155 (updateHostAttributes -- the underlying GET/ETag/PUT choke point)
async function updateHostAttributes(
  host: string,
  mutate: (attributes: Record<string, unknown>) => Record<string, unknown>,
): Promise<void> {
  const path = `/objects/host_config/${encodeURIComponent(host)}`;
  const getResp = await request("GET", path);
  const etag = getResp.headers.get("ETag");
  if (!etag) {
    throw new CheckmkWriteError("GET", `${API_PREFIX}${path}`, getResp.status, "missing ETag header");
  }
  const json = (await getResp.json()) as { extensions?: { attributes?: Record<string, unknown> } };
  const attributes: Record<string, unknown> = { ...(json.extensions?.attributes ?? {}) };
  delete attributes.meta_data;
  const mutated = mutate(attributes);

  await request("PUT", path, {
    body: { attributes: mutated },
    headers: { "If-Match": etag },
    expect: [200, 204],
  });
}
```
Extract the `currentLabels`/spread-merge lines above into a shared `updateLabels(host, mutate: (labels) => labels)` helper that itself calls `updateHostAttributes`, then `setCriticality`/`setServiceCriticality`/`updateDependsOn` become one-line wrappers over it — exactly the generalization RESEARCH.md's Don't-Hand-Roll table names. Every new write function must go through the same `serialize()` queue (`dashboard-react/src/lib/checkmkWrite.ts:112-121`) so it cannot race a concurrent map-position drag.

**Host-name / value validation convention to copy:**
```typescript
// dashboard-react/src/lib/checkmkWrite.ts:123-129
const HOST_NAME_RE = /^[-0-9a-zA-Z_.]+$/;

export function isValidHostName(name: string): boolean {
  return HOST_NAME_RE.test(name);
}
```
`updateDependsOn` should validate every target host id against this exact same `isValidHostName`/`HOST_NAME_RE` before writing the comma-joined label value, per RESEARCH.md's Label Design.

---

### `dashboard-react/src/components/IncidentList.tsx` (component, request-response)

**Analog:** `dashboard-react/src/components/StatsStrip.tsx` for "small summary strip reading store-derived props, placed in `centreTop`" — read that file directly for its exact prop-in/render-out shape (it was not re-read in full here since its role is fully described by `IndexRoute.tsx`'s usage at line 186: `<StatsStrip counts={counts} />`, a plain-props component with no internal store subscription).

**Placement pattern (copy from `IndexRoute.tsx`'s existing `centreTop` composition):**
```tsx
// dashboard-react/src/routes/IndexRoute.tsx:181-213 (centreTop, abbreviated)
centreTop={
  <div className="flex h-full flex-col gap-2 p-3">
    <StatsStrip counts={counts} />
    <div className="flex min-h-0 flex-1 flex-col gap-2" onPointerDown={touch} onWheel={touch} onKeyDown={touch}>
      <TopologyToolbar ... />
      <div className="min-h-0 flex-1"><TopologyMap ... /></div>
    </div>
  </div>
}
```
Per the UI-SPEC's Layout Integration section, add `<IncidentList />` as one more sibling above `<StatsStrip counts={counts} />` inside this same wrapper — additive JSX, no restructuring of the existing tree.

---

### `dashboard-react/src/components/IncidentCard.tsx` (component, request-response)

**Analog:** `kone-design-system`'s `Message` component (`design-system/src/components/Message.tsx:13-24`) — first consumer in this app, per the UI-SPEC's Design System table ("no dedicated `Card` component... `Message` is the closest primitive").

```typescript
// design-system/src/components/Message.tsx:13-35
export interface MessageProps {
  status?: MessageStatus; // "info" | "success" | "warning" | "danger"
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm?: () => void;
  onCancel?: () => void;
  shadow?: boolean;
}
```
`IncidentCard` wraps one `Message` per incident, mapping props per the UI-SPEC's "Incident Card List" table (`status`: `danger` if any confirmed-down consequence, else `warning`; `title`: root line + inferred badge; `description`: consequence summary + criticality badge; `icon`: the root's device-type mask icon via `deviceTypeMaskUrl` from `dashboard-react/src/lib/mapIcons.ts`, the same helper `TreeNode.tsx` already uses at line 10/96).

**Existing sibling-component style to match** (for how a `kone-design-system` primitive is imported/used in this repo, e.g. `Badge` usage):
```typescript
// dashboard-react/src/components/StateBadge.tsx:5 (import)
import { Badge } from "kone-design-system";
```

---

### `dashboard-react/src/components/CriticalityEditor.tsx` (component, CRUD)

**Analog:** `dashboard-react/src/components/TopologyToolbar.tsx` in full (already read):
```tsx
// dashboard-react/src/components/TopologyToolbar.tsx:1-55
import { Banner, Button, Switch } from "kone-design-system";

export function TopologyToolbar({ editMode, onEditModeChange, pendingCount, applying, onApply, editingConfigured }: TopologyToolbarProps) {
  return (
    <div className="flex items-center gap-2 rounded-md bg-bg-subtle p-3">
      <Switch label="Edit topology" checked={editMode} disabled={!editingConfigured} onChange={...} />
      {editMode && pendingCount > 0 && (
        <Banner status="warning" message={`${pendingCount} change${pendingCount === 1 ? "" : "s"} not yet applied`} />
      )}
      {editMode && (
        <Button variant="primary" disabled={pendingCount === 0 || applying} loading={applying} onClick={onApply}>
          {applying ? "Applying…" : "Apply changes"}
        </Button>
      )}
      {!editingConfigured && <span className="text-xs text-fg-tertiary">{CONFIGURATION_HINT}</span>}
    </div>
  );
}
```
Per the UI-SPEC ("this is **not** a separate edit mode... lives inside the existing 'Edit topology' `Switch`"), `CriticalityEditor` is a new panel rendered *inside* `TopologyToolbar`'s `editMode &&` branch (or a sibling mounted alongside it from `IndexRoute`), reusing the exact same `pendingCount`/`onApply`/`applying` props threaded down from `IndexRoute.tsx` — no new Switch, no second pending counter, no second Apply button (binding constraint, D-06/D-07).

**Destructive-confirm pattern to copy** (removing a depends-on link) — Phase 13's `window.confirm()` convention referenced by the UI-SPEC; locate and reuse the exact call site in `TopologyMap.tsx`'s edge-delete handler (not re-read here; grep `window.confirm` in that file before writing this component) rather than inventing a new confirmation modal.

---

### `dashboard-react/src/hooks/useKioskRotation.ts` (hook, event-driven)

**Analog:** `dashboard-react/src/hooks/useNowTick.ts` in full (already read):
```typescript
// dashboard-react/src/hooks/useNowTick.ts:16-31
import { useEffect, useState } from "react";

export const CLOCK_TICK_MS = 12000;

export function useNowTick(intervalMs: number = CLOCK_TICK_MS): number {
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => {
      setNowMs(Date.now());
    }, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);

  return nowMs;
}
```
Note this file's own docstring: "This is the app's only periodic timer -- IndexRoute must not add a second one." `useKioskRotation` is explicitly named by RESEARCH.md as "the **second** sanctioned timer, gated so it only ever mounts under `?kiosk=1`" — mount it only inside the kiosk branch (never unconditionally in `IndexRoute`), same `useState`+`useEffect`+`setInterval`+cleanup shape, returning which view (`"incidents" | "topology"`) is current plus elapsed-fraction for the progress bar.

---

### `dashboard-react/src/store/useAppStore.ts` — extend for `incidents` slice (store, pub-sub)

**Analog:** itself — the existing `topology` slice's exact handling (wholesale-replace, malformed-payload tolerance)

```typescript
// dashboard-react/src/store/useAppStore.ts:200-207
if (topic === "lan/devices/topology") {
  const parsed = parsePayload(payload);
  if (!parsed.ok || parsed.value === null || !isPlainObject(parsed.value)) {
    return;
  }
  set({ topology: parsed.value as TopologyPayload });
  return;
}
```
For `lan/incidents/{id}/status`, follow the per-device wildcard-topic pattern instead (id in `parts[2]`, wholesale-replace one entry, tombstone-on-null-payload deletes the entry) — copy the `lan/devices/+/status` handling block verbatim as the closer structural analog (it is a per-id wildcard topic, unlike singleton `topology`):
```typescript
// dashboard-react/src/store/useAppStore.ts:117-144 (per-id wildcard handling + tombstone)
if (parts[1] === "devices" && parts[3] === "status") {
  const id = parts[2];
  const parsed = parsePayload(payload);
  if (!parsed.ok) { return; }
  if (parsed.value === null) {
    const devices = { ...get().devices };
    ...
    delete devices[id];
    set({ devices, ... });
    return;
  }
  if (!isPlainObject(parsed.value)) { return; }
  set({ devices: { ...get().devices, [id]: parsed.value as DevicePayload } });
  return;
}
```
New `incidents: Record<string, IncidentPayload>` state field, added the same way `devices`/`history`/`services` are declared in `AppState` (lines 50-56) and initialized to `{}` in the store's initial state (lines 96-105) — never `set(..., true)` (the "never wipe the whole store" rule stated in this file's own header comment, lines 26-29).

---

### `dashboard-react/src/store/mqttClient.ts` — extend `SUBSCRIBE_TOPICS` (config, pub-sub)

**Analog:** itself
```typescript
// dashboard-react/src/store/mqttClient.ts:29-37
export const SUBSCRIBE_TOPICS = [
  "lan/devices/+/status",
  "lan/devices/+/history",
  "lan/devices/+/services",
  "lan/devices/+/service_history",
  "lan/devices/topology",
  "lan/events/recent",
  "lan/poller/status",
];
```
Append `"lan/incidents/+/status"` as one more array entry — no other change to this file; subscribing is what triggers retained-message replay on SUBACK per this file's own header comment (lines 91-93), so every currently-open incident arrives for free on connect.

---

### `dashboard-react/src/routes/IndexRoute.tsx` — mount `IncidentList`, add kiosk branch (route, request-response)

**Analog:** itself, in full (already read above) — the existing `centreTop` composition and the `editMode`/`pendingCount`/`snackbar` state-lifting pattern are the direct templates; see the "IncidentList" and "CriticalityEditor" sections above for the specific insertion points. The kiosk `?kiosk=1` branch is a **new top-level conditional**, not a pattern extension — closest structural analog in this file is the existing `!editingConfigured` conditional-render branch (`TopologyToolbar.tsx:52`, "hide/shrink chrome based on a boolean gate"), generalized to "swap the entire `ThreePaneLayout` for a full-bleed view based on `useSearchParams().get('kiosk')`."

---

## Shared Patterns

### Change-only, retained, tombstoned MQTT publish
**Source:** `scripts/mqtt_poller.py:1244-1330` (`publish_device_status`, `publish_topology`, `publish_tombstone`), `_publish_json()` at `scripts/mqtt_poller.py:1225-1241`
**Apply to:** `compute_incidents`/`publish_incident`/`publish_incident_tombstone`
```python
def _publish_json(client: mqtt.Client, topic: str, payload: object, qos: int, retain: bool) -> None:
    try:
        client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
    except (TimeoutError, OSError) as exc:
        _logger.warning("Failed to publish to %s: %s", topic, exc)
```

### Checkmk label GET→validate→degrade-to-default (never raise)
**Source:** `scripts/mqtt_poller.py:859-870` (`fetch_host_config`'s map_position/unmanaged parse)
**Apply to:** criticality/service_criticality/depends_on label parsing in the same function
```python
raw_map_position = labels.get(MAP_POSITION_LABEL)
map_position = (
    raw_map_position
    if isinstance(raw_map_position, str) and _MAP_POSITION_RE.match(raw_map_position)
    else None
)
```

### Checkmk label GET→merge→PUT-with-ETag (browser write side)
**Source:** `dashboard-react/src/lib/checkmkWrite.ts:135-191` (`updateHostAttributes`, `setMapPosition`)
**Apply to:** `updateLabels`/`setCriticality`/`setServiceCriticality`/`updateDependsOn`
```typescript
async function updateHostAttributes(host, mutate) {
  const path = `/objects/host_config/${encodeURIComponent(host)}`;
  const getResp = await request("GET", path);
  const etag = getResp.headers.get("ETag");
  ...
  await request("PUT", path, { body: { attributes: mutated }, headers: { "If-Match": etag }, expect: [200, 204] });
}
```

### One source-of-truth rank table, imported everywhere a comparison happens
**Source:** `dashboard-react/src/lib/grouping.ts:18-26` (`SEVERITY_RANK`), enforced by `dashboard-react/src/lib/treeModel.ts`'s own header comment
**Apply to:** a new `CRITICALITY_RANK` in `incidents.ts`, imported by card sort logic, worst-affected calc, and any future criticality badge color lookup — never re-derived ad hoc.

### Wholesale-replace Zustand slice, malformed-payload tolerance, never blank the page
**Source:** `dashboard-react/src/store/useAppStore.ts:1-30` (header comment) and `:111-237` (`handleMessage`)
**Apply to:** the new `incidents` slice
```typescript
// A payload that fails to parse, or parses to the wrong shape, is dropped and the
// last-known-good value is kept -- it must never throw out of the message handler.
```

### The app's one (now two, kiosk-gated) periodic timer
**Source:** `dashboard-react/src/hooks/useNowTick.ts` (full file, quoted above)
**Apply to:** `useKioskRotation.ts` — same `useState`+`useEffect(setInterval, cleanup)` shape, mounted only under `?kiosk=1`.

### Single Apply/pending-count flow, never a second toggle
**Source:** `dashboard-react/src/routes/IndexRoute.tsx:94-155` (`editMode`/`pendingCount`/`onEditSaved`/`onApply`), `dashboard-react/src/components/TopologyToolbar.tsx` (the Switch/Banner/Button UI)
**Apply to:** `CriticalityEditor` — every field write calls the same `onEditSaved`-equivalent increment, feeds the same `pendingCount`, is cleared by the same `activateChanges()`/`onApply`.

---

## No Analog Found

None. Every file in this phase's scope has at least a role-match analog in the same repo (see table above) — consistent with RESEARCH.md's own framing that Phase 14 introduces zero new infrastructure shapes, only extensions of five already-established patterns (retained-topic publish/tombstone, label GET/PUT, wholesale-replace store slice, one-rank-table sort, one-periodic-timer hook).

---

## Conventions

Derived via the shared deterministic module (`bin/gsd-tools.cjs verify conventions --derive`), scoped to `dashboard-react/src` (the directory this phase's frontend files land in; the Python backend side of this phase has no separate derivation — `scripts/mqtt_poller.py`'s own conventions are documented file-by-file above and in `CLAUDE.md`'s Conventions section, which already covers `snake_case`, dataclasses, and module-private `_`-prefixed helpers with high confidence from direct source reading).

| Axis | Dominant | Share | Entropy | Status |
|---|---|---|---|---|
| File-name casing | *(none — split)* | 61.5% camel / 38.5% Pascal | 0.961 | **contested hotspot** |
| Identifier casing | camel | 79.5% | 0.496 | named contract |
| Export style | esm | 100% | 0 | named contract |
| Import style | esm | 100% | 0 | named contract |

**Contested hotspots (author's choice):** file-name casing in `dashboard-react/src` sits below the 70% dominance threshold (24 camelCase files — `checkmkWrite.ts`, `topologyLayout.ts`, `useNowTick.ts` — vs. 15 PascalCase files — `IndexRoute.tsx`, `TreeNode.tsx`, `IncidentList.tsx`-to-be) and is genuinely a **directory-local, self-consistent split already present in this exact codebase**, not a defect: `lib/`/`hooks/`/`store/` modules are camelCase, `components/`/`routes/` React component files are PascalCase — mirroring this project's own prototype intentional-contested split (the CJS<->SDK dual resolver in `bin/lib/**` vs. `sdk/src/**`, each half internally consistent per-directory, contested only when measured repo-wide). New Phase 14 files should match their directory's local convention rather than the repo-wide split: `incidents.ts`/`useKioskRotation.ts` (camelCase, in `lib/`/`hooks/`) and `IncidentList.tsx`/`IncidentCard.tsx`/`CriticalityEditor.tsx` (PascalCase, in `components/`) — which is exactly what this PATTERNS.md's File Classification table above already assigns. Identifier casing, export style, and import style are all named contracts (camelCase identifiers, ESM `export`/`import` throughout) with no contested exceptions to flag.

---

## Metadata

**Analog search scope:** `scripts/mqtt_poller.py`, `tests/test_mqtt_poller.py`, `dashboard-react/src/lib/{checkmkWrite,topologyLayout,treeModel,grouping}.ts`, `dashboard-react/src/store/{useAppStore,mqttClient}.ts`, `dashboard-react/src/components/{TopologyToolbar,TreeNode,StatsStrip}.tsx`, `dashboard-react/src/hooks/{useNowTick,useEditIdleTimeout}.ts`, `dashboard-react/src/routes/IndexRoute.tsx`, `design-system/src/components/Message.tsx`, `dashboard-react/node_modules/kone-design-system/dist/index.d.ts`
**Files scanned:** 17 read directly (full or targeted-range) + 1 grep-only structural check (`tests/test_mqtt_poller.py` class-vs-function convention)
**Pattern extraction date:** 2026-09-26
