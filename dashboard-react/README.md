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
- `HISTORY_MAX_ENTRIES` — bounds the event-history list.
- `CHECKMK_SITE` — the Checkmk site name used to build deep links.

## 5. Version pins and why

- `tailwindcss` is pinned to the 3.x line. A bare `npm install tailwindcss` would grab v4,
  which uses a CSS-native `@theme` configuration model and would silently ignore
  `tailwind.config.js` entirely (no error — it just doesn't apply).
- `typescript` is pinned to the 5.x line. TypeScript 7 is a from-scratch compiler rewrite.
- Import from `react-router`, **not** `react-router-dom` — `react-router-dom` was dropped as a
  re-export in v8.

## 6. Known drift risk

`dashboard-react/tailwind.config.js` duplicates `design-system/tailwind.config.js`'s
`theme.extend` block by hand, because the package's `exports` map does not expose its config
for import. The two must be kept in step by hand whenever the design system's token set
changes.

## 7. Cutover checklist (D-42 — tracked, deliberately NOT executed by this phase)

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
3. Add the `design-system` and `dashboard-react` builds (§2) as deployment steps.
4. Delete `dashboard/`.
