# Phase 11: Live Dashboard - Research

**Researched:** 2026-09-12
**Domain:** Static (build-step-free) browser dashboard consuming MQTT-over-WebSockets, plus an additive extension to an existing Python Livestatus-to-MQTT poller
**Confidence:** HIGH (MQTT contract, poller extension mechanics, broker deployment — all live-code or official-doc verified) / MEDIUM (mqtt.js reconnect internals, Checkmk `staleness` column on the `hosts` table — verified via official README + strong multi-source community corroboration, not a live `GET columns` probe against the target site)

<user_constraints>
## User Constraints (from CONTEXT.md)

**Full text preserved verbatim in `.planning/phases/11-live-dashboard/11-CONTEXT.md` — this is a condensed carry-forward for planner convenience; consult the source file for complete rationale.**

### Scope Revision (read first)
Two capabilities were moved out of this phase during a second discussion session and now require a ROADMAP/REQUIREMENTS amendment before planning proceeds without a requirements-coverage gate failure:
- The vis-network topology map (parents unset on the target site) → new **DASH-07**, owned by **Phase 13**.
- Agent-derived metrics (CPU/RAM/disk gauges) and per-service status → **Phase 12** (new Livestatus `GET services` query the poller does not currently issue).
- `index.html`'s success criterion is now: stats-by-state strip + grouped fleet overview (no map, no parent/child links).
- One deliberate exception survives: **D-17** additively extends `scripts/mqtt_poller.py` and `tests/test_mqtt_poller.py` — this phase is not a purely backend-less consumer phase.

### Locked Decisions (D-01 through D-24)
- **D-01:** `wsreader`/`wsreader` WS credentials hardcoded in `dashboard/js/config.js`, checked in, documented as disposable defaults (matches `cmkadmin`/`minioadmin` convention). Read-only (`topic read lan/#`).
- **D-02:** Broker host derived from `location.hostname` at runtime; WS port is the named constant `9002` in `config.js`.
- **D-03 (REVISED):** `mqtt.js` 5.15.2 browser UMD is vendored into `dashboard/js/vendor/`, committed, not CDN-loaded. `vis-network` is NOT part of this phase (moved to Phase 13).
- **D-04:** New `dashboard` nginx service on host port **8090**.
- **D-05:** Grouping is a runtime toggle (folder vs `device_type`), default **device_type**, persisted per-browser in `localStorage`. Sidebar tree and index overview always agree.
- **D-06:** Group color = worst-of children's states + a count badge of non-OK children.
- **D-07:** Grouped by folder → host shows a `device_type` icon. Grouped by type → folder not shown.
- **D-10:** A DOWN host gets `⛔` prepended to its label (sidebar, overview tile, device table) in addition to red fill.
- **D-11:** Mirror Checkmk's own palette: OK green, WARN yellow, CRIT red, UNKNOWN orange, UNREACH orange, DOWN red. Grey is reserved exclusively for this dashboard's own stale/no-data condition (verified against docs.checkmk.com — UNKNOWN is orange in Checkmk, not grey).
- **D-12:** Staleness threshold = **3× the poll interval** (180s at the 60s default) — a *factor*, mirroring Checkmk's own staleness-factor UI setting shape (whose own default is 1.5×, deliberately widened here to absorb one fully missed poll cycle across the extra MQTT/broker/browser hops).
- **D-13:** Same 3× factor applies to `lan/poller/status.last_poll`, but as a page-level global condition, not a per-host mark.
- **D-14:** Poller confirmed offline (LWT fired, or `last_poll` past threshold) → persistent top banner ("Poller offline since HH:MM — data is N minutes old") + stale hatch on every row/tile. Last known values stay visible/legible.
- **D-15:** Stale never masks a known-bad child in a roll-up — group color is worst-of the *fresh* children; the group additionally gets the hatch if any child is stale (both facts preserved simultaneously).
- **D-16:** `device_type: "unknown"` means the tag group itself doesn't exist on the site (not a device category) — dismissible banner, neutral glyph fallback, degrade to a single "untyped" group.
- **D-17:** Poller additively gains Checkmk's authoritative `staleness` value and the real host state (DOWN vs UNREACHABLE, currently collapsed). Both fields additive — existing subscribers/payloads stay valid. Dashboard prefers `staleness` when present, falls back to `timestamp` age against the 3× factor. Verify both columns via `mqtt_poller.py --check-columns` against the live site before relying on them.
- **D-18:** Display name = `alias` when non-empty, else `id` (hostname). Hostname stays visible in detail panel/table column.
- **D-19:** `details.html` reads its target from a query string — `details.html?id=<hostname>` via `URLSearchParams`.
- **D-20:** Checkmk base URL and site name live in `dashboard/js/config.js` alongside broker settings (browser cannot derive them — poller reaches Checkmk over an internal container hostname).
- **D-21:** Three real HTML files (`index.html`, `devices.html`, `details.html`) that each render correctly opened cold (bookmarkable), but all load the same `js/shell.js`, with in-app navigation intercepted via `history.pushState`.
- **D-22 (REVISED):** Persistent shell with a swappable main area, dark/dense/panel-based (per `docs/DMC-networkmap.png`/`docs/DMC-server.png` layout language only — text is AI-garbled, not binding). Left column split vertically: grouped tree on top, event-history panel beneath it, both always on screen.
- **D-23 (NEW):** Clicking a host anywhere (tree/tile/row) opens the detail as an in-place panel in the main area — shell, tree, and event history stay mounted and live; URL updates via `pushState` to `details.html?id=<host>`.
- **D-24 (NEW):** `index.html` = stats-by-state strip + grouped fleet overview (the surviving half of DASH-01); this slot is where Phase 13's real map will later drop in.

### Claude's Discretion
- Exact color hex values, spacing, typography, dark-theme tokens (D-11 fixes *meaning*, not exact value)
- `device_type` → glyph mapping for the six configured types (`other`, `E-link`, `ACS`, `Multimedia`, `NetworkDevice`, `GroupController`)
- Device-table columns and default sort beyond what DASH-02 requires
- Event-panel row formatting and timestamp rendering
- Overview tile vs card shape and density
- Exact nginx configuration and the shape of the `dashboard` compose service block
- File naming/layout under `dashboard/js/vendor/`
- Internal module layout of `shell.js` and the shared state store
- How the two D-17 fields are named in the payload (should follow Phase 9 D-07's convention of mirroring Livestatus's own column naming)

### Deferred Ideas (OUT OF SCOPE)
- **To Phase 12:** CPU/RAM/disk gauges, disk-health (SMART) readouts, per-host service status list explaining "why" a host is red — requires a new `GET services` Livestatus query and `perf_data` parsing (Python, not browser JS), plus a new topic.
- **To Phase 13:** Wizard `parents` REST support; the vis-network topology map itself; vendoring `vis-network` 10.1.2; original D-08 (synthetic group-root nodes) and D-09 (stabilize-once-then-freeze physics), both fully reasoned in `11-DISCUSSION-LOG.md` and not to be re-derived.
- **Permanently out of scope:** Time-series graphing beyond the bounded transition-history strip; per-service drill-down inside the dashboard (link out to Checkmk instead); sidebar search/filter box (DASH2-02, v2); mobile-responsive polish (DASH2-01, v2); nginx reverse-proxy of `/mqtt`; restricting the 1883 TCP listener to container-internal reachability.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-------------------|
| DASH-01 | `index.html` shows an at-a-glance stats strip (counts by state) above a grouped fleet overview, merging incoming updates in place rather than re-rendering from scratch | Pattern 1 (wholesale-replace merge), Pattern 2's per-message vs per-sort-event distinction, Don't-Hand-Roll row on JSON schema tolerance; D-24 scopes this to stats-strip + overview only (map moved to DASH-07/Phase 13) |
| DASH-02 | `devices.html` shows a live sortable device table plus a recent-events panel, updating in place | Pattern 2 (vanilla-JS sortable table, ~21 rows), Pattern 1 (events topic is a wholesale bounded-array replace, per `publish_events()`/`TOPIC_EVENTS` in `mqtt_poller.py`) |
| DASH-03 | `details.html` shows a per-device drill-down with a bounded status-history strip, linking out to Checkmk's own UI for full service-level detail | D-19/D-20 mechanics (query-string routing, `config.js`-held Checkmk base URL); `device_history_topic()`'s already-bounded (`HISTORY_MAX_ENTRIES=20`) array needs only a wholesale replace on message, per Pattern 1 |
| DASH-04 | Dashboard shows a distinct stale/unknown visual state (separate from down) when a device's last-seen timestamp exceeds a threshold, or when the poller's own liveness signal goes stale | Code Example "Staleness detection preferring Checkmk's own value, falling back to timestamp age"; Pitfall 4 (unverified `staleness` column) and Pitfall 6 (must key off the new field, not the existing `state` enum) |
| DASH-05 | Dashboard shows a connection-status indicator with jittered exponential-backoff reconnect for the MQTT-over-WebSockets connection | Pattern 3 and Pitfall 1 — the central finding of this research: mqtt.js's `reconnectPeriod` is fixed-interval only, requiring a hand-rolled backoff wrapper |
| DASH-06 | Dashboard color-codes/icons hosts by device type and groups/colors by the folder-derived location/group label | Code Example "Worst-of group roll-up," Pitfall 5 (group-index scaling), D-05/D-06/D-07/D-16 mechanics |

DASH-07 (topology map) is explicitly out of scope for this phase's research per the Scope Revision — do not plan against it here.
</phase_requirements>

## Summary

This phase is a pure-consumer static site (three real HTML files, one shared `js/shell.js`, vendored `mqtt.js`) with one deliberate, narrow exception: `scripts/mqtt_poller.py` gains two additive fields (D-17). Every locked decision in `11-CONTEXT.md` (D-01 through D-24) already answers *what* to build; this research fills in *how*, at the level of exact library mechanics, exact current payload shape, and pitfalls specific to "MQTT client in a browser with no backend and no build step."

The single most consequential finding: **mqtt.js's built-in `reconnectPeriod` is a fixed interval, not exponential backoff, and has no jitter** (confirmed against the official README and a still-open upstream feature request, mqttjs/MQTT.js#561). DASH-05 ("jittered exponential-backoff reconnect") cannot be satisfied by passing an option to `mqtt.connect()` — it requires disabling the library's auto-reconnect (`reconnectPeriod: 0`) and hand-rolling the backoff loop around `client.reconnect()`, listening for `close`/`offline`/`connect`. This is exactly the kind of library-capability assumption CLAUDE.md's "verify before asserting" principle exists to catch, and it directly changes the shape of a task in the plan (it's not "wire up mqtt.js's reconnect option," it's "build a small backoff wrapper around mqtt.js's connect lifecycle").

The second consequential finding: D-17's "real host state" distinction (DOWN vs UNREACHABLE) needs **no new Livestatus column** — `state` is already in `REQUIRED_HOST_COLUMNS` and already parsed as `host_state` inside `query_devices()`; today `compute_overall_state()` just collapses `1` (DOWN) and `2` (UNREACHABLE) into the same string. The only genuinely new column is `staleness`, which is community-documented for `GET hosts` (MEDIUM confidence — not confirmed against this project's own live site) and must go through the same `available_host_columns()` / `select_host_columns()` / `--check-columns` probe path every other optional column already uses.

**Primary recommendation:** Build the dashboard as three static files sharing one `js/` module set (state store, mqtt connection wrapper with hand-rolled backoff, render functions per page), vendor `mqtt.js` 5.15.2's browser UMD bundle unmodified, keep every per-topic merge a wholesale-replace of that topic's own payload (never an append — the poller already ships bounded arrays), and extend the poller with two new additive keys on the existing `lan/devices/{id}/status` payload rather than a new topic.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| MQTT connection lifecycle (connect, subscribe, reconnect/backoff) | Browser / Client | — | No backend exists; `mqtt.js` runs entirely in the browser tab, per D-01–D-03 |
| Device/topology/history/events state store + in-place DOM merge | Browser / Client | — | D-21–D-24 lock this as vanilla JS with no server-side rendering |
| Grouping toggle, worst-of roll-up, staleness derivation | Browser / Client | — | D-05, D-06, D-12–D-15 are all pure functions over already-delivered MQTT payloads; nothing here needs a round trip |
| Static file serving (`index.html`/`devices.html`/`details.html`/`js/`/`css/`) | CDN / Static | — | New `dashboard` nginx service (D-04); nginx does no templating, proxying, or logic — pure static file host |
| MQTT broker (retained-message store, ACL, WS listener) | API / Backend | — | Already built in Phase 8; this phase only consumes it, never reconfigures it |
| Livestatus polling, diffing, and the two new D-17 fields | API / Backend | Database / Storage (Livestatus is itself a read-only view over Checkmk's live state, not a store this phase owns) | `scripts/mqtt_poller.py` is the sole write path into the MQTT "database"; D-17 extends it |
| Checkmk deep-link construction (`details.html` → Checkmk host page) | Browser / Client | — | Pure string templating from `config.js`'s base URL + `?host=<id>` (D-20); no new backend call |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `mqtt.js` | **5.15.2** [VERIFIED: npm registry — `npm view mqtt version` confirms latest dist-tag as of 2026-09-12; already the pinned choice in `.planning/research/STACK.md` D-03] | MQTT-over-WebSockets client, entirely in-browser | De facto standard browser MQTT client; ships a single-file browser UMD bundle with no runtime dependency on a bundler — matches the "no build step" constraint exactly |
| `paho-mqtt` | **2.1.0** (already deployed, unchanged by this phase) [VERIFIED: live-running in `deploy/compose.yaml`'s `poller` service] | Python MQTT publisher inside `mqtt_poller.py` | Already the project's chosen Python MQTT client (Phase 9); D-17 only adds fields to existing `publish_device_status()`, no new client library |
| `nginx` (`nginx:alpine` image) | current `alpine` tag [ASSUMED — not pinned to a digest, consistent with this repo's existing convention of moving tags for `checkmk/check-mk-raw:2.4.0-latest`, `eclipse-mosquitto:2`, `minio/minio:latest`] | Serves the three static HTML files + `js/`/`css/` with zero server-side logic | Smallest, most common static-file image; needs no config beyond a bind mount per this repo's other services (Component Responsibilities in `.planning/research/ARCHITECTURE.md`) |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Browser-native `URLSearchParams` | n/a (Web platform API) | Parse `details.html?id=<hostname>` (D-19) | No library needed — every evergreen browser supports it |
| Browser-native `history.pushState` / `popstate` | n/a (Web platform API) | Intercept in-app navigation across the 3 real HTML files without a full reload (D-21, D-23) | Standard SPA-without-a-framework technique; no router library needed for 3 fixed routes |
| Browser-native `localStorage` | n/a (Web platform API) | Persist the grouping-mode toggle per browser (D-05) | Simple key-value persistence; no need for IndexedDB at this data volume |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled backoff wrapper around mqtt.js | A dedicated reconnect-backoff micro-library (e.g. `p-retry`-style patterns) | Would be another vendored file for ~20 lines of logic; not worth a second dependency given the no-build-step, minimize-surface-area constraint |
| `mqtt.js`'s fixed `reconnectPeriod` alone | Nothing — it does not provide jitter or exponential growth (confirmed finding, see Pitfalls) | Not a real alternative; documented here because it is easy to *assume* the option exists |
| Vanilla JS table sort | A table/grid library (e.g. `Tabulator`) | Out of scope — DASH-02 asks for a simple sortable table over ~21 rows; a full grid library is unjustified weight for this row count and violates "no build step" more than a single vendored file would need to |

**Installation:**
```bash
# Dashboard has no package manager — vendor the file directly, matching D-03's committed-not-CDN choice:
curl -o dashboard/js/vendor/mqtt.min.js https://unpkg.com/mqtt@5.15.2/dist/mqtt.min.js
# (or the jsdelivr URL — both confirmed HTTP 200 and byte-identical origin package as of 2026-09-12)

# scripts/mqtt_poller.py's D-17 change needs no new Python dependency —
# `staleness` and the raw `state` int are both read via the existing
# stdlib-only Livestatus query path; no `uv add` required.
```

**Version verification:** `npm view mqtt version` → `5.15.2` (checked 2026-09-12, matches `.planning/research/STACK.md`'s prior finding — no drift since the 2026-09-05 milestone research pass). No Python package version changes in this phase.

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `mqtt` (mqtt.js) | npm | ~10 years (`mqttjs/MQTT.js`, long-established) | Tens of millions/week (Eclipse-adjacent, widely used MQTT client) | `github.com/mqttjs/MQTT.js` [VERIFIED: `npm view mqtt repository.url` → `git://github.com/mqttjs/MQTT.js.git`] | `[OK]` [VERIFIED: `slopcheck install mqtt --ecosystem npm` run 2026-09-12, verdict OK] | Approved — vendor the 5.15.2 browser UMD build |

**Packages removed due to slopcheck `[SLOP]` verdict:** none
**Packages flagged as suspicious `[SUS]`:** none

No new Python packages are introduced by this phase (D-17 uses only Livestatus columns already reachable through the existing stdlib-only query path), so no PyPI legitimacy check applies. `nginx:alpine` is a container base image, not a package-manager dependency, and is exempt from this gate the same way `eclipse-mosquitto:2`/`minio/minio:latest` were in Phases 8–9.

## Architecture Patterns

### System Architecture Diagram

```
┌───────────────────────────────── LAN ─────────────────────────────────┐
│                                                                          │
│  Browser tab (index.html / devices.html / details.html + js/shell.js)  │
│    │                                                                    │
│    │ 1. GET / (once, on load) ───────────────► dashboard (nginx:8090)  │
│    │                                             serves static files    │
│    │                                             only — no logic        │
│    │                                                                    │
│    │ 2. mqtt.connect('ws://<location.hostname>:9002')                  │
│    │    with wsreader / wsreader (D-01, D-02)                          │
│    ▼                                                                    │
│  mosquitto:9002(WS)/1883(TCP) ── same broker, same retained store ──┐  │
│    ▲                                                                 │  │
│    │ 3. subscribe lan/devices/+/status, lan/devices/topology,        │  │
│    │    lan/devices/+/history, lan/events/recent, lan/poller/status  │  │
│    │    → broker replies with every matching RETAINED message        │  │
│    │      immediately on SUBACK (no poller round trip)               │  │
│    │                                                                 │  │
│    │ 4. publish (retained, QoS per D-07/Phase-9 rules) ◄─────────────┘  │
│    │                                                                    │
│  scripts/mqtt_poller.py (unchanged loop shape; D-17 adds 2 fields)      │
│    │                                                                    │
│    │ 5. GET hosts (Livestatus/TCP :6557) — one query per cycle         │
│    │    + one REST folder lookup per cycle                             │
│    ▼                                                                    │
│  checkmk container (source of truth: state, staleness, folder, tags)   │
│                                                                          │
└──────────────────────────────────────────────────────────────────────┘

Client-side data flow (per incoming MQTT message):
  on 'message' → parse topic → route to one of:
    lan/devices/{id}/status   → stateStore.devices.set(id, payload)      → re-render 1 row/tile
    lan/devices/topology      → stateStore.topology = payload            → re-render tree/overview shape
    lan/devices/{id}/history  → stateStore.history.set(id, payload)      → re-render 1 sparkline (details.html only)
    lan/events/recent         → stateStore.events = payload              → re-render event panel (wholesale replace)
    lan/poller/status         → stateStore.pollerStatus = payload        → toggle global stale banner (D-13/D-14)
  Every payload above is already a complete, bounded snapshot for its topic
  (the poller never sends deltas) — the client's job is "replace this one
  slot in the store, then re-render only what reads that slot," never
  "accumulate."
```

### Recommended Project Structure

```
dashboard/
├── index.html            # D-24: stats-by-state strip + grouped fleet overview
├── devices.html           # DASH-02: sortable device table + recent-events panel
├── details.html           # DASH-03: per-device drill-down, ?id=<hostname> (D-19)
├── css/
│   └── dashboard.css      # dark/dense theme (D-22 discretion: exact tokens)
└── js/
    ├── config.js          # D-01/D-02/D-20: broker creds, WS port, Checkmk base URL/site
    ├── vendor/
    │   └── mqtt.min.js    # D-03: vendored, committed, 5.15.2 browser UMD
    ├── mqtt-connection.js # connect + hand-rolled jittered backoff wrapper (see Pitfall below)
    ├── state-store.js     # in-memory Maps: devices, history, events, topology, pollerStatus
    ├── staleness.js       # pure functions: isDeviceStale(), isPollerStale() (D-12/D-13)
    ├── grouping.js         # pure functions: groupByFolder(), groupByDeviceType(), worstOf() (D-05/D-06)
    ├── render-shell.js     # persistent chrome: connection indicator, sidebar tree, event panel (D-22/D-23)
    ├── render-index.js     # stats strip + overview tiles
    ├── render-devices.js   # sortable table
    ├── render-details.js   # detail panel, history strip, Checkmk deep link
    └── shell.js            # entry point all 3 HTML files load: wires pushState routing (D-21),
                             # instantiates the mqtt connection once, dispatches to the
                             # render-*.js module matching the current view
```

`deploy/compose.yaml` gains one service (structure matches the existing `dashboard` stub already sketched in `.planning/research/ARCHITECTURE.md`, updated for D-04's real port and this repo's actual `deploy/` bind-mount conventions):

```yaml
  dashboard:
    image: nginx:alpine
    container_name: dashboard
    restart: unless-stopped
    volumes:
      - ../dashboard:/usr/share/nginx/html:ro,z
    ports:
      - "8090:80"     # D-04
    networks:
      - cmk_net
```

### Pattern 1: Wholesale-replace merge, never append, on every topic

**What:** On each `message` event, `JSON.parse` the payload and **replace** the store's entry for that topic/device wholesale — never push/concat onto an existing array.
**When to use:** Every one of this project's topics, because the poller already publishes the *full* bounded array (history, events) or the *full* current object (status, topology) every time — Pitfall 6 in `.planning/research/PITFALLS.md` documents exactly this trap for a browser client that "helpfully" appends instead.
**Example:**
```javascript
// state-store.js
client.on('message', (topic, payloadBuf) => {
  const parts = topic.split('/');
  let payload;
  try {
    payload = payloadBuf.length ? JSON.parse(payloadBuf.toString()) : null; // zero-length = tombstone
  } catch {
    return; // malformed retained message — ignore, keep last-known-good (mirrors poller's own tolerance)
  }
  if (parts[1] === 'devices' && parts[3] === 'status') {
    const id = parts[2];
    if (payload === null) { store.devices.delete(id); }
    else { store.devices.set(id, payload); }        // REPLACE, not merge-append
    rerenderDevice(id);
  } else if (topic === 'lan/devices/topology') {
    store.topology = payload;                        // whole object replace
    rerenderTree();
  } else if (parts[1] === 'devices' && parts[3] === 'history') {
    store.history.set(parts[2], payload || []);       // whole bounded array replace
    if (currentView === 'details' && currentDeviceId === parts[2]) rerenderHistoryStrip();
  } else if (topic === 'lan/events/recent') {
    store.events = payload || [];                     // whole bounded array replace
    rerenderEventPanel();
  } else if (topic === 'lan/poller/status') {
    store.pollerStatus = payload;
    rerenderStaleBanner();
  }
});
```

### Pattern 2: Sortable table without a library (vanilla JS)

**What:** A single click handler on `<th>` elements that re-sorts the in-memory device array and re-renders `<tbody>` rows via `innerHTML` diffing keyed by `data-id`, not a full table teardown.
**When to use:** DASH-02's device table, ~21 rows at current fleet size (per `device_types.json`'s scope and `STATE.md`'s "21 onboarded hosts" figure) — well within vanilla-JS territory; no virtualization or library needed.
**Example:**
```javascript
// render-devices.js
let sortKey = 'id', sortDir = 1;
function renderTable() {
  const rows = [...store.devices.values()].sort((a, b) =>
    sortDir * (a[sortKey] > b[sortKey] ? 1 : a[sortKey] < b[sortKey] ? -1 : 0)
  );
  const tbody = document.querySelector('#device-table tbody');
  tbody.replaceChildren(...rows.map(rowFor));  // full rebuild is fine at 21 rows/re-sort event (not per-message)
}
function rerenderDevice(id) {
  const row = document.querySelector(`tr[data-id="${CSS.escape(id)}"]`);
  const fresh = rowFor(store.devices.get(id));
  if (row) row.replaceWith(fresh); else renderTable(); // new device: full re-sort needed anyway
}
document.querySelectorAll('#device-table th[data-key]').forEach(th =>
  th.addEventListener('click', () => {
    const key = th.dataset.key;
    sortDir = (sortKey === key) ? -sortDir : 1;
    sortKey = key;
    renderTable();
  })
);
```
Note the split: a **per-message** update (`rerenderDevice`) only touches one `<tr>` (this is what makes DASH-02's "update in place" true); a **sort-triggered** update rebuilds the whole `<tbody>` (acceptable — it's a user click, not a streaming event, and 21 rows is trivial).

### Pattern 3: Hand-rolled jittered exponential backoff around mqtt.js (see Pitfalls — mqtt.js does not provide this)

**What:** Disable mqtt.js's own fixed-interval reconnect (`reconnectPeriod: 0`) and drive reconnection manually from the `close`/`offline` events, computing `delay = min(maxDelay, base * 2**attempt) * (0.5 + Math.random() * 0.5)` and calling `client.reconnect()` after that delay; reset `attempt` to 0 on `connect`.
**When to use:** DASH-05, exactly as specified — "reconnects with jittered exponential backoff."
**Example:**
```javascript
// mqtt-connection.js — Source: mqtt.js README (github.com/mqttjs/MQTT.js) confirms
// reconnectPeriod is a fixed interval with no jitter/backoff (verified 2026-09-12);
// this wrapper supplies what the library does not.
const BASE_DELAY_MS = 1000, MAX_DELAY_MS = 30000;
let attempt = 0;
let reconnectTimer = null;

const client = mqtt.connect(`ws://${location.hostname}:${WS_PORT}`, {
  username: WS_USERNAME,
  password: WS_PASSWORD,
  reconnectPeriod: 0,          // disable mqtt.js's own fixed-interval retry
  connectTimeout: 30 * 1000,   // library default, stated explicitly for clarity
  clean: true,                 // a fresh client identity each page load is correct here —
});                             // retained messages arrive regardless of clean session (see Pitfalls)

function scheduleReconnect() {
  const delay = Math.min(MAX_DELAY_MS, BASE_DELAY_MS * 2 ** attempt) * (0.5 + Math.random() * 0.5);
  attempt += 1;
  setConnectionIndicator('reconnecting', delay);
  reconnectTimer = setTimeout(() => client.reconnect(), delay);
}

client.on('connect', () => { attempt = 0; clearTimeout(reconnectTimer); setConnectionIndicator('connected'); });
client.on('close', scheduleReconnect);
client.on('offline', () => setConnectionIndicator('disconnected'));
client.on('error', (err) => console.error('MQTT error', err)); // must not throw — see mqtt.js docs on unhandled 'error'
```

### Pattern 4: Poller extension is additive fields on an existing topic, not a new topic

**What:** D-17 adds `staleness` (float, from Livestatus) and a distinct real-host-state signal to the *existing* `lan/devices/{id}/status` payload — it does not introduce a fourth device-scoped topic.
**When to use:** Any time a new field is "more detail about a thing that already has a topic," per this project's own `topics.py`-equivalent single-source-of-contract pattern (`.planning/research/ARCHITECTURE.md` Pattern/Structure Rationale) — new topics are for new *kinds* of entities, not new fields on an existing one.
**Example (the shape to extend, based on the live file read of `scripts/mqtt_poller.py:699-711`):**
```python
# DeviceSnapshot gains two fields (defaults preserve every existing call site,
# per this codebase's own convention for additive dataclass fields — see
# alias's own D-09/D-10 precedent, mqtt_poller.py:298-303):
@dataclass
class DeviceSnapshot:
    id: str
    state: str                    # UNCHANGED: still the worst-of aggregate string
    ...
    staleness: float | None = None      # NEW: raw Livestatus `staleness`, None if column absent/unqueryable
    host_state_raw: str = "UP"          # NEW: "UP" | "DOWN" | "UNREACH", from the *already-fetched* `state` int
                                          # (0/1/2 — no new column needed, see compute_overall_state below)

# compute_overall_state already receives host_state (int); it just never
# returned the distinction. A second, small function derives the new field
# from data query_devices() already has in hand:
def host_state_label(host_state: int) -> str:
    return {0: "UP", 1: "DOWN", 2: "UNREACH"}.get(host_state, "UP")

# publish_device_status: two new keys appended to the existing dict —
# existing subscribers that don't know these keys are unaffected (JSON
# objects tolerate unknown keys; this is what "additive" means in practice).
payload = {
    "id": snapshot.id, "state": snapshot.state, ...,
    "staleness": snapshot.staleness,
    "host_state_raw": snapshot.host_state_raw,
    "timestamp": timestamp,
}
```

### Anti-Patterns to Avoid

- **Assuming `mqtt.js`'s `reconnectPeriod` gives you exponential backoff or jitter:** it does not (see Pattern 3 and Pitfalls). Passing a bigger number just changes the fixed interval.
- **`network.setData()`-style full re-render on every MQTT message:** this project has no `vis-network` in this phase, but the same anti-pattern applies to the DOM — never `innerHTML = ''` + rebuild the whole tree/table/overview on a single device's status update; only the affected row/tile/group should repaint (DASH-01/02 explicitly require "merge in place").
- **Appending to `history`/`events` client-side:** the poller already sends the full bounded array every time it changes (Pitfall 6, `.planning/research/PITFALLS.md`); appending client-side double-bounds incorrectly and leaks memory on a long-lived kiosk tab.
- **Treating a stale group the same as a worst-of-red group:** D-15 requires both signals to coexist (red fill AND hatch pattern) — collapsing them into one visual state loses information the operator needs.
- **Writing the WS credentials fetch as a `fetch('config.json')` call:** D-01 locks `config.js` as a committed `<script>`-tag file, not a fetched JSON resource — this avoids a race between page load and config availability and needs no CORS/MIME configuration on nginx.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| MQTT wire protocol / WebSocket framing | A raw `WebSocket` + hand-parsed MQTT packets | `mqtt.js` (vendored) | MQTT's binary framing (fixed header, variable-length remaining-length encoding, packet-identifier tracking for QoS 1/2) is exactly the kind of "deceptively complex protocol" this guidance exists for; mqtt.js already handles it correctly against Mosquitto |
| Retained-message replay-on-subscribe semantics | Any client-side "ask the broker for current state" round trip | Native MQTT `retain` flag + `subscribe()` | This is a broker-guaranteed behavior (mosquitto delivers retained messages immediately on SUBACK) — building a client-side cache-warming request would duplicate what the protocol already provides for free |
| Exponential backoff *math* (the formula itself) | A bespoke ad-hoc "wait a bit longer each time" counter with magic numbers | The standard `min(max, base * 2**n) * jitter_factor` formula (Pattern 3) | This is a well-known, well-tested formula (AWS/Google SRE literature); reinventing the constants risks either hammering the broker (no cap) or an unbounded wait (no cap on the other end) |
| JSON schema/version tolerance for retained payloads | Nothing new — already solved | `scripts/mqtt_poller.py`'s own `_normalise_restored_node()` pattern (defensive `.get()` + `isinstance` checks) is the project's precedent; the dashboard's `state-store.js` should apply the same defensive-parse discipline to payloads it did not itself just publish (a payload from an older poller version may lack `staleness`/`host_state_raw`) | Mirrors an already-debugged pattern in this exact codebase (see the two dated bug-fix comments at `mqtt_poller.py:819-853`) rather than re-discovering the same class of bug in JS |

**Key insight:** Everything genuinely hard in this phase (MQTT framing, retained-message delivery, per-cycle diffing) is already solved by an existing library or an already-shipped, already-tested Python module. The only "build it yourself" surface this phase legitimately owns is the backoff *policy* (a ~20-line wrapper) and the rendering/grouping logic (inherently application-specific, not a solved-problem library fit).

## Common Pitfalls

### Pitfall 1: Assuming mqtt.js's `reconnectPeriod` satisfies DASH-05 as-is

**What goes wrong:** A plan/task that says "pass `reconnectPeriod: 5000` to `mqtt.connect()`" ships a fixed 5-second retry forever — no growth, no jitter — which technically "reconnects" but does not meet DASH-05's literal requirement and reintroduces `.planning/research/PITFALLS.md` Pitfall 5's synchronized-reconnect-storm risk (every open dashboard tab retries at the exact same fixed interval after a shared broker restart).
**Why it happens:** The option is *named* `reconnectPeriod` and *sounds* like it configures "the reconnect strategy" in general; the README does document a default and lets you override it, so it reads as configurable when what's actually configurable is only the fixed interval's length.
**How to avoid:** Set `reconnectPeriod: 0` (disables the built-in retry entirely) and drive reconnection from `close`/`offline` via a manual `setTimeout` + `client.reconnect()` loop, per Pattern 3 above.
**Warning signs:** Multiple browser tabs' Network/WS panels show reconnect attempts landing at visually identical timestamps after a `podman compose restart mosquitto`.

### Pitfall 2: Treating `clean: true` (mqtt.js's default) as a reason retained messages won't arrive

**What goes wrong:** A developer sees `clean session = true` in mqtt.js's default options and assumes "since we're not persisting a session, we'll miss messages" and reaches for `clean: false` — which does nothing useful here and is a wasted broker-side session-table entry per browser tab (every page load is a new/random client, so a persistent session never gets reused anyway — the exact "brand new browser tab" case `.planning/research/ARCHITECTURE.md` Anti-Pattern 3 already documents for this project).
**Why it happens:** MQTT persistent sessions and retained messages are two genuinely different, easily-conflated mechanisms — this exact confusion is called out in this project's own `.planning/research/ARCHITECTURE.md` Pattern 2 ("Broker-persisted retain... is a different mechanism from MQTT persistent sessions").
**How to avoid:** Keep `clean: true` (the mqtt.js default; no need to even specify it). Retained-message delivery on `subscribe()` is entirely independent of the clean-session flag.
**Warning signs:** None expected if `clean: true` is kept — this is a preventive note, not a symptom to detect after the fact.

### Pitfall 3: Publishing an unhandled `'error'` listener gap crashes nothing visibly but silently drops the connection-status UI

**What goes wrong:** mqtt.js emits `'error'` on connection failures (auth rejection, DNS failure, etc.); if no listener is attached, Node's EventEmitter semantics (which mqtt.js inherits, including in its browser build) throw on an unhandled `'error'` event, which in a browser context surfaces as an uncaught exception that can abort the rest of `shell.js`'s initialization silently (no dashboard renders at all, no visible reason why).
**Why it happens:** It's easy to wire `connect`/`close`/`offline`/`message` and forget `error`, since the "happy path" tests never trigger it (wrong WS credentials, or a typo'd `location.hostname`-derived host, would).
**How to avoid:** Always attach `client.on('error', ...)` even if it only logs — never leave it unhandled (Pattern 3's example above includes this deliberately).
**Warning signs:** Dashboard shows a blank page with no console-visible reason, specifically when WS credentials or the derived broker host are wrong — an easy first-deploy mistake to hit and misdiagnose as "the broker is unreachable" when it's actually an unhandled-exception crash of the init script.

### Pitfall 4: D-17's `staleness` column may not exist on the target site (unverified against the live `dmc` site)

**What goes wrong:** Community sources (Nagios/Livestatus forums, general MK Livestatus documentation patterns) document a `staleness` column on `GET hosts`, and this is very likely accurate (Livestatus computes it generically for any table with a check interval), but — unlike `parents`/`filename`/`alias`/`tags`, which this project's own `mqtt_poller.py` comments record as *live-verified* against the real `dmc` site on 2026-09-08 and 2026-09-11 — `staleness` has never been probed against this specific site/version (2.4.0p36.cre). Coding against an assumed column name that turns out to be spelled differently, or absent, silently degrades: `select_host_columns()` already handles an absent optional column gracefully (logs a warning, omits it), so the failure mode is "the field is quietly always `null`," not a crash — but a planner who doesn't know this needs a live-verification checkpoint might ship code that works in every unit test yet never actually populates the field in production.
**Why it happens:** Checkmk publishes no static, versioned column reference for the `hosts` table (confirmed by fetching `docs.checkmk.com/latest/en/livestatus_references.html` directly — it explicitly tells you to run `GET columns` live rather than enumerating columns in the docs).
**How to avoid:** Follow this project's own established precedent exactly: add `"staleness"` to `OPTIONAL_HOST_COLUMNS`, then run `uv run python scripts/mqtt_poller.py --check-columns` against the live `dmc` site (the same tool that resolved `parents`/`filename`/`tags`/`alias` in Phases 9–10) **before** trusting the field in any downstream dashboard logic, exactly as D-17 itself instructs ("Planning should confirm both columns via `mqtt_poller.py --check-columns`").
**Warning signs:** Every device's `staleness` value in the retained MQTT payload is `null` even for a host that has clearly not reported in a long time.

### Pitfall 5: A group's roll-up color computed from a `Map` iteration order that isn't guaranteed stable across re-renders

**What goes wrong:** D-06's worst-of + count-badge roll-up needs to iterate every child device in a group on every incoming per-device status message (to recompute both the roll-up color and the count). If this iterates `store.devices` (a `Map` keyed by hostname) without also maintaining a `groupId → Set<hostname>` index, recomputing "which children belong to group X" becomes an O(n) scan of the *entire* fleet on every single device update — harmless at 21 hosts, but the wrong shape to build and one `.planning/research/ARCHITECTURE.md`-style "measure, don't guess" habit worth encoding in the plan now rather than after Phase 12/13 grow the fleet.
**Why it happens:** The natural first implementation is "just filter the devices map by group on demand," which is correct but O(n) per update; it's easy to not notice this scales poorly until device count grows.
**How to avoid:** Maintain a secondary index (`groupId -> Set<hostname>`) alongside `store.devices`, updated whenever a device's group-relevant fields (`folder`, `device_type`) change via the topology topic (which is the only topic that carries those fields per `topology_nodes()` in `mqtt_poller.py:352-362`) — the roll-up recompute for one group is then O(group size), not O(fleet size).
**Warning signs:** None visible at 21 hosts; this is a "build it right from the start" pitfall, not a symptom-driven one, given Phase 12/13 will grow both fleet size and update frequency on the same store.

### Pitfall 6: Reusing the poller's `state` field values to drive the dashboard's UNREACH color, instead of the new `host_state_raw` field

**What goes wrong:** The existing `state` field (already shipped, already consumed by nothing yet) only ever contains `{"OK","WARN","CRIT","UNKNOWN","DOWN"}` — it structurally *cannot* say `"UNREACH"`, because `compute_overall_state()` deliberately collapses both raw states 1 and 2 into the string `"DOWN"` (see `mqtt_poller.py:340-344`, and the inline comment naming both Nagios codes). A dashboard developer who reads only the *payload* (not the poller source) might reasonably expect `state` itself to eventually contain `"UNREACH"` once D-17 lands, and build a switch statement keyed on `state` that silently never hits the UNREACH branch.
**Why it happens:** D-17 is described as adding "real host state" — it's a natural but wrong inference that this means the *existing* `state` field's enum grows, rather than a **new**, differently-named field being added alongside it (which is what "additive... existing subscribers... stay valid" actually requires).
**How to avoid:** Palette/state-switch code in `render-*.js` must branch on the **new** field (e.g. `host_state_raw`) for the DOWN/UNREACH visual distinction, and only fall back to `state` for the OK/WARN/CRIT/UNKNOWN branches it was always meant to cover.
**Warning signs:** Every UNREACH host in the fleet renders identically to a DOWN host despite D-17 having shipped — the classic "the data is there, the UI just reads the wrong key" bug.

## Code Examples

### Staleness detection preferring Checkmk's own value, falling back to timestamp age (D-12, D-17)

```javascript
// staleness.js
// Source: 11-CONTEXT.md D-12 (3x poll-interval factor) and D-17
// ("dashboard should prefer Checkmk's `staleness` when present and fall
// back to timestamp-age against the 3x factor").
const POLL_INTERVAL_SECONDS = 60;      // config.js constant, mirrors mqtt_poller.py's own default
const STALENESS_FACTOR = 3;            // D-12

function isDeviceStale(devicePayload, nowMs = Date.now()) {
  if (devicePayload.staleness != null) {
    // Checkmk's own authoritative value: staleness is expressed in
    // check-interval multiples already (same shape as Checkmk's UI
    // setting, see D-12's rationale) — compare directly to the factor.
    return devicePayload.staleness >= STALENESS_FACTOR;
  }
  // Fallback for a payload published before D-17 landed, or a site where
  // `--check-columns` found `staleness` unavailable (Pitfall 4).
  const ageSeconds = (nowMs - Date.parse(devicePayload.timestamp)) / 1000;
  return ageSeconds >= STALENESS_FACTOR * POLL_INTERVAL_SECONDS;
}

function isPollerStale(pollerStatusPayload, nowMs = Date.now()) {
  // D-13: same factor, but a page-level global condition, not per-host.
  if (!pollerStatusPayload || pollerStatusPayload.status === 'offline') return true; // LWT fired
  if (!pollerStatusPayload.last_poll) return false; // birth message, not yet stale
  const ageSeconds = (nowMs - Date.parse(pollerStatusPayload.last_poll)) / 1000;
  return ageSeconds >= STALENESS_FACTOR * POLL_INTERVAL_SECONDS;
}
```

### Worst-of group roll-up with stale-never-masks-known-bad (D-06, D-15)

```javascript
// grouping.js
// Checkmk's own severity order (mirrors compute_overall_state's WARN<CRIT
// asymmetry with DOWN/UNREACH always dominating — see mqtt_poller.py:340).
const SEVERITY_RANK = { OK: 0, PEND: 0, WARN: 1, UNKNOWN: 2, CRIT: 3, UNREACH: 3, DOWN: 4 };

function rollUpGroup(deviceIds, store, nowMs = Date.now()) {
  let worst = 'OK', worstRank = 0, nonOkCount = 0, anyStale = false;
  for (const id of deviceIds) {
    const device = store.devices.get(id);
    if (!device) continue;
    if (isDeviceStale(device, nowMs)) { anyStale = true; continue; } // D-15: excluded from worst-of, not counted as bad
    const effectiveState = device.host_state_raw === 'UNREACH' ? 'UNREACH' : device.state;
    const rank = SEVERITY_RANK[effectiveState] ?? SEVERITY_RANK.UNKNOWN;
    if (rank > worstRank) { worst = effectiveState; worstRank = rank; }
    if (effectiveState !== 'OK') nonOkCount += 1;
  }
  return { worst, nonOkCount, hatched: anyStale }; // D-15: red-and-hatched is a valid, meaningful combination
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| paho-mqtt.js as the "official" browser MQTT client (paired historically with Python's paho-mqtt) | `mqtt.js` is the community-standard browser client | Predates this project; already the correct call in `.planning/research/STACK.md` | No change needed — this phase's D-03 already matches current practice |
| paho-mqtt v1 callback API (`Client()` with no `CallbackAPIVersion`) | `CallbackAPIVersion.VERSION2` required since paho-mqtt 2.0 | paho-mqtt 2.0 release (already adopted in Phase 9's `mqtt_poller.py`) | Not this phase's concern — D-17 only edits an already-VERSION2 file; no migration needed |
| Assuming MQTT client libraries provide exponential backoff out of the box | mqtt.js still does not (confirmed 2026-09-12; open GitHub issue #561 unresolved) | No change — this is a persistent gap, not a regression | Directly shapes DASH-05's implementation (Pattern 3) |

**Deprecated/outdated:** Nothing in this phase's stack has moved since the 2026-09-05 milestone research pass (`.planning/research/STACK.md`) — re-verified current as of 2026-09-12.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|----------------|
| A1 | The Livestatus `hosts` table exposes a `staleness` column on the live `dmc` site (2.4.0p36.cre) | Standard Stack / Pitfall 4 | If absent or differently named, `staleness` stays `null` forever and the dashboard falls back to timestamp-age staleness only (a documented, graceful degradation — not a crash) — but a plan that doesn't include the `--check-columns` verification step as an explicit task risks shipping dead code silently |
| A2 | `nginx:alpine` (moving tag, no digest pin) is an acceptable choice for the new `dashboard` service | Standard Stack | Matches this repo's existing convention for other services' tags (`eclipse-mosquitto:2`, `minio/minio:latest`); low risk, but an image update could in theory change default behavior between deploys — same risk profile as the other 4 services already accept |
| A3 | mqtt.js 5.15.2's `error` event, if unhandled, throws in the browser build the same way it does in Node (EventEmitter semantics) | Pitfall 3 | If the browser build actually swallows unhandled `'error'` events instead (behavior not independently confirmed by directly executing code in this research pass, only inferred from mqtt.js's Node-derived EventEmitter base), the failure mode is merely "silent connection failure with no console error" rather than "script crash" — the mitigation (always attach the listener) is correct either way, so this assumption does not change the recommended action, only its exact symptom |

**If this table is empty:** N/A — see above.

## Open Questions (RESOLVED)

Both questions below are operationally closed by the Phase 11 plan set — see the
"Resolved by" line under each. Left in place because the reasoning behind each
resolution is the useful part, not the question itself.

1. **Exact spelling/availability of the `staleness` Livestatus column on the target site**
   - What we know: community sources consistently document `staleness` as a real column computable for both `hosts` and `services` tables in MK Livestatus implementations generally; this project's own docs-URL fetch confirms Checkmk provides no static column reference and directs live verification instead.
   - What's unclear: whether the exact string `"staleness"` (vs., e.g., a Checkmk-specific rename) is what this site's 2.4.0p36.cre Livestatus actually exposes.
   - Recommendation: the plan's first D-17 task should be a live `--check-columns`-style probe (extending the existing `available_host_columns()` call) before any code assumes the column exists, exactly as D-17's own text already instructs.
   - **Resolved by:** plan `11-01` — a standalone wave-1 plan whose only job is that live probe, recording the result as a dated comment. It gates `11-04` (wave 2) and `11-06` (wave 3), each of which carries the stated timestamp-age fallback if the column turns out to be absent.

2. **Whether `mqtt.js`'s browser build differs from its Node build in unhandled-`'error'`-event behavior**
   - What we know: the README documents the `error` event identically for both environments; the library is a single isomorphic codebase.
   - What's unclear: this research pass did not execute the browser bundle in an actual browser console to directly observe the unhandled-exception behavior (only read documentation/source-adjacent community discussion).
   - Recommendation: attach the listener regardless (Pattern 3 already does) — this makes the open question moot for implementation purposes; only relevant if someone is tempted to skip it as "probably fine."
   - **Resolved by:** plan `11-05` — the connection module attaches the `error` listener unconditionally, so the browser-vs-Node difference cannot be reached.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Podman/Docker + the existing 4-service compose stack | New `dashboard` service joins `deploy/compose.yaml` | ✓ (on the LAN deploy host — confirmed via `STATE.md`/Phase 8-10 SUMMARY.md history of live deployment; not present in this research sandbox, which is expected — this sandbox is not the deploy target) | Podman (rootless), per `docs/Podman setup for checkmk, minio, mosquitto, worker.md` | — |
| Mosquitto WS listener (`9002:9001`) | D-01/D-02, every browser MQTT connection | ✓ (live-verified in Phase 8's `08-03-SUMMARY.md`/`smoke_test_broker.py` per `check_ws_subscribe`) | Mosquitto 2.x, `protocol websockets` | — |
| `wsreader` / `wsreader` credentials in `deploy/mosquitto.passwd` | D-01 | ✓ (`deploy/gen-mosquitto-passwd.sh` confirms the exact defaults; documented in `docs/Podman setup...md` §6) | n/a | — |
| Network egress to unpkg.com/jsdelivr.net (for the one-time vendoring `curl`, not at runtime) | D-03 vendoring step | ✓ (confirmed both CDN URLs return HTTP 200 for `mqtt@5.15.2` from this research sandbox on 2026-09-12) | n/a | Manual download from `https://github.com/mqttjs/MQTT.js` releases if CDN access is unavailable from the actual deploy host |
| Live Checkmk site (`dmc`, 2.4.0p36.cre) reachable for the `--check-columns` staleness probe | D-17, Pitfall 4/Open Question 1 | Not verified in this research pass (no live site reachable from this sandbox) | — | None — this is a hard prerequisite for D-17's staleness field to ever populate; must be run against the real deploy host before/during planning's verification steps |

**Missing dependencies with no fallback:**
- Live-site reachability for the `--check-columns` staleness probe (Open Question 1) — must happen against the real `dmc` site, not in a sandbox, before D-17's `staleness` field can be trusted.

**Missing dependencies with fallback:**
- CDN reachability for vendoring `mqtt.min.js` — a manual GitHub-release download is a viable one-time fallback if the deploy host itself has no internet egress (consistent with D-03's own "monitoring LAN with no internet egress" framing — the vendoring/build step happens on a dev machine with egress, then the resulting file is committed and reaches the LAN via git, not via the LAN pulling from a CDN at runtime).

## Security Domain

`security_enforcement` is not set to `false` in `.planning/config.json`, so this section is included per the default-enabled rule — scoped to what actually applies to a static, unauthenticated-by-design, LAN-only dashboard (per `PROJECT.md`'s explicit Out of Scope: "Multi-user accounts/login... broker-level ACL is the only access control layer").

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | Explicitly out of scope by design (`PROJECT.md`) — broker-level read-only ACL (`wsreader`, Phase 8 D-03) is the only access boundary, not a user-authentication layer |
| V3 Session Management | No | No user sessions exist; each browser tab is a stateless, anonymous MQTT client identity |
| V4 Access Control | Partial | Enforced entirely at the broker (Mosquitto ACL, already built in Phase 8) — the dashboard has no access-control logic of its own to get wrong |
| V5 Input Validation | Yes | Every value rendered into the DOM (`alias`, `folder`, `device_type`, event descriptions) originates from Checkmk via the poller and MQTT — none of it is attacker-supplied in the traditional sense, but Checkmk itself allows an operator to type an `alias` containing arbitrary characters, so rendering must still avoid `innerHTML` with unescaped string interpolation |
| V6 Cryptography | No | `ws://`/plaintext is the accepted posture for this LAN-only deployment (mirrors the project's existing plaintext-HTTP-to-Checkmk convention, documented as an accepted tradeoff in `.planning/research/PITFALLS.md`'s Security Mistakes table) — not revisited by this phase |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|-----------------------|
| Stored/reflected DOM-based XSS via an operator-set `alias` or event description rendered with `innerHTML = payload.alias` | Tampering / Elevation of Privilege (if a compromised or malicious LAN device could ever influence retained payloads) | Use `textContent` (or an equivalent escaping helper) for every dynamically-rendered string field, never raw `innerHTML` string interpolation — cheap, and closes the gap even though the realistic attacker model here is "a misbehaving/compromised device on the LAN able to publish to `lan/#`," which the read-only `wsreader` ACL (Phase 8) already prevents from the browser side, but does not prevent from a rogue TCP-side publisher using the `poller` credentials if those were ever leaked |
| A malicious LAN device publishing forged retained payloads over the *TCP* listener (1883, `poller` user creds) that the WS-side dashboard then renders unescaped | Tampering | Out of this phase's scope to prevent at the broker level (Phase 8 already scoped `poller`'s credentials to that listener); this phase's only obligation is not to compound a forged-payload risk into an XSS risk by rendering it unsafely — same mitigation as above |
| `details.html?id=<value>` used directly as a `lan/devices/{id}/status` topic-subscription segment without validation | Tampering (topic-injection, `+`/`#` wildcard abuse) | D-19's own rationale already covers this: `is_publishable_device_id()` server-side (poller) rejects any hostname containing `+ # /` at publish time, so a crafted query string can at most subscribe to a topic that will never have a retained message — no wildcard escalation is possible purely from a URL parameter, but the dashboard should still not blindly interpolate the query param into a *subscribe* call without at minimum stripping `+`/`#` defensively, since a URL is a more attacker-reachable input surface than a Livestatus-sourced hostname |

## Sources

### Primary (HIGH confidence)
- `scripts/mqtt_poller.py` (read in full, this session) — the authoritative current MQTT contract: topics (`TOPIC_TOPOLOGY`, `TOPIC_EVENTS`, `TOPIC_POLLER_STATUS`, `device_status_topic()`, `device_history_topic()`), `DeviceSnapshot` fields, `compute_overall_state()` (lines 340-344, confirms the DOWN/UNREACH collapse D-17 must undo), `REQUIRED_HOST_COLUMNS`/`OPTIONAL_HOST_COLUMNS` (lines 140-151), `publish_device_status()` payload shape (lines 699-711), QoS/retain rules per topic
- `tests/test_mqtt_poller.py` (function names enumerated, this session) — existing test conventions D-17 must extend (e.g. `test_compute_overall_state_host_down_or_unreachable_wins_outright`, `test_query_devices_alias_defaults_to_empty_string_when_column_absent` as the precedent shape for a new `staleness`/`host_state_raw` default test)
- `deploy/compose.yaml`, `deploy/mosquitto.conf`, `deploy/mosquitto.acl`, `deploy/gen-mosquitto-passwd.sh` (read in full, this session) — confirms D-01/D-02/D-04's exact deployed shape: `wsreader`/`wsreader` read-only on `topic read lan/#`, WS listener at container `9001`→host `9002`, 1883 published with `poller` auth, `allow_anonymous false`, `persistence true`
- `docs.checkmk.com/latest/en/livestatus_references.html` (fetched this session) — confirms Checkmk provides no static per-table column reference and directs live `GET columns` verification, corroborating this project's own `--check-columns` precedent
- `github.com/mqttjs/MQTT.js` README (fetched this session, `raw.githubusercontent.com/mqttjs/MQTT.js/main/README.md`) — confirms browser UMD global (`mqtt`), `connect()` option defaults (`reconnectPeriod: 1000`, `connectTimeout: 30000`, `clean: true`, `keepalive: 60`), and the exact event names/signatures used in Pattern 3
- `npm view mqtt version` / `npm view mqtt repository.url` (run this session) — confirms `5.15.2` is the current published version and the source repo matches the official `mqttjs/MQTT.js` project
- `slopcheck install mqtt --ecosystem npm` (run this session, verdict `[OK]`) — package legitimacy check per this project's audit protocol
- `.planning/phases/11-live-dashboard/11-CONTEXT.md` and `11-DISCUSSION-LOG.md` (read in full) — the 22 locked decisions and the scope-revision history this research does not relitigate

### Secondary (MEDIUM confidence)
- WebSearch results corroborating a `staleness` column on `GET hosts` in MK Livestatus (multiple independent community sources: Nagios support forum, `cerebro` project's Livestatus notes, `simplified.guide`'s Checkmk Livestatus query guide) — not confirmed against this project's own live site (see Open Question 1)
- WebSearch results confirming Livestatus's `state` column values (0=UP, 1=DOWN, 2=UNREACHABLE) for the `hosts` table — cross-checked against `mqtt_poller.py`'s own inline comment at line 342 (`# 1=DOWN, 2=UNREACHABLE`), which independently states the same mapping, giving two-source agreement
- WebSearch results on mqtt.js's lack of built-in exponential backoff/jitter, corroborated by the still-open `mqttjs/MQTT.js#561` GitHub issue requesting exactly this feature

### Tertiary (LOW confidence)
- None retained as authoritative in this document — every WebSearch finding above was either cross-verified against a second independent source or against this project's own live-verified code comments.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — mqtt.js version/repo/legitimacy independently re-verified this session; no drift from the 2026-09-05 milestone research
- Architecture: HIGH — the poller contract, broker deployment, and ACL shape were all read directly from live-deployed source/config files, not inferred
- Pitfalls: MEDIUM-HIGH — the mqtt.js reconnect-backoff gap and the `staleness` column uncertainty are both flagged with explicit confidence caveats and concrete verification steps rather than asserted as settled fact

**Research date:** 2026-09-12
**Valid until:** 30 days (stable stack, no fast-moving dependencies; re-verify mqtt.js version and the live `staleness` column probe result if planning is delayed past this window)
