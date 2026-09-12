# Phase 11: Live Dashboard - Context

**Gathered:** 2026-09-12
**Revised:** 2026-09-12 (second session — topology map and agent metrics moved out, see Scope Revision)
**Status:** Ready for planning — **blocked on a ROADMAP/REQUIREMENTS amendment, see Scope Revision**

<domain>
## Phase Boundary

Three static HTML pages, served by a new nginx container, that consume the Phase 9 MQTT
topic contract over Mosquitto's WebSockets listener and render live device status, a
grouped fleet overview, and bounded per-device history. No build step, no server-side
application — all state comes from retained MQTT messages. Checkmk's own UI remains the
destination for service-level detail; this phase links out to it.

**Not in this phase** (moved out during the second discussion session):
- The vis-network topology map — deferred to the map phase, because `parents` is empty on
  the target site so there is no topology to render
- Agent-derived metrics (CPU/RAM/disk gauges) and per-service status — deferred to Phase 12

One deliberate exception to "pure consumer" remains: D-17 extends the Phase 9 poller
payload additively.

</domain>

<scope_revision>
## Scope Revision — read this before planning

A second discussion session materially changed this phase. Two capabilities were moved out,
and that requires a ROADMAP/REQUIREMENTS amendment **before** planning, or the
requirements-coverage gate will fail on DASH-01.

### What moved out

| Moved | To | Why |
|---|---|---|
| vis-network topology map | New map phase (13) | `parents` is unset on the target site, so an auto-built map renders as disconnected dots. Hand-drawing it needs a layout-persistence design with no backend — separate work. The real fix is teaching the wizard to set `parents` over the REST API (as Phase 10 already does for tags), which is a wizard phase, not a dashboard phase. |
| CPU/RAM/disk gauges, per-service status, disk health | New Phase 12 | The poller runs exactly one query (`GET hosts`) and never touches the `services` table — no per-service state, no `plugin_output`, no `perf_data` exists in the contract. Adding them is a new query, a new topic, perfdata parsing and new UI. Also contradicts a locked PROJECT.md Out of Scope entry. |

### Required amendments (do these first)

1. **Split DASH-01.** It currently conflates two deliverables. Phase 11 keeps the
   *at-a-glance stats-by-state strip, merging in place rather than re-rendering*. The
   *live topology map (vis-network) with parent/child links* becomes a new requirement
   owned by the map phase.
2. **DASH-06** ("color-codes/icons nodes by device type and groups/colors by the
   folder-derived location/group label") stays in Phase 11 but now applies to the sidebar
   tree and the index overview rather than to map nodes.
3. **ROADMAP Phase 11 success criterion #1** must be reworded to drop vis-network and the
   parent/child links.
4. **PROJECT.md Out of Scope** — the entry "Duplicating Checkmk's own per-service drill-down
   UI in the new dashboard" is being partially reversed by Phase 12 and should be amended
   when that phase is added, not silently left contradicted.
5. **Add Phase 12** (agent metrics + per-service status) and **Phase 13** (wizard `parents`
   support + topology map), in that order — metrics first because the data already exists in
   Checkmk and only needs querying, whereas the map depends on wizard work landing first.

### Already satisfied, nothing to build
Service state already drives host color: the poller pulls `worst_service_state` and folds it
into the host state via worst-of aggregation (Phase 9 D-08), so a CRIT filesystem or SMART
check already turns the host red today. Phase 12 adds *visibility* into which service, not
the influence itself.

</scope_revision>

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
- **D-03 (REVISED):** `mqtt.js` 5.15.2 (browser UMD) is **vendored** into
  `dashboard/js/vendor/` and committed — not loaded from a CDN — so the dashboard works on a
  monitoring LAN with no internet egress and its version is pinned by the file itself.
  *`vis-network` is no longer needed in this phase* and moves to the map phase along with
  the map itself.
- **D-04:** The new `dashboard` nginx service publishes on host port **8090** (clear of the
  existing 80xx/90xx clusters: 8080/8000/6556 checkmk, 1883 mqtt, 9000/9001 minio,
  9002 mosquitto-WS).

### Grouping & Roll-up (drives the sidebar tree and the index overview)
- **D-05:** Grouping is a **runtime toggle** with two modes — by folder (the derived
  location/group label) or by `device_type`. Default mode is **device_type**; the choice is
  persisted in `localStorage` per browser. The sidebar tree and the index overview follow the
  same toggle, so they never disagree about how the fleet is grouped.
- **D-06:** A group's color is **worst-of its children's states** (any CRIT → red, any WARN →
  amber, all OK → green), plus a **count badge** showing how many children are non-OK.
  Worst-of matches the aggregation the poller already applies across a host's services
  (Phase 9 D-08), so UI and payload agree; the badge supplies "how much" without expanding.
- **D-07:** When grouped **by folder**, each host row/tile carries a `device_type` icon. When
  grouped **by device_type**, the host's folder is not shown — the group already carries the
  only classification that matters in that mode.
- **D-10:** A DOWN host gets **`⛔` prepended to its label** in the sidebar tree, the overview
  tile, and the device table, in addition to its red fill. Chosen over a shade-only
  distinction because it needs no icon font or sprite sheet to vendor, renders identically in
  all three surfaces, and does not carry the signal through hue alone.

> **Moved to the map phase:** D-08 (synthetic group-root nodes for parentless hosts) and
> D-09 (stabilize-once-then-freeze physics). Both are meaningless without a map. Their
> rationale is preserved in `11-DISCUSSION-LOG.md` so the map phase need not re-derive it.

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
  global condition** rather than a per-host mark. Scope differs, timing does not: a stale
  device is one grey row; a stale `last_poll` means every reading on screen is suspect.
- **D-14:** When the poller is confirmed gone (LWT fired, or `last_poll` past threshold): a
  **persistent top banner** — "Poller offline since HH:MM — data is N minutes old" — plus the
  stale hatch on every row and tile. Last known values stay legible, because they remain the
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
    purely backend-less consumer phase.
  - Both fields are **additive** — existing subscribers and existing retained payloads stay
    valid.
  - Consequence for D-12: the dashboard should **prefer Checkmk's `staleness`** when present
    and fall back to `timestamp`-age against the 3× factor. Consequence for D-11: UNREACH
    becomes separately renderable in Checkmk's orange.
  - Planning should confirm both columns via `mqtt_poller.py --check-columns` against the live
    site before relying on them, following the precedent of the 2026-09-08 column probe.

### Page Shell, Routing & Checkmk Links
- **D-18:** Display name is **`alias` when non-empty, else `id` (hostname)**. The wizard's
  Phase 4/10.1 alias prompt exists precisely so an operator can give a host a human name.
  The hostname stays visible in the detail panel and as a device-table column.
- **D-19:** `details.html` reads its target from a **query string** —
  `details.html?id=<hostname>` via `URLSearchParams`. Bookmarkable, shareable, survives
  refresh, and works with browser back/forward. Host ids are safe here: the wizard validates
  hostnames against a strict regex and `is_publishable_device_id()` already rejects ids
  containing `+ # /`.
- **D-20:** The Checkmk base URL and site name live in **`dashboard/js/config.js`** alongside
  the broker settings — one file an operator edits per deployment. The browser cannot derive
  them: the poller reaches Checkmk over an internal container hostname (`checkmk:5000`) that
  no LAN browser can resolve.
- **D-21:** **Three real HTML files that behave as one app.** `index.html`, `devices.html` and
  `details.html` all exist and each renders correctly when opened cold (keeping every URL
  bookmarkable), but all three load the same `js/shell.js`, and in-app navigation is
  intercepted with `history.pushState`.
- **D-22 (REVISED):** Layout is a **persistent shell with a swappable main area**, modelled on
  `docs/DMC-networkmap.png` / `docs/DMC-server.png`: dark, dense, panel-based. The **left
  column is split vertically** — grouped tree on top, **event-history panel beneath it**, both
  always on screen. The main area swaps between overview, device table and detail without ever
  unmounting them.
- **D-23 (NEW):** Clicking a host anywhere — tree, overview tile, or table row — opens the
  detail **as a panel in the main area, in place**. The shell, the tree and the event history
  stay mounted and live; the URL updates to `details.html?id=<host>` via `pushState`. This is
  what makes "event history always visible" true: a full page swap would unmount and
  re-subscribe it, losing scroll position mid-incident.
- **D-24 (NEW):** `index.html` is the **stats-by-state strip plus a grouped fleet overview**
  (cards/tiles honouring D-05's toggle and D-06's roll-up). It delivers the surviving half of
  DASH-01 and is the natural place to drop the real map into during the map phase.

### Claude's Discretion
- Exact color hex values, spacing, typography, and dark-theme tokens (D-11 fixes the *meaning*
  of each color, not its exact value)
- The `device_type` → glyph mapping for the six configured types
- Device-table columns and default sort beyond what DASH-02 requires
- Event-panel row formatting and timestamp rendering
- Overview tile vs card shape and its density
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
- `.planning/ROADMAP.md` — Phase 11 section. **Note:** success criterion #1 still names
  vis-network and parent/child links; see Scope Revision above — it must be amended before
  planning.
- `.planning/REQUIREMENTS.md` — DASH-01 through DASH-06. **DASH-01 requires splitting**; see
  Scope Revision.
- `.planning/PROJECT.md` — Constraints (no new backend, container boundary) and Out of Scope
  (no time-series graphing; the per-service drill-down entry is partially reversed by the new
  Phase 12)

### The MQTT contract this phase consumes (fixed by Phase 9, extended by D-17)
- `scripts/mqtt_poller.py` — **the authoritative contract**. Topic constants (`TOPIC_TOPOLOGY`,
  `TOPIC_EVENTS`, `TOPIC_POLLER_STATUS`), `device_status_topic()` / `device_history_topic()`,
  the `DeviceSnapshot` dataclass, `publish_device_status/topology/history/events/poller_status/tombstone`,
  `compute_overall_state()` (worst-of, D-08), `extract_device_type()`'s docstring on what
  `"unknown"` means, and `REQUIRED_HOST_COLUMNS`/`OPTIONAL_HOST_COLUMNS` (note: `GET hosts`
  only — the `services` table is never queried). D-17 modifies this file.
- `tests/test_mqtt_poller.py` — existing poller tests; D-17 extends these
- `.planning/phases/09-poller-core/09-CONTEXT.md` — Phase 9's locked decisions, especially D-05/D-06
  (history 20 / events 50 bounds), D-07 (`in_downtime`/`acknowledged` naming), D-08 (worst-of),
  D-09/D-10 (`alias` carried specifically so Phase 11 decides display preference — resolved here as D-18)

### Browser stack and rendering
- `.planning/research/STACK.md` — mqtt.js 5.15.2 browser bundle (exact CDN path to vendor
  from), its `reconnectPeriod`/`connectTimeout` options and its
  `connect`/`reconnect`/`offline`/`close`/`error` events for the connection indicator.
  *(The vis-network sections of this file belong to the map phase, not this one.)*
- `.planning/research/ARCHITECTURE.md` — `dashboard/` directory layout, the `dashboard` nginx
  compose service shape, and the "browser talks to mosquitto directly, nginx serves static
  files only" boundary
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
- `docs/DMC-networkmap.png` — shell layout: split left column (tree over event history), main
  canvas. *(Its map panel belongs to the map phase.)*
- `docs/DMC-server.png` — detail-panel layout and the SERVICES/HISTORY tab strip. *(Its gauges
  and process table belong to Phase 12.)*

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
  them. They are AI-generated (the text is garbled) so only the **layout language** is binding:
  dark dense panels, left column split between a grouped tree and an always-visible event
  history, a main area that swaps between views.
- "The event history needs to be always visible" is a direct operator requirement and is what
  forced D-23's in-place detail panel over a page swap.
- The operator's own framing of the group roll-up was "green if all its children are green,
  yellow if at least one child is yellow, red if all children are red". The yellow and red
  halves used opposite logic; on being shown that one CRIT among nine OK would not turn a group
  red, they chose worst-of plus a count badge (D-06).
- The operator asked for an icon rather than a color shade to mark a DOWN host, and left the
  choice open — resolved as `⛔` (D-10).
- The operator asked that the staleness design be checked against Checkmk's own documented
  definition rather than invented; that check changed the palette (UNKNOWN is orange in Checkmk,
  not grey) and gave D-12 its factor shape.
- The operator's reason for dropping the map: "the live network map is something I would need to
  draw manually, as the automatic network mapping is not available yet" — i.e. `parents` is
  unset, so there is nothing to auto-render.

</specifics>

<deferred>
## Deferred Ideas

### To Phase 12 — agent metrics and per-service status
- CPU / RAM / disk-space gauges and disk-health (SMART) readouts on the detail panel, sourced
  from Checkmk agent services. Requires a `GET services` Livestatus query (the poller currently
  issues only `GET hosts`), a new retained topic, and `perf_data` parsing — which belongs in
  the poller, in Python, not in browser JS.
- A per-host service status list explaining *why* a host is red.
- Amending PROJECT.md's "Duplicating Checkmk's own per-service drill-down UI" Out of Scope entry.
- Publish cadence for services is an open design question: ~21 hosts × ~20 services is ~420 rows
  per cycle, so change-only publishing is likely needed rather than every-cycle retention.
- The `docs/DMC-server.png` gauges and SERVICES tab are the visual reference for this phase.

### To Phase 13 — wizard `parents` support and the topology map
- Teaching the wizard to set Checkmk's `parents` host attribute over the REST API, the same way
  Phase 10 sets `tag_device_type`. This makes topology real monitoring data, benefits Checkmk's
  own views, and removes the need for any layout persistence.
- The vis-network topology map itself, vendoring `vis-network` 10.1.2 standalone UMD, and the
  original D-08 (synthetic group-root nodes for parentless hosts) and D-09
  (stabilize-once-then-freeze physics) decisions — both fully reasoned in `11-DISCUSSION-LOG.md`
  and should not need re-deriving.
- If a hand-drawn map is still wanted after `parents` support lands: layout persistence with no
  backend is the unsolved problem. Options considered were localStorage (per-browser, lost
  elsewhere), an export/import `layout.json` committed to the repo (read-only, clunky), or a
  retained `lan/dashboard/layout` topic (shared and backend-free, but requires a writable
  mosquitto user and so gives up the read-only posture D-01's safety argument rests on).

### Permanently out of scope / already deferred
- Time-series graphing beyond the bounded transition-history strip — no time-series database
  (PROJECT.md)
- Per-service drill-down to Checkmk's depth — `details.html` links out instead
- Sidebar search/filter box — overlaps DASH2-02, already deferred to v2 in STATE.md
- Mobile-responsive layout polish — DASH2-01, already deferred to v2
- nginx reverse-proxy of `/mqtt` for single-origin and future TLS termination
- Restricting the 1883 TCP listener to container-internal reachability — carried over from
  Phase 8's deferred list

</deferred>

---

*Phase: 11-live-dashboard*
*Context gathered: 2026-09-12 (revised same day after scope discussion)*
