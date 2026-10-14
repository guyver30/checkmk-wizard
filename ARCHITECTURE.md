# Architecture

Detailed container topology of the `master` branch, drawn in
[`ARCHITECTURE_TOPOLOGY.excalidraw`](ARCHITECTURE_TOPOLOGY.excalidraw) (open at excalidraw.com or in an
Excalidraw editor extension). Source of truth: `deploy/compose.yaml`, `deploy/mosquitto.acl.template`,
`deploy/dashboard-nginx.conf`, `scripts/mqtt_poller.py`, `analytics/`. All containers share the `cmk_net`
bridge network. Grafana is intentionally omitted from the diagram and from this document.

## How the pieces fit together

```
monitored hosts ──▶ checkmk ──Livestatus──▶ mqtt-poller ──MQTT──▶ mosquitto ──WebSockets──▶ browser
                       ▲  ▲                     │ INSERT                ▲  │ lan/# state
         REST          │  │ REST                ▼                       │  ▼
 automation-worker ────┘  └── dashboard      clickhouse ◀── analytics ──┘ (needs, forecasts, narration)
                              (nginx)           │  ▲            │
                                ▲ /ch-api/      ▼  │            ▼ rollups
                                └───────────── minio ◀──────────┘
```

In one sentence: **Checkmk is the only source of truth about the network; everything else either configures
it (worker), reads it and republishes it (poller), derives insight from that stream (analytics), stores
history (ClickHouse, MinIO), or shows it (dashboard).** Live state travels over retained MQTT topics; history
travels over ClickHouse and MinIO; configuration writes go only through Checkmk's REST API.

## Container roles

### `checkmk` — the monitoring system itself

- **What it is:** the stock `checkmk/check-mk-raw:2.4.0` Community Edition image, running one OMD site
  (`CMK_SITE_ID`, default `dmc`). It is the authoritative store of hosts, folders, rules, parents, service
  states and check results.
- **What it exposes:**
  - Web UI and REST API on `:5000` (published as host `8080`).
  - Agent TLS registration on `:8000` and agent pull on `:6556`.
  - Livestatus over TCP on `:6557`, reachable only on `cmk_net`. A pre-start hook
    (`checkmk-hooks/pre-start/10-livestatus-tcp-plaintext.sh`) switches off Livestatus TLS so the poller can
    use the plain LQL protocol.
- **Who talks to it:** monitored hosts (agents and SNMP), the worker (REST), the poller (Livestatus, REST),
  and the dashboard's nginx (REST, allow-listed).
- **State:** volume `checkmk_data` holds the whole OMD site, so the configuration survives restarts.

### `automation-worker` — the wizard's runtime

- **Role:** a long-idle `python:3.12-slim` shell (`tail -f /dev/null`) that has this repository mounted at
  `/app`. The operator runs `uv run checkmk-wizard` inside it. It drives the seven wizard phases: site
  bring-up, folders, network discovery, classification, host onboarding (including SSH agent install),
  discovery, and activation.
- **Why a separate container:** it must work against a containerized Checkmk without touching the
  `checkmk` container's filesystem (the project's container boundary), so every operation goes through the
  REST API (`http://checkmk:5000/<site>/check_mk/api/1.0`) as the `automation` user.
- **Also provisions:** the narrowly-scoped `topology_editor` role/user whose secret is later injected by the
  dashboard's nginx, and the `automation` credentials written into `deploy/.env`.
- **Connects to:** Checkmk REST only (in practice); the compose file also hands it the MQTT and S3
  endpoints, which the wizard does not currently use in the container flow.

### `mqtt-poller` — Checkmk → MQTT bridge and history writer

- **Role:** a standalone script (`scripts/mqtt_poller.py`, deliberately not part of the installable
  package) that every 15 s (`POLL_INTERVAL_SECONDS`) queries Checkmk and republishes the result.
- **Reads:**
  - Livestatus `:6557` for host and service state, check results, performance data and the event log.
  - REST `:5000` (as `automation`) for what Livestatus lacks: each host's folder, map position and
    unmanaged-switch marker.
- **Publishes (retained, under `sites/<site_id>/`):**
  - `lan/devices/<id>/status` and `lan/devices/<id>/services` per device.
  - `lan/devices/topology` for the parent/child graph.
  - `lan/events/recent`, a bounded array (1000 entries) of state changes.
  - `lan/incidents/<id>/status` for correlated incidents.
  - A poller status/last-will message so the dashboard can tell the poller is down.
  - Tombstones (empty retained payloads) for devices that disappeared, only after a safe sweep gate.
- **Writes history:** inserts host state, service state and metrics rows into ClickHouse over HTTP `:8123`
  as `poller_writer`. This is the **only writer of fleet history**. History is enrichment; a ClickHouse
  failure never blocks live publishing.
- **Executes admin commands:** subscribes to `admin/cmd`, validates the payload strictly, turns it into a
  Livestatus external command (fake host up/down for demos) and publishes `admin/ack` and the retained
  `admin/faked`.
- **State:** none of its own; it reconciles retained topics against Checkmk on start.

### `mosquitto` — the live-state broker

- **Role:** Eclipse Mosquitto 2, the single bus for live state. Keeps retained messages, so a browser that
  connects mid-day immediately receives the current picture without any backend.
- **Listeners:** `:1883` plain MQTT (published on the LAN for debugging and used by the poller and
  analytics) and `:9001` WebSockets (published as host `9002`, used by the browser).
- **Security model:** anonymous access is off. Passwords are generated from `deploy/.env` at start. The ACL
  is rendered per deployment from `mosquitto.acl.template`, scoped to `sites/<site_id>/`:

  | User | Purpose | Rights |
  |------|---------|--------|
  | `poller` | the poller | read/write `sites/<site_id>/#` |
  | `analytics` | analytics | read `lan/#` and `needs/triage/cmd`; write `lan/needs/#`, `lan/forecasts/#`, `lan/incidents/+/narration` |
  | `wsreader` | dashboard, default view | read `lan/#` |
  | `wsadmin` | dashboard admin view (`?admin=1`) | read `lan/#`, `admin/ack`, `admin/faked`; write `admin/cmd` |
  | `wstriage` | dashboard triage action | write `needs/triage/cmd` only |

- **State:** volumes `mosquitto_data` (persistence, autosave every 60 s) and `mosquitto_log`.

### `analytics` — needs, forecasts and incident narration

- **Role:** the derived-insight service (`analytics/`, run as `python -m analytics`). It turns the poller's
  raw fleet stream into things an operator should act on. It has no inbound port.
- **Consumes:** `lan/#` from MQTT (device status, services, events, incidents) and triage commands from
  `needs/triage/cmd`. Input is treated as untrusted JSON.
- **Produces (retained MQTT):**
  - `lan/needs/<need_id>/status`: prioritized "needs" with tiers (immediate / urgent / standard). Sources
    are failures, trends that will reach a critical level, and sustained or breached readings
    (`rules.py`).
  - `lan/forecasts/<host>`: trend-fit anchors and crossing dates (`fit.py`, ordinary least squares with a
    quality gate). The browser never refits; it draws the published line.
  - `lan/incidents/<id>/narration`: template-only, English-only text (`narrate.py`). No model or external
    service is called; nothing leaves the operator's tenancy.
- **Records (ClickHouse, as `analytics_writer`):** events, incidents and triage audit rows
  (`recorder.py`, `triage.py`).
- **Rolls up availability (MinIO):** daily availability JSON and Parquet objects into the
  `fleet-availability` bucket (`rollup.py`), with automatic 28-day backfill. Writes are never-overwrite.
- **Triage:** validates every command from the dashboard (strict shape, whitelisted actions, capped text)
  and audits it. Triage overrides are dropped automatically if the computed tier worsens.
- **Resilience:** every insert and publish is best-effort; a failure degrades one cycle and self-corrects
  on the next. Evaluation runs every 900 s.

### `clickhouse` — fleet history store

- **Role:** ClickHouse 26.9, the analytical database for history. Database `history` holds `metrics`,
  `host_state`, `service_state`, `availability_daily`, `events`, `incidents` and `need_triage`.
- **Storage:** hot data lives on local disk (`clickhouse_data`); parts older than 31 days are moved to an S3 disk
  backed by MinIO (bucket `clickhouse-s3-disk`) by ClickHouse's own tiered-storage TTL (see Data flow, path 10).
  volume `clickhouse_data` for metadata.
- **Access:** HTTP `:8123` on `cmk_net` only (no published port). Users, created on first start from
  `initdb/02-users.sh`:

  | User | Rights |
  |------|--------|
  | `ch_admin` | administration |
  | `poller_writer` | insert history |
  | `analytics_writer` | insert plus S3 export for rollups |
  | `dashboard_reader` | `readonly = 1`, SELECT on `history` only |

### `minio` — object storage

- **Role:** S3-compatible store (S3 API `:9000`, console `:9001`, both published).
- **Holds:**
  - `clickhouse-s3-disk`: ClickHouse's table data.
  - `fleet-availability`: daily availability JSON and Parquet rollups written by analytics. Anonymous
    read is enabled so the dashboard can fetch them through nginx.
- **State:** volume `minio_data`.

### `minio-init` — one-shot bucket bootstrap sidecar

- **Role:** waits for MinIO, creates both buckets (idempotent `mc mb --ignore-existing`), sets anonymous
  download on `fleet-availability`, then exits. ClickHouse declares a dependency on it so its S3 disk has
  a bucket to open.

### `dashboard` — nginx plus the React SPA

- **Role:** serves the static React + TypeScript + Tailwind single-page app (built from `dashboard-react/`)
  on `:80` (published as host `8090`). It is **not** an application server; it adds no backend logic. The
  SPA subscribes to MQTT over WebSockets directly from the browser.
- **What the SPA shows:** the topology map (including a shared drawing layer), device and service state,
  incident cards with narration, needs with triage, forecast charts, and an admin view for faking host
  up/down in demos.
- **nginx locations (the only things it does server-side):**

  | Location | Behaviour |
  |----------|-----------|
  | `/` | static SPA with fallback |
  | `/config.json`, `/admin-config.json`, `/triage-config.json` | rendered at start from env: broker URL, site id and the `wsreader`, `wsadmin`, `wstriage` logins (open on the closed demo network) |
  | `/map-drawing.json` | `GET`/`PUT` of exactly one JSON file (256 KB cap, `application/json` only) on volume `map_drawing_data`, via the stock DAV module |
  | `/checkmk-api/` | method + path allow-list to Checkmk REST; nginx injects the `topology_editor` secret so the browser holds no credential; everything else returns 403 |
  | `/ch-api/` | `GET`-only proxy to ClickHouse `:8123` as `dashboard_reader` (used by the forecast chart) |
  | `/availability/` | `GET`-only proxy to MinIO `fleet-availability` rollup objects |

### Operator browser — the client

- Loads the SPA over HTTP `:8090`, then opens its own MQTT WebSocket connection to `:9002`. Live state
  comes from there; edits and activations go through `/checkmk-api/`; history charts go through
  `/ch-api/` and `/availability/`; triage and admin actions are MQTT publishes with the write-only
  `wstriage` and `wsadmin` logins.

## Port summary

| Container | Container port → host | Purpose |
|-----------|-----------------------|---------|
| `checkmk` | 5000 → 8080 | Web UI and REST |
| `checkmk` | 8000 → 8000 | agent TLS registration |
| `checkmk` | 6556 → 6556 | agent pull |
| `checkmk` | 6557 (internal) | Livestatus TCP |
| `mosquitto` | 1883 → 1883 | MQTT |
| `mosquitto` | 9001 → 9002 | MQTT over WebSockets |
| `minio` | 9000 → 9000 | S3 API |
| `minio` | 9001 → 9001 | console |
| `clickhouse` | 8123 (internal) | HTTP interface |
| `dashboard` | 80 → 8090 | SPA and same-origin proxies |

## Connection summary

| From | To | Protocol | Notes |
|------|----|----------|-------|
| monitored hosts | `checkmk` | Agent TCP `:6556` / TLS `:8000` | SNMP and ping probes originate from Checkmk |
| `automation-worker` | `checkmk` | REST/HTTP `:5000` | user `automation` |
| `mqtt-poller` | `checkmk` | Livestatus/TCP `:6557`, REST `:5000` | read-only for state; external commands for admin |
| `mqtt-poller` | `mosquitto` | MQTT/TCP `:1883` | user `poller` |
| `mqtt-poller` | `clickhouse` | HTTP `:8123` | user `poller_writer` |
| `analytics` | `mosquitto` | MQTT/TCP `:1883` | user `analytics` |
| `analytics` | `clickhouse` | HTTP `:8123` | user `analytics_writer` |
| `analytics` | `minio` | S3/HTTP `:9000` | rollup objects |
| `clickhouse` | `minio` | S3/HTTP `:9000` | storage disk |
| `minio-init` | `minio` | `mc`/HTTP `:9000` | one-shot |
| `dashboard` | `checkmk` | REST/HTTP `:5000` | allow-listed `/checkmk-api/` |
| `dashboard` | `clickhouse` | HTTP `:8123` | `GET` `/ch-api/` |
| `dashboard` | `minio` | HTTP `:9000` | `GET` `/availability/` |
| browser | `dashboard` | HTTP `:8090` | SPA and proxies |
| browser | `mosquitto` | MQTT/WebSockets `:9002` | live state, admin and triage commands |

Volumes: `checkmk_data`, `mosquitto_data`, `mosquitto_log`, `minio_data`, `clickhouse_data`,
`map_drawing_data`.

## Data flow

A macro view (ingestion → processing → broker → stores → presentation) is in
[`DATA_FLOW_HIGHLEVEL.excalidraw`](DATA_FLOW_HIGHLEVEL.excalidraw). The detailed view is in
[`DATA_FLOW.excalidraw`](DATA_FLOW.excalidraw): sources on the left, the broker in the centre,
stores on the right. Dashed arrows are asynchronous paths and red labels are triggers. Topics are relative to
`sites/<site_id>/`.

| # | Path | Trigger | What moves |
|---|------|---------|------------|
| 1 | hosts → Checkmk core | Checkmk check interval | agent / SNMP / ping results become host and service state |
| 2 | wizard → Checkmk REST | operator runs the wizard | hosts, folders, rules, activation; activation reloads the core |
| 3 | Livestatus → `mqtt-poller` | cron, every 15 s | LQL `GET hosts`, `GET services`, `GET log` over `:6557`; REST `GET host_config` for folder, position, switch marker |
| 4 | `mqtt-poller` → `mosquitto` | each poll | retained `lan/devices/{id}/status` (QoS 0), `lan/devices/{id}/services`, `lan/devices/topology`, `lan/events/recent`, `lan/incidents/{id}/status`, `lan/poller/status` (QoS 1); tombstones for removed devices |
| 5 | `mqtt-poller` → ClickHouse | each poll | `INSERT … FORMAT JSONEachRow` into `history.metrics`, `host_state`, `service_state` |
| 6 | `mosquitto` → `analytics` | on event | QoS 1 subscriptions: `lan/devices/+/status`, `lan/devices/+/services`, `lan/devices/topology`, `lan/events/recent`, `lan/incidents/+/status`, `needs/triage/cmd`; a 5 s restore window also reads retained `lan/needs/+/status` and `lan/incidents/+/narration` at start |
| 7 | `analytics` → `mosquitto` | failure needs every 15 s; trend needs and forecasts every 900 s | retained `lan/needs/{need_id}/status`, `lan/forecasts/{host}`, `lan/incidents/{id}/narration` |
| 8 | `analytics` ↔ ClickHouse | event / evaluation | INSERT `events`, `incidents`, `need_triage`; SELECT hourly metrics as fit input |
| 9 | `analytics` → ClickHouse → MinIO (daily availability rollup) | scheduler tick every 30 s; a day is rolled up once it has ended plus a 5 min delay (`ROLLUP_DELAY_MINUTES`); never the current day; auto-backfills 28 days; retries after 300 s on failure | For each device, folder and the fleet: UP / DOWN / UNREACHABLE / scheduled-downtime / no-data minutes and `availability_pct = up / (up + down) × 100`, computed from `history.host_state` samples (one sample = one 15 s poll) over the local day in `ROLLUP_TZ`. Rows go to `history.availability_daily`, then to MinIO bucket `fleet-availability` as JSON `availability/YYYY/MM/YYYY-MM-DD.json` and Parquet `availability_parquet/date=YYYY-MM-DD/availability.parquet` (exported from the same rows, so they cannot drift). HEAD-before-PUT: objects are never overwritten, so a day is computed once and then frozen |
| 10 | ClickHouse → MinIO (tiered storage sync) | not scheduled by any application: ClickHouse's background TTL/merge machinery, once a part's rows are older than 31 days (`TTL ts + INTERVAL 31 DAY TO VOLUME 's3'`); also when local free space drops below 20 % (`move_factor 0.2`) | Whole data parts of `history.metrics`, `host_state` and `service_state` (policy `s3_tiered`) move from the local `default` volume to the `s3` disk, i.e. objects under `clickhouse-s3-disk/data/`; only metadata stays local. Reads of tiered data go through a 2 GiB filesystem cache (`s3_cache`). Nothing flows for the first 31 days. Other tables (`availability_daily`, `events`, `incidents`, `need_triage`) never move |
| 11 | `mosquitto` → browser | on event | WebSocket `:9002`, `wsreader` subscribes to `lan/#` |
| 12 | browser → `mosquitto` | user action | `admin/cmd` (`wsadmin`) and `needs/triage/cmd` (`wstriage`) |
| 13 | `mosquitto` → `mqtt-poller` → core | on `admin/cmd` | validated command becomes a Livestatus `COMMAND [ts] …`; the poller publishes `admin/ack` and retained `admin/faked` |
| 14 | ClickHouse / MinIO → nginx → browser | page load, chart view | `GET /ch-api/` hourly series for the forecast chart; `GET /availability/` rollup objects |
| 15 | browser → nginx → Checkmk REST | edit mode, discovered-hosts banner | `/checkmk-api/` allow-list with `topology_editor` injected by nginx |
| 16 | browser ↔ nginx ↔ `map_drawing_data` | map edit | `GET` / `PUT /map-drawing.json` (JSON only, 256 KB cap) |

Data lifecycle in ClickHouse (`metrics`, `host_state`, `service_state`): 0–30 days raw rows on local disk; 30 days
rolled up to 5-minute buckets (mean/min/max, worst state); 31 days parts moved to MinIO; 365 days rolled up to
1-hour buckets; 1095 days deleted.

Persistence: live state is retained MQTT (`mosquitto_data`); history is ClickHouse (hot) plus MinIO (tiered); availability
rollups are MinIO objects; the map drawing layer is one file on `map_drawing_data`; configuration lives in
Checkmk (`checkmk_data`).
