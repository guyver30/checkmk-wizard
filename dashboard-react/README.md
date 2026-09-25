# dashboard-react

## 1. What this is, and what it is not yet

A React + TypeScript + Tailwind single-page app that replaces the vanilla `dashboard/` per
D-40/D-42 — same live, at-a-glance topology/status picture, built against the company's own
`kone-design-system` component library instead of hand-rolled markup and CSS.

`dashboard/` **keeps running and remains the deployed dashboard** (host port 8090, see
`deploy/compose.yaml`) until this app reaches feature parity. This is a parity-then-cutover
migration, not a big-bang replace — nothing under `dashboard/` was edited by this phase, and
`dashboard-react/` is not yet wired into the compose stack. See the cutover checklist (§7).

## 2. Build precondition — build `design-system` first

`design-system/dist/` is gitignored, so a fresh checkout has no build output. Before installing
this app's own dependencies, build and pack the design system:

```bash
npm --prefix design-system ci
npm --prefix design-system run build
npm --prefix design-system pack --pack-destination design-system
```

Then install this app's dependencies:

```bash
npm --prefix dashboard-react ci
```

Skipping the design-system build first produces `kone-design-system` import errors that
**only reproduce on a clean checkout** — the previous developer's local `dist/` was still on
disk, so nothing forced the build step to be run in order.

## 3. Commands

```bash
npm --prefix dashboard-react run dev        # start the Vite dev server
npm --prefix dashboard-react run build      # typecheck + production build -> dist/
npm --prefix dashboard-react test           # run the test suite
npm --prefix dashboard-react run typecheck  # tsc -b --noEmit only
```

## 4. Configuration — `src/lib/config.ts`

This is the one file an operator edits per deployment. Read it before deploying.

**`CHECKMK_BASE_URL`** ships as the literal placeholder `http://<HOST_IP>:8080`. The "View in
Checkmk" deep link disables itself while this placeholder is present (same rule as the vanilla
dashboard's D-20) — the visible symptom of forgetting to edit it is a link that merely **looks
broken**, not an error message. The browser cannot derive this value itself: the poller
(`scripts/mqtt_poller.py`) reaches Checkmk over the container-internal name `checkmk:5000`,
which no LAN browser can resolve, so a human-facing URL has to be supplied separately.

The remaining constants in `src/lib/config.ts`:

- `WS_PORT` — the Mosquitto WebSockets listener port.
- `WS_USERNAME` / `WS_PASSWORD` — deliberately-committed disposable read-only broker
  credentials (same convention as `dashboard/js/config.js`, `cmkadmin`/`cmkadmin`, and
  `deploy/mosquitto.passwd`). Rotate them before exposing the dashboard beyond a trusted LAN.
- `POLL_INTERVAL_SECONDS` / `STALENESS_FACTOR` — must be kept in step with
  `scripts/mqtt_poller.py`'s own defaults; a mismatch would make staleness flip at the wrong
  time.
- `HISTORY_MAX_ENTRIES` — mirrors the poller's per-device history bound (20); it does not
  bound the global event feed (see "Event history" below).
- `CHECKMK_SITE` — the Checkmk site name used to build deep links.
- `TOPOLOGY_EDITOR_SECRET` — ships as the literal placeholder `<TOPOLOGY_EDITOR_SECRET>`.
  Unlike `WS_USERNAME`/`WS_PASSWORD`, this credential is WRITE-capable: it edits/adds
  Checkmk hosts and activates its own pending changes (map edit mode, 13-06/13-07). Paste in
  the secret printed once by `scripts/provision_topology_editor.py`; edit-mode writes stay
  disabled (`isTopologyEditingConfigured()` returns `false`) until you do.
- `CHECKMK_REST_ORIGIN` — the same-origin `/checkmk-api` path prefix the browser calls
  instead of `CHECKMK_BASE_URL` directly, because Checkmk does not answer CORS preflights
  (13-01 VERDICT V-CORS). `vite.config.ts`'s `server.proxy`/`preview.proxy` forward it to
  Checkmk; set `CHECKMK_PROXY_TARGET` if Checkmk isn't reachable at `http://localhost:8080`
  from wherever `vite dev`/`vite preview` runs.
- `TOPOLOGY_EDITOR_USER` — the fixed username (`topology_editor`) of the scoped write
  credential `scripts/provision_topology_editor.py` provisions. Not normally edited; listed
  here because it pairs with `TOPOLOGY_EDITOR_SECRET` above in every `checkmkWrite.ts` call.

## 5. Topology map and editing

The centre pane's primary view is a live [vis-network](https://visjs.github.io/vis-network/)
map of the monitored fleet (DASH-07), replacing the earlier stats-strip-only placeholder.

**Read-only behaviour (default state):**

- Node icons are coloured by the same live state (`OK`/`WARN`/`CRIT`/`UNKNOWN`/`DOWN`) as the
  rest of the dashboard, updated in place as MQTT messages arrive.
- Edges are drawn parent→child from each host's Checkmk `parents` attribute.
- Clicking a node opens its detail page (`/details?id=...`).
- A saved position (`map_position`, a Checkmk host label written by edit mode) is applied only
  the first time a node appears on the map; positions are never re-applied to a node a viewer
  has since dragged locally, and the map never moves a node out from under someone looking at
  it.

**Edit mode:** the "Edit topology" toggle (off by default, on every page load) switches on
vis-network's manipulation toolbar:

- **Add Edge** / reconnect / delete draws, moves and removes parent→child links, written
  immediately to the child host's `parents` attribute over `CHECKMK_REST_ORIGIN`.
- Dragging a node writes its new `map_position` label immediately.
- **Add Node** creates an unmanaged switch — a real, check-free Checkmk host (DASH-13) added at
  the drop position; see `scripts/provision_topology_editor.py`'s docstring and 13-CONTEXT.md
  D-06 for the exact no-agent/no-ip/no-snmp attribute shape that keeps it at zero services.
- The dashboard deliberately has **no delete-host action** — to remove a mistakenly added
  switch, delete it in Checkmk's own UI (Setup > Hosts) and activate the change there.

Every individual edit above writes straight to Checkmk but does not go live until **Apply changes**
is pressed once — this runs Checkmk's own Activate Changes for exactly the scoped
credential's own pending changes. If another operator has unrelated changes pending in Checkmk
at the same time, Apply shows "Saved, but not live yet" and stays that way: the scoped
`topology_editor` credential never force-activates someone else's foreign changes, by design
(13-CONTEXT.md D-04, `wato.activateforeign` is deliberately not granted). The pending Checkmk
change must be activated (by that other operator, or by `cmkadmin`) before your edit and theirs
both go live.

Edit mode also has a 5-minute idle auto-exit: if the toggle is left on with no interaction, it
switches itself off and shows a one-time notice, so a browser tab left open overnight doesn't
sit in a writable state indefinitely.

## 5a. Event history

The centre-bottom pane lists state-change events newest-first. Each row shows the event's
local date and time as `YYYY-MM-DD HH:MM:SS` (the raw ISO value is on the `<time>` element's
`datetime` attribute).

A From / To filter above the list narrows the rows to an inclusive range:

- Either bound may be left empty (open-ended). To includes its whole minute, since the
  `datetime-local` input has minute granularity.
- A From later than To shows an inline error and leaves the list unfiltered.
- Clear resets both bounds; when events exist but none match, the pane says "No events in
  this range" (distinct from "No recent events" for an empty feed).
- Filtering is client-side only, over the retained `lan/events/recent` array. That array is
  capped by the poller's `EVENTS_MAX_ENTRIES` (default 1000, about 160 KB when full), so the
  range can only reach as far back as the last 1000 events.

## 6. Version pins and why

- `tailwindcss` is pinned to the 3.x line. A bare `npm install tailwindcss` would grab v4,
  which uses a CSS-native `@theme` configuration model and would silently ignore
  `tailwind.config.js` entirely (no error — it just doesn't apply).
- `typescript` is pinned to the 5.x line. TypeScript 7 is a from-scratch compiler rewrite.
- Import from `react-router`, **not** `react-router-dom` — `react-router-dom` was dropped as a
  re-export in v8.

## 7. Known drift risk

`dashboard-react/tailwind.config.js` duplicates `design-system/tailwind.config.js`'s
`theme.extend` block by hand, because the package's `exports` map does not expose its config
for import. The two must be kept in step by hand whenever the design system's token set
changes.

## 8. Cutover checklist (D-42 — tracked, deliberately NOT executed by this phase)

1. Repoint `deploy/compose.yaml`'s `dashboard` service volume from `../dashboard` to
   `../dashboard-react/dist`.
2. Add the SPA fallback to the nginx config: the stock `nginx:alpine` image's default config
   has none, so a cold-loaded `/details?id=...` bookmark would 404. Add it by mounting a
   custom `nginx.conf` or switching to a purpose-built image:
   ```nginx
   location / {
       try_files $uri $uri/ /index.html;
   }
   ```
3. Add the `/checkmk-api/` same-origin forwarding rule that `vite.config.ts`'s dev/preview
   proxy provides today (§4/§5), as an nginx `location` block inside the same dashboard
   service's config — a forwarding rule on the existing container, not a new service:
   ```nginx
   location /checkmk-api/ {
       proxy_pass http://checkmk:5000/;
   }
   ```
4. Add the `design-system` and `dashboard-react` builds (§2) as deployment steps.
5. Delete `dashboard/`.
