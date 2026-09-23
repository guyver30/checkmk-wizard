# Phase 13: Wizard Parents Support and Topology Map - Pattern Map

**Mapped:** 2026-09-23
**Files analyzed:** 12 (dashboard-react only — see "Python Side: No Files Touched" below)
**Analogs found:** 12 / 12

## Python Side: No Files Touched

CONTEXT.md's Scope Revision and RESEARCH.md both conclude the wizard's Phase 4/5 flow
(`src/checkmk_wizard/wizard.py`) and the poller (`scripts/mqtt_poller.py`) are **unmodified** by
this phase — parent/child capture moved entirely into the dashboard (D-01), and the poller
already reads/publishes `parents` (`topology_nodes()`/`publish_topology()`). The
`api.py`/`wizard.py` references in CONTEXT.md's canonical refs (`update_host_attributes()`,
`create_host()`, `create_host_tag_group()`, `_ensure_device_type_tag_group()`) are **precedent
for the new TypeScript `checkmkWrite.ts` client to mirror**, not files this phase edits. They are
cited below as the source analogs for that new file. If planning's live-verification (Open
Question 1, Assumption A4) discovers a poller change is needed after all (Open Question 2 —
`map_position` riding MQTT), `scripts/mqtt_poller.py`'s `OPTIONAL_HOST_COLUMNS` /
`topology_nodes()` pattern is the analog to extend at that time; not pre-classified here since it
is explicitly undecided.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `dashboard-react/src/components/TopologyMap.tsx` | component | event-driven (imperative canvas mount + write callbacks) | `dashboard-react/src/components/Splitter.tsx` (imperative ref/event pattern) + `src/checkmk_wizard/api.py` (write shape) | role-match (no in-repo vis-network/canvas precedent exists — first of its kind) |
| `dashboard-react/src/lib/checkmkWrite.ts` | service (REST client) | request-response | `src/checkmk_wizard/api.py` (`update_host_attributes()`, `create_host()`, `_request()`, `bootstrap_automation_user()`'s activation-poll loop) | exact (pattern-port across languages) |
| `dashboard-react/src/lib/mapIcons.ts` | utility | transform | `dashboard-react/src/lib/display.ts` (`deviceTypeIcon()`) | role-match |
| `dashboard-react/src/lib/topologyLayout.ts` | utility | transform | `dashboard-react/src/lib/grouping.ts` / `treeModel.ts` (pure data-shaping `lib/` module, no DOM) | role-match |
| `dashboard-react/src/assets/icons/device-types/*.svg` | asset (static) | file-I/O (build-time `?raw` import) | pre-React `dashboard/icons/` vendored set (superseded) / `web_assets/kone-design-system-main/.../icons/` (source) | exact (vendoring convention, not code) |
| `dashboard-react/src/routes/IndexRoute.tsx` | route/component | request-response (render from store) | itself (existing file, edited in place) | exact |
| `dashboard-react/src/lib/types.ts` | model (types) | — | itself (existing file, edited in place) | exact |
| `dashboard-react/src/lib/config.ts` | config | — | itself (existing file, edited in place) | exact |
| `dashboard-react/src/components/TopologyMap.test.tsx` | test | — | `dashboard-react/src/components/GroupingControls.test.tsx` (component wired-into-IndexRoute test style) | role-match |
| `dashboard-react/src/lib/checkmkWrite.test.ts` | test | — | `dashboard-react/src/lib/display.test.ts` (pure-function `describe`/`it` style) | role-match |
| `dashboard-react/src/lib/mapIcons.test.ts` | test | — | `dashboard-react/src/lib/display.test.ts` | exact |
| `dashboard-react/src/lib/topologyLayout.test.ts` | test | — | `dashboard-react/src/lib/grouping.test.ts` | exact |

## Pattern Assignments

### `dashboard-react/src/components/TopologyMap.tsx` (component, event-driven)

**Analogs:** `dashboard-react/src/components/Splitter.tsx` (imperative DOM/event handling inside
a React component — the closest structural precedent, since no vis-network/canvas component
exists yet) and `src/checkmk_wizard/api.py` (for the write callbacks' REST shape, via
`checkmkWrite.ts`).

**Imports pattern** (`Splitter.tsx` lines 1-14 — adapt, don't copy verbatim; add `vis-network`/
`vis-data`):
```tsx
import { useRef } from "react";
// New for this file:
// import { useEffect, useRef, useState } from "react";
// import { DataSet } from "vis-data";
// import { Network } from "vis-network";
// import { useNavigate } from "react-router"; // D-10 node-click navigation
```

**Imperative mount + cleanup pattern** (mirrors `Splitter.tsx`'s `useRef`-owned mutable state,
extended to `useEffect`-scoped lifecycle per `13-RESEARCH.md` Pattern 1 — mount once, destroy on
unmount):
```tsx
// Source: 13-RESEARCH.md Pattern 1 (vis-network official examples + Phase 11 D-09)
const containerRef = useRef<HTMLDivElement>(null);
const networkRef = useRef<Network | null>(null);

useEffect(() => {
  if (!containerRef.current) return;
  const nodes = new DataSet(initialNodes);
  const edges = new DataSet(initialEdges);
  const network = new Network(containerRef.current, { nodes, edges }, options);
  network.once("stabilizationIterationsDone", () => {
    network.setOptions({ physics: false }); // Phase 11 D-09: freeze after first layout
  });
  networkRef.current = network;
  return () => network.destroy();
}, []); // mount once; MQTT/status updates go through DataSet.update(), never remount
```

**Merge-in-place pattern** (never `network.setData()` — `13-RESEARCH.md` Pattern 2 /
Anti-Patterns, same "patch in place" discipline `useAppStore.ts`'s `set({...})` calls already
follow for every other MQTT topic):
```ts
nodesDataSet.update(
  topologyPayload.devices.map((d) => ({ id: d.id, parents: d.parents, image: recoloredIconFor(d) })),
);
```

**Click-mode gating** (new interaction contract, `13-UI-SPEC.md` "Click-mode gating" section —
mirrors `TreeNode.tsx`'s `<Link to={`/details?id=${encodeURIComponent(device.id)}`}>` navigation
target exactly, D-10):
```tsx
// Source: dashboard-react/src/components/TreeNode.tsx:87 (Link target string), adapted to
// imperative navigate() since vis-network's click event is not a React <Link>.
network.on("click", (params) => {
  if (editMode) return; // manipulation toolbar owns clicks in edit mode
  const nodeId = params.nodes[0];
  if (nodeId) navigate(`/details?id=${encodeURIComponent(nodeId)}`);
});
```

**Edit-mode toggle gating** (`13-UI-SPEC.md` "Edit Mode & Manipulation Toolbar"):
```ts
network.setOptions({
  manipulation: { enabled: editMode, addEdge: onAddEdge, editEdge: onEditEdge, deleteEdge: onDeleteEdge },
  interaction: { dragNodes: editMode },
});
```

**Error handling pattern** (mirrors `api.py`'s "best-effort, never fatal" posture for the write
path, but the UI-SPEC explicitly requires *visible* failure, not silent swallow — see Copywriting
Contract "Couldn't save that connection" / "Saved, but not live yet"):
```ts
try {
  await checkmkWrite.updateHostAttributes(hostName, { parents });
} catch (err) {
  showSnackbar("Couldn't save that connection", "Checkmk rejected the update. Check that both devices still exist, then try again.");
  return; // do not optimistically apply the edge to the DataSet
}
```

---

### `dashboard-react/src/lib/checkmkWrite.ts` (service, request-response)

**Analog:** `src/checkmk_wizard/api.py` — `_request()` (lines 104-140, the single choke point),
`update_host_attributes()` (lines 214-223), `create_host()` (lines 193-207), and
`bootstrap_automation_user()`'s activation-polling loop (lines 508-532).

**GET-etag-PUT pattern to port** (`api.py:214-226`):
```python
async def update_host_attributes(
    self, host_name: str, attributes: dict[str, Any], etag: str
) -> dict[str, Any]:
    resp = await self._request(
        "PUT",
        f"/objects/host_config/{host_name}",
        json_body={"attributes": attributes},
        extra_headers={"If-Match": etag},
    )
    return resp.json()

async def get_host(self, host_name: str) -> httpx.Response:
    return await self._request("GET", f"/objects/host_config/{host_name}")
```

**TypeScript port** (`13-RESEARCH.md` Pattern 3, "mirrors `update_host_attributes()` exactly"):
```ts
// Source: mirrors src/checkmk_wizard/api.py update_host_attributes() (line 214)
const getResp = await fetch(`${CHECKMK_BASE_URL}/${CHECKMK_SITE}/check_mk/api/1.0/objects/host_config/${hostName}`, {
  headers: { Authorization: `Bearer ${TOPOLOGY_EDITOR_USER} ${TOPOLOGY_EDITOR_SECRET}`, Accept: "application/json" },
});
const etag = getResp.headers.get("ETag");
await fetch(`${CHECKMK_BASE_URL}/${CHECKMK_SITE}/check_mk/api/1.0/objects/host_config/${hostName}`, {
  method: "PUT",
  headers: {
    Authorization: `Bearer ${TOPOLOGY_EDITOR_USER} ${TOPOLOGY_EDITOR_SECRET}`,
    "Content-Type": "application/json",
    "If-Match": etag ?? "",
  },
  body: JSON.stringify({ attributes: { parents: [...], labels: { map_position: "120,340" } } }),
});
```

**Single choke-point pattern** (`api.py:104-140` — every REST call funnels through one function
that normalizes both HTTP-level and status-code-level failures; `checkmkWrite.ts` should have an
equivalent single `request()` helper other exported functions call, not ad hoc `fetch()` per
call site):
```python
async def _request(self, method, path, *, json_body=None, params=None, extra_headers=None, expect=(200, 201)) -> httpx.Response:
    headers = {"Content-Type": "application/json"} if json_body is not None else {}
    if extra_headers:
        headers.update(extra_headers)
    try:
        resp = await self._client.request(method, path, json=json_body, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise CheckmkAPIError(method, f"{self._client.base_url}{path.lstrip('/')}", 0, str(exc)) from exc
    if resp.status_code not in expect and resp.status_code != 204:
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        raise CheckmkAPIError(method, str(resp.url), resp.status_code, body)
    return resp
```

**Activation-polling pattern to port** (`api.py:508-532`, `13-RESEARCH.md` Don't-Hand-Roll table —
"port the same 30-iteration/0.3s pattern to TypeScript"):
```python
pending_resp = await client.get(f"{base}/api/v1/domain-types/activation_run/collections/pending_changes")
etag = pending_resp.headers.get("ETag")
if etag:
    activate_resp = await client.post(
        f"{base}/api/v1/domain-types/activation_run/actions/activate-changes/invoke",
        json={"redirect": False, "sites": [site], "force_foreign_changes": False},
        headers={"Accept": "application/json", "If-Match": etag},
    )
    activation = activate_resp.json()
    self_url = next((link["href"] for link in activation.get("links", []) if link.get("rel") == "self"), None)
    is_running = activation.get("extensions", {}).get("is_running", False)
    for _ in range(30):
        if not is_running or not self_url:
            break
        await asyncio.sleep(0.3)
        status_resp = await client.get(self_url, headers={"Accept": "application/json"})
        is_running = status_resp.json().get("extensions", {}).get("is_running", False)
```
Port this as an exported `activateChanges()` in `checkmkWrite.ts`, called once from the "Apply
changes" button handler (batched — see `13-RESEARCH.md` Anti-Patterns: never call per-edge).

**Error type pattern:** `api.py`'s `CheckmkAPIError(RuntimeError)` (lines 19-27, carries
`method`/`url`/`status_code`/`body`) is the analog for a `CheckmkWriteError` class/type in
`checkmkWrite.ts` — one error shape thrown from the single `request()` choke point, not ad hoc
`Error`s per call site.

---

### `dashboard-react/src/lib/mapIcons.ts` (utility, transform)

**Analog:** `dashboard-react/src/lib/display.ts` — `deviceTypeIcon()` (lines 62-76), the existing
`device_type` → icon-class lookup this new module extends with an SVG-string variant.

**Lookup-table pattern to mirror** (`display.ts:62-76`):
```ts
export function deviceTypeIcon(deviceType: string | null | undefined): string {
  const icons: Record<string, string> = {
    other: "icon-circle",
    "E-link": "icon-api",
    ACS: "icon-secured",
    Multimedia: "icon-videocam",
    NetworkDevice: "icon-internet",
    GroupController: "icon-controls",
    unknown: "icon-question-circle",
  };
  return (deviceType && icons[deviceType]) || "icon-circle";
}
```

**New module's parallel table + recolor function** (per D-08/D-09, `13-RESEARCH.md` Code
Examples — same `device_type` keys as `display.ts`, values are `?raw`-imported SVG strings
instead of CSS class names):
```ts
import internetSvg from "../assets/icons/device-types/internet.svg?raw";
// ...same device_type keys as deviceTypeIcon() above...
const DEVICE_TYPE_SVG: Record<string, string> = {
  other: circleSvg,
  "E-link": apiSvg,
  ACS: securedSvg,
  Multimedia: videocamSvg,
  NetworkDevice: internetSvg,
  GroupController: controlsSvg,
};

function recoloredDataUri(svgMarkup: string, hexColor: string): string {
  const recolored = svgMarkup.replace(/fill="#141414"/g, `fill="${hexColor}"`);
  return `data:image/svg+xml;utf8,${encodeURIComponent(recolored)}`;
}
```
**No-DOM-access constraint** (module header comment convention from `display.ts:1-8`): this file
must stay a pure function module, same "No DOM access, no broker connection, no browser storage,
no network calls" contract `display.ts` states explicitly in its header comment — reuse that
comment verbatim as the header for `mapIcons.ts`.

**Defensive-fallback convention** (`display.ts`'s `(deviceType && icons[deviceType]) || "icon-circle"`
pattern): `mapIcons.ts`'s lookup should default to the same `NetworkDevice`/generic fallback
rather than throwing on an unrecognized `device_type`, consistent with `display.ts`'s
"tolerates a payload that predates a plan... returns a safe default instead of throwing" rule.

---

### `dashboard-react/src/lib/topologyLayout.ts` (utility, transform)

**Analog:** `dashboard-react/src/lib/grouping.ts` / `treeModel.ts` — pure, DOM-free `lib/`
modules that reshape `DevicePayload[]` into a derived structure (grouping keys / tree nodes),
the same "pure function, no side effects" contract the grid-placement algorithm needs.

**Pattern to follow** (module shape, not exact algorithm — `grouping.ts`/`treeModel.ts`'s own
header-comment convention of stating inputs/outputs and defensive-parse posture applies here
too):
```ts
// Source: 13-RESEARCH.md Code Examples ("Initial grid placement for parentless hosts")
export function initialGridPositions(devices: { id: string }[]): Record<string, { x: number; y: number }> {
  const COLS = Math.ceil(Math.sqrt(devices.length));
  const SPACING = 150;
  const positions: Record<string, { x: number; y: number }> = {};
  devices.forEach((d, i) => {
    positions[d.id] = { x: (i % COLS) * SPACING, y: Math.floor(i / COLS) * SPACING };
  });
  return positions;
}
```
**Forward-compatibility constraint (D-11):** per CONTEXT.md D-11, this module's exported shape
must not hard-code "one global unfiltered view" — accept a pre-filtered device list as input
(matching how `buildTree()` in `treeModel.ts` already takes `devices`/`mode`/`nowMs` as plain
parameters rather than reading the store directly) so a future Phase 15 tower-filter pass can
call it with a subset, not rewrite it.

---

### `dashboard-react/src/routes/IndexRoute.tsx` (route, edited in place)

**Analog:** itself — existing mount point for `MapPlaceholder` (line 5 import, lines 85-94 JSX).

**Current mount to replace** (`IndexRoute.tsx` lines 85-94):
```tsx
centreTop={
  // D-25: the stats strip sits ABOVE the map placeholder, content-sized, with the
  // placeholder taking the remaining height -- both are always visible together.
  <div className="flex h-full flex-col gap-2 p-3">
    <StatsStrip counts={counts} />
    <div className="min-h-0 flex-1">
      <MapPlaceholder />
    </div>
  </div>
}
```
Per `13-UI-SPEC.md` "Layout Integration": swap `<MapPlaceholder />` for a new toolbar row
(`Switch`/`Banner`/`Button`) + `<TopologyMap />`, inside the **same** `min-h-0 flex-1` wrapper —
no resize of `ThreePaneLayout`, no new breakpoint, no change to `tree`/`centreBottom` props.

**State-lifted-in-route pattern to reuse** (`IndexRoute.tsx` lines 37-54, `useGroupingPrefs` +
`openKeys` state): edit-mode boolean and pending-edit count are exactly this shape of
"UI-session state lifted into the route, not the Zustand store" — same rationale (`useAppStore`
updates on every MQTT message must not reset local UI state) applies to `editMode`/pending-count
state for the topology toolbar. Reuse `useState` at the route level exactly as `openKeys` does,
not a new store slice.

---

### `dashboard-react/src/lib/types.ts` (model, edited in place)

**Analog:** itself — `TopologyPayload` interface (lines 80-84), currently loose.

**Existing shape to tighten** (`types.ts:80-84`):
```ts
export interface TopologyPayload {
  devices?: unknown[];
  timestamp?: string;
  [key: string]: unknown;
}
```
**Convention to follow when tightening** (`DevicePayload`'s own style, `types.ts:15-44` — every
field optional, loosely typed, module header comment explaining why): add a `parents?: string[]`
and (if Open Question 2 resolves to "yes, MQTT carries it") `map_position?: string` field to
whatever per-device shape `devices` resolves to, following the same "every field optional... the
runtime guards in display.ts/staleness.ts/grouping.ts remain load-bearing regardless" doctrine
stated in the file's header comment (lines 1-6) — do not add non-optional fields or throw-on-parse
validation here.

---

### `dashboard-react/src/lib/config.ts` (config, edited in place)

**Analog:** itself — `WS_USERNAME`/`WS_PASSWORD` (lines 25-26) and `isCheckmkLinkConfigured()`
(lines 41-43), the exact "disposable, plainly-committed per-deployment credential" convention
D-04 explicitly follows.

**Existing pattern to extend** (`config.ts:14-31`):
```ts
// WS_USERNAME/WS_PASSWORD are deliberately-committed disposable read-only credentials,
// the same convention already used by deploy/mosquitto.passwd itself, cmkadmin/cmkadmin,
// and minioadmin/minioadmin. The grant behind them is read-only (`topic read lan/#` in
// deploy/mosquitto.acl), which bounds the exposure to reading the device list, never
// writing anything back to the broker.

export const WS_PORT = 9002;
export const WS_USERNAME = "wsreader";
export const WS_PASSWORD = "wsreader";
export const CHECKMK_BASE_URL = "http://<HOST_IP>:8080";
export const CHECKMK_SITE = "dmc";
```
**New constants to add** (per CONTEXT.md's "Claude's Discretion" on exact naming — precedent is
the pattern, not the literal name): a `TOPOLOGY_EDITOR_USER`/`TOPOLOGY_EDITOR_SECRET` pair (or
similarly-named), documented with the same style of comment block explaining the credential's
**write** scope (contrast with `WS_USERNAME`'s explicitly documented read-only scope) — per
Pitfall 4/D-04, this credential must NOT reuse `WS_USERNAME`, and its comment should name the
one-time manual WATO role-clone step (`topology_editor` role) it depends on, mirroring how the
existing comment documents the broker ACL its own credential depends on.

---

### `dashboard-react/src/components/TopologyMap.test.tsx` (test)

**Analog:** `dashboard-react/src/components/GroupingControls.test.tsx` — component-wired-into-
`IndexRoute` test style: reset `useAppStore` to its initial snapshot in `beforeEach`, seed
`devices` via `act(() => useAppStore.setState(...))`, render inside `<MemoryRouter>`.

**Setup pattern to copy** (`GroupingControls.test.tsx` lines 1-46):
```tsx
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";
import { IndexRoute } from "../routes/IndexRoute";
import { useAppStore } from "../store/useAppStore";
import type { DevicePayload } from "../lib/types";

const INITIAL_STATE = useAppStore.getState();

beforeEach(() => {
  useAppStore.setState(INITIAL_STATE, true);
  localStorage.clear();
});

function setDevices(devices: Record<string, DevicePayload>) {
  act(() => {
    useAppStore.setState({ devices });
  });
}

function renderIndex() {
  return render(
    <MemoryRouter>
      <IndexRoute />
    </MemoryRouter>,
  );
}
```
**vis-network/jsdom caveat (new, no existing precedent):** `Splitter.test.tsx`'s comment
("jsdom does not implement setPointerCapture/releasePointerCapture... stubs both on the element")
is the closest existing precedent for a canvas/DOM-API gap in tests — `vis-network`'s `Network`
constructor calls canvas APIs jsdom does not implement (`getContext('2d')` returns `null` by
default); the test file will need an equivalent stub/mock, following the same "stub what jsdom
lacks, comment why" convention rather than skipping canvas-touching tests wholesale.

---

### `dashboard-react/src/lib/checkmkWrite.test.ts`, `mapIcons.test.ts`, `topologyLayout.test.ts` (tests)

**Analog:** `dashboard-react/src/lib/display.test.ts` — plain `describe`/`it` blocks per exported
function, asserting on defensive fallbacks (null/malformed input) as their own `it` case.

**Pattern to copy** (`display.test.ts:1-25`):
```ts
import { describe, expect, it } from "vitest";
import { displayName, effectiveState } from "./display";

describe("displayName", () => {
  it("returns the trimmed alias when present", () => {
    expect(displayName({ alias: "  Tower B  ", id: "h1" })).toBe("Tower B");
  });
  it("returns an empty string for a null/malformed payload", () => {
    expect(displayName(null)).toBe("");
  });
});
```
For `checkmkWrite.test.ts`, mock `fetch` (this codebase's Python equivalent, `respx` for
`httpx`, has no direct npm counterpart already in `devDependencies` — `vitest`'s built-in
`vi.stubGlobal("fetch", ...)` or `vi.fn()` is the standard substitute; no new test-mocking
library is needed, matching CLAUDE.md's simplicity-first bias).

---

## Shared Patterns

### REST write choke point (Checkmk PUT-with-ETag)
**Source:** `src/checkmk_wizard/api.py:104-140` (`_request()`) and `:214-223`
(`update_host_attributes()`)
**Apply to:** `checkmkWrite.ts` (all exported write functions), and transitively every
`addEdge`/`editEdge`/`deleteEdge`/Apply callback in `TopologyMap.tsx`
**Rule:** GET current ETag → PUT with `If-Match: <etag>` and `{"attributes": {...}}`; one
normalizing choke point, not ad hoc `fetch()` per call site.

### Best-effort vs. visible-failure posture
**Source:** `src/checkmk_wizard/api.py:426-427` docstring ("this is best-effort; the caller
should treat a failure here as 'fall back to...', never as fatal") contrasted with
`13-UI-SPEC.md`'s explicit requirement that write failures surface via `Snackbar`
**Apply to:** `TopologyMap.tsx`'s write callbacks
**Rule:** Unlike the wizard's CLI (where the operator is already watching and silent
best-effort retries are acceptable), the dashboard's write path must surface every failure
visibly (Copywriting Contract's two named error states) — do not port the wizard's "swallow and
warn" convention here; port only its *error-wrapping* discipline (one error type, one choke
point), not its *silence*.

### Disposable per-deployment credential convention
**Source:** `dashboard-react/src/lib/config.ts:14-26` (`WS_USERNAME`/`WS_PASSWORD` +
surrounding comment)
**Apply to:** `config.ts`'s new topology-editor credential constants
**Rule:** Plainly committed, documented inline with its exact permission scope and the
manual provisioning step (role clone) it depends on — never silently assume "same pattern,
narrower scope" without writing out the scope explicitly, per Pitfall 4.

### Pure, DOM-free `lib/` modules
**Source:** `dashboard-react/src/lib/display.ts:1-8` header comment ("No DOM access, no broker
connection, no browser storage, no network calls -- pure functions only")
**Apply to:** `mapIcons.ts`, `topologyLayout.ts` (NOT `checkmkWrite.ts`, which is explicitly a
network-calling exception, same as `mqttClient.ts` already is for the broker)
**Rule:** Same defensive-parse-returns-safe-default posture as `display.ts`/`stateMapping.ts` —
never throw on unrecognized `device_type` or malformed device list.

### Route-level lifted UI state (not Zustand)
**Source:** `dashboard-react/src/routes/IndexRoute.tsx:37-54` (`useGroupingPrefs`, `openKeys`
`useState`)
**Apply to:** Edit-mode toggle state, pending-edit count in `IndexRoute.tsx`
**Rule:** UI-session state that must survive a device-status re-render lives in route-level
`useState`, not the Zustand store — the store is reserved for MQTT-sourced data.

## No Analog Found

None among the 12 dashboard-react files — every file has at least a role-match analog (see
per-file "Match Quality" column above; the weakest matches are `TopologyMap.tsx` itself, since
no canvas/graph-library component exists yet in this codebase, and the vendored SVG assets,
which are a copy operation rather than code).

## Conventions

Derived via the shared `gsd-tools.cjs verify conventions --derive` module, scoped to
`dashboard-react/src` (33 files, 77 identifiers sampled):

| Axis | Dominant | Share | Entropy | Status |
|---|---|---|---|---|
| File-name casing | camelCase (18) vs PascalCase (15) | 55% | 0.994 | **contested hotspot** |
| Identifier casing | camelCase | 71% | 0.593 | named contract |
| Export style | ESM (`export`) | 100% | 0.0 | named contract |
| Import style | ESM (`import`) | 100% | 0.0 | named contract |

**Contested hotspots (author's choice).** File-name casing sits below the 70% dominance
threshold (55/45 camel/Pascal split) and is a genuine, intentional dual convention in this repo,
not drift: React **components** are named PascalCase (`TreeNode.tsx`, `GroupingControls.tsx`,
`StatsStrip.tsx`) while **`lib/`/`hooks/`/`store/` modules** are named camelCase
(`display.ts`, `useGroupingPrefs.ts`, `useAppStore.ts`) — each half is internally consistent
per-directory, contested only when counted repo-wide. This is the dashboard's own local version
of the project's broader documented prototype for this split (the CJS↔SDK dual resolver in
`bin/lib/**` vs `sdk/src/**`, where CJS `module.exports`/`require` and ESM `export`/`import`
each stay internally consistent per-directory and are contested only in aggregate). For this
phase's new files: `TopologyMap.tsx` and `TopologyMap.test.tsx` (components) → PascalCase;
`checkmkWrite.ts`, `mapIcons.ts`, `topologyLayout.ts` and their `.test.ts` files (`lib/` modules)
→ camelCase. Match the directory's local style, not a repo-wide vote — reviewers/planners should
do the same rather than flagging the split itself as an inconsistency. Identifier casing
(camelCase, 71%) and both ESM axes (100%) are named contracts with no discretion: every new
export/import in this phase's files must be camelCase identifiers and ESM `import`/`export`,
matching every existing `dashboard-react/src` file already read above.

## Metadata

**Analog search scope:** `dashboard-react/src/{components,lib,routes,store,hooks}`,
`src/checkmk_wizard/{api.py,wizard.py}`, `design-system/src/components/{Switch,Button}.tsx`
**Files scanned:** ~20 read directly (MapPlaceholder.tsx, IndexRoute.tsx, config.ts, types.ts,
useAppStore.ts, display.ts, GroupingControls.tsx, useGroupingPrefs.ts, TreeNode.tsx,
stateMapping.ts, Splitter.tsx, Switch.tsx, Button.tsx, api.py, wizard.py excerpts,
display.test.ts, GroupingControls.test.tsx, package.json) plus a directory listing of all 60
`dashboard-react/src` files
**Pattern extraction date:** 2026-09-23
