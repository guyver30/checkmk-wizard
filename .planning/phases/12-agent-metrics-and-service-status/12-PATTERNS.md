# Phase 12: Agent Metrics and Service Status - Pattern Map

**Mapped:** 2026-09-21
**Files analyzed:** 11 (2 Python, 9 TypeScript/TSX)
**Analogs found:** 11 / 11 (all files have at least a role-match; most are exact self-extension)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `scripts/mqtt_poller.py` (extended: `query_services`, `parse_perf_data`, `publish_services`, `publish_service_history`, `available_service_columns`, `select_service_columns`, `build_services_query`, `services_signature`, `publish_device_status` gauge fields, `run_cycle`/`run_forever` wiring) | service (poller) | batch/poll → CRUD-ish publish + event-driven change-detection | itself — the existing `GET hosts` pipeline (`available_host_columns`/`select_host_columns`/`build_hosts_query`/`query_devices`/`publish_topology`/`publish_history`) | exact (self-extension, same module, same shape) |
| `tests/test_mqtt_poller.py` (extended with services/perfdata/signature/publish tests) | test | — | itself — existing `test_query_devices_*` / `test_topology_signature_*` / `test_publish_topology_*` blocks | exact |
| `dashboard-react/src/routes/DetailsRoute.tsx` (filled in: gauge row, SMART badge, service `Table`, history strip) | route/page component | request-response (render from store snapshot) | `dashboard-react/src/components/EventHistory.tsx` (store-read + list-render shape) + `dashboard-react/src/components/TreeNode.tsx` (`StateBadgeForState` usage, per-row severity) | role-match (composed from two analogs, no single existing "filled-in route" to copy wholesale) |
| `dashboard-react/src/store/mqttClient.ts` (`SUBSCRIBE_TOPICS` += 2 wildcard topics) | provider/config (MQTT choke point) | pub-sub | itself | exact |
| `dashboard-react/src/store/useAppStore.ts` (`handleMessage()` += 2 branches, 2 new state slices) | store | event-driven (message → state replace) | itself — existing `status`/`history` branches | exact |
| `dashboard-react/src/lib/types.ts` (`DevicePayload` gains gauge fields; new `ServiceEntry`/`ServiceHistoryEntry` types) | model/types | transform | itself | exact |
| `dashboard-react/src/components/TreeNode.tsx` (add `onClick`/`Link` navigation, D-15) | component | request-response (client routing) | itself (existing `onToggle` button pattern) | exact |
| `dashboard-react/src/lib/serviceSort.ts` (new — `SEVERITY_ORDER`, `compareServices`) | utility/transform | transform | `dashboard-react/src/lib/staleness.ts` / `dashboard-react/src/lib/display.ts` (small pure-function module shape) | role-match (no existing sort-by-severity precedent, per RESEARCH.md) |
| `dashboard-react/src/routes/DetailsRoute.test.tsx` (new) | test | — | `dashboard-react/src/App.test.tsx` / `dashboard-react/src/routes/IndexRoute.test.tsx` | role-match |
| `dashboard-react/src/store/useAppStore.test.ts` (extended) | test | — | itself — existing status/history branch tests | exact |
| `dashboard-react/src/store/mqttClient.test.ts` (extended) | test | — | itself | exact |

Documentation-only, mechanical edits (no code pattern needed): `.planning/REQUIREMENTS.md` (mint new REQ IDs per RESEARCH.md's recommendation), `.planning/PROJECT.md` (amend the "duplicating Checkmk's per-service drill-down UI" Out of Scope entry per D-15/16/17).

---

## Pattern Assignments

### `scripts/mqtt_poller.py` — services query pipeline (service, batch/event-driven)

**Analog:** the existing hosts pipeline in the same file.

**Column-availability probe pattern** (copy shape from `available_host_columns()` / `select_host_columns()` / `build_hosts_query()`, lines 527-573):
```python
# Source: scripts/mqtt_poller.py:527-543
def available_host_columns(host: str, port: int, timeout: float) -> set[str]:
    query = "GET columns\nColumns: name\nFilter: table = hosts\nOutputFormat: json\n\n"
    body = _livestatus_request(host, port, query, timeout)
    if not body.strip():
        return set()
    try:
        rows = json.loads(body)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LivestatusError(f"Malformed columns response from {host}:{port}: {exc}") from exc
    return {row[0] for row in rows}

# Source: scripts/mqtt_poller.py:546-569
def select_host_columns(available: set[str]) -> list[str]:
    missing = [name for name in REQUIRED_HOST_COLUMNS if name not in available]
    if missing:
        raise LivestatusError(
            f"Livestatus hosts table is missing required column(s): {', '.join(missing)}"
        )
    columns = list(REQUIRED_HOST_COLUMNS)
    for name in OPTIONAL_HOST_COLUMNS:
        if name in available:
            columns.append(name)
        else:
            _logger.warning(
                "Livestatus hosts table does not expose optional column %r; "
                "degrading to a safe default for that field",
                name,
            )
    return columns

# Source: scripts/mqtt_poller.py:572-573
def build_hosts_query(columns: list[str]) -> str:
    return f"GET hosts\nColumns: {' '.join(columns)}\nOutputFormat: json\n\n"
```
Build `available_service_columns()` / `select_service_columns()` / `build_services_query()` as a literal parallel triad, filtered to `table = services`. Per Pitfall 4 (RESEARCH.md): `REQUIRED_SERVICE_COLUMNS = ("host_name", "description", "state")`, `OPTIONAL_SERVICE_COLUMNS = ("plugin_output", "perf_data")` — never put `perf_data` in required, or one missing optional column takes down gauges + SMART + the whole per-service list together.

**Row-parsing pattern** (copy shape from `query_devices()`, lines 576-685 — defensive per-column `try/except`, skip-not-raise on one bad row):
```python
# Source: scripts/mqtt_poller.py:606-627 (excerpt from query_devices)
index = {name: position for position, name in enumerate(columns)}
snapshots: list[DeviceSnapshot] = []
for row in rows:
    try:
        name = row[index["name"]]
    except (IndexError, TypeError):
        _logger.warning("Skipping malformed hosts row: %r", row)
        continue
    if not is_publishable_device_id(name):
        _logger.warning("Skipping host %r: not publishable as an MQTT topic segment", name)
        continue
    try:
        host_state = int(row[index["state"]])
    except (IndexError, TypeError, ValueError):
        _logger.warning("Skipping host %r: non-numeric state", name)
        continue
```
`query_services()` mirrors this exact per-field `try/except`, skip-the-row-not-the-cycle posture — one malformed service row must not drop the whole `GET services` response (T-09-03 posture, same as hosts).

**Nagios perfdata parser** — no direct prior art in this repo (RESEARCH.md's "Key insight": this is the one genuinely new piece). Follow the shape RESEARCH.md already drafted, matching this module's existing "skip a malformed token, never raise" posture used throughout `query_devices()`:
```python
# New function for mqtt_poller.py — from 12-RESEARCH.md Pattern 2 (Architecture Patterns)
def parse_perf_data(raw: str) -> dict[str, dict]:
    """Parse a Nagios-format perf_data string into {label: {value, warn, crit, min, max}}."""
    result: dict[str, dict] = {}
    for token in raw.split():
        if "=" not in token:
            continue
        label, _, rest = token.partition("=")
        label = label.strip("'")
        parts = rest.split(";")
        try:
            value = float(_strip_uom(parts[0]))
        except (ValueError, IndexError):
            continue
        def _num(i: int) -> float | None:
            try:
                return float(parts[i]) if i < len(parts) and parts[i] else None
            except ValueError:
                return None
        result[label] = {"value": value, "warn": _num(1), "crit": _num(2), "min": _num(3), "max": _num(4)}
    return result
```
Place it near `extract_device_type()` (line 414) — same "one small pure parsing helper, no class" style.

**Change-only signature pattern** (copy from `topology_signature()`, lines 398-411 — D-13's basis):
```python
# Source: scripts/mqtt_poller.py:398-411
def topology_signature(nodes: list[dict]) -> tuple:
    """Order-independent signature used to decide whether topology actually changed."""
    return tuple(
        sorted(
            (
                node["id"],
                tuple(sorted(node["parents"])),
                node["device_type"],
                node["folder"],
                node["alias"],
            )
            for node in nodes
        )
    )
```
`services_signature()` follows this exact shape — sorted tuple of ONLY `(host_name, description, state)`. Per Pitfall 2: never include `plugin_output` in the signature tuple, or the "publish only on state/set change" cadence (D-13) is defeated.

**Bounded history append** — reuse `append_bounded()` verbatim, no new helper:
```python
# Source: scripts/mqtt_poller.py:380-382
def append_bounded(entries: list[dict], entry: dict, max_entries: int) -> list[dict]:
    """Return a new bounded list with `entry` appended, never mutating `entries`."""
    return (entries + [entry])[-max_entries:]
```

**Publish pattern** (copy shape from `publish_topology()` / `publish_history()`, lines 762-770 — all funnel through `_publish_json()`):
```python
# Source: scripts/mqtt_poller.py:762-770
def publish_topology(client: mqtt.Client, nodes: list[dict], timestamp: str) -> None:
    """Publish the full device topology. QoS 1: only republished when it actually changes."""
    payload = {"devices": nodes, "timestamp": timestamp}
    _publish_json(client, TOPIC_TOPOLOGY, payload, qos=1, retain=True)


def publish_history(client: mqtt.Client, device_id: str, entries: list[dict]) -> None:
    """Publish one device's full bounded transition history (already truncated by the caller)."""
    _publish_json(client, device_history_topic(device_id), entries, qos=1, retain=True)
```
`publish_services()` / `publish_service_history()` follow this exact shape — QoS 1, retain=True, change-triggered (D-11/D-14). Add `device_services_topic()` / `device_service_history_topic()` helper functions mirroring `device_status_topic()`/`device_history_topic()` (lines 333-338):
```python
# Source: scripts/mqtt_poller.py:333-338
def device_status_topic(device_id: str) -> str:
    return f"lan/devices/{device_id}/status"


def device_history_topic(device_id: str) -> str:
    return f"lan/devices/{device_id}/history"
```

**`_publish_json()` choke point** — every new publish call must go through this, never `client.publish()` directly:
```python
# Source: scripts/mqtt_poller.py:724-740
def _publish_json(client: mqtt.Client, topic: str, payload: object, qos: int, retain: bool) -> None:
    try:
        client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
    except (TimeoutError, OSError) as exc:
        _logger.warning("Failed to publish to %s: %s", topic, exc)
```

**Extending `publish_device_status()`** (D-12's gauge fields, additive keys only — an older subscriber is unaffected):
```python
# Source: scripts/mqtt_poller.py:743-759
def publish_device_status(client: mqtt.Client, snapshot: DeviceSnapshot, timestamp: str) -> None:
    payload = {
        "id": snapshot.id,
        "state": snapshot.state,
        "in_downtime": snapshot.in_downtime,
        "acknowledged": snapshot.acknowledged,
        "device_type": snapshot.device_type,
        "folder": snapshot.folder,
        "alias": snapshot.alias,
        "staleness": snapshot.staleness,
        "host_state_raw": snapshot.host_state_raw,
        "timestamp": timestamp,
    }
    _publish_json(client, device_status_topic(snapshot.id), payload, qos=0, retain=True)
```
Add `cpu_percent`/`ram_percent`/`disk_percent`/`disk_other_mounts_worst`/`smart_*` as new additive dict keys, same posture as D-17's `staleness`/`host_state_raw` addition (dated comment already documents "additive keys" as the established migration convention here).

**Wiring into `run_cycle()`/`run_forever()`** — extend, don't restructure:
```python
# Source: scripts/mqtt_poller.py:1151-1179 (existing hosts-column startup probe to mirror)
columns: list[str] | None = None
last_exc: LivestatusError | None = None
max_attempts = len(_STARTUP_RETRY_DELAYS_SECONDS) + 1
for attempt in range(1, max_attempts + 1):
    try:
        available = available_host_columns(
            config.livestatus_host, config.livestatus_port, DEFAULT_LIVESTATUS_TIMEOUT_SECONDS
        )
        columns = select_host_columns(available)
        break
    except LivestatusError as exc:
        last_exc = exc
        if attempt < max_attempts:
            delay = _STARTUP_RETRY_DELAYS_SECONDS[attempt - 1]
            time.sleep(delay)
```
Add a second, parallel probe loop for services columns (same bounded-retry-then-log-and-degrade posture; per RESEARCH.md, a services-probe failure should NOT be as fatal as the hosts probe — hosts is the poller's sole mandatory data source, services only adds gauges/SMART/list). `run_cycle()` (lines 1018-1104) gets the new `query_services()` call, `services_signature()` diff against `state.previous_services_signature` (a new `PollerState` field), and calls to `publish_services()`/`publish_service_history()` alongside the existing topology/history/events diff logic already there — same "diff this cycle vs. state, publish only on change" shape already used for topology (lines 1094-1095).

**Error/data types** — new query/publish work raises the SAME `LivestatusError`/uses the SAME `_publish_json()` — do not introduce a second exception type for services.

---

### `tests/test_mqtt_poller.py` — new tests (test)

**Analog:** existing test blocks in the same file.

```python
# Source: tests/test_mqtt_poller.py:315-343 (pattern to mirror for available/select/build)
def test_select_host_columns_orders_required_then_available_optional():
    result = poller.select_host_columns({"name", "state", "parents"})
    assert result == ["name", "state", "parents"]


def test_available_host_columns_sends_expected_lql_query():
    sock = _fake_connection(b'[["name"], ["state"]]')
    with patch("socket.create_connection", return_value=sock):
        result = poller.available_host_columns("checkmk", poller.DEFAULT_LIVESTATUS_PORT, 10)
    sent = sock.sendall.call_args[0][0].decode()
    assert sent == "GET columns\nColumns: name\nFilter: table = hosts\nOutputFormat: json\n\n"
    assert result == {"name", "state"}
```
```python
# Source: tests/test_mqtt_poller.py:349-384 (pattern to mirror for query_services row-parsing)
def test_query_devices_parses_full_row_into_device_snapshot():
    columns = ["name", "state", "scheduled_downtime_depth", "acknowledged",
               "worst_service_state", "parents", "tags", "alias"]
    row = ["web1", 0, 1, True, 2, ["switch-01"], {"device_type": "server"}, "Web Server 1"]
    sock = _fake_connection(json.dumps([row]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices(
            "checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10, folders={"web1": "vlan10"}
        )
    assert snapshots[0].id == "web1"
```
Also add a unit test asserting a `plugin_output`-only diff does NOT trigger a `services_signature()` change (RESEARCH.md Pitfall 2's explicit recommendation), mirroring `test_topology_signature_differs_on_*` (lines 104-123) but asserting *sameness*.

---

### `dashboard-react/src/routes/DetailsRoute.tsx` (route/page component, request-response)

**Analog 1 — store-reading + defensive-empty-state shape:** `dashboard-react/src/components/EventHistory.tsx`
```tsx
// Source: dashboard-react/src/components/EventHistory.tsx:9-19
export function EventHistory() {
  const events = useAppStore((s) => s.events);
  const devices = useAppStore((s) => s.devices);

  if (events.length === 0) {
    return (
      <div role="log" aria-label="Recent events" aria-live="polite" className="p-3 text-sm text-fg-tertiary">
        {NO_EVENTS_TEXT}
      </div>
    );
  }
  ...
```
`DetailsRoute` reads `useAppStore((s) => s.devices[id])`, `s.services?.[id]`, `s.history[id]` the same selector-per-slice way, and needs the same three-state shape UI-SPEC.md's Copywriting Contract locks: no id selected / id not found in store / found-but-services-not-yet-arrived — each an early return, exactly like `EventHistory`'s empty-state early return above.

**Analog 2 — per-row `StateBadgeForState` usage and severity-driven styling:** `dashboard-react/src/components/TreeNode.tsx`
```tsx
// Source: dashboard-react/src/components/TreeNode.tsx:31-33, 96-97
export function TreeNode({ node, depth, isOpen, onToggle }: TreeNodeProps) {
  const spec = badgeForState(node.worst);
  const accentClass = ACCENT_BORDER_CLASS[spec.color] ?? "border-neutral-300";
  ...
  <StateBadgeForState state={displayState} />
```
The service `Table`'s status cell renders `<StateBadgeForState state={row.state} />` (per 12-UI-SPEC.md's explicit correction: NOT the design-system's own `StatusBadge`), imported the same way `TreeNode.tsx` already does (`import { StateBadgeForState } from "./StateBadge";`).

**Gauge overlay pattern** (locked verbatim by 12-UI-SPEC.md, `ProgressCircle` from `kone-design-system`):
```tsx
// Source: 12-UI-SPEC.md "Typography" — Gauge value override; ProgressCircle itself at
// design-system/src/components/Progress.tsx:55-90
<span className="relative inline-flex">
  <ProgressCircle value={cpuPercent} color={gaugeColor} size={96} strokeWidth={8} showValue={false} />
  <span className="absolute inset-0 flex items-center justify-center text-2xl font-semibold text-fg-primary">
    {cpuPercent}%
  </span>
</span>
```
`color` is one of `ProgressColor = "brand" | "success" | "warning" | "danger"` (`design-system/src/components/Progress.tsx:1`) — computed by comparing the gauge's own `perf_data` value against its own warn/crit (D-04), never Checkmk's service `state`.

**Service `Table` pattern:**
```tsx
// Source: design-system/src/components/Table.tsx:12-19
export interface TableProps<T> {
  columns: TableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  sortKey?: string;
  sortDirection?: SortDirection;
  onSort?: (key: string) => void;
}
```
Per 12-UI-SPEC.md's Layout section: no `onSort`/`sortKey` — pass only `columns`/`rows`/`rowKey`; ordering is fixed worst-first via `compareServices()` (see `serviceSort.ts` below), not user-resortable.

**History strip (D-16):** reuse `EventHistory.tsx`'s per-entry rendering (`EventRow.tsx`'s time/label/badge row shape), scoped to one device's `history[id]` array instead of the global `events` feed:
```tsx
// Source: dashboard-react/src/components/EventRow.tsx:31-47 (per-entry rendering to reuse)
<div className="flex items-center gap-2 py-1.5 text-sm">
  <span className="shrink-0 font-mono text-xs text-fg-tertiary">{formatClock(entry?.timestamp)}</span>
  ...
  <StateBadgeForState state={fromState} />
  <span aria-hidden>→</span>
  <StateBadgeForState state={toState} />
</div>
```

**Route registration:** no change needed to `App.tsx` (`/details` already routed, line 47 of `dashboard-react/src/App.tsx`); `DetailsRoute` keeps its existing `useSearchParams()`-based `?id=` read (current stub, lines 1-15 of the file being filled in).

---

### `dashboard-react/src/store/mqttClient.ts` (provider/config, pub-sub)

**Analog:** itself — extend the existing array literal, no other change needed.
```typescript
// Source: dashboard-react/src/store/mqttClient.ts:29-35
export const SUBSCRIBE_TOPICS = [
  "lan/devices/+/status",
  "lan/devices/+/history",
  "lan/devices/topology",
  "lan/events/recent",
  "lan/poller/status",
];
```
Add `"lan/devices/+/services"` and `"lan/devices/+/service_history"` to this array. No other change to `mqttClient.ts` — subscription is the only integration point (`connect()`'s `client.subscribe(SUBSCRIBE_TOPICS)` at line 92 needs no edit since it iterates the array).

---

### `dashboard-react/src/store/useAppStore.ts` (store, event-driven)

**Analog:** itself — the existing `status`/`history` topic branches inside `handleMessage()`.
```typescript
// Source: dashboard-react/src/store/useAppStore.ts:111-133 (status branch — mirror for services)
if (parts[1] === "devices" && parts[3] === "status") {
  const id = parts[2];
  const parsed = parsePayload(payload);
  if (!parsed.ok) {
    return; // malformed -- ignore, keep last-known-good
  }
  if (parsed.value === null) {
    const devices = { ...get().devices };
    const history = { ...get().history };
    delete devices[id];
    delete history[id];
    set({ devices, history });
    return;
  }
  if (!isPlainObject(parsed.value)) {
    return; // wrong shape -- malformed, drop
  }
  set({ devices: { ...get().devices, [id]: parsed.value as DevicePayload } });
  return;
}
```
```typescript
// Source: dashboard-react/src/store/useAppStore.ts:135-150 (history branch — mirror for service_history)
if (parts[1] === "devices" && parts[3] === "history") {
  const id = parts[2];
  const parsed = parsePayload(payload);
  if (!parsed.ok) {
    return;
  }
  if (parsed.value === null) {
    set({ history: { ...get().history, [id]: [] } });
    return;
  }
  if (!Array.isArray(parsed.value)) {
    return;
  }
  set({ history: { ...get().history, [id]: parsed.value as HistoryEntry[] } });
  return;
}
```
Add two new branches for `parts[3] === "services"` (array payload → new `services: Record<string, ServiceEntry[]>` slice, tombstone clears the id's entry) and `parts[3] === "service_history"` (array payload → new `serviceHistory: Record<string, ServiceHistoryEntry[]>` slice) — same `parsePayload()`/`isPlainObject()`/`Array.isArray()` guards, same last-known-good-on-malformed contract, same tombstone-on-zero-length-payload handling. Add the two new state fields to the `AppState` interface (lines 47-66) next to `history`.

---

### `dashboard-react/src/lib/types.ts` (model/types, transform)

**Analog:** itself.
```typescript
// Source: dashboard-react/src/lib/types.ts:15-27
export interface DevicePayload {
  id?: string;
  alias?: string;
  state?: string;
  host_state_raw?: string;
  device_type?: string;
  folder?: string;
  timestamp?: string;
  staleness?: number | null;
  downtime?: boolean;
  acknowledged?: boolean;
  services?: unknown;
}
```
Note `services?: unknown` already exists as a placeholder field — replace/extend with the real gauge fields (`cpu_percent`, `ram_percent`, `disk_percent`, `disk_other_mounts_worst`, `smart_pass_count`, `smart_total_count`, etc., all optional per this file's "every field optional, loosely typed" convention stated in its header comment lines 1-6). Add new `ServiceEntry` (`{ host_name?: string; description?: string; state?: string; plugin_output?: string }`) and `ServiceHistoryEntry` (`{ timestamp?: string; description?: string; from?: string | null; to?: string | null }`) interfaces alongside `HistoryEntry`/`EventEntry` (lines 29-46), following their exact "every field optional + index signature" shape.

---

### `dashboard-react/src/components/TreeNode.tsx` (component, request-response — D-15 navigation)

**Analog:** itself — the existing group-row `<button onClick>` pattern, applied to the device row.
```tsx
// Source: dashboard-react/src/components/TreeNode.tsx:37-46 (group row — button+onClick pattern to mirror)
<button
  type="button"
  onClick={() => onToggle(node.key)}
  aria-expanded={isOpen}
  style={{ paddingLeft: depth * INDENT_PX + ROW_START_PX }}
  className={[
    "flex w-full items-center gap-2 border-l-4 py-2 pr-3 text-left hover:bg-bg-subtle-hover",
    accentClass,
  ].join(" ")}
>
```
The device row currently rendered at lines 76-100 is a plain `<div role="treeitem">` with no interaction — wrap it (or its label) in a `react-router` `Link` to `/details?id={device.id}` (same `react-router` import already used app-wide, e.g. `App.tsx:2`), reusing this row's existing hover/style classes per 12-UI-SPEC.md ("no new visual contract needed").

---

### `dashboard-react/src/lib/serviceSort.ts` (new — utility/transform)

**No direct precedent** (RESEARCH.md's Code Examples section states this explicitly). Closest shape analog for a small, pure, single-purpose lib module:
```typescript
// Source: dashboard-react/src/lib/staleness.ts header-comment shape (small pure-function
// module, no class, one exported function + one exported constant) — mirror this file's
// organization, not its content.
```
Content is fully specified by RESEARCH.md's Code Examples section:
```typescript
const SEVERITY_ORDER: Record<string, number> = { CRIT: 0, WARN: 1, UNKNOWN: 2, OK: 3 };
export function compareServices(a: ServiceEntry, b: ServiceEntry): number {
  const diff = (SEVERITY_ORDER[a.state ?? ""] ?? 2) - (SEVERITY_ORDER[b.state ?? ""] ?? 2);
  return diff !== 0 ? diff : (a.description ?? "").localeCompare(b.description ?? "");
}
```

---

## Shared Patterns

### Livestatus transport choke point
**Source:** `scripts/mqtt_poller.py:439-461` (`_livestatus_request`)
**Apply to:** `query_services()`, `available_service_columns()` — every new Livestatus call must go through this one function, never open a new socket.

### MQTT publish choke point
**Source:** `scripts/mqtt_poller.py:724-740` (`_publish_json`)
**Apply to:** `publish_services()`, `publish_service_history()`, the extended `publish_device_status()` — every new publish call, no exceptions.

### Change-only republish via sorted-tuple signature
**Source:** `scripts/mqtt_poller.py:398-411` (`topology_signature`)
**Apply to:** `services_signature()` (D-13) — same "sorted tuple of only the fields that matter" technique; deliberately excludes `plugin_output` (Pitfall 2).

### Bounded list truncation
**Source:** `scripts/mqtt_poller.py:380-382` (`append_bounded`)
**Apply to:** the new per-service transition history (D-14) — call with the same `(entries, entry, max_entries)` signature, no new helper.

### Checkmk state → badge color/variant/icon
**Source:** `dashboard-react/src/lib/stateMapping.ts:30-43` (`badgeForState`) via `dashboard-react/src/components/StateBadge.tsx:36-43` (`StateBadgeForState`)
**Apply to:** every service-row status cell in the new `Table`, and the device-title badge in `DetailsRoute` — never a second color-mapping table (12-UI-SPEC.md's explicit "Design System" correction).

### Defensive MQTT payload parsing, last-known-good on malformed
**Source:** `dashboard-react/src/store/useAppStore.ts:68-90` (`isPlainObject`, `parsePayload`)
**Apply to:** the two new `handleMessage()` branches for `services`/`service_history` — must never throw, must keep last-known-good on a malformed payload, exactly like the existing four branches.

### Design-system gauge/table/badge primitives (no new components)
**Source:** `design-system/src/components/Progress.tsx` (`ProgressCircle`), `design-system/src/components/Table.tsx` (`Table`), `design-system/src/components/StateBadge.tsx`'s wrapping of `Badge`
**Apply to:** `DetailsRoute.tsx` exclusively — 12-UI-SPEC.md locks "no new design-system components this phase."

---

## No Analog Found

| File / Function | Role | Data Flow | Reason |
|---|---|---|---|
| `parse_perf_data()` (new, `scripts/mqtt_poller.py`) | utility/transform | transform | No Nagios-perfdata parser exists anywhere in this repo today; RESEARCH.md explicitly calls this "the one place that genuinely IS new work." Its *style* (defensive, skip-not-raise per token) still follows `query_devices()`'s established posture — use RESEARCH.md's Pattern 2 code example as the base, not a from-scratch design. |
| `dashboard-react/src/lib/serviceSort.ts` (new) | utility/transform | transform | No existing sort-by-severity precedent in `dashboard-react/src/lib/`; RESEARCH.md's own Code Examples section notes "no existing precedent in this repo to cite." Use the `SEVERITY_ORDER`/`compareServices` shape given directly in RESEARCH.md. |

---

## Conventions

Derived via the shared deterministic module (`gsd-tools.cjs verify conventions --derive`), scoped to `dashboard-react/src` (the TypeScript/TSX tree this phase's frontend files live in; the tool has no Python-file support, so `scripts/mqtt_poller.py` continues to follow the `snake_case`/module-docstring conventions already documented in this project's root `CLAUDE.md` — that axis was not machine-derived here).

| Axis | Dominant | Share | Entropy | Status |
|---|---|---|---|---|
| File-name casing | (none — split) | 43.6% (`other`, i.e. dotted/multi-segment names like `App.test.tsx`) | 0.979 | contested hotspot |
| Identifier casing | `camel` | 75.3% | 0.552 | named contract |
| Export style | `esm` | 100% | 0.0 | named contract |
| Import style | `esm` | 100% | 0.0 | named contract |

**Contested hotspots (author's choice).** File-name casing in `dashboard-react/src` is genuinely split (`camel` for lib/hook files like `stateMapping.ts`, `Pascal` for components/routes like `TreeNode.tsx`/`DetailsRoute.tsx`, `other` for the `*.test.tsx`/`*.test.ts` dotted-suffix convention) — below the 70% dominance bar, so no single casing rule can be imposed; match whichever sibling files in the same directory already use (a new route file follows `Pascal` per `DetailsRoute.tsx`/`TreeNode.tsx`; a new lib utility follows `camel` per `stateMapping.ts`/`staleness.ts`). This project's own prototype of an intentional, contested-but-locally-consistent split is the CJS↔SDK dual resolver elsewhere in this monorepo family: `bin/lib/**` is CJS (`module.exports`/`require`) and `sdk/src/**` is ESM (`export`/`import`) — each half is internally consistent per-directory, contested only when compared repo-wide. The same rule applies here: `dashboard-react/src`'s `esm` export/import style (100% dominant, a true named contract, unlike file-naming) must not be mixed with the poller's Python/CJS-adjacent module style — match the target directory's local convention, not a repo-wide average.

---

## Metadata

**Analog search scope:** `scripts/mqtt_poller.py`, `tests/test_mqtt_poller.py`, `dashboard-react/src/{routes,store,components,lib}/**`, `design-system/src/components/{Progress,Table,Badge}.tsx`, `design-system/src/components/index.ts`
**Files scanned:** 16 read in full (poller script, its test file, 9 dashboard TS/TSX files, 3 design-system components + index, `App.tsx`, `DevicesRoute.tsx`), plus `12-CONTEXT.md`/`12-RESEARCH.md`/`12-UI-SPEC.md`
**Pattern extraction date:** 2026-09-21
