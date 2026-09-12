# Phase 11: Live Dashboard - Context

**Gathered:** 2026-09-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Three static HTML pages, served by a new nginx container, that consume the Phase 9 MQTT
topic contract over Mosquitto's WebSockets listener and render live topology, device
status, and bounded history. No build step, no server-side application — all state comes
from retained MQTT messages. Checkmk's own UI remains the destination for service-level
detail; this phase links out to it rather than reproducing it.

One deliberate exception to "pure consumer" was chosen during this discussion: D-17
extends the Phase 9 poller payload additively (see Poller Contract Extension below).

</domain>

<decisions>
## Implementation Decisions

### Broker Connection & Credentials
- **D-01:** WebSocket credentials (the `wsreader` user from `deploy/mosquitto.passwd`) are
  hardcoded in `dashboard/js/config.js`, checked into the repo, and documented as
  disposable defaults to rotate before exposing beyond a trusted LAN — the same convention
  this project already uses for `cmkadmin`/`cmkadmin`, `minioadmin`/`minioadmin`, and
  `deploy/mosquitto.passwd` itself. `wsreader` is `topic read lan/#` only, so the exposure
  is read-only access to the device list from the LAN.
- **D-02:** The broker host is derived at runtime from `location.hostname`; the WS port is a
  named constant (`9002`) in `config.js`. The dashboard therefore works unchanged from any
  LAN device without per-client configuration, because nginx and mosquitto are published
  from the same host.
- **D-03:** `vis-network` 10.1.2 (standalone UMD, bundles `vis-data`) and `mqtt.js` 5.15.2
  (browser UMD) are **vendored** into `dashboard/js/vendor/` and committed — not loaded from
  a CDN. Rationale: the dashboard must work on a monitoring LAN with no internet egress,
  versions are pinned by the file itself, and an infrastructure tool should not have a
  third-party runtime dependency.
- **D-04:** The new `dashboard` nginx service publishes on host port **8090** (clear of the
  existing 80xx/90xx clusters: 8080/8000/6556 checkmk, 1883 mqtt, 9000/9001 minio,
  9002 mosquitto-WS).

### Topology Visual Encoding
- **D-05:** Grouping is a **runtime toggle** with two modes — by folder (the derived
  location/group label) or by `device_type`. Default mode is **device_type**; the choice is
  persisted in `localStorage` per browser. The sidebar tree follows the same toggle, so tree
  and map never disagree about how the fleet is grouped.
- **D-06:** A group/parent node's color is **worst-of its children's states** (any CRIT →
  red, any WARN → amber, all OK → green), plus a **count badge** showing how many children
  are non-OK. Worst-of matches the aggregation the poller already applies across a host's
  services (Phase 9 D-08), so map and payload agree; the badge supplies "how much" without
  expanding the group.
- **D-07:** When grouped **by folder**, each child node carries a `device_type` icon. When
  grouped **by device_type**, the child's folder is not shown on the node — the group itself
  already carries the only classification that matters in that mode.
- **D-08:** Hosts with no `parents` value attach to a **synthetic group-root node** (one per
  group, distinctly styled so it is visibly not a device). This is necessary, not cosmetic:
  on a typical Checkmk site most hosts have no parent set, and without it the "topology map"
  renders as a scatter of unconnected dots.
- **D-09:** Physics **stabilizes once on load, then freezes**. Status updates recolor nodes in
  place via `DataSet.update()` with zero movement, preserving the user's pan/zoom and mental
  map — which is the entire point of DASH-01's "merge, don't re-render". Physics
  re-stabilizes only when topology actually changes.
- **D-10:** A DOWN host gets **`⛔` prepended to its label** in the map, the sidebar tree, and
  the device table, in addition to its red fill. Chosen over a shade-only distinction because
  it needs no icon font or sprite sheet to vendor, renders identically in all three surfaces,
  and does not carry the signal through hue alone.

### State Colors & Staleness
- **D-11:** **Mirror Checkmk's own state palette** so a color means the same thing in both
  UIs: OK green, WARN yellow, CRIT red, UNKNOWN **orange**, UNREACH orange, DOWN red. Grey is
  reserved exclusively for the dashboard's own stale/no-data condition. (Verified against
  https://docs.checkmk.com/latest/en/monitoring_basics.html — note UNKNOWN is orange in
  Checkmk, and grey there means PEND/"never yet polled", which is closer to our stale.)
- **D-12:** Staleness threshold is **3 × the poll interval** (180s at the 60s default),
  stored as a *factor* in `config.js` mirroring the shape of Checkmk's own
  "Staleness value to mark hosts / services stale" parameter. Checkmk's default factor is 1.5,
  but its checks are scheduled locally; our chain adds a Livestatus query, an MQTT publish, a
  broker hop, and a browser — so 1.5× (90s) would mark the whole fleet stale whenever a single
  cycle runs long. 3× absorbs exactly one fully missed cycle.
- **D-13:** The same 3× factor applies to `lan/poller/status.last_poll`, but as a **page-level
  global condition** rather than a per-node mark. Scope differs, timing does not: a stale
  device is one grey node; a stale `last_poll` means every reading on screen is suspect.
- **D-14:** When the poller is confirmed gone (LWT fired, or `last_poll` past threshold): a
  **persistent top banner** — "Poller offline since HH:MM — data is N minutes old" — plus the
  stale hatch on every node and row. Last known values stay legible, because they remain the
  best information available and the operator may well be looking at the dashboard *because*
  something broke; the hatch ensures nothing can be mistaken for live.
- **D-15:** **Stale never masks a known-bad child** in a roll-up. A group's color is worst-of
  the children with fresh data, and the group additionally gets the hatch if any child is
  stale. A group with 1 CRIT and 3 stale children renders red-and-hatched — "something is
  broken AND we are partly blind", both facts preserved.
- **D-16:** `device_type: "unknown"` means the Checkmk `device_type` tag group does not exist
  on the site at all (Phase 10 was never run there) — it is a site-configuration warning, never
  a device category beside `other`. Surface it as a **dismissible banner** ("No device_type tag
  group on this site — run the wizard's tagging phase"), fall back to a neutral glyph, and
  degrade type-grouping to a single "untyped" group. This matches
  `scripts/mqtt_poller.py::extract_device_type`'s own docstring contract.

### Poller Contract Extension (deliberate scope addition)
- **D-17:** Phase 11 **extends the Phase 9 status payload** with two fields Livestatus already
  exposes but the poller does not publish: Checkmk's authoritative **`staleness`** value, and
  the **real host state** so DOWN and UNREACHABLE can be told apart (the poller currently
  collapses every non-zero host state into `"DOWN"`).
  - Operator was told the cost before choosing: this phase now edits
    `scripts/mqtt_poller.py` and `tests/test_mqtt_poller.py`, so Phase 11 is no longer a
    purely backend-less consumer phase, and the "nail the contract in Phase 9 before writing
    dashboard JS" build-order rationale is partly reopened.
  - Both fields are **additive** — existing subscribers and existing retained payloads stay
    valid.
  - Consequence for D-12: the dashboard should **prefer Checkmk's `staleness`** when present
    and fall back to `timestamp`-age against the 3× factor. Consequence for D-11: UNREACH
    becomes separately renderable in Checkmk's orange.

### Page Shell, Routing & Checkmk Links
- **D-18:** Display name is **`alias` when non-empty, else `id` (hostname)**. The wizard's
  Phase 4/10.1 alias prompt exists precisely so an operator can give a host a human name.
  The hostname stays visible on `details.html` and as a device-table column, so nothing is
  hidden.
- **D-19:** `details.html` reads its target from a **query string** — `details.html?id=<hostname>`
  via `URLSearchParams`. Bookmarkable, shareable, survives refresh, and works with browser
  back/forward. Host ids are safe here: the wizard validates hostnames against a strict regex
  and `is_publishable_device_id()` already rejects ids containing `+ # /`.
- **D-20:** The Checkmk base URL and site name live in **`dashboard/js/config.js`** alongside
  the broker settings — one file an operator edits per deployment. The browser cannot derive
  them: the poller reaches Checkmk over an internal container hostname
  (`checkmk:5000`) that no LAN browser can resolve.
- **D-21:** **Three real HTML files that behave as one app.** `index.html`, `devices.html` and
  `details.html` all exist and each renders correctly when opened cold (satisfying DASH-01/02/03
  and keeping every URL bookmarkable), but all three load the same `js/shell.js`, and in-app
  navigation is intercepted with `history.pushState` — so clicking a map node or a table row
  swaps the view instantly with the MQTT connection and accumulated state fully intact, never
  reconnecting.
- **D-22:** Visual language follows the operator's reference mockups
  (`docs/DMC-networkmap.png`, `docs/DMC-server.png`): **dark, dense, panel-based**; persistent
  **left sidebar** with a grouped tree; a **bottom-left event-history panel** fed by
  `lan/events/recent` (severity glyph + timestamp + text); the main canvas swapping per view.

### Claude's Discretion
- Exact color hex values, spacing, typography, and dark-theme tokens (D-11 fixes the *meaning*
  of each color, not its exact value)
- The `device_type` → glyph mapping for the six configured types
- Device-table columns and default sort beyond what DASH-02 requires
- Event-panel row formatting and timestamp rendering
- Whether to include a minimap inset on the topology view (present in the reference mockup;
  genuinely useful only past a certain node count)
- Exact nginx configuration and the shape of the `dashboard` compose service block
- File naming and layout under `dashboard/js/vendor/`
- Internal module layout of `shell.js` and the shared state store
- How the two D-17 fields are named in the payload (should follow Phase 9 D-07's convention of
  mirroring Livestatus's own column naming)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and requirements
- `.planning/ROADMAP.md` — Phase 11 section (locked success criteria 1–5, `Depends on: Phase 8, 9, 10`)
- `.planning/REQUIREMENTS.md` — DASH-01 through DASH-06 requirement text
- `.planning/PROJECT.md` — Constraints (no new backend, container boundary) and Out of Scope
  (no time-series graphing, no duplication of Checkmk's service drill-down)

### The MQTT contract this phase consumes (fixed by Phase 9, extended by D-17)
- `scripts/mqtt_poller.py` — **the authoritative contract**. Topic constants (`TOPIC_TOPOLOGY`,
  `TOPIC_EVENTS`, `TOPIC_POLLER_STATUS`), `device_status_topic()` / `device_history_topic()`,
  the `DeviceSnapshot` dataclass, `publish_device_status/topology/history/events/poller_status/tombstone`,
  `compute_overall_state()` (worst-of, D-08), and `extract_device_type()`'s docstring on what
  `"unknown"` means. D-17 modifies this file.
- `tests/test_mqtt_poller.py` — existing poller tests; D-17 extends these
- `.planning/phases/09-poller-core/09-CONTEXT.md` — Phase 9's locked decisions, especially D-05/D-06
  (history 20 / events 50 bounds), D-07 (`in_downtime`/`acknowledged` naming), D-08 (worst-of),
  D-09/D-10 (`alias` carried specifically so Phase 11 decides display preference — resolved here as D-18)

### Browser stack and rendering
- `.planning/research/STACK.md` — vis-network 10.1.2 standalone UMD and mqtt.js 5.15.2 browser
  bundle (exact CDN paths to vendor from), `DataSet.update()` upsert/shallow-merge semantics,
  mqtt.js `reconnectPeriod`/`connectTimeout` and its `connect`/`reconnect`/`offline`/`close`/`error`
  events for the connection indicator, and the standalone-vs-non-standalone build footgun
- `.planning/research/ARCHITECTURE.md` — `dashboard/` directory layout, the `dashboard` nginx
  compose service shape, the "browser talks to mosquitto directly, nginx serves static files only"
  boundary, and Build Order Implications §4–5
- `.planning/research/PITFALLS.md` — Pitfall C (a stalled poll loop reads as permanently online,
  which is why `last_poll` exists and D-13 checks it) and the retained-vs-persistent-session reasoning

### Broker and deployment (from Phase 8, already built)
- `deploy/mosquitto.conf` — the `listener 9001` / `protocol websockets` block the browser connects to
- `deploy/mosquitto.acl` — `user wsreader` / `topic read lan/#`, the read-only grant D-01 relies on
- `deploy/mosquitto.passwd` — the `wsreader` credentials D-01 checks into `config.js`
- `deploy/compose.yaml` — the 4-service stack this phase adds the `dashboard` service to; host
  port 9002 → container 9001 mapping for WS; the `poller` service D-17 touches
- `.planning/phases/08-broker-infrastructure-hardening/08-CONTEXT.md` — D-09's disposable-default
  credential convention that D-01 follows

### Device types and tagging
- `device_types.json` — the six configured values (`other`, `E-link`, `ACS`, `Multimedia`,
  `NetworkDevice`, `GroupController`); `other` is guaranteed first
- `.planning/phases/10-checkmk-tag-group-onboarding-integration/10-CONTEXT.md` — tag group and
  folder-derived location/group label decisions
- `.planning/phases/10.1-bulk-device-type-tagging-and-deployment-gaps/10.1-CONTEXT.md` — D-09's
  alias-handling rules that D-18 consumes

### External
- https://docs.checkmk.com/latest/en/monitoring_basics.html — host/service state model and the
  "Staleness value to mark hosts / services stale" factor (default 1.5 × check interval). Source
  for D-11's palette and D-12's factor shape.

### Visual reference
- `docs/DMC-networkmap.png` — topology view layout: sidebar tree, event-history panel, map with
  icon-by-role and color-by-health, minimap inset
- `docs/DMC-server.png` — detail view layout: same shell, per-device main panel, SERVICES/HISTORY
  tab strip

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/mqtt_poller.py` — every topic string and payload field the dashboard needs is defined
  here in one place, with docstrings explaining the *why* of each field. The dashboard's JS
  comments should point at this file rather than restating the contract.
- `scripts/smoke_test_broker.py` — this repo's own live-tested reference for what a working
  client session against the deployed broker looks like (connect, subscribe, retained delivery,
  ACL rejection). Useful for confirming the `wsreader` credentials and WS port before writing
  any rendering code.
- `deploy/compose.yaml`'s existing service blocks — the pattern the new `dashboard` service
  follows (bind mount from the repo checkout, `cmk_net` network, `restart: unless-stopped`).

### Established Patterns
- Environment-variable configuration at the compose-service level for Python components — but
  the dashboard has no server-side process, so its equivalent is D-01/D-02/D-20's single
  `dashboard/js/config.js`. This is a new pattern for this repo, and the file should carry a
  header comment explaining that it is the browser-side analogue of the compose env vars.
- Disposable default credentials documented plainly in-repo rather than hidden — extended here
  from `deploy/mosquitto.passwd` to `dashboard/js/config.js`.
- Python tests are 100% mocked against live infrastructure; the D-17 poller changes must stay
  within that convention (`tests/test_mqtt_poller.py`), while the dashboard JS itself has no
  test harness in this repo — verification for the browser side is manual/live, as with
  `scripts/smoke_test_broker.py`.

### Integration Points
- `deploy/compose.yaml` — gains the `dashboard` nginx service on host port 8090 (D-04).
- `deploy/mosquitto.acl` / `.passwd` — already provision `wsreader`; no broker change needed.
- `scripts/mqtt_poller.py` + `tests/test_mqtt_poller.py` — modified by D-17 only.
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` — will need the new service and
  the `config.js` edit-before-deploy step documented.

</code_context>

<specifics>
## Specific Ideas

- The operator supplied two reference mockups and asked the dashboard to be organized after
  them. They are AI-generated (the text in them is garbled) so only the **layout language** is
  binding, not their literal content: dark dense panels, left sidebar with search + grouped
  tree, always-visible bottom-left event history, main canvas swapping between topology map
  and per-device detail, SERVICES/HISTORY tab strip in the detail view.
- The operator's own framing of the group roll-up was "green if all its children are green,
  yellow if at least one child is yellow, red if all children are red". The yellow and red
  halves used opposite logic; on being shown that one CRIT among nine OK would not turn a group
  red, they chose worst-of plus a count badge (D-06).
- The operator asked for an icon rather than a color shade to mark a DOWN host, and left the
  choice of icon open — resolved as `⛔` (D-10).
- The operator asked that the staleness design be checked against Checkmk's own documented
  definition rather than invented; that check changed the palette (UNKNOWN is orange in Checkmk,
  not grey) and gave D-12 its factor shape.

</specifics>

<deferred>
## Deferred Ideas

- **CPU/RAM/Disk gauges, the real-time process table, 7-day metric graphs, and "Top-3 congested
  links" sparklines** — all visible in the reference mockups, none buildable: the poller contract
  carries no metrics or time-series, and time-series graphing is explicitly Out of Scope in
  PROJECT.md. Checkmk's own UI is the destination for these (DASH-03's link-out).
- **Sidebar search/filter box** — present in both mockups, but already deferred to v2 as DASH2-02
  ("Search/filter box on device table") in STATE.md's Deferred Items. Kept out of this phase for
  consistency with that existing deferral.
- **Mobile-responsive layout polish** — DASH2-01, already deferred to v2.
- **nginx reverse-proxy of `/mqtt` through to `mosquitto:9001`** for a single origin and future
  TLS termination — the more production-grade shape per ARCHITECTURE.md, but not required by this
  milestone's constraints and inconsistent with how 1883/9002 are already published directly.
- **Restricting the 1883 TCP listener to container-internal reachability** — carried over from
  Phase 8's deferred list, unchanged.
- **Per-service drill-down inside the dashboard** — permanently out of scope per PROJECT.md;
  `details.html` links out to Checkmk instead.

</deferred>

---

*Phase: 11-live-dashboard*
*Context gathered: 2026-09-12*
