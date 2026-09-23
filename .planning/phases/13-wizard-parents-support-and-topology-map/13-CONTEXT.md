# Phase 13: Wizard Parents Support and Topology Map - Context

**Gathered:** 2026-09-23
**Status:** Ready for planning — **ROADMAP.md Phase 13 scope bullets 1 and 3 are superseded, see Scope Revision**

<domain>
## Phase Boundary

Checkmk's `parents` host attribute gets populated, and the dashboard's map placeholder
(`MapPlaceholder.tsx`) becomes a real, live vis-network topology map — so DASH-07 renders
real monitoring data instead of disconnected dots.

**Not in this phase** (explicitly deferred during discussion):
- Per-tower dashboard tabs and sub-location rectangle grouping — belongs to Phase 15
  (Location Hierarchy for Hosts and Dashboard Tower Tabs), which is parked/not-urgent. This
  phase must not block that later work (see Deferred and D-11 below).
- Folder/device_type grouping overlays on the map itself (D-05's toggle keeps driving only
  the tree/stats strip, unchanged).

</domain>

<scope_revision>
## Scope Revision — supersedes ROADMAP.md Phase 13 bullets 1 and 3

ROADMAP.md's Phase 13 section (written before this discussion) says:
1. "Teach the wizard to set Checkmk's `parents` host attribute over the REST API, the same
   way Phase 10 sets `tag_device_type`" — **superseded**. The operator explicitly rejected a
   wizard-CLI-prompt flow as not UI-friendly. Parent/child relationships are now captured
   **in the dashboard itself**, via an interactive edit mode on the topology map, not via
   wizard questionary prompts. The wizard's Phase 4/5 classification/onboarding flow is
   **unchanged** by this phase.
3. "Vendor `vis-network` 10.1.2 standalone UMD into `dashboard/js/vendor/`" — **superseded**.
   That instruction predates the Phase 11.1 rewrite to a Vite/npm React SPA. vis-network is
   an **npm dependency** (`npm install vis-network`) wrapped in a thin React component, the
   same way `mqtt` is already a plain npm dep — not vendored.

Everything else in ROADMAP's scope list (bullets 2, 4, 5 — drop the map into `index.html`
replacing `MapPlaceholder`, apply D-08/D-09, inherit D-05/D-06/D-11/D-12/D-15) still holds.

**This is an architecture shift, not just an implementation detail**: the dashboard has been
read-only/MQTT-only since Phase 11 (D-01's explicit safety argument — no write credentials
in the browser). This phase deliberately reverses that for this one feature: the browser
calls Checkmk's REST API **directly** to write `parents` and a new `map_position` custom
host attribute. Checkmk's REST/GUI port is already LAN-published (`8080:5000` in
`deploy/compose.yaml`), and `CHECKMK_BASE_URL` already exists in
`dashboard-react/src/lib/config.ts` (currently unused — gated behind
`isCheckmkLinkConfigured()`) for exactly this kind of direct browser-to-Checkmk reach.

</scope_revision>

<decisions>
## Implementation Decisions

### Parent/child relationship capture (replaces wizard-CLI approach)
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

### Unmanaged (non-Checkmk-agent) switches
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

### Position persistence
- **D-07:** A real host's map position is stored as a new Checkmk **custom host attribute**
  (e.g. `map_position`, holding x/y), written via the same REST path as `parents`. This
  reuses Checkmk's own config storage — which already lives on the `checkmk_data` volume per
  `deploy/compose.yaml` — so "stored in the container volume" is satisfied with no new
  backend, no new volume mount, and no broker/ACL changes. Consistent with D-05: since
  unmanaged switches are now real hosts too, they use the identical `map_position` attribute
  — no separate sentinel-host/folder-blob mechanism needed (this supersedes an
  intermediate idea floated mid-discussion of a shared JSON blob on a sentinel host or the
  root folder; D-05/D-06 made that unnecessary).

### Rendering: node shape, icons, coloring
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

### Map interaction and scope boundaries
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

### Carried forward from Phase 11 (apply as-is, don't re-derive)
- **D-08 (Phase 11, renumbered context — synthetic group-root):** superseded by this phase's
  D-05/D-06 — unmanaged switches are now real hosts with real `parents` edges, not synthetic
  group-root nodes. The original Phase 11 rationale for group-roots (parentless hosts need
  *some* visual anchor) no longer applies the same way since every host that has no drawn
  parent simply sits in the initial grid, undrawn-to, rather than needing a synthetic root.
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

</decisions>

<specifics>
## Specific Ideas

- "I think doing this on the wizard is not UI friendly. I have a better idea: network map in
  dashboard with edit mode... User will draw lines between hosts to define relations, and
  eventually add unmanaged LAN switch if there's no managed switches as hosts." — the pivot
  that reshaped this entire phase away from ROADMAP's original wizard-CLI plan.
- "it can be a host in checkmk topology, but it shouldn't be monitored in terms of ping or
  others, as it's not pingable. So I don't want to see warns / critic because of this" — the
  exact constraint behind D-06.
- "can this layout be stored in the container volume?" — resolved as D-07 (Checkmk's own
  custom host attribute, which already lives on the `checkmk_data` volume — no new volume
  needed).
- Tower tabs / sub-location rectangles: "prepare the map for this" even though the tagging
  and tabs themselves are Phase 15 work — see D-11's "don't design for one global unfiltered
  view" note.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 13's own prior scoping
- `.planning/ROADMAP.md` §"Phase 13: Wizard Parents Support and Topology Map" — the original
  scope list; bullets 1 and 3 are superseded by this CONTEXT.md's Scope Revision, bullets 2/4/5
  still hold. Also carries the "Open question for this phase's discussion" about layout
  persistence — resolved here as D-07.
- `.planning/REQUIREMENTS.md` — DASH-07 (the only requirement ID currently mapped to this
  phase) and its traceability note explaining the DASH-01 split. ROADMAP.md itself notes
  "Additional requirement IDs covering the wizard's parents support still need defining" —
  given the scope pivot to a dashboard-edit-mode approach, this now needs REQUIREMENTS.md
  amendments for the write-back/edit-mode capability, not wizard-CLI requirements. Not done
  in this discussion — flag for whoever runs requirements definition before/during planning.
- `.planning/phases/11-live-dashboard/11-CONTEXT.md` §Deferred "To Phase 13" and
  `11-DISCUSSION-LOG.md` — original D-08 (synthetic group-root, now superseded by this
  phase's D-05/D-06) and D-09 (stabilize-then-freeze physics, still locked) rationale.
- `.planning/phases/11-live-dashboard/11-UI-SPEC.md` §"Iconography" and §"Device-Type
  Iconography" — the existing vendored-KONE-SVG icon convention this phase's D-09 extends to
  map nodes (25 hand-picked SVGs, `mask-image` for DOM elements elsewhere in the app; this
  phase's data-URI technique is the canvas-compatible equivalent).
- `.planning/STATE.md` §"Roadmap Evolution" — Phase 15 entry (Location Hierarchy for Hosts
  and Dashboard Tower Tabs), parked/not-urgent, referenced by D-11's forward-compatibility
  note.

### Checkmk REST API
- `src/checkmk_wizard/api.py` — `update_host_attributes()` (line 214, PUT with If-Match
  ETag), `create_host()` (line 193), `create_host_tag_group()` (line 334, the closest
  existing precedent for a new custom-attribute-shaped REST call). D-04/D-05/D-06/D-07's
  write path reuses this exact PUT-with-ETag pattern, just called from the browser instead
  of the wizard's Python client.
- `src/checkmk_wizard/wizard.py` — `_ensure_device_type_tag_group()` (line 727) and
  `bootstrap_automation_user()` in `api.py` (line 386) — precedent for how a narrowly-scoped
  vs. full-power automation credential distinction already exists in this codebase; D-04's
  flagged credential-scoping question should follow this precedent, not reuse the wizard's
  own bootstrap user.

### Dashboard (React)
- `dashboard-react/src/components/MapPlaceholder.tsx` — the exact slot this phase's map
  replaces (D-27's reserved geometry, sized by container not fixed pixels).
- `dashboard-react/src/routes/IndexRoute.tsx` — where `MapPlaceholder` is currently mounted
  (`centreTop`, below `StatsStrip`).
- `dashboard-react/src/store/useAppStore.ts` — `topology` state slot already exists and is
  already populated from `lan/devices/topology` (line ~200); this phase is the first
  consumer that actually renders it.
- `dashboard-react/src/lib/types.ts` — `TopologyPayload` interface (line 80) — currently a
  loose `{devices?: unknown[]; ...}` shape; will need tightening once the map consumes it.
- `dashboard-react/src/lib/config.ts` — `CHECKMK_BASE_URL`, `isCheckmkLinkConfigured()`, and
  the committed-disposable-credential convention (`WS_USERNAME`/`WS_PASSWORD`) that D-04's
  write-credential decision follows.
- `dashboard-react/package.json` — confirms npm/Vite-based deps (`mqtt`, `kone-design-system`
  as a `file:` tarball dep) — the precedent D-08's "npm dependency, not vendored UMD" choice
  follows.
- `web_assets/kone-design-system-main/packages/kone-ds-assets/icons/` — source of the
  vendored SVG set D-09 points at (25 hand-picked icons, already copied once before into
  `./dashboard/icons/` for the now-superseded static-HTML dashboard).

### Poller (already ships what this phase needs, unmodified)
- `scripts/mqtt_poller.py` — `REQUIRED_HOST_COLUMNS` includes `parents` (line 179, already
  live-verified present on the target site); `DeviceSnapshot.parents` (line 358);
  `publish_topology()` and `topology_signature()` (lines ~460-489) already build and
  change-detect the exact `{id, parents, device_type, folder, alias}` node shape the map
  will consume. **No poller changes are needed for this phase** — it already queries and
  publishes `parents`; the gap this phase closes is that `parents` is empty in Checkmk
  because nothing has ever written to it.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `update_host_attributes()` / `create_host()` in `api.py` — the PUT/POST-with-attributes
  pattern the browser-side write calls should mirror (same body shape: `{"attributes": {...}}`
  with an `If-Match` ETag on update).
- `topology_signature()` / `publish_topology()` in `scripts/mqtt_poller.py` — already
  produces the live node/edge data the map renders; nothing to change here.
- Phase 11.1's `useGroupingPrefs` / localStorage-guarded-storage pattern — precedent for any
  small per-browser UI preference this phase might still want (e.g. "edit mode was last
  left on"), even though D-07 puts position data in Checkmk, not localStorage.

### Established Patterns
- Disposable, plainly-committed per-deployment credentials in `lib/config.ts`
  (`WS_USERNAME`/`WS_PASSWORD`) — the precedent D-04's embedded write credential follows.
- Live-verification discipline: every REST/Livestatus shape this codebase depends on gets
  verified against a real 2.4.0p35 CE site before being trusted (`tag_device_type`'s shape in
  Phase 10, `staleness`/`parents` columns in the 2026-09-08/09-11 probes). D-04's credential
  scope and D-06's no-IP/no-agent host shape both need the same treatment before/during
  planning.

### Integration Points
- `IndexRoute.tsx`'s `centreTop` slot — where `MapPlaceholder` is swapped for the real map.
- `useAppStore.ts`'s existing `topology` state — already wired to `lan/devices/topology`,
  ready to feed the map's initial node list (positions/edges then augmented by the
  browser's own direct Checkmk REST reads for `parents`/`map_position`, since MQTT's
  topology payload doesn't currently carry `map_position`— see Claude's Discretion on
  whether to add it to the poller's payload or have the browser read it directly from
  Checkmk. **Not decided in this discussion — flag for planning.**)

</code_context>

<deferred>
## Deferred Ideas

### To Phase 15 (parked, not-urgent — per STATE.md Roadmap Evolution)
- Per-tower dashboard tabs, filtering the map to one physical tower at a time.
- Sub-location rectangle grouping on the map (e.g. a visible "motor room xyz" / "lobby A"
  boundary around the hosts in that sub-location).
- The new Checkmk tag group capturing tower + sub-location that both of the above depend on.
- This phase (13) should prepare for these (D-11) but not implement any of them.

### Open, not resolved in this discussion — flag for planning/research
- Whether `map_position` (and any per-host edit-mode metadata) gets added to the poller's
  MQTT `lan/devices/topology` payload (so all viewers see the same positions without each
  browser needing its own direct Checkmk read), or stays a browser-side direct-read-from-
  Checkmk concern only. Affects `scripts/mqtt_poller.py` — the one place this phase might
  still need to touch, if research concludes MQTT should carry it.
- Exact Checkmk role/permission scope for the write-capable browser credential (D-04).
- Exact no-IP/no-agent host attribute shape for unmanaged switches (D-06).
- REQUIREMENTS.md amendment covering the dashboard-edit-mode write-back capability (the
  wizard-CLI requirement IDs ROADMAP.md anticipated no longer apply as scoped).

</deferred>

---

*Phase: 13-wizard-parents-support-and-topology-map*
*Context gathered: 2026-09-23*
