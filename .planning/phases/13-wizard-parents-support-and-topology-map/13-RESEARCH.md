# Phase 13: Wizard Parents Support and Topology Map - Research

**Researched:** 2026-09-23
**Domain:** Browser-embedded Checkmk REST API writes (vis-network topology editor) + Checkmk host-attribute/role REST semantics
**Confidence:** MEDIUM (stack/library facts HIGH; several Checkmk REST *capability boundaries* are load-bearing findings this research surfaced that were not anticipated in CONTEXT.md, and must be live-verified against the real 2.4.0p35 CE site before/during planning)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Parent/child relationship capture (replaces wizard-CLI approach)**
- **D-01:** Relationships are drawn **in the dashboard's topology map**, not prompted by the
  wizard CLI. On first load with no `parents` set, hosts are placed in a non-overlapping grid
  layout so every node is reachable/draggable. Hosts that already carry Livestatus `parents`
  data render with real edges immediately (per-host handling, not a bulk migration step).
- **D-02:** The map has an explicit **"Edit topology" toggle** — manipulation (add/edit/delete
  edge, drag position) is only active in edit mode, never always-on, so a stray drag on a
  shared/kiosk display can't silently rewrite Checkmk's topology.
- **D-03:** Edit mode uses vis-network's own built-in **manipulation toolbar** (addEdge/
  editEdge/deleteEdge callbacks) rather than fully custom drag-to-connect interaction code.
  The callback receives the two node ids; the browser PUTs the resulting `parents` attribute
  directly to Checkmk in that callback.
- **D-04:** The browser calls **Checkmk's REST API directly** (no new backend, no proxy) to
  write `parents` and `map_position`. This needs a write-capable Checkmk automation
  credential embedded client-side — acceptable under this project's existing trusted-LAN,
  no-multi-user-accounts posture (same convention as the already-committed disposable
  `WS_USERNAME`/`WS_PASSWORD` in `dashboard-react/src/lib/config.ts`). **Flagged for
  research/planning**: this credential should be a narrowly-scoped automation user, not a
  reuse of the wizard's own full-power `automation` user from `bootstrap_automation_user()` —
  exact Checkmk role/permission shape needs live verification.

**Unmanaged (non-Checkmk-agent) switches**
- **D-05:** An unmanaged switch (no agent, not reliably pingable, added purely to complete
  the topology picture) is onboarded as a **real Checkmk host**, one per switch — not a
  dashboard-only synthetic node, not a shared sentinel host. This makes its `parents`/
  `map_position` attributes storable the same way as any other host, using the exact same
  write path as D-04.
- **D-06:** That host must produce **zero services/checks** — no PING, no WARN/CRIT ever,
  since the device isn't guaranteed pingable. Recommended approach: Checkmk's "No IP
  address" host attribute + no-agent tag, so there's nothing for Checkmk to check by
  construction. **Flagged for research/planning**: exact attribute/tag shape needs live
  verification against the 2.4.0p35 CE site, following this codebase's established
  live-verification discipline (same as `tag_device_type`'s REST shape was verified in
  Phase 10).

**Position persistence**
- **D-07:** A real host's map position is stored as a new Checkmk **custom host attribute**
  (e.g. `map_position`, holding x/y), written via the same REST path as `parents`. This
  reuses Checkmk's own config storage — which already lives on the `checkmk_data` volume per
  `deploy/compose.yaml` — so "stored in the container volume" is satisfied with no new
  backend, no new volume mount, and no broker/ACL changes. Consistent with D-05: since
  unmanaged switches are now real hosts too, they use the identical `map_position` attribute
  — no separate sentinel-host/folder-blob mechanism needed (this supersedes an
  intermediate idea floated mid-discussion of a shared JSON blob on a sentinel host or the
  root folder; D-05/D-06 made that unnecessary).

**Rendering: node shape, icons, coloring**
- **D-08:** Map nodes use `shape: 'circularImage'` with a **dynamically-recolored SVG data
  URI** as the `image` (string-replace the SVG's fill color per current state, embed as a
  `data:image/svg+xml` URI) — not `ctxRenderer`. Simpler, no custom canvas draw code,
  accepted tradeoff of "full-color icon that tints by state" rather than pixel-identical
  parity with the Tree/StateBadge colored-circle-plus-white-icon look.
- **D-09:** Icon source is a **curated SVG set the operator places directly**, not
  lucide-react/tabler. Location: `dashboard-react/src/assets/icons/device-types/`, imported
  with Vite's `?raw` suffix (e.g. `import internetSvg from
  "../assets/icons/device-types/internet.svg?raw"`) so the code gets raw SVG text to
  recolor, not just a URL. Keep the existing lowercase-kebab filenames already established
  by the pre-React dashboard's vendored set (`internet.svg`, `api.svg`, `secured.svg`,
  `videocam.svg`, `controls.svg`, `circle.svg` — copyable from
  `web_assets/kone-design-system-main/packages/kone-ds-assets/icons/`) so `device_type` →
  filename stays a 1:1, rename-free mapping; the operator adds new files (e.g. for the
  unmanaged-switch type) as needed.

**Map interaction and scope boundaries**
- **D-10:** Clicking a map node navigates to `/details?id={id}` — matches DASH-11's existing
  tree-row click pattern. Distinct from edit-mode drag/connect interactions.
- **D-11:** The map stays **flat** in this phase — no folder/device_type grouping overlay,
  edges are the whole point and shouldn't compete visually with a grouping hull. D-05 (the
  Phase 11 grouping toggle) keeps driving only the sidebar tree/stats strip, unchanged.
  **However**, build the map's data model and component so it isn't hard-wired to "one
  global unfiltered view" — Phase 15 (parked, not this phase) will add a physical-location
  tag group (tower + sub-location) and per-tower dashboard tabs with sub-location rectangle
  grouping on the map. Don't implement tower filtering now; don't design the map in a way
  that makes adding a "filter nodes by tag" pass later a rewrite.

**Carried forward from Phase 11 (apply as-is, don't re-derive)**
- Phase 11 D-08 (synthetic group-root): superseded by this phase's D-05/D-06 — unmanaged
  switches are now real hosts with real `parents` edges, not synthetic group-root nodes.
- **Phase 11 D-09 (stabilize-then-freeze physics):** still applies, unchanged — physics runs
  once on load, then freezes so `DataSet.update()` recolors nodes in place without disturbing
  pan/zoom or (now) manually-dragged positions.
- **Phase 11 D-11/D-12/D-15 (state palette, staleness factor, stale-never-masks-a-known-bad-
  child):** still apply, unchanged, to node coloring.

### Claude's Discretion
- Exact grid-layout algorithm for initial (no-`parents`-yet) node placement
- Exact custom-attribute id/shape for `map_position` (single string "x,y" vs. two separate
  attributes) — pick whichever is simpler against the live-verified REST shape
- Manipulation toolbar's exact button labels/styling within kone-design-system's visual
  language
- Whether the write-capable credential lives in `config.ts` alongside `WS_USERNAME`/
  `WS_PASSWORD` or a new constant — the precedent is set, the exact naming isn't

### Deferred Ideas (OUT OF SCOPE)

**To Phase 15 (parked, not-urgent — per STATE.md Roadmap Evolution)**
- Per-tower dashboard tabs, filtering the map to one physical tower at a time.
- Sub-location rectangle grouping on the map (e.g. a visible "motor room xyz" / "lobby A"
  boundary around the hosts in that sub-location).
- The new Checkmk tag group capturing tower + sub-location that both of the above depend on.
- This phase (13) should prepare for these (D-11) but not implement any of them.

**Open, not resolved in the discussion — flagged for planning/research (this research
document addresses these; final lock-in is planning's job)**
- Whether `map_position` (and any per-host edit-mode metadata) gets added to the poller's
  MQTT `lan/devices/topology` payload, or stays a browser-side direct-read-from-Checkmk
  concern only — see this document's Open Question 2.
- Exact Checkmk role/permission scope for the write-capable browser credential (D-04) — see
  this document's Pitfall 4 / Assumption A3.
- Exact no-IP/no-agent host attribute shape for unmanaged switches (D-06) — see this
  document's Assumption A1.
- REQUIREMENTS.md amendment covering the dashboard-edit-mode write-back capability — see
  this document's Phase Requirements note and Open Question 3. Not resolved by research.

**Explicitly not in this phase** (per CONTEXT.md's Phase Boundary)
- Per-tower dashboard tabs and sub-location rectangle grouping (Phase 15).
- Folder/device_type grouping overlays on the map itself (D-11's toggle keeps driving only
  the tree/stats strip, unchanged).
</user_constraints>

## Summary

This phase has two halves: (1) a React topology-map component (`vis-network` + `vis-data`, wrapped
in a thin component, rendering `useAppStore`'s existing `topology` slot) with an edit mode that
writes `parents` (and a position) straight back to Checkmk over REST from the browser, and (2)
onboarding unmanaged LAN switches as real, check-free Checkmk hosts. Both halves are additive to
the existing MQTT-only dashboard (D-04's explicit architecture reversal) and touch no backend.

Research surfaced three findings CONTEXT.md's open questions did not anticipate, all stemming from
the same underlying fact: **Checkmk's REST API lets you use pre-existing "definition" objects
(tag groups, custom attributes, roles) but does not let you create new ones — only the GUI/WATO
can define them.** This directly affects three of CONTEXT.md's "flagged for research" items:

1. **`map_position` storage:** a *custom host attribute* needs a one-time GUI-only definition step
   with no REST equivalent — but Checkmk **host labels** (`attributes.labels`, a free-form
   key:value dict) need **zero predefinition** and are settable via the exact same
   `update_host_attributes()` PUT this codebase already uses for `tag_device_type`. Recommend
   labels over custom attributes — same storage guarantee (lives in Checkmk's own config on the
   `checkmk_data` volume), zero manual GUI setup, same REST call shape. **This revises D-07's
   named mechanism ("custom host attribute") while satisfying its intent — flag for plan-checker/
   discuss-phase confirmation, not silently substitute.**
2. **Unmanaged-switch device type:** the existing `device_types.json` seed already has
   `NetworkDevice` (icon `internet.svg`). Since Checkmk's tag-group REST endpoint is
   create-only (no update/PUT endpoint exists in this codebase or, per research, in Checkmk's
   REST API at all), adding a brand-new device-type *value* to an already-provisioned site's tag
   group cannot be done over REST at all. Recommend reusing `NetworkDevice` for unmanaged switches
   rather than inventing a new tag value — avoids a REST capability gap entirely.
3. **Write-capable credential's role:** Checkmk custom **roles** are also GUI/WATO-only to create
   (clone-from-template in Setup > Users > Roles). The wizard's own `bootstrap_automation_user()`
   sidesteps this by hardcoding `"roles": ["admin"]` — explicitly NOT reusable per D-04. The
   correct pattern is a **one-time manual step** (documented, not automated): the operator clones
   Checkmk's built-in `user` role into a new role (e.g. `topology_editor`) with edit-host and
   activate-changes permissions only, then a REST-created automation user is assigned
   `"roles": ["topology_editor"]` — the user-creation call itself IS REST-automatable (same
   `POST .../user_config/collections/all` shape `bootstrap_automation_user()` already uses), only
   the role definition needs a manual GUI step.

**A fourth, independent finding not flagged in CONTEXT.md at all:** every `update_host_attributes()`
write (parents, labels, the switch hosts' no-agent/no-ip tags) is a **pending WATO change**, exactly
like every other host/folder/tag-group write this codebase already makes — it does **not** take
effect in Livestatus (and therefore never reaches the poller's `parents` column or other browsers'
maps) until **Activate Changes** runs. CONTEXT.md's edit-mode flow (draw an edge → PUT `parents`
in the `addEdge` callback) is incomplete without an activation step. Per-edge activation would be
slow (Checkmk's own activation is an async background job, ~seconds per run per
`bootstrap_automation_user()`'s own polling loop) and spammy for a multi-edge editing session —
recommend a single explicit "Apply"/batch-activate action in edit mode, not an activation call
inside every `addEdge`/`editEdge`/`deleteEdge` callback.

**Primary recommendation:** Add `vis-network` + `vis-data` as npm deps (both `[OK]` per slopcheck,
both high-download, actively maintained, GitHub-backed packages); build a thin `TopologyMap.tsx`
wrapping `Network`/`DataSet` per Phase 11 D-09's stabilize-then-freeze pattern; write `parents` and
`map_position` (as a host **label**, not a custom attribute) via a new minimal
`checkmkWrite.ts` client mirroring `api.py`'s PUT-with-ETag shape; batch activation behind an
explicit "Apply" action in edit mode; onboard unmanaged switches as real hosts tagged
`tag_agent=no-agent`, `tag_snmp_ds=no-snmp`, `tag_address_family=no-ip`, `device_type=NetworkDevice`
(reusing the existing tag value); document a one-time manual WATO role-clone step for the
write-capable credential rather than attempting to automate role creation over REST.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Topology map rendering (nodes/edges from `parents`) | Browser / Client | — | `vis-network` is a canvas-rendering library; data is already in the Zustand store via MQTT, no server round-trip needed to draw it |
| Parent/child edge capture (edit mode) | Browser / Client | API / Backend (Checkmk) | The browser owns the interaction (vis-network's manipulation toolbar); Checkmk's REST API is the persistence boundary — there is no intermediate app backend by design (D-04) |
| `parents` / `map_position` persistence | API / Backend (Checkmk REST) | Database/Storage (OMD site config on `checkmk_data` volume) | Checkmk's own WATO host-attribute store is reused; no new datastore |
| Config activation (pending → live) | API / Backend (Checkmk REST `activation_run`) | — | Mandatory Checkmk semantics — a host-attribute PUT is inert until activated; not optional, not skippable |
| Unmanaged-switch host object | API / Backend (Checkmk host_config) | — | Per D-05, it's a real Checkmk host, created the same way `create_host()` already creates every other host |
| Node icon assets (SVG, recolored) | Browser / Client (Vite build-time `?raw` import) | CDN / Static (served as part of the built SPA bundle) | Bundled at build time, not fetched at runtime — same pattern as the existing `mask-image` icon set |
| Poller `topology` payload (`id`/`parents`/`device_type`/`folder`/`alias`) | API / Backend (poller, reading Livestatus) | Browser / Client (consumer via MQTT) | Unchanged by this phase — `scripts/mqtt_poller.py` already emits this; only the values become non-empty |

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DASH-07 | `index.html` renders a live topology map (vis-network) with parent/child links, merging incoming updates via `DataSet.update()` rather than re-rendering from scratch | vis-network 10.1.2 + vis-data 8.0.5 confirmed current/legitimate (see Package Legitimacy Audit); `DataSet.update()` merge pattern confirmed as vis-network's standard API and already locked by Phase 11 D-09 (stabilize-then-freeze physics); node/edge source data (`topology_nodes()`/`topology_signature()` in `scripts/mqtt_poller.py`) already ships `id`/`parents`/`device_type`/`folder`/`alias` — no poller change required to satisfy the *read* half of DASH-07 |

**Note (flagged in CONTEXT.md, confirmed still open by this research):** the dashboard-edit-mode
write-back capability (browser PUTs `parents`/labels to Checkmk; unmanaged-switch onboarding;
scoped write credential) has **no requirement ID** in REQUIREMENTS.md — DASH-07's wording only
covers rendering, not editing. This is a gap for whoever runs requirements definition before/during
planning; out of scope for this research agent to fix directly.
</phase_requirements>

## Project Constraints (from CLAUDE.md)

From `/home/kone/checkmk-wizard/CLAUDE.md` (project-level, checked into the repo):

- **No new backend for the dashboard** — state comes entirely from MQTT retained messages, per
  the project's stated constraint — **explicitly reversed for this one feature** by the project's
  own Scope Revision note (2026-09-21, Phase 11.1 D-40 amendment carried into this phase's
  CONTEXT.md D-04): the browser is allowed to call Checkmk's REST API directly for
  `parents`/`map_position` writes. No plan for this phase should introduce a *new* backend/proxy
  service — the constraint's spirit ("no server-side application for the dashboard") still holds;
  only the "MQTT-only" half is lifted, and only for this feature.
- **Container boundary:** the poller/publisher must not require filesystem access to the
  `checkmk` container — Livestatus-over-TCP and the REST API are the only touchpoints. Unaffected
  by this phase (no poller filesystem access is introduced; if Open Question 2 concludes
  `map_position` should ride the MQTT payload, the poller would still reach it only via
  Livestatus/REST, consistent with this constraint).
- **Compatibility:** the wizard's existing 7-phase flow and its tests must not break. This phase's
  Scope Revision (D-01) already establishes that `wizard.py`'s Phase 4/5 code is untouched — no
  plan for this phase should add wizard-CLI prompts or touch `phase4_classification`/
  `phase5_onboarding`.
- **Tech stack:** Python 3.11+ via `uv` for anything touching the wizard/poller (unaffected by
  this phase unless Open Question 2 resolves to "add `map_position` to the poller" — that edit
  must still use `uv run`/`uv add`, never bare `python`/`pip`, matching every existing
  `scripts/mqtt_poller.py` change); the dashboard is npm/Vite-based (`dashboard-react/`), matching
  this phase's own new dependencies (`vis-network`, `vis-data`).
- **Live-verification discipline:** every REST/Livestatus shape this codebase depends on is
  verified against a real running 2.4.0p35 CE site before being trusted in code, with the
  verification method cited in a comment (live test, source file read, or docs URL) — this
  research's Assumptions A1/A2/A3/A4 are explicitly NOT yet live-verified and must be closed this
  way during planning/execution, not left as permanent inline guesses.
- **Naming/structure conventions (for any new TypeScript modules this phase adds):**
  `dashboard-react/` already establishes its own conventions (Zustand slices, pure-function `lib/`
  modules with no DOM access, component files matching one responsibility) — new files
  (`checkmkWrite.ts`, `mapIcons.ts`, `topologyLayout.ts`, `TopologyMap.tsx`) should match the
  existing `lib/`/`components/` split already used by `display.ts`/`StateBadge.tsx` rather than
  introducing a new organizational pattern.

From `~/.claude/CLAUDE.md` (user-global, applies across all projects):

- **Update documentation after implementation:** any markdown docs this phase's feature touches
  (e.g. a `dashboard-react/README.md` "Topology editing" section, or the deployment doc's
  `CHECKMK_BASE_URL`/credential-setup instructions if the manual role-clone step from Pitfall 4
  gets documented there) must be updated to match the final implementation — flag as a plan task,
  not an afterthought.
- **Simplicity first / surgical changes:** this research's recommendations (labels over custom
  attributes, reusing `NetworkDevice` over a new tag value) are themselves simplicity-first
  choices — they avoid introducing GUI-only manual provisioning steps where a REST-only path
  already exists. Planning should preserve that bias rather than "completing" D-07/D-09's literal
  wording at the cost of a manual step this research shows is avoidable.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `vis-network` | 10.1.2 [VERIFIED: npm registry, `dist-tags.latest`] | Canvas-based graph rendering, manipulation toolbar (addEdge/editEdge/deleteEdge), physics/stabilization | Already named in CONTEXT.md/D-08/D-03; this is the de facto standard vanilla-JS network-graph library with first-class React-agnostic usage (no React wrapper needed — a `useEffect`-mounted imperative instance is the standard pattern) |
| `vis-data` | 8.0.5 [VERIFIED: npm registry] | `DataSet` — the mutable, in-place-updatable node/edge collection `vis-network`'s `Network` constructor consumes | Required peer of `vis-network` (`peerDependencies: "vis-data": ">=8.0.0"`); must be installed explicitly, not left to npm's peer auto-install, because code imports `DataSet` directly from it |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| (none new) | — | — | `react-router`'s existing `useNavigate()` hook (already used via `<Link>` in `TreeNode.tsx`) covers D-10's node-click navigation; `kone-design-system`'s `Switch` component (already vendored, `design-system/src/components/Switch.tsx`) is the closest existing primitive for the "Edit topology" toggle (D-02) — no new UI library needed |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `vis-network`'s built-in manipulation toolbar | Custom drag-to-connect canvas code | D-03 already locks the toolbar choice — rejected because it duplicates a well-tested interaction vis-network ships for free |
| Host **labels** for `map_position` | Checkmk custom host attribute | Custom attributes need a one-time GUI-only definition step (no REST endpoint to create the definition — see Common Pitfalls); labels need none. Recommend labels; flag for plan confirmation since it revises D-07's stated mechanism |
| Reusing `device_type=NetworkDevice` for unmanaged switches | A new `device_type` tag value (e.g. `UnmanagedSwitch`) | Checkmk's host-tag-group REST endpoint is create-only — no update/PUT exists to add a value to an already-provisioned site's tag group (verified: `api.py` has no `update_host_tag_group`, and Checkmk's REST API generally does not expose tag-group mutation). A new value would require either a brand-new tag group (disruptive) or a manual WATO edit outside this project's REST-only convention. Reusing `NetworkDevice` sidesteps the gap entirely — same icon (`internet.svg`) already applies |

**Installation:**
```bash
cd dashboard-react
npm install vis-network vis-data
```

**Version verification:** confirmed via `npm view vis-network version` → `10.1.2` (published
2026-08-19, matches CONTEXT.md D-03's superseded-vendoring version number, so the npm-dependency
switch changes packaging only, not the underlying library version) and `npm view vis-data version`
→ `8.0.5`.

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `vis-network` | npm | ~7 yrs (first published 2019-07-16) | ~190K–610K/wk (source-dependent estimates; consistently high across Snyk/Socket/npmtrends) | `github.com/visjs/vis-network` | OK | Approved |
| `vis-data` | npm | mature (peer-locked to vis-network's `>=8.0.0` requirement; current 8.0.5) | high (transitive dependency of every vis-network install) | `github.com/visjs/vis-data` (monorepo sibling of vis-network) | OK | Approved |

No `postinstall` script found on `vis-network` (`npm view vis-network scripts.postinstall` returned
empty) — no supply-chain red flag.

**Packages removed due to slopcheck [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none.

## Architecture Patterns

### System Architecture Diagram

```text
                         ┌─────────────────────────────────────────┐
                         │            Browser (React SPA)            │
                         │                                           │
  MQTT-over-WS ─────────▶│  useAppStore.topology  ──▶  TopologyMap  │
  (read path,             │  (existing, unchanged)      component    │
   unchanged)             │                                  │        │
                         │                                  ▼        │
                         │                     vis-network Network   │
                         │                     + vis-data DataSet    │
                         │                     (nodes/edges, D-08    │
                         │                      circularImage icons) │
                         │                                  │        │
                         │                    ┌─────────────┴──────┐ │
                         │                    │  Edit-topology mode │ │
                         │                    │  toggle (D-02)      │ │
                         │                    │  addEdge/editEdge/  │ │
                         │                    │  deleteEdge (D-03)  │ │
                         │                    └─────────────┬──────┘ │
                         └──────────────────────────────────┼────────┘
                                                              │
                                     PUT /objects/host_config/{name}
                                     {attributes: {parents:[...],
                                       labels:{map_position:"x,y"}}}
                                     If-Match: <etag>          │
                                                              ▼
                         ┌─────────────────────────────────────────┐
                         │        Checkmk (REST API, port 5000)      │
                         │                                           │
                         │   Pending WATO change (NOT yet live)      │
                         │                    │                      │
                         │      explicit "Apply" batch action        │
                         │      POST .../activation_run/actions/     │
                         │           activate-changes/invoke         │
                         │                    │                      │
                         │                    ▼                      │
                         │        Live config (Livestatus reads      │
                         │        the now-activated `parents`)       │
                         └────────────────────┬──────────────────────┘
                                               │
                                    scripts/mqtt_poller.py
                                    (Livestatus GET hosts, parents
                                     column — unchanged, already reads
                                     it — see topology_nodes())
                                               │
                                               ▼
                                  lan/devices/topology (MQTT, retained)
                                               │
                                               ▼
                                   Every viewer's TopologyMap re-renders
                                   with the now-non-empty parents/edges
```

Two independent write paths converge on the same Checkmk config: the browser's direct REST write
(fast, single-editor path) and the existing poller's read-only Livestatus poll (the path every
*other* open dashboard tab sees the change through, once activated).

### Recommended Project Structure
```
dashboard-react/src/
├── components/
│   ├── TopologyMap.tsx          # new — wraps vis-network Network/DataSet, imperative useEffect mount
│   └── icons/device-types/      # new — actually place under src/assets/ per D-09, not components/
├── assets/
│   └── icons/device-types/      # new — internet.svg, api.svg, secured.svg, videocam.svg,
│                                 #   controls.svg, circle.svg — imported with Vite `?raw`
├── lib/
│   ├── checkmkWrite.ts           # new — minimal REST client: GET host (etag) → PUT attributes,
│   │                              #   mirrors api.py's update_host_attributes() shape exactly
│   ├── mapIcons.ts               # new — SVG string-replace recolor helper (D-08), keyed off the
│   │                              #   same device-type → filename map deviceTypeIcon() already uses
│   └── topologyLayout.ts         # new — initial grid-placement algorithm for parentless hosts (D-01)
└── routes/IndexRoute.tsx         # edited — MapPlaceholder swapped for TopologyMap in centreTop
```

### Pattern 1: Imperative vis-network mount in a React `useEffect`
**What:** `vis-network`'s `Network` class is not a React component — it takes a raw DOM container
ref and a data object, and manages its own re-renders internally via `DataSet` mutation, not React
re-renders.
**When to use:** Any time `vis-network` is embedded in a React tree — this is the only supported
integration pattern (no maintained official React wrapper for vis-network 10.x).
**Example:**
```tsx
// Source: vis-network official examples (https://visjs.github.io/vis-network/examples/) +
// Phase 11 D-09 (stabilize-then-freeze), applied together
const containerRef = useRef<HTMLDivElement>(null);
const networkRef = useRef<Network | null>(null);

useEffect(() => {
  if (!containerRef.current) return;
  const nodes = new DataSet(initialNodes);
  const edges = new DataSet(initialEdges);
  const network = new Network(containerRef.current, { nodes, edges }, options);
  network.once("stabilizationIterationsDone", () => {
    network.setOptions({ physics: false }); // D-09: freeze after first layout
  });
  networkRef.current = network;
  return () => network.destroy();
}, []); // mount once; subsequent MQTT updates go through DataSet.update(), not remount
```

### Pattern 2: `DataSet.update()` for merge-in-place (not full re-render)
**What:** `DataSet.update(items)` patches existing items by `id` (adds if new) without touching
unrelated nodes/edges or resetting camera/physics state.
**When to use:** Every incoming `lan/devices/topology` MQTT message and every device-status update
that changes a node's color — never call `network.setData()` on a per-message basis.
**Example:**
```ts
// Source: vis-data DataSet API (https://visjs.github.io/vis-data/data/dataset.html)
nodesDataSet.update(
  topologyPayload.devices.map((d) => ({ id: d.id, parents: d.parents, image: recoloredIconFor(d) })),
);
```

### Pattern 3: Checkmk PUT-with-ETag write, mirrored from `api.py`
**What:** Every Checkmk host-attribute mutation is GET (read current ETag) → PUT with
`If-Match: <etag>` and `{"attributes": {...}}` (update) or `{"update_attributes": {...}}` for
partial folder updates.
**When to use:** The browser's `addEdge`/`editEdge`/`deleteEdge` callbacks and the "Apply" batch
action, mirroring `update_host_attributes()` (`src/checkmk_wizard/api.py:214-223`) exactly — same
shape, just from `fetch()`/`httpx` in TypeScript rather than Python.
**Example:**
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

### Anti-Patterns to Avoid
- **Activating changes inside every `addEdge`/`editEdge`/`deleteEdge` callback:** each activation
  is an async background job (seconds, per `bootstrap_automation_user()`'s own 30-iteration poll
  loop) — firing one per edge drawn in a multi-edge editing session would serialize the UI or spam
  the site with overlapping activation runs. Batch behind a single explicit "Apply" action instead.
- **`network.setData()` on every MQTT message:** rebuilds the whole graph, resets pan/zoom/physics
  — Phase 11 D-09/11-RESEARCH.md's anti-pattern list already calls this out for the DOM equivalent;
  it applies identically here. Use `DataSet.update()`.
- **Reusing the wizard's `bootstrap_automation_user()`-created `admin`-role user for browser
  writes:** that user is full-power by design (`api.py:462`, `"roles": ["admin"]`) — embedding an
  admin secret in browser-shipped JS is a materially larger blast radius than the read-only
  `WS_USERNAME`/`WS_PASSWORD` precedent D-04 explicitly invokes. Use a purpose-cloned role.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Graph layout / force-directed positioning | Custom physics simulation | `vis-network`'s built-in physics engine (already locked, D-08/D-09) | Battle-tested; reinventing force-directed layout for a LAN topology map is pure waste |
| Drag-to-connect edge creation UI | Custom canvas mouse-event handling for edge drawing | `vis-network`'s manipulation toolbar (`addEdge`/`editEdge`/`deleteEdge`) | D-03 already locks this; the toolbar handles hit-testing, visual feedback, and cancel-on-Escape for free |
| SVG icon recoloring | A canvas `ctxRenderer` per-node custom draw function | String-replace fill + `circularImage`'s built-in `data:` URI image loading (D-08) | D-08 already rejected `ctxRenderer` for exactly this reason — simpler, no custom canvas draw code |
| Checkmk config activation polling | A custom exponential-backoff poll loop for activation completion | Mirror `bootstrap_automation_user()`'s own already-written polling loop (`api.py:508-532`, poll `is_running` via the activation's own `self` link) | This exact problem (Checkmk activation is an async background job, not a synchronous call) is already solved once in this codebase — port the same 30-iteration/0.3s pattern to TypeScript rather than re-deriving it |

**Key insight:** This phase's temptation to hand-roll is almost entirely on the Checkmk-REST side,
not the graph-rendering side — `vis-network` already covers every interaction CONTEXT.md asked for.
The actual net-new code is the browser-side Checkmk REST client (`checkmkWrite.ts`), and it should
be a near-verbatim TypeScript port of `api.py`'s already-proven GET-etag-PUT and
poll-activation-until-done patterns, not a fresh design.

## Common Pitfalls

### Pitfall 1: Custom host attributes cannot be *defined* over the REST API
**What goes wrong:** A plan that says "create a `map_position` custom host attribute via REST,
same as `tag_device_type`" will hit a 404/400 on first attempt, because no such creation endpoint
exists in Checkmk 2.3/2.4 CE — `POST .../domain-types/host_config/collections/all` and
`attributes`/`update_attributes` only let you **set values** for attributes the GUI has already
defined (community-confirmed: "In 2.3 there is no endpoint for the custom host attributes inside
the API").
**Why it happens:** `tag_device_type` (Phase 10's precedent) is a **tag group**, which DOES have a
REST creation endpoint (`create_host_tag_group()`) — it's easy to assume custom attributes work the
same way. They are a different Checkmk object type with a different (GUI-only) provisioning story.
**How to avoid:** Use host **labels** instead (`attributes.labels`, arbitrary key:value, zero
predefinition, same PUT call). See Standard Stack "Alternatives Considered."
**Warning signs:** A `create_host_tag_group`-style call for `map_position` failing with 400
("unknown attribute") even though the request shape looks identical to the tag-group precedent.

### Pitfall 2: Host tag groups cannot be *updated* over the REST API either
**What goes wrong:** A plan to add a new `device_type` value (e.g. `UnmanagedSwitch`) to the
already-provisioned tag group on the live site, expecting a PUT-style update like
`update_host_attributes()`.
**Why it happens:** `create_host_tag_group()` is genuinely create-only (verified: no
`update_host_tag_group` exists anywhere in `api.py`, and this matches the general Checkmk pattern
of definition-objects being GUI-only to mutate after creation).
**How to avoid:** Reuse the existing `NetworkDevice` device-type value for unmanaged switches
(already present in `device_types.json`, already has an icon — `internet.svg`). If a visually
distinct type is truly wanted later, that requires either a manual one-time WATO edit (outside this
project's REST-automation convention) or scrapping and recreating the tag group (destructive to
every already-tagged host) — flag as a real cost, not a config tweak, if raised during planning.
**Warning signs:** Any task description that says "add a new device type for switches" without
also naming who/how the tag-group's choice list gets mutated on an already-live site.

### Pitfall 3: A host-attribute PUT does not take effect until "Activate Changes" runs
**What goes wrong:** The browser draws an edge, PUTs `parents`, the UI shows success — but the
poller's next Livestatus poll still reports empty `parents`, and other open dashboard tabs never
see the edge. This looks like a bug in the write path when it's actually a missing activation step.
**Why it happens:** Every Checkmk WATO-domain REST write (hosts, folders, tag groups — all of them,
per this codebase's own Phase 7 `activate_changes()` precedent) is staged as a "pending change" and
only reaches Livestatus/the live monitoring config after activation. This is Checkmk core semantics,
not a quirk of this endpoint specifically.
**How to avoid:** After a batch of edit-mode writes, call `POST .../activation_run/actions/
activate-changes/invoke` with the site name and the pending-changes ETag (`get_pending_changes_etag()`
equivalent), and poll `is_running` before reporting success to the operator — port
`bootstrap_automation_user()`'s existing activation-polling code (`api.py:508-532`).
**Warning signs:** "It worked in the UI but the map on another tab/laptop never updates" — or the
poller's `parents` column staying empty despite a successful-looking 200 PUT.

### Pitfall 4: Checkmk custom roles cannot be created over the REST API
**What goes wrong:** Attempting to automate D-04's "narrowly-scoped role, not admin" entirely via
REST (analogous to how `bootstrap_automation_user()` automates user creation) — there is no
`user_role` creation endpoint; role cloning is a WATO GUI action (Setup > Users > Roles and
permissions > Clone).
**Why it happens:** Same class of gap as Pitfalls 1/2 — Checkmk's REST API is built around
*using* configured objects, not *defining new categories of configuration itself*.
**How to avoid:** Document a one-time manual WATO step (clone `user`, name it e.g.
`topology_editor`, enable only host-edit and activate-changes permissions) as a prerequisite the
operator runs once per deployment — analogous to how `CHECKMK_BASE_URL` in `config.ts` is already a
documented per-deployment manual edit. The **user** that gets that role, though, IS
REST-creatable, reusing `bootstrap_automation_user()`'s exact POST shape with `"roles":
["topology_editor"]` instead of `["admin"]`.
**Warning signs:** A task that says "wizard creates the scoped role via REST" — that's the wrong
half of the problem to automate; only the *user* assignment is automatable, not the *role*
definition.

### Pitfall 5: `circularImage` needs an actual reachable image URL/data-URI — a bare SVG string is not enough
**What goes wrong:** Passing raw SVG markup (the string vs `?raw` import) directly as the `image`
option renders a broken-image icon.
**Why it happens:** vis-network's `image`/`circularImage` shapes expect a URL (http(s), relative
path, or `data:` URI) that resolves to a raster-loadable image source — an `<img>`-style contract,
not raw markup.
**How to avoid:** Wrap the recolored SVG string as `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
(or base64) before assigning to `image` — this is what D-08 already specifies ("embed as a
`data:image/svg+xml` URI"), just make sure the encoding step isn't skipped.
**Warning signs:** Nodes render with vis-network's default `brokenImage` fallback or a blank circle.

## Code Examples

### Recoloring a vendored SVG and building the data URI (D-08/D-09)
```ts
// Source: pattern derived from D-08's spec; mirrors deviceTypeIcon()'s existing
// device_type -> filename map in dashboard-react/src/lib/display.ts
import internetSvg from "../assets/icons/device-types/internet.svg?raw";

const DEVICE_TYPE_SVG: Record<string, string> = {
  other: circleSvg,
  "E-link": apiSvg,
  ACS: securedSvg,
  Multimedia: videocamSvg,
  NetworkDevice: internetSvg,
  GroupController: controlsSvg,
};

// State-color hex values mirror kone-design-system's own tokens (design-system/src/tokens.css):
// --green-500: #22c55e (success/OK), --orange-500: #f97316 (warning/WARN),
// --red-500: #e5252a (danger/CRIT/DOWN/UNREACH). These are resolved at build/runtime from the
// same CSS custom properties the Badge component reads, not re-hardcoded as a second source of
// truth -- confirm exact token names against stateMapping.ts's BadgeColor set during planning.
function recoloredDataUri(svgMarkup: string, hexColor: string): string {
  const recolored = svgMarkup.replace(/fill="#141414"/g, `fill="${hexColor}"`);
  return `data:image/svg+xml;utf8,${encodeURIComponent(recolored)}`;
}
```

### Initial grid placement for parentless hosts (D-01, Claude's Discretion)
```ts
// Source: no vis-network precedent needed -- this is plain layout math. A simple row-major
// grid keyed by array index is sufficient; vis-network's physics engine (D-09) settles nodes
// from there on first stabilization, so the grid only needs to avoid exact-overlap starting
// positions, not produce a "good" final layout.
const COLS = Math.ceil(Math.sqrt(devices.length));
const SPACING = 150;
const positions = devices.map((d, i) => ({
  id: d.id,
  x: (i % COLS) * SPACING,
  y: Math.floor(i / COLS) * SPACING,
}));
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| ROADMAP.md's original plan: vendor `vis-network` 10.1.2 as a standalone UMD build into `dashboard/js/vendor/` | `vis-network`/`vis-data` as npm deps in `dashboard-react/` | Phase 11.1 (2026-09-21), reaffirmed by this phase's CONTEXT.md Scope Revision | Same library version either way (10.1.2 is still current) — only the packaging mechanism changed, consistent with the whole dashboard's Vite/React rewrite |
| ROADMAP.md's original plan: wizard-CLI parent/child prompts (Phase 4/5 questionary flow) | Dashboard-embedded interactive topology editor, writing directly to Checkmk REST from the browser | This phase's discuss-phase session, 2026-09-23 (D-01) | The wizard's Phase 4/5 code is entirely unchanged by this phase — all new code lives in `dashboard-react/` |
| Dashboard as MQTT-only, zero write credentials in the browser (Phase 11 D-01's explicit safety argument) | Dashboard now embeds a write-capable Checkmk credential for this one feature | This phase's Scope Revision (D-04) | A genuine security-posture change, not a detail — flagged explicitly in Security Domain below |

**Deprecated/outdated:**
- The `dashboard/` (pre-React, static HTML/CSS/JS) directory's vendored-icon convention is
  superseded by `dashboard-react/src/assets/icons/device-types/` + Vite `?raw` imports (D-09)
  — do not add new icon files to the old `dashboard/icons/` path.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `tag_agent`/`tag_snmp_ds`/`tag_address_family` are the exact REST attribute keys, and `no-agent`/`no-snmp`/`no-ip` the exact values, that produce a zero-service unmanaged-switch host on Checkmk 2.4.0p35 CE | Common Pitfalls / Standard Stack Alternatives | If the exact key/value strings differ, the switch host onboarding step 400s or (worse) silently creates a host that still gets a PING check, reintroducing the WARN/CRIT noise D-06 exists to prevent. **Must be live-verified against the real site before trusting**, per this codebase's own established discipline (same treatment `tag_device_type` got in Phase 10) |
| A2 | Host **labels** (`attributes.labels`) are settable via the same `update_host_attributes()` PUT shape as tags/aliases, with no predefinition required, on Checkmk 2.4.0p35 CE specifically | Summary / Standard Stack Alternatives / Pitfall 1 | If labels behave differently than documented (e.g. some Checkmk versions had "reading and writing host labels via the API has some issues" per one forum thread found in research), `map_position` persistence needs a fallback — likely the MQTT-payload-carries-position alternative CONTEXT.md's Deferred section already names as an open option |
| A3 | The exact permission name for "activate changes" (used to scope the `topology_editor` role) — research found no authoritative confirmation of the literal permission string (candidate: `wato.activate`, based on Checkmk's `wato.*` permission-namespace convention, not directly confirmed) | Common Pitfalls Pitfall 4 / Code Examples | If the guessed permission name is wrong, the scoped role either can't activate its own changes (breaking the batch-Apply flow) or the operator over-grants during the manual role-clone step. Verify by enumerating the built-in `user`/`admin` role's permission list via `GET /objects/user_role/{role_id}` against the live site during planning/execution |
| A4 | No REST endpoint exists in Checkmk 2.4 CE to create custom host attribute *definitions* or new host *tag-group values* on an already-provisioned group, or to create new *roles* — based on 2026-09-23 WebSearch of Checkmk community forum threads (2.0–2.3 era) and docs, not a direct read of the 2.4.0p35 OpenAPI spec | Summary (all three numbered findings) / Common Pitfalls 1/2/4 | This is the single highest-leverage claim in this research — if Checkmk 2.4 quietly added any of these three endpoints, the recommended workarounds (labels instead of custom attributes, reusing `NetworkDevice`, manual role-clone) become unnecessary complexity. **Verify first** by fetching the live site's own `openapi-doc.yaml` (the same source `bootstrap_automation_user()`'s docstring already cites as authoritative over generic docs) and grepping for `host_attribute`, `user_role`, and tag-group PUT/PATCH operations, before committing to the workarounds in a plan |

**If this table is empty:** N/A — see rows above. Every numbered finding in this research's Summary
traces to one of these four assumptions; none should be treated as locked fact until the A4 live
check (and A1/A3's narrower live checks) happen.

## Open Questions

1. **(RESOLVED by plan 13-01's live probe)** Does the live 2.4.0p35 CE site's `openapi-doc.yaml` actually lack `host_attribute`/`user_role`
   creation endpoints, or did WebSearch only surface older (2.0–2.3) forum threads?
   - What we know: Multiple community forum threads (2.0.0p5 through 2.3-era) consistently report
     no REST endpoint for defining custom host attributes or roles; no contradicting source found.
   - What's unclear: Whether 2.4 changed this — Checkmk's REST API has grown steadily across
     minor versions (e.g. Werk #16099 changed `create_host` attribute-echo behavior between
     versions), so a version-specific gap is plausible.
   - Recommendation: First task of implementation (not planning) should be a live probe —
     `GET {base}/check_mk/api/1.0/openapi-doc.yaml` and grep — exactly the technique
     `bootstrap_automation_user()`'s own docstring says was used to verify ITS undocumented shape.
     If a capability was added, the labels/`NetworkDevice`/manual-role workarounds can be dropped
     in favor of the more literal D-07/D-09/D-04 wording.

2. **(RESOLVED — YES, implemented conditionally in plan 13-04, gated on 13-01's V-LABELS-IN-COLLECTION verdict)** Should `map_position` also ride the poller's MQTT `lan/devices/topology` payload, or stay a
   browser-side direct-Checkmk-read concern? (Explicitly left open by CONTEXT.md's Deferred
   section.)
   - What we know: `topology_nodes()`/`publish_topology()` in `scripts/mqtt_poller.py` already
     read every host's Livestatus-exposed columns each cycle and could trivially add a `labels`
     (or `map_position` specifically) column to `REQUIRED_HOST_COLUMNS`'s sibling
     `OPTIONAL_HOST_COLUMNS` list (same defensive-probe pattern already used for `parents`/`tags`).
   - What's unclear: Whether Livestatus exposes host **labels** as a queryable column at all (this
     research did not verify — `tags` is confirmed queryable per Phase 10's `extract_device_type()`
     precedent, but labels are a structurally different Checkmk object and may or may not appear
     in the same `GET hosts` column set).
   - Recommendation: If Livestatus does expose labels, adding `map_position` to the poller payload
     is low-cost and gives every viewer consistent positions for free (the D-05/D-09 grouping-
     toggle precedent already establishes "derive display state from the poller's payload, not a
     second per-browser fetch" as this codebase's preferred pattern). If it does not, the browser
     must read positions directly from Checkmk REST (an extra fetch per page load, no live-update
     path for position drift between browsers) — this is a real architecture fork, not a minor
     detail, and should be resolved with a quick live Livestatus column probe (mirroring
     `mqtt_poller.py --probe`'s existing capability, referenced at line 1835) before planning locks
     the data-flow diagram.

3. **(RESOLVED — planner minted DASH-12, DASH-13, PLR-13 in REQUIREMENTS.md)** REQUIREMENTS.md has no requirement ID for the write-back/edit-mode capability (CONTEXT.md
   already flags this; restated here because it blocks clean traceability in the plan). Not
   resolved by this research agent — flagged for whoever runs requirements definition.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|--------------|-----------|---------|----------|
| Node.js | `dashboard-react` build/dev tooling (Vite, tsc, vitest) | Yes (this research sandbox) | v24.20.0 | — |
| npm | Installing `vis-network`/`vis-data`, running `npm run build` | Yes | 11.19.0 | — |
| A running Checkmk site reachable at `CHECKMK_BASE_URL` | Live-verifying Assumptions A1-A4 (the labels shape, no-ip/no-agent tag values, activation permission name, openapi-doc.yaml probe); manual end-to-end testing of the edit-mode write path | **No** — not reachable from this research sandbox (`curl` to `localhost:8080` timed out; no `docker`/`podman` present to bring up `deploy/compose.yaml`'s stack) | — | None for the live-verification work itself — those checks require access to the actual deployment (or a disposable Checkmk container spun up via `deploy/compose.yaml`, per the project's own Podman setup doc). This is not a phase-blocking gap for *planning* (the plan can name the exact live-verification steps as tasks), but it IS a blocking gap for *closing* Assumptions A1-A4 before/during execution — flag clearly in the plan as a required live-environment step, not something this research agent could complete itself |
| `uvx`/`slopcheck` | Package legitimacy audit (already run, see above) | Yes | slopcheck via `uvx` | — |

**Missing dependencies with no fallback:**
- A reachable live Checkmk 2.4.0p35 CE site — required to close every item in the Assumptions Log
  before this phase's edit-mode write path can be trusted. Execution (not planning) must run these
  probes against the real deployment.

**Missing dependencies with fallback:**
- None — the one missing dependency (a live Checkmk site) has no viable substitute for the
  live-verification work; a plan should schedule those checks as explicit early tasks against the
  real deployment rather than skipping them.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | Yes | Checkmk's own Bearer-token automation-user auth (`Authorization: Bearer <user> <secret>`) — no new auth scheme introduced |
| V3 Session Management | No | Stateless Bearer-token REST calls, no session/cookie use in this write path (the GUI-cookie login flow `_gui_login()` uses is wizard-only, not reused here) |
| V4 Access Control | **Yes — the core risk of this phase** | A purpose-scoped Checkmk role (Pitfall 4), NOT the wizard's admin-role automation user, must back the browser-embedded credential. This is the single most important control in this phase, since it directly bounds what a leaked/exfiltrated browser secret can do |
| V5 Input Validation | Yes | `parents` values written by the edit-mode callback must be validated as existing host names before PUT (Checkmk will reject a nonexistent parent, but validating client-side avoids a confusing 400 mid-interaction); `map_position` label value should be validated as `^-?\d+,-?\d+$` or similar before writing, not trusted as arbitrary operator-typed text |
| V6 Cryptography | No new requirement | REST calls run over the same `http://` LAN-trusted transport already used by `CHECKMK_BASE_URL`/`WS_*` — no new crypto surface; this project's existing trusted-LAN posture (per D-04's own justification) is unchanged, not newly introduced by this phase |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| Committed write-capable credential is exfiltratable from any browser DevTools session on the LAN (same exposure class as `WS_USERNAME`/`WS_PASSWORD`, but with WRITE power instead of read-only) | Elevation of Privilege | Scope the role to the minimum permission set (host-edit + activate-changes only — no user management, no global settings, no folder deletion); this is the entire point of Pitfall 4's role-clone recommendation, not a nice-to-have |
| A malicious or buggy browser tab could draw arbitrary edges/positions and activate them, corrupting the live topology for every viewer | Tampering | D-02's edit-mode toggle (manipulation only active when explicitly enabled) already mitigates the "stray drag on a kiosk display" case named in CONTEXT.md; the same toggle also bounds this threat — a tab left in edit mode is the residual risk, worth a plan task considering an idle-timeout auto-exit from edit mode |
| Unvalidated `map_position`/label text written to Checkmk could later be read back and rendered without escaping elsewhere (e.g. if a future admin view lists label values) | Tampering / Information Disclosure (low severity here) | Validate the position format client-side before PUT (V5 above); Checkmk's own label-value handling on the server side is out of this project's control but labels are plain key:value strings, not executable |

## Sources

### Primary (HIGH confidence)
- `src/checkmk_wizard/api.py` (read in full this session) — `update_host_attributes()`,
  `create_host()`, `create_host_tag_group()`, `bootstrap_automation_user()`,
  `bootstrap_agent_registration_secret()`, `_request()` choke point, activation-polling pattern
- `src/checkmk_wizard/wizard.py` lines 670-770 — `_ensure_device_type_tag_group()`,
  `_device_type_and_alias_attributes()`, `_load_device_types()` (device_types.json drift caveat)
- `dashboard-react/src/lib/display.ts`, `stateMapping.ts`, `types.ts` — existing `deviceTypeIcon`
  map, `BadgeSpec`/state-color semantics, `TopologyPayload` shape
- `dashboard-react/src/store/useAppStore.ts`, `routes/IndexRoute.tsx`,
  `components/MapPlaceholder.tsx` — exact mount point and existing topology state slot
- `scripts/mqtt_poller.py` lines 440-490, 1150-1190 — `topology_nodes()`, `topology_signature()`,
  `publish_topology()` (confirmed: no poller code change is required for the read half of DASH-07)
- `design-system/src/tokens.css` — exact hex values behind `success`/`warning`/`danger` tokens
  (`--green-500: #22c55e`, `--orange-500: #f97316`, `--red-500: #e5252a`)
- `deploy/compose.yaml` — confirmed `checkmk` service's `8080:5000` LAN-published port backing
  `CHECKMK_BASE_URL`
- npm registry (`npm view vis-network`/`vis-data version`, `dist-tags`, `scripts.postinstall`,
  `repository.url`, `time.created`) — package legitimacy and version facts
- `uvx slopcheck scan --pkg npm vis-network` / `vis-data` — both `[OK]`, zero flags

### Secondary (MEDIUM confidence)
- WebSearch cross-verified vis-network manipulation API (`addEdge`/`editEdge`/`deleteEdge`
  signatures) against `visjs.github.io/vis-network/docs/network/manipulation.html`
- WebSearch cross-verified `circularImage` shape + `image` data-URI usage against
  `visjs.github.io/vis-network/examples/network/nodeStyles/circularImages.html`
- WebSearch cross-verified `stabilizationIterationsDone` → `setOptions({physics: false})` pattern
  against vis-network community/docs sources (confirms, does not contradict, Phase 11 D-09's
  already-locked design)
- WebSearch cross-verified Checkmk host labels as free-form, no-predefinition key:value pairs
  against `docs.checkmk.com/latest/en/labels.html` ("Labels do not have to be predefined
  anywhere... Everything is free-form")
- WebSearch cross-verified "No IP" host attribute behavior ("host check of these hosts will
  always report UP by default") against `docs.checkmk.com/latest/en/hosts_setup.html` and
  Werk #5945

### Tertiary (LOW confidence — flagged in Assumptions Log for live verification)
- Community forum threads (2.0.0p5–2.3-era) reporting no REST endpoint exists for custom
  host-attribute *definitions* or role creation — not cross-checked against the live 2.4.0p35
  site's own `openapi-doc.yaml` (Open Question 1)
- Exact `tag_agent`/`tag_snmp_ds`/`tag_address_family` REST key/value strings for a zero-service
  host (Assumption A1) — inferred from forum examples and training knowledge of Checkmk's built-in
  tag groups, not confirmed against the live site
- Candidate `wato.activate`-style permission name for the scoped role (Assumption A3) — not
  confirmed by any source found

## Metadata

**Confidence breakdown:**
- Standard stack (vis-network/vis-data versions, legitimacy): HIGH — npm registry + slopcheck are
  direct tool verification, not inference
- Architecture (write path, activation requirement, labels-vs-custom-attribute): MEDIUM — the
  *pattern* (PUT-with-ETag, pending-change/activation semantics) is HIGH confidence (directly
  read from this codebase's own working code), but the *specific capability gaps* (no REST
  creation of custom attributes/tag-group values/roles) are MEDIUM, sourced from community forum
  threads rather than a direct read of the live 2.4.0p35 OpenAPI spec
- Pitfalls: MEDIUM-HIGH — Pitfalls 1/2/4 (REST capability gaps) are the research's most important
  findings but carry the same MEDIUM sourcing caveat as Architecture above; Pitfall 3 (activation
  requirement) is HIGH, directly evidenced by this codebase's own `activate_changes()` design

**Research date:** 2026-09-23
**Valid until:** 30 days for the npm-package facts (stable ecosystem); the Checkmk-capability
findings (Assumptions A1-A4) should be treated as valid only until the live-verification probes
in Open Question 1 run — do not let this research's 30-day window imply those are safe to skip.
