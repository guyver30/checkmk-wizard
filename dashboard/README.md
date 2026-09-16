# Live Dashboard

A static, backend-less web dashboard that visualizes the Checkmk-monitored network topology and
device status this repo's wizard onboards, updating in real time over MQTT. There is no
server-side process and no build step — every file here is served as-is by the `dashboard` nginx
service (`deploy/compose.yaml`, host port 8090; see
[`docs/Podman setup for checkmk, minio, mosquitto, worker.md`](../docs/Podman%20setup%20for%20checkmk,%20minio,%20mosquitto,%20worker.md)
§2/§3/§6/§7 for deployment, configuration and verification steps).

State comes entirely from the `poller` service's retained MQTT messages
(`scripts/mqtt_poller.py`) — the browser subscribes over Mosquitto's WebSockets listener and
never talks to Checkmk directly except for the one-way "View in Checkmk →" deep link out of the
detail page.

## Directory layout

```
dashboard/
├── index.html          # DASH-01: stats-by-state strip + grouped fleet overview
├── devices.html         # DASH-02: sortable device table
├── details.html         # DASH-03: per-device drill-down
├── css/
│   └── dashboard.css    # the only stylesheet — design tokens + every class the JS references
├── js/
│   ├── config.js         # the one file an operator edits per deployment (see below)
│   ├── display.js        # display naming, state/icon classification, relative-time formatting
│   ├── grouping.js        # group membership, worst-of roll-up, stale-never-masks-known-bad
│   ├── staleness.js       # per-device and poller-liveness staleness derivation
│   ├── mqtt-connection.js # the single choke point for the MQTT-over-WebSockets lifecycle
│   ├── state-store.js     # in-memory store for every retained topic, wholesale-replace merge
│   ├── render-shell.js    # persistent chrome: connection indicator, banners, tree, event panel
│   ├── render-index.js    # ViewModules.index — stats strip + grouped overview
│   ├── render-devices.js  # ViewModules.devices — sortable table
│   ├── render-details.js  # ViewModules.details — per-device drill-down
│   ├── shell.js           # entry point every page loads last: wiring + pushState router
│   └── vendor/
│       └── mqtt.min.js    # vendored mqtt@5.15.2 browser build (see vendor/README.md)
├── fonts/                # vendored KONE Information + Inter (see fonts/README.md)
├── icons/                # vendored KONE SVG icon set (see icons/README.md)
└── images/
    └── kone-logo.png     # trimmed KONE logo (see "Vendored assets" below)
```

Each `js/*.js` file owns exactly one concern; `shell.js` composes the others together and is the
only file with cross-module wiring — see each file's own header comment for its full contract.

## The one file you edit: `config.js`

`dashboard/js/config.js` is the browser-side equivalent of a compose `environment:` block: one
file an operator edits per deployment, loaded before every other dashboard script. It has no
runtime discovery mechanism of its own by design (no server-side process to ask), so it must be
edited before first use:

- `CHECKMK_BASE_URL` — the "View in Checkmk →" deep link's base URL. Must be changed from the
  checked-in `http://<HOST_IP>:8080` placeholder to a URL a LAN browser can resolve; the poller
  reaches Checkmk over the container-internal name `checkmk:5000`, which no browser can.
- `CHECKMK_SITE` — the Checkmk site name (`dmc` by default).
- `WS_PORT`, `WS_USERNAME`, `WS_PASSWORD` — the Mosquitto WebSockets listener and its disposable
  `wsreader`/`wsreader` read-only credentials, rotate before exposing this dashboard beyond a
  trusted LAN (same convention as `deploy/mosquitto.passwd`'s other default credentials).
- `POLL_INTERVAL_SECONDS`, `HISTORY_MAX_ENTRIES` — must be kept in step with the poller's own
  `POLL_INTERVAL_SECONDS`/`HISTORY_MAX_ENTRIES` environment values in `deploy/compose.yaml`.

No broker hostname constant is defined here on purpose — it is derived at runtime from
`location.hostname` in `mqtt-connection.js`, so the same `config.js` works unmodified whichever
LAN address a browser used to reach port 8090.

## Vendored assets and no-CDN/no-egress rationale

The dashboard runs on a monitoring LAN with no internet egress, so every runtime asset must
resolve from its own origin — nothing is fetched from a CDN, npm registry, or Google Fonts at
runtime or at deploy time. Each vendored group was copied once, at authoring time, and committed:

- **`js/vendor/mqtt.min.js`** — `mqtt@5.15.2`, the browser UMD build, downloaded verbatim from
  `unpkg.com` and never hand-edited. See `js/vendor/README.md` for the exact source URL, download
  date, and legitimacy audit.
- **`fonts/`** — self-hosted KONE Information (woff2/woff) and Inter (ttf, Regular + SemiBold),
  copied from KONE's internal design-system checkout. See `fonts/README.md` for the source path
  and per-file mapping.
- **`icons/`** — 25 individual KONE SVG icons (of ~207 available), hand-picked for the three pages
  this dashboard builds, applied via CSS `mask-image` rather than `<img>` because every vendored
  SVG hardcodes a fixed fill color. See `icons/README.md` and
  `.planning/phases/11-live-dashboard/11-UI-SPEC.md`'s Asset Vendoring Manifest for the full file
  list and per-icon usage.
- **`images/kone-logo.png`** — the KONE logo, one-time whitespace-trimmed
  (`convert -trim +repage`) from `web_assets/KONE_logo.png` so it doesn't render as a large white
  square against the dashboard's dark top bar. No pixel of the logo mark itself is redrawn or
  recolored — only the surrounding whitespace is cropped.

The KONE brand assets (fonts, icons, logo) are internal company design-system files, not a public
package-registry dependency, so no npm/pip-style legitimacy audit applies to them — the same
treatment this repo already gives any other checked-in image asset.

## No build step

There is no `npm install`, no bundler, and no `package.json` for this directory. Every script is
a classic (non-module) `<script src="...">` tag loaded in a fixed order, every asset is committed
as-is, and deployment is nothing more than a read-only bind mount
(`../dashboard:/usr/share/nginx/html:ro,z` in `deploy/compose.yaml`).

## Out of scope

An interactive network-topology visualization, per-device resource-usage gauges, storage-health
readouts, and individual service-level status are not part of this dashboard — they belong to
later phases. `details.html`'s "View in Checkmk →" link is the deliberate stopping point: that
level of detail lives in Checkmk's own UI.
