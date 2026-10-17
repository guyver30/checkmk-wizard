# Architecture

Detailed container topology of the `master` branch, drawn in
[`ARCHITECTURE_TOPOLOGY.excalidraw`](ARCHITECTURE_TOPOLOGY.excalidraw) (open at excalidraw.com or in an
Excalidraw editor extension). Source of truth: `deploy/compose.yaml`, `deploy/mosquitto.acl.template`,
`deploy/dashboard-nginx.conf`, `scripts/mqtt_poller.py`, `analytics/`. All containers share the `cmk_net`
bridge network. Grafana is intentionally omitted from the diagram and from this document.

This is the reference for what the pieces are and how data moves. To deploy and operate them see
[`docs/DEPLOY-NEW-MACHINE.md`](docs/DEPLOY-NEW-MACHINE.md); for the wizard see [`docs/WIZARD-OPERATION.md`](docs/WIZARD-OPERATION.md). The MQTT topic contract and
the cloud archive contract are at the end of this document.

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

## MQTT topic contract (poller)

The `poller` service (`scripts/mqtt_poller.py`) is the only publisher on these topics; everything else is a consumer. Browser clients read them over the WebSockets listener (endpoint table in [`docs/DEPLOY-NEW-MACHINE.md`](docs/DEPLOY-NEW-MACHINE.md) §6) with the read-only `wsreader` credentials — only the `poller` user can publish.

**Per-site namespace (Phase 14.3).** Every topic below lives under `sites/<site_id>/`, where `site_id` is `CMK_SITE_ID`, the Checkmk site id. The rows keep the full prefixed form; the dashboard strips the prefix once at its MQTT edge (`dashboard-react/src/lib/topics.ts`), so its stores see the relative `lan/...` form.

**Broker ACL.** `deploy/mosquitto.acl` is no longer a tracked file. The `mosquitto` container renders it at start from `deploy/mosquitto.acl.template` by running `deploy/render-mosquitto-acl.sh`, which substitutes a validated `CMK_SITE_ID` for `@SITE_ID@`. Mosquitto ACL files have no environment expansion, so rendering is how the grants get scoped to one site subtree. Per-user grants:

| User | Grants |
| --- | --- |
| `poller` | `readwrite sites/<site_id>/#` |
| `wsreader` | `read sites/<site_id>/lan/#` |
| `wsadmin` | `read sites/<site_id>/lan/#`, `read sites/<site_id>/admin/ack`, `read sites/<site_id>/admin/faked`, `write sites/<site_id>/admin/cmd` |
| `analytics` | `read sites/<site_id>/lan/#`, `read sites/<site_id>/needs/triage/cmd`, `write sites/<site_id>/lan/needs/#`, `write sites/<site_id>/lan/forecasts/#`, `write sites/<site_id>/lan/incidents/+/narration` |
| `wstriage` | `write sites/<site_id>/needs/triage/cmd` |

Phase 14.2 added topics written by the `analytics` service, not the poller: `sites/<site_id>/lan/needs/{need_id}/status`, `sites/<site_id>/lan/forecasts/{host}` and `sites/<site_id>/lan/incidents/{incident_id}/narration` (all QoS 1, retained, tombstoned when they no longer apply), and the browser-published, non-retained `sites/<site_id>/needs/triage/cmd`. Their writers, payload keys and tombstone rules are in Appendix A below. The table below lists the poller's topics only.

| Topic | Publish Trigger | QoS | Retain | Payload keys |
| --- | --- | --- | --- | --- |
| `sites/<site_id>/lan/devices/{id}/status` | Every poll cycle, for every known device | 0 | true | `id`, `state` (`OK`/`WARN`/`CRIT`/`UNKNOWN`/`DOWN`), `in_downtime`, `acknowledged`, `device_type`, `folder`, `alias`, `address`, `staleness`, `host_state_raw`, `timestamp`, `cpu_percent`, `cpu_warn`, `cpu_crit`, `cpu_load1`, `cpu_load5`, `cpu_load15`, `cpu_load_warn`, `cpu_load_crit`, `ram_percent`, `ram_warn`, `ram_crit`, `disk_percent`, `disk_warn`, `disk_crit`, `disk_other_worst_percent`, `disk_other_worst_warn`, `disk_other_worst_crit`, `disk_other_worst_mount`, `smart_total`, `smart_failing` |
| `sites/<site_id>/lan/devices/topology` | Only when the id+parents+device_type+folder structure changes vs. the previous cycle, or a label changes (`map_position`, `unmanaged`, `criticality`, `service_criticality`, `depends_on`) | 1 | true | `devices` (list of `{id, parents, device_type, folder, alias, map_position, unmanaged, criticality, service_criticality, depends_on}`), `timestamp` |
| `sites/<site_id>/lan/devices/{id}/services` | Only when a service's state changes or the service set changes (never on `plugin_output` alone) | 1 | true | JSON array of `{description, state, plugin_output}` — every monitored service except the CPU/RAM/Filesystem/SMART gauge-backing services |
| `sites/<site_id>/lan/events/recent` | Only on any device's state transition, or a device add/remove | 1 | true | Full bounded array (max `EVENTS_MAX_ENTRIES`, default 1000, about 160 KB when full) of `{timestamp, device_id, event, from, to}` |
| `sites/<site_id>/lan/poller/status` | Birth (on connect), heartbeat (every poll cycle), and LWT (on ungraceful disconnect) or graceful stop | 1 | true | `{status, since, last_poll, device_count}` (birth/heartbeat) or `{status: "offline"}` (LWT/graceful stop) |
| `sites/<site_id>/lan/incidents/{incident_id}/status` | Only when an incident opens, closes, or its root, consequence set, dependents or worst criticality change | 1 | true | `id`, `root`, `root_state`, `inferred`, `confirmed_down`, `not_observable`, `dependents`, `worst_criticality`, `since`, `timestamp` |

A removed device is tombstoned by publishing an empty retained payload to its `status` and `services` topics (and, for one release, the retired `history` and `service_history` topics, which the poller no longer publishes; transition history lives in ClickHouse). On startup the poller also tombstones, the same way, any retained per-device topic whose host is absent from the site, and clears any retained `history`/`service_history` topic once; this is gated so that a failed or unconfirmed-empty Livestatus query never clears anything, and it adds no `removed` event.

`folder` is a generic location/group label derived from the host's Checkmk folder — whatever grouping the operator chose in the wizard's Phase 2 (a VLAN, a physical location, a site, etc.). It is read from Checkmk's REST folder association (`fetch_host_folders()` in `scripts/mqtt_poller.py`), not parsed from a filesystem path — see [`docs/DEPLOY-NEW-MACHINE.md`](docs/DEPLOY-NEW-MACHINE.md) §3.5 for the credential this requires. `alias` is Checkmk's native host alias, set optionally through the wizard's Phase 4 prompt; it is empty for any host without one. `address` is the host's configured IP, read from Livestatus's `hosts.address` column; it is empty for a host with no configured address (e.g. an unmanaged switch), and absent entirely from payloads written by a poller older than quick task 260928-m6f.

`state` on an agent host (one with a `Check_MK Agent` service) is the worst of the services the dashboard shows — the wizard-chosen `Systemd Service <unit>` / `Service <name>` entries, `TCP Port N` checks, CPU, memory, filesystem and SMART services, `Check_MK` and `Uptime` — not Livestatus's `worst_service_state`, so a service the dashboard hides (for example `Systemd Timesyncd Time` or `Systemd Service Summary`) cannot turn the host CRIT (quick 261003-lnr). Hosts without an agent, and any host whose host state is DOWN/UNREACHABLE, are unchanged. On a cycle whose services query failed the host-column state is published as before.

`staleness` (Phase 11, D-17) is Checkmk's own authoritative Livestatus `staleness` value (a float), additive to the payload above. It is `null` when the live site's `hosts` table does not expose the column — a graceful degradation, not an error; a consumer should then fall back to a timestamp-age check against `timestamp` above. `host_state_raw` (Phase 11, D-17) is also additive: one of `UP`/`DOWN`/`UNREACH`, derived from Checkmk's raw host-state integer. **`state` never contains `"UNREACH"`** — it keeps its collapsed `OK`/`WARN`/`CRIT`/`UNKNOWN`/`DOWN` meaning, folding both DOWN and UNREACHABLE raw states into `"DOWN"`; a consumer that needs to tell them apart must read `host_state_raw` instead. Both fields are additive — a subscriber written before Phase 11 sees a payload it already understands, just without these two keys.

The twenty gauge keys above (Phase 12, D-12; the five `cpu_load*` keys added in quick 261008-d0w) — `cpu_percent`/`cpu_warn`/`cpu_crit`, `cpu_load1`/`cpu_load5`/`cpu_load15`/`cpu_load_warn`/`cpu_load_crit`, `ram_percent`/`ram_warn`/`ram_crit`, `disk_percent`/`disk_warn`/`disk_crit`, `disk_other_worst_percent`/`disk_other_worst_warn`/`disk_other_worst_crit`/`disk_other_worst_mount`, `smart_total`/`smart_failing` — are additive to `status` and follow the same null-when-absent convention as `staleness`: each is `null` when its backing Checkmk service does not exist, never an omitted key. `sites/<site_id>/lan/devices/{id}/services` is a new topic, not an additive payload, so no pre-Phase-12 subscriber is affected by its existence — it is simply absent from a subscriber that has not added the new subscription.

**`sites/<site_id>/lan/incidents/{incident_id}/status` (Phase 14, PLR-14/PLR-15/PLR-16):** the incident id is `incident-{root host id}`; a closed incident is cleared with an empty retained payload, the same tombstone contract as every other topic above. The poller rebuilds the full incident set from Livestatus every cycle — there is no poller-side incident file — and, after a restart, `reconcile_state()` reads only the retained incident *topic names* (never the payload body) so the first post-restart cycle republishes a still-open incident unchanged or tombstones one that closed while the poller was down. Grouping rules, one sentence each:

- A DOWN host whose parent is not an unmanaged switch is a root.
- UNREACH hosts, and DOWN hosts reachable through a contiguous chain of non-OK hosts, join the topmost root.
- An unmanaged switch becomes an *inferred* root when at least two of its children are non-OK and at least one of those is DOWN, and every consequence of an inferred incident is reported as `not_observable`, never `confirmed_down` (Checkmk cannot see past an unchecked switch).
- A lone DOWN host under an unmanaged switch is its own incident, not folded into the switch.

`since` comes from Livestatus's `last_state_change` and is `null` if the column is absent (or every candidate value is non-positive). `worst_criticality` counts the root, every consequence, and every host that transitively depends on them (host-level criticality only — per-service criticality does not feed this in Phase 14) and defaults to `low` until an operator sets criticality labels. Known v1 limitation: an unrelated host that happens to be DOWN at the same time, inside the same non-OK chain, is folded into the incident as a consequence — Livestatus's `parents`/`host_state_raw` alone cannot disambiguate "down because of the incident" from "coincidentally also down".

**Criticality and dependency labels (Phase 14, PLR-16/DASH-16):** three Checkmk host labels drive
the incident engine's severity and dependency fan-out above. All three are written by the
dashboard's "Edit topology" mode (the `CriticalityEditor` panel, plan 14-08) using the same
`topology_editor` credential Phase 13's map edits already use — no new Checkmk permission is
needed — and go live only once **Apply changes** is pressed, identical to every other topology
edit. They can equally be hand-edited directly in Checkmk (Setup > Hosts > *host* > Labels); the
poller reads whichever value Checkmk actually stores, dashboard or not.

- `criticality`: one of `low`/`medium`/`high`/`critical`, set on the host itself. Absent, or any
  other value, degrades to `low`.
- `service_criticality`: `<name>=<tier>;<name>=<tier>;...`, a per-service override on the host. A
  service name may not contain `:` (reserved by Checkmk's own service naming), `;` or `=` (this
  label's own separators). Stored and republished on every topology node, but does **not** feed
  `worst_criticality` in Phase 14 — only host-level `criticality` does.
- `depends_on`: `<host>,<host>,...`, set on the *dependent* host, listing the hosts it depends on.
  This is what lets `worst_criticality` count a still-UP dependent one tier below a critical host
  it depends on that is currently down (D-15).

The poller's label parsers never raise: an out-of-vocabulary tier, a malformed entry (missing
`=`, empty name, a name containing a reserved character), or an invalid host id is silently
dropped rather than rejected or crashing the poll cycle. Both multi-value labels are capped
against a runaway label value — `service_criticality` at 200 entries, `depends_on` at 50 ids —
counting only the entries that parsed successfully, not raw comma/semicolon-split segments.

---

## Appendix A: MQTT contract walkthrough and history-over-MQTT proposal

> **Update 2026-10-04 (Phase 14.3):** every topic now lives under `sites/<site_id>/`, where `site_id` is
> `CMK_SITE_ID`, and the broker ACL is rendered per deployment from `deploy/mosquitto.acl.template`. The
> worked examples below keep the relative suffixes for readability: read each `lan/...` or `admin/...` topic
> as `sites/<site_id>/lan/...` or `sites/<site_id>/admin/...`. The formal topic tables use the full form.

> **Update 2026-10-04 (Phase 14.2):** the analytics container now exists and publishes three more topics
> (needs, forecasts, incident narration) and consumes one (the triage command). They are documented in
> [Phase 14.2 analytics topics](#phase-142-analytics-topics) at the end of Appendix A. The `history/#`
> proposal in Part 1 is superseded for 14.2 (see the note there).

Written 2026-10-03 during the Phase 14.2 discussion, for whoever builds the cloud side (broker, ClickHouse,
analytics container, new dashboard). It has three parts:

1. How the poller publishes today, how its history rows are assembled, and the proposal to move history
   writing onto MQTT (a proposal, not yet a locked decision).
2. A worked timeline showing exactly which messages the poller publishes when a host changes.
3. How the current dashboard consumes those topics, and what a different broker location would change.
4. Bandwidth options for a metered link (4G) with many sites feeding one cloud broker.

The examples were built from the code (`publish_*` and `compute_incidents` in `scripts/mqtt_poller.py`) and
the topic table in "MQTT topic contract (poller)" above. They were not captured from
a live broker, and timestamps are shortened. The Podman doc stays the reference for the formal topic table.

---

#### Part 1: how the poller publishes, and the history proposal

##### Target architecture (decided 2026-10-03)

- **On-prem:** Checkmk, the poller, the worker.
- **Cloud (own tenancy, which counts as inside the network):** broker, AWS S3, ClickHouse, a new dashboard,
  Grafana, and the analytics container.
- Local-first today (everything on one machine), split later with config-only changes where possible.

##### What the poller publishes today (every 15 s cycle, `run_cycle`)

| Topic | When | QoS | Retained |
|---|---|---|---|
| `sites/<site_id>/lan/devices/{id}/status` | every cycle, every host | 0 | yes |
| `sites/<site_id>/lan/devices/{id}/services` | only when the service list changes | 1 | yes |
| `sites/<site_id>/lan/events/recent` | only on any host's state change, add or remove | 1 | yes |
| `sites/<site_id>/lan/incidents/{incident_id}/status` | only when an incident opens or its content changes | 1 | yes |
| `sites/<site_id>/lan/devices/topology` | only when structure or a label changes | 1 | yes |
| `sites/<site_id>/lan/poller/status` | birth, every cycle, last will | 1 | yes |

Removed 2026-10-04 (quick 261004-kbt): per-device `history` and `service_history` are no longer published;
host/service transition history comes only from ClickHouse (`history.host_state`, `history.service_state`).
Already-retained copies are cleared once at poller startup.

Things to know:

- It is all MQTT and mostly **retained whole-state**, not a stream of events. `events` is a bounded array
  that is rewritten whole.
- A closed incident is **tombstoned**: an empty retained payload clears its topic. No "closed" message is
  ever delivered, and a subscriber that is offline at that moment never learns the incident ended.
- The history rows for ClickHouse are **not** on MQTT. After MQTT publishing, `build_history_rows()` turns the
  cycle's already-fetched data into rows and `write_history()` POSTs them to ClickHouse over HTTP:
  - `history.host_state`: one row per host (state code, downtime flag, folder).
  - `history.service_state`: one row per service (state code).
  - `history.metrics`: one row per `perf_data` label (value, warn, crit).
  - Every row in a cycle carries the same UTC timestamp. There is no buffering: if ClickHouse is
    unreachable that cycle's rows are dropped and the gap reads as "no data" (D-44, D-47).

##### The proposal: publish history over MQTT, write to ClickHouse from the cloud

> **Shipped in Phase 17:** see "Phase 17: cloud contract and archive feed" at the end of this document for the history topics, envelope and `event_id`.

> **Superseded for Phase 14.2 (D-02/D-03).** 14.2 does not add `history/samples`, `history/events` or
> `history/incidents`. The analytics container instead reads the existing `lan/events/recent` and
> `lan/incidents/+/status` topics (interim ingestion, see the Decisions at the end) and writes
> `history.events`, `history.incidents` and `history.need_triage` itself. The poller still writes
> `history.host_state`, `history.service_state` and `history.metrics` straight to ClickHouse. The
> transport redesign described below is a later phase; read the rest of this section as that later
> proposal.

- Replace `write_history()`'s HTTP insert with a **publish** of the same rows, for example one message per
  cycle on `history/samples` (QoS 1, not retained). `build_history_rows()` itself does not change.
- Publish discrete messages for events and incident open/close on `history/events` and `history/incidents`
  (QoS 1, not retained). The retained `lan/events/recent` array is awkward for a database writer, because it
  is rewritten whole and would need deduplicating.
- The **analytics container** subscribes to `history/#` with a persistent session and inserts into
  ClickHouse over HTTP, locally. The poller then holds no ClickHouse credentials, and ClickHouse is never
  exposed to the internet. The poller's only outbound dependency becomes the broker.

Implications to plan for:

- **ACL.** The browser user `wsreader` can read `sites/<site_id>/lan/#`. The `history/` prefix must sit outside it, so the
  dashboard never receives raw samples. Only the poller writes it, and only the analytics user reads it.
- **Message size.** With real agent hosts a cycle is thousands of rows, probably hundreds of KB as one JSON
  message. Not measured. Measure with:
  `SELECT count() FROM history.metrics WHERE ts = (SELECT max(ts) FROM history.metrics)`.
  If large, split the batch per host.
- **Duplicates.** QoS 1 is at-least-once, so a redelivery could insert a batch twice. Give each batch an id
  so the writer can deduplicate (a planning detail).
- **Persistence.** Mosquitto already has `persistence true`, which queues messages for a persistent
  subscriber while it is offline.
- **WAN outage.** Routing history through MQTT does not by itself fix it, because the poller can't reach the
  broker either. A local Mosquitto bridged to the cloud broker would queue messages during an outage. I
  believe Mosquitto bridges support that but have not verified it; check with the docs before relying on it.

##### Consequence: the availability rollup has to move

The daily availability rollup runs in the poller. It reads ClickHouse and writes JSON and Parquet to MinIO.
Once the poller has no ClickHouse access, the rollup job **moves to the analytics container**: same code,
running next to ClickHouse and S3. Resolved in Phase 14.2 (D-04): the rollup moved in 14.2, and the poller
no longer has any rollup or S3 code.

##### Other cloud-split items noted for later (not Phase 14.2)

- Topology edit mode writes straight to Checkmk's REST API through the dashboard's nginx (`/checkmk-api`).
  That cannot work from the cloud without exposing Checkmk. Edits would go through a command topic on the
  broker, executed by an on-prem agent, as admin mode (`admin/cmd`) already does.
- Admin-mode commands travel through the broker, so TLS and ACLs on the cloud broker become important.

---

#### Part 2: worked timeline of the messages

**The cast:** `sw1`, a managed switch at 192.168.100.1. `linux1`, an agent host at .20 with `sw1` as its
parent. `cam1`, a ping-only host at .30, also behind `sw1`. The poll cycle is 15 s.

##### Every cycle: one `status` per host, even when nothing changed

> **Changed in Phase 17:** `status` is now throttled (state change, band crossing, or heartbeat); see "Phase 17: cloud contract and archive feed" below. The timeline in this part shows the pre-throttle behaviour.

`lan/devices/linux1/status`, QoS 0, retained. A cycle where nothing changes still publishes this, plus the
`lan/poller/status` heartbeat, and nothing else:

```json
{"id":"linux1","state":"OK","in_downtime":false,"acknowledged":false,
 "device_type":"server","folder":"/vlan100","alias":"","address":"192.168.100.20",
 "staleness":0.4,"host_state_raw":"UP","timestamp":"2026-10-03T04:00:00+00:00",
 "cpu_percent":12.3,"cpu_warn":80,"cpu_crit":90,
 "cpu_load1":0.42,"cpu_load5":0.35,"cpu_load15":0.30,"cpu_load_warn":3,"cpu_load_crit":4,
 "ram_percent":41.0,"ram_warn":80,"ram_crit":90,
 "disk_percent":55.2,"disk_warn":80,"disk_crit":90,
 "disk_other_worst_percent":38.0,"disk_other_worst_warn":80,"disk_other_worst_crit":90,
 "disk_other_worst_mount":"/var","smart_total":1,"smart_failing":0}
```

The CPU, RAM and disk numbers change on every cycle, so the payload does too. A consumer that wants only
changes has to compare.

**`sw1` and `cam1` get the same publish every cycle.** Every host the poller knows about gets its own
`status`, whatever its type. The difference is in the content, because neither has an agent:

`lan/devices/sw1/status`, QoS 0, retained (an unmanaged-or-managed switch, ping/SNMP only):

```json
{"id":"sw1","state":"OK","in_downtime":false,"acknowledged":false,
 "device_type":"switch","folder":"/vlan100","alias":"core switch","address":"192.168.100.1",
 "staleness":0.2,"host_state_raw":"UP","timestamp":"2026-10-03T04:00:00+00:00",
 "cpu_percent":null,"cpu_warn":null,"cpu_crit":null,
 "cpu_load1":null,"cpu_load5":null,"cpu_load15":null,"cpu_load_warn":null,"cpu_load_crit":null,
 "ram_percent":null,"ram_warn":null,"ram_crit":null,
 "disk_percent":null,"disk_warn":null,"disk_crit":null,
 "disk_other_worst_percent":null,"disk_other_worst_warn":null,"disk_other_worst_crit":null,
 "disk_other_worst_mount":null,"smart_total":null,"smart_failing":null}
```

`lan/devices/cam1/status` has the same shape, with `"id":"cam1"`, `"device_type":"camera"` (or whatever
its `device_type` tag is), `"address":"192.168.100.30"` and the same twenty `null` gauge keys.

What differs from `linux1`:

- **All twenty gauge keys are present but `null`.** The poller sets a gauge key to `null` when its backing
  Checkmk service does not exist (a ping-only host has no `CPU utilization`, `Memory`, `Filesystem *` or
  `SMART` service). The keys are never omitted, with one exception: on a cycle where the services query
  failed, the gauge keys are left out of every host's payload, so a retained good value is not overwritten
  with wrong `null`s.
- **`state` comes from Livestatus's `worst_service_state`**, which covers every service the host has (for
  example `PING`, and interface checks if it is SNMP-monitored). The "visible services only" rule applies
  only to hosts that have a `Check_MK Agent` service. A non-agent host's full service table is what the
  dashboard shows, so nothing is hidden from it.
- **The other topics are the same, just quieter.** `sw1` and `cam1` each have a `services` topic
  (published at startup and whenever a service state changes). A steady `PING` OK produces nothing beyond the per-cycle `status`.

**12:00:00 and 12:00:15:** nothing changes. For all three hosts, only `status` (and the `lan/poller/status`
heartbeat) is published.

##### 12:00:30: a service changes (`Systemd Service cron` goes OK to CRIT)

This is a service that is **not** CPU, RAM, disk or SMART. Three kinds of message follow in the same cycle.

1. **`lan/devices/linux1/services`**, QoS 1, retained. The whole list is republished because its signature
   changed. The signature is the sorted (description, state) pairs; a change in `plugin_output` text alone
   never triggers it.

   ```json
   [{"description":"Check_MK","state":"OK","plugin_output":"Success, execution time 0.4 sec"},
    {"description":"Check_MK Agent","state":"OK","plugin_output":"Version: 2.4.0p35 ..."},
    {"description":"Systemd Service cron","state":"CRIT","plugin_output":"cron.service: inactive (dead)"},
    {"description":"Systemd Timesyncd Time","state":"OK","plugin_output":"Offset: 3.2 ms"},
    {"description":"TCP Port 22 (expected open)","state":"OK","plugin_output":"..."},
    {"description":"Uptime","state":"OK","plugin_output":"up since ..."}]
   ```

2. **`lan/devices/linux1/status`** now has `"state":"CRIT"`, because `cron` is a service the dashboard
   shows. The status topic is the only topic that carries the host-level result.

   The services that count towards an agent host's state are the ones the dashboard shows or backs with a
   gauge: `Check_MK`, `Uptime`, `CPU utilization`, `CPU load`, `Memory`, `Filesystem *`, `SMART ... Stats`,
   the chosen `Systemd Service ...` / `Service ...` entries and `TCP Port ...`.

3. **`lan/events/recent`** (the global feed):

   ```json
   // events (whole bounded array, up to 1000 entries; shown with one entry)
   [{"timestamp":"2026-10-03T04:00:30+00:00","device_id":"linux1","event":"state_change","from":"OK","to":"CRIT"}]
   ```

**No incident is created.** Incidents only come from host-level DOWN and UNREACH.

##### 12:01:00: CPU, RAM, filesystem and SMART do not use `services`

`CPU utilization`, `Memory`, every `Filesystem *` and the `SMART ... Stats` services are excluded from the
`services` list, as is `Systemd Service Summary`. They appear on the **`status`** topic as the gauge keys
above. So when `/var` goes from 70% to 82%:

- The `status` payload's `disk_other_worst_percent` changes. That is all that is published for the numbers.
- If `/var` crosses its warning threshold the host state changes from OK to WARN, which publishes an `events`
  entry, exactly as in the `cron` example. But there is **no `services` republish**, because those services are not in the list.

**`CPU load` is the exception.** Its numbers are the `cpu_load1`, `cpu_load5`, `cpu_load15` gauge keys
(absolute load; `cpu_load_warn`/`cpu_load_crit` are the per-core rule levels already multiplied by the core
count), but its row **stays in the `services` topic**, because analytics builds failure needs from that
topic; it is hidden from the service list only on the dashboard, which shows it as the Load gauge. A
`CPU load` WARN or CRIT counts towards the agent host's state, and raises a failure need with a fixed tier:
`urgent` on WARN, `immediate` on CRIT (same need id, independent of host criticality).

##### 12:05:00: `sw1` goes DOWN, so `linux1` and `cam1` become UNREACH

Each of the three hosts has a state change, so each gets an `events` entry. The
`events` array gains three entries, for example `{"device_id":"sw1","event":"state_change","from":"OK","to":"DOWN"}`.
The status payloads have `"state":"DOWN"` for all three, because `state` never contains `UNREACH`; the
children differ only in `"host_state_raw":"UNREACH"`. For example, on that cycle:

```json
// lan/devices/sw1/status (root cause: really DOWN)
{"id":"sw1","state":"DOWN","host_state_raw":"DOWN", ...gauge keys all null...}
// lan/devices/cam1/status (behind sw1: Checkmk cannot reach it, so UNREACH)
{"id":"cam1","state":"DOWN","host_state_raw":"UNREACH", ...gauge keys all null...}
// lan/devices/linux1/status (agent host, also behind sw1)
{"id":"linux1","state":"DOWN","host_state_raw":"UNREACH", ...gauge keys from the last good services read...}
```

`linux1`'s state is not recomputed from its visible services here, because a host that is DOWN or UNREACH
keeps `"DOWN"` outright. Whether its gauge keys carry values or `null` on those cycles depends on what
Checkmk's `services` rows contain for an unreachable host; that was not verified live.

Then one incident message, **`lan/incidents/incident-sw1/status`**, QoS 1, retained:

```json
{"id":"incident-sw1","root":"sw1","root_state":"DOWN","inferred":false,
 "confirmed_down":[],"not_observable":["cam1","linux1"],"dependents":[],
 "worst_criticality":"low","since":"2026-10-03T04:05:00+00:00",
 "timestamp":"2026-10-03T04:05:00+00:00"}
```

It is published again only when its content changes (a signature check), not every cycle.

##### 12:08:00: `sw1` recovers

- `status` and `events` for each of the three hosts, back to `OK`/`UP`.
- The incident is **tombstoned**: an empty retained payload on `lan/incidents/incident-sw1/status`, QoS 1.
  A consumer never receives an "incident closed" message. It only sees the topic cleared, and only if it is
  connected at that moment.

##### The other messages

- **`lan/devices/topology`**, QoS 1, retained, only when the structure or a label changes. A list of
  `{id, parents, device_type, folder, alias, map_position, unmanaged, criticality, service_criticality, depends_on}`.
- **`lan/poller/status`**, every cycle, QoS 1, retained:
  `{"status":"online","since":...,"last_poll":...,"device_count":N}`. A broker-side Last Will publishes
  `{"status":"offline"}` if the poller drops.
- **Host removal** tombstones the host's retained `status` and `services` topics (plus, for one release, the
  retired `history` and `service_history` paths) and adds an `events` entry with `"event":"removed"` and `"to":null`.

##### What a cloud-side programmer must know

1. **Almost everything is retained and whole-state, not a stream.** A new subscriber gets the latest state per
   topic immediately. That is why `events` is rewritten as a whole array:
   it is bounded, not append-only.
2. **There is no per-event message anywhere today.** To store events durably, a consumer must diff the bounded
   arrays or deduplicate by (timestamp, device_id, event). That is the reason for the proposed dedicated
   `history/events` and `history/incidents` topics.
3. **Closed incidents vanish** (tombstone). They cannot be reconstructed from the broker afterwards.
4. **`state` is collapsed.** It never says `UNREACH`; read `host_state_raw`.
5. **Gauge services are not in `services`.** They live in `status`. Services hidden from the dashboard (for
   example `Systemd Timesyncd Time`) are in `services`, but do not affect an agent host's `state`
   (quick 261003-lnr).
6. **The history samples do not go over MQTT yet.** `metrics`, `host_state` and `service_state` rows go
   straight to ClickHouse. That is the part Part 1 proposes to move.

---

#### Part 3: how the current dashboard uses these topics

Source: `dashboard-react/src/store/mqttClient.ts` (connection), `store/useAppStore.ts` (message handling) and
the components that read the store. Verified by reading the code, not by running it.

##### Connection

- The dashboard is a pure MQTT consumer in the browser. It uses **mqtt.js over WebSockets** with one
  module-level connection (no second connection even under React StrictMode).
- **URL:** `ws://<the page's own hostname>:<WS_PORT>`, so it works from any LAN device when nginx and
  Mosquitto share a host. The browser user is `wsreader` (read `sites/<site_id>/lan/#` only), with the login read from the
  runtime `/config.json` that nginx serves from `deploy/.env`.
- **Clean session, no persistence on the client.** Everything the dashboard knows comes from the broker's
  retained messages, replayed when it subscribes. There is no cache-warming request of any kind.
- **Reconnects** use its own jittered exponential backoff (1 s up to 30 s), driven from the `close` event.
  mqtt.js's built-in fixed-interval retry is turned off.
- **On every (re)connect the incidents slice is cleared first**, then it subscribes, so the retained replay
  rebuilds incidents from scratch. Incidents are change-triggered and tombstoned on close, so a tombstone
  missed while disconnected would otherwise leave a closed incident on screen forever.
- **Admin mode only (`?admin=1`)** adds a second login (`wsadmin`), subscribes to `sites/<site_id>/admin/ack` and
  `sites/<site_id>/admin/faked`, and publishes commands on `sites/<site_id>/admin/cmd` (QoS 1, not retained, so a command never replays after
  a poller restart).

##### Subscriptions

`mqttClient.ts` subscribes to `sites/<checkmkSite>/...`, with `checkmkSite` read from the runtime `/config.json`. It strips the prefix once, in `dashboard-react/src/lib/topics.ts`, so the store sees the relative topics below; a message outside this site's prefix is dropped.

```
lan/devices/+/status           lan/devices/+/services
lan/devices/topology           lan/events/recent
lan/poller/status              lan/incidents/+/status
```

##### How a message becomes state

- The store (Zustand) **replaces** each slot with the latest message and never appends. Every topic is
  already a full snapshot (see Part 1), so appending would double-bound an already-bounded array and leak
  memory on a kiosk tab that stays open for days.
- A payload that fails to parse, or has the wrong shape, is dropped and the last good value stays. A bad
  message can't blank the page.
- A **zero-length retained payload is a tombstone.** On a `status` tombstone the device and all its
  per-device slices (`services`) are removed together. On an incident
  tombstone the incident is removed.
- Messages are **batched per animation frame**: the client queues them and applies the queue in one store
  update (`handleMessages`). Arrival order and last-write-wins per topic are unchanged, and a tombstone
  that follows a status in the same batch still removes the host.

##### Which topic feeds which part of the screen

| Topic | Store slice | Where it is used |
|---|---|---|
| `sites/<site_id>/lan/devices/{id}/status` | `devices` | The **device tree** (grouped by folder or by `device_type`, ordered by severity). The **map**: node colour and label (state, stale override, alias, address). The **header counts** (OK/WARN/CRIT/DOWN/STALE). The **host details pane**: state badge, address, and the CPU, RAM, disk and SMART gauges from the gauge keys. Display names in the event list and editors. |
| `sites/<site_id>/lan/devices/topology` | `topology` | The **map layout**: nodes, parent links (edges), saved `map_position`, unmanaged-switch marker. The **criticality editor** (criticality, per-service criticality, `depends_on`). |
| `sites/<site_id>/lan/devices/{id}/services` | `services` | The **host details pane**'s service tables. For an agent host it shows the chosen `Systemd Service` and `Service` entries, `TCP Port` checks, `Check_MK` (agent connected) and `Uptime`. For any other host it shows the full table. Also the editor's per-service criticality list (the same filtered set). |
| `sites/<site_id>/lan/events/recent` | `events` | The **event history pane** (newest first, filtered to the open host, with a From/To date-time filter). |
| `sites/<site_id>/lan/incidents/{id}/status` | `incidents` | The **incident pane** (cards ordered by criticality tier, then longest open) and the markers that dim or flag affected hosts in the tree and map. |
| `sites/<site_id>/lan/poller/status` | `pollerStatus`, `lastKnownPollerTimestamp` | **Stored, but not displayed.** `isPollerStale()` exists in `lib/staleness.ts` but only tests call it. |

The poller heartbeat is published and kept in memory, but the UI doesn't show it yet. A new dashboard can
ignore it, or start using it.

##### Staleness: why `status` is published every cycle

> **Changed in Phase 17:** `status` is no longer published every cycle; the timestamp fallback is widened by the payload's `heartbeat_s` (`3 x max(15, heartbeat_s)`). See "Phase 17: cloud contract and archive feed".

- A device is stale if Checkmk's own `staleness` value is at or above the configured factor, or, when that
  is `null`, if the payload `timestamp` is older than the factor times the poll interval.
- A stale device is shown and counted as **STALE** instead of its reported state.
- The dashboard re-evaluates this on a timer (`useNowTick`), so a host whose messages simply stop turns
  STALE with no new message. That is why the per-cycle QoS 0 `status` matters: it acts as the per-host
  heartbeat, and a retained `status` that never updates ages out.

##### What the dashboard does **not** use MQTT for

- **Topology edits** go straight to Checkmk's REST API through the dashboard's nginx `/checkmk-api`
  location (nginx adds the `topology_editor` credential). Nothing on MQTT.
- **History and availability** are not shown yet. The nginx paths `/ch-api/` (read-only ClickHouse) and
  `/availability/` (rollup objects in MinIO) exist and are smoke-tested, but no dashboard view uses them
  (D-50). Grafana reads ClickHouse directly.

##### What this means for a cloud broker or a new dashboard

1. **It depends on retained replay at subscribe time.** The broker must retain and persist these topics.
   A new client sees nothing until messages are published again if retention is off.
2. **It depends on tombstones.** An empty retained message must be carried through any bridge or proxy
   unchanged, or removed hosts and closed incidents will stay on screen. A bridge that drops empty
   retained messages would break this. Not verified for Mosquitto bridges.
3. **The broker URL is derived from the page's hostname** (`ws://<hostname>:<WS_PORT>`), which only works
   when the dashboard and broker share a host. A dashboard in the cloud needs the broker URL from runtime
   config, and **`wss://`** (TLS), since `ws://` is plain text.
4. **The browser login is served openly** from `/config.json`. That is acceptable on a closed LAN, but a
   cloud dashboard needs real per-user authentication and ACLs.
5. **Initial load size.** On connect the client receives every retained message at once: one `status`
   and `services` per host, plus the topology, the events array (up to
   about 125 to 160 KB) and the open incidents.
6. **Topology editing and admin commands cross the same boundary the other way.** Editing needs a command
   path to on-prem Checkmk. Admin commands already travel over MQTT.

---

#### Part 4: bandwidth options for a metered link and many sites

Context (discussion 2026-10-03): the broker, ClickHouse and dashboard will move to the cloud, each site
may be on 4G, and one broker may receive tens of host updates from hundreds of sites. Today's contract
(Parts 1 to 3) was designed for a single LAN, so several choices that are free on a LAN are expensive here.

Every figure below is an **estimate**: payload sizes were measured from the example shapes in Part 2, and
the host, service and metric counts are assumptions. Replace them with live numbers before deciding
(see "Measure first" at the end).

##### Where the bytes go (per site, per day, if today's design is moved as is)

| Traffic | Size | Per day | Notes |
|---|---|---|---|
| `status` every cycle, per host | about 590 bytes (gzip only halves it) | about 3.4 MB per host, about 100 MB for 30 hosts | Mostly unchanged data, 5760 times a day. |
| History samples over MQTT (the Part 1 proposal) | about 380 KB per cycle for an assumed 2400 rows (20 agent hosts x 40 services x 3 metrics) | about 2.2 GB raw, about 210 MB gzipped | By far the biggest. The test data was random, so real data likely compresses better. |
| `sites/<site_id>/lan/events/recent` | up to about 127 KB per republish | small normally, up to about 730 MB if it changes every cycle | A flapping fleet is the worst case. |
| Per-device `history` and `service_history` | none | none | Removed 2026-10-04 (quick 261004-kbt); transition history comes from ClickHouse. |

Downstream matters too: a cloud dashboard that pulls every retained message on connect would fetch tens of
MB when hundreds of sites share one broker.

##### Options, by lever

1. **Send only what changed.**
   - `status`: publish when a discrete field changes (state, `host_state_raw`, downtime, acknowledged), and
     refresh the gauges at a slower pace or when a value crosses a band. Replace the per-host-per-cycle
     heartbeat with one site-level heartbeat. Catch: the dashboard's staleness check (Part 3) relies on the
     per-host message, so it would have to use the site heartbeat instead.
   - Samples: send a metric row only when the service's check actually ran. Checkmk normally checks a
     service about once a minute, but the poller reads Livestatus every 15 s, so roughly three of every four
     samples would be a repeat of the same value. **Unverified on this site.** Check by adding Livestatus's
     `last_check` column and seeing how often it advances. If it holds, this cuts about 4x with no loss of
     information, and ClickHouse is currently storing about 4x more rows than it needs to.
2. **Stop shipping whole arrays across the WAN.**
   - Events become one small non-retained message each (about 125 bytes), written to ClickHouse by the
     cloud subscriber.
   - Drop the per-device `history` and `service_history` topics from the WAN. **Done 2026-10-04 (quick
     261004-kbt):** the poller no longer publishes them; the durable copy is in ClickHouse.
   - The dashboard then reads recent events and history from ClickHouse over the existing read-only HTTP
     path (`/ch-api/`), not from retained MQTT arrays. A small retained "last 20 events" (about 2.5 KB)
     could stay for instant fill on page load.
3. **Shrink the history samples.**
   - Compress each batch with gzip or zstd (about 10x on the synthetic test); no schema change needed. The
     subscriber decompresses before inserting.
   - Aggregate on-prem to 1-minute min, max, sum and count before sending. `history.metrics` already has
     `value_min`, `value_max`, `value_sum` and `value_count` for exactly this.
   - Send `warn` and `crit` only when they change, since they rarely do.
4. **Protocol and topology.**
   - A per-site namespace `sites/<site_id>/...` (done in Phase 14.3, see `deploy/mosquitto.acl.template`; per-site broker users remain future work), so a dashboard
     subscribes only to the site it is showing. A cloud-side aggregator can publish a small fleet summary.
   - Store-and-forward: a local Mosquitto bridged to the cloud broker should queue messages during a 4G
     outage and send them as a burst afterwards (believed, not verified for Mosquitto bridges).
   - QoS 0 for data that repeats, MQTT 5 topic aliases to shorten topic bytes, and long keepalives to
     survive 4G NAT timeouts.

##### Recommendation (proposed, not yet decided)

Take three levers together:

- **1, samples:** only publish a sample row when `last_check` advances.
- **2:** events as small messages, no whole arrays, recent history read from ClickHouse.
- **3:** gzip, plus 1-minute aggregation.

The **per-site namespace** was added in Phase 14.3 (done), because renaming topics later is painful. With these, the rough
estimate is a few tens of MB per site per day instead of gigabytes.

Status-by-exception (lever 1, status) is the biggest change to the dashboard, so treat it as a second
step.

##### Decisions (2026-10-03)

> **Phase 17 follow-up:** the bridge, history topics, throttle and `event_id` that implement these decisions are described in "Phase 17: cloud contract and archive feed".

1. **Gauge freshness: 60 s is acceptable** for CPU, RAM and disk on the cloud dashboard. State changes must
   still be immediate.
2. **Recent events and history are read from ClickHouse over HTTP**, not from retained MQTT arrays. So the
   cloud dashboard does not need `lan/events/recent` or the per-device `history` and `service_history`
   topics.
3. **The transport work belongs to a separate phase**, not Phase 14.2: the per-site namespace, per-event
   messages, sample de-duplication (`last_check`), compression and aggregation, and status-by-exception.
   Phase 14.2 stays limited to forecasting and narration.

4. **Phase 14.2 ingestion, before the transport phase exists:** the analytics container subscribes to the
   existing `lan/events/recent` and `lan/incidents/+/status` topics (persistent session, QoS 1), deduplicates
   events by (timestamp, device_id, event), and writes `history.events` and `history.incidents`. No poller
   change. The transport phase later replaces this with per-event messages.
5. **The daily availability rollup job moves from the poller to the analytics container in Phase 14.2**, so
   the poller no longer needs ClickHouse or S3 settings for it.

##### Measure first

- Rows per cycle on the live stack:
  `SELECT count() FROM history.metrics WHERE ts = (SELECT max(ts) FROM history.metrics)`.
- Whether Checkmk really checks once a minute: add `last_check` to the services query and count how often
  it changes between 15 s polls for a typical service.

---

#### Phase 14.2 analytics topics

The `analytics` container (`python -m analytics`, source in `analytics/`) added three published topics and
one consumed command topic. Every topic is shown with its full `sites/<site_id>/` prefix; the dashboard strips
the prefix once at its MQTT edge. Payload keys come from the implementation (`Need.to_payload` in
`analytics/rules.py`, `Fit.to_payload` in `analytics/fit.py`, `_publish_forecasts` and `_publish_narration`
in `analytics/service.py`, `parse_triage_command` in `analytics/triage.py`). The example values are
illustrative: they were not captured from a live broker. Every analytics publish is compact JSON, QoS 1.

| Topic | Writer | When published | QoS | Retained | Cleared by |
|---|---|---|---|---|---|
| `sites/<site_id>/lan/needs/{need_id}/status` | analytics | when a need appears or changes (failure needs are checked every `POLL_INTERVAL_SECONDS`, 15 s), after a triage command, and each slow evaluation cycle (default every 900 s) | 1 | yes | tombstone |
| `sites/<site_id>/lan/forecasts/{host}` | analytics | every evaluation cycle, for each host that has at least one fit | 1 | yes | tombstone |
| `sites/<site_id>/lan/incidents/{incident_id}/narration` | analytics | when an incident's narration text or tier changes | 1 | yes | tombstone |
| `sites/<site_id>/needs/triage/cmd` | dashboard, as `wstriage` | on an operator triage action | 1 | no | n/a |

`needs/triage/cmd` sits outside `lan/`, so the read-only `wsreader` login never receives it.

##### Needs: `lan/needs/{need_id}/status`

`need_id` is the source initial and 12 hex characters, `f-` (failure), `t-` (trend) or `s-` (sustained), the
hex being the start of a SHA-1 over `source|host|service|metric`, so an id is stable across restarts. Tiers are
`immediate`, `urgent` and `standard`. Example, a trend need:

```json
{"id":"t-3fa91c07be21","source":"trend","host":"linux1","service":"Filesystem /","metric":"fs_used_percent",
 "unit":"%","tier":"urgent","computed_tier":"urgent","days_to_warn":4.2,"days_to_crit":11.8,
 "warn_date":"2026-10-08","crit_date":"2026-10-16","confidence":"medium","history_days":31.5,
 "value":88.4,"warn":80.0,"crit":90.0,"sustained_fraction":null,"window_hours":null,
 "since":"2026-10-03T21:15:00Z","narration":"linux1 Filesystem / ...","triage":null,
 "generated_at":"2026-10-04T08:15:00Z"}
```

A failure need leaves the trend fields null; a sustained need fills `sustained_fraction` and `window_hours`.
`tier` is the effective tier (an operator override applied); `computed_tier` is what the rules produced.
After a triage action `triage` is `{"action","tier","set_at","computed_tier_at_set","note","by"}`, otherwise
`null` (a `cancel` also sets it, with `tier` equal to `computed_tier`).

**Tombstone rule (D-14, D-23):** a need is tombstoned (an empty retained payload) only after it has been absent
for 2 consecutive evaluation cycles (`RESOLVE_AFTER_CLEAN_CYCLES`), so a one-cycle flicker neither removes it
nor wipes its triage. An override is dropped, and audited as `auto_reset`, when the computed tier becomes worse
than it was at triage time. While ClickHouse is unreachable the previous cycle's trend and sustained needs are
carried over, so an outage is not read as those needs resolving.

##### Forecasts: `lan/forecasts/{host}`

One topic per host, carrying every fit for that host:

```json
{"host":"linux1","generated_at":"2026-10-04T08:15:00Z","fits":[
  {"status":"trending","history_days":31.5,"slope_per_day":0.42,"value_at_end":88.4,
   "fit_start_ts":1759000000.0,"fit_end_ts":1759560000.0,"r2":0.93,"confidence":"medium",
   "last_value":88.5,"warn":80.0,"crit":90.0,"warn_ts":null,"crit_ts":1760600000.0,
   "warn_date":null,"crit_date":"2026-10-16","days_to_warn":null,"days_to_crit":11.8,
   "service":"Filesystem /","metric":"fs_used_percent","unit":"%"}]}
```

`status` is `trending`, `stable` or `no_clear_trend`; the slope, anchor and date fields are null unless the fit
passed its quality gate. Timestamps are Unix seconds (UTC) and `*_date` fields are `YYYY-MM-DD`.

**The dashboard never refits (D-15).** The chart's dashed line is drawn from the published anchor:

```
y(t) = value_at_end + slope_per_day * (t - fit_end_ts) / 86400
```

and a level is crossed at `fit_end_ts + (level - value_at_end) / slope_per_day * 86400`, which reproduces
the published dates. A host that no longer has any fit is tombstoned on the next cycle. A host id that is
unsafe as a topic segment (contains `+`, `#`, `/` or a control character) is skipped with a warning. Known
limitation: a forecast topic orphaned by a restart (the host vanished while analytics was down) is not
tombstoned.

##### Incident narration: `lan/incidents/{incident_id}/narration`

Published beside the poller's `lan/incidents/{incident_id}/status`. Analytics reads that topic and never
writes it (D-29). Example:

```json
{"id":"incident-sw1","headline":"sw1 (critical criticality) is the inferred common cause since 12:05.",
 "sentences":["..."],"tier":"immediate","generated_at":"2026-10-04T12:05:30Z"}
```

`tier` comes from the incident's `worst_criticality` (`critical` is `immediate`, `high` is `urgent`, `medium`
and `low` are `standard`). The narration carries no elapsed duration, because it would go stale between
publishes; the dashboard renders the live elapsed time itself. It is republished only when the headline,
sentences or tier change (once after every analytics restart, as the signatures are not seeded from the
retained copies). It is tombstoned when the incident's `status` topic is tombstoned (the incident closed), and
at startup any retained narration whose incident is no longer retained is cleared.

##### Triage command: `needs/triage/cmd`

Published by the browser, not retained, QoS 1:

```json
{"id":"cmd-1759563000-a1","need_id":"t-3fa91c07be21","action":"downgrade","note":"planned","by":"jo"}
```

`action` is `downgrade` (one step below the *computed* tier, so a QoS 1 redelivery produces the same result),
`upgrade` (to `immediate`) or `cancel` (back to the computed tier). `note` is capped at 200 characters, `by` at
64 and the message at 4096 bytes. Analytics ignores retained deliveries, commands failing the strict shape
check, and commands naming a need that does not currently exist; every accepted command is audited in
`history.need_triage`.

It is **not acknowledged**: there is no ack topic. The confirmation is the need being republished on its own
`status` topic with `triage` set to the new `{"action",...}` object (a `cancel` sets `triage.action` to
`cancel` and `tier` back to `computed_tier`). The `triage` object is dropped only by the auto-reset rule above.

##### ACL for the new logins

From `deploy/mosquitto.acl.template`:

| User | Grants |
|---|---|
| `analytics` | `read sites/<site_id>/lan/#`, `read sites/<site_id>/needs/triage/cmd`, `write sites/<site_id>/lan/needs/#`, `write sites/<site_id>/lan/forecasts/#`, `write sites/<site_id>/lan/incidents/+/narration` |
| `wstriage` | `write sites/<site_id>/needs/triage/cmd` only; no read |

`analytics` has no write on `lan/incidents/+/status`, which stays the poller's. `wstriage` is served openly on
`/triage-config.json` (like `wsadmin` on `/admin-config.json`), so it is for a closed network only. Its reach
is bounded: analytics validates every command, and a command can only change a need's tier.


---

#### Phase 17: cloud contract and archive feed

Phase 17 makes the site's MQTT namespace available to a shared cloud broker, so an S3 archive (fsu-mqtt) and a
cloud ClickHouse writer can consume it. The archive-side wording of the contract lives in
Appendix B below; this section records what the on-prem stack actually does. Placeholder values
only (SEN 4711, site `dmc`).

##### Bridge and topic remap

The local Mosquitto broker runs an outbound-only, TLS bridge (rendered from `deploy/mosquitto.bridge.template`
by `deploy/render-mosquitto-bridge.sh` when `CLOUD_BROKER_HOST` is set). It forwards everything under
`sites/<site_id>/` to `app/<SEN>/<site_id>/` on the cloud broker, direction `out` only, so nothing from the cloud
can write the local broker. The poller, the ACLs and the dashboard keep the local `sites/<site_id>/` namespace.

- Cloud topic: `app/<SEN>/<site_id>/<suffix>`, where `<suffix>` is the local topic after `sites/<site_id>/`,
  for example `app/4711/dmc/lan/devices/linux1/status`.
- Session: MQTT v5 bridge, persistent (`cleansession false`), stable `remote_clientid bridge-<SEN>-<site_id>`,
  remote username is the SEN, `notifications false`.
- TLS is mandatory: the renderer refuses to start without `deploy/certs/cloud-ca.pem`. A renderer validation
  error stops the mosquitto container with a message naming the variable.
- The cloud broker ACL is per SEN (`deploy/mosquitto.cloud-acl.example`): a SEN may write only below
  `app/<its SEN>/`.
- Live-verified (plan 17-01): remap, `event_id` user-property pass-through, retained flag and tombstone
  forwarding, `include_dir`, queueing across a WAN outage, per-SEN ACL isolation. TLS was not exercised by that
  smoke test.

##### event_id and the dedupe key

The poller and the analytics container connect with MQTT v5 and set a deterministic `event_id` user property
on every discrete publish. The id derives only from message identity (content hash, cycle epoch, command id),
never from the publish-time clock, so a retry computes the same id. The cloud-side dedupe key is
`(sen, site, subtopic, event_id)`.

| Topic suffix | event_id |
|---|---|
| `lan/topology` | `topology-<16 hex sha1 of payload>` |
| `lan/devices/{id}/services` | `<id>-services-<hash>` |
| `lan/events/recent` | `events-<hash>` (hash of the whole array, shape unchanged) |
| `lan/incidents/{id}/status` | `<incident_id>-<hash>` |
| incident tombstone | `<incident_id>-closed-<cycle_epoch>` |
| device tombstone (also stale sweep) | `<device_id>-removed-<cycle_epoch>` |
| `admin/faked` | `faked-<hash>` |
| `admin/ack` | `<command id>-ack` |
| `history/<table>` | `<cycle_epoch>-<table>-<chunk_index>` |
| `lan/needs/{need_id}/status` (analytics) | `<need.id>-<hash>`; tombstone `<need>-cleared-<epoch>` |
| `lan/forecasts/{host}` (analytics) | `<host>-forecast-<hash>`; tombstone `<host>-forecast-cleared-<epoch>` |
| `lan/incidents/{id}/narration` (analytics) | `<incident>-narration-<hash>`; tombstone `<incident>-narration-closed-<epoch>` |

Topics that carry **no** `event_id`: device `status` (including its raw legacy tombstones), `lan/poller/status`,
the last-will and shutdown message, and the browser-published commands `admin/cmd` and `needs/triage/cmd`
(the browser speaks MQTT 3.1.1; each command payload has its own `id`).

##### History over MQTT

When `SITE_SEN` is non-empty the poller also publishes each cycle's history rows, exactly what
`build_history_rows()` produces, in chunks of at most 500 rows (QoS 1, not retained, so a bridge reconnect does
not re-send an old batch). Topics: `sites/<site_id>/history/metrics`, `history/host_state`,
`history/service_state`; on the cloud `app/<SEN>/<site_id>/history/<table>`.

```json
{
  "event_id": "1790000000-metrics-0",
  "ts": "2026-10-14 12:00:00",
  "table": "history.metrics",
  "chunk": 0,
  "chunks": 2,
  "rows": [ ]
}
```

`event_id` appears both in the payload and as the MQTT user property. The cloud writer adds site and SEN from the
topic. History is sent every cycle, uncompressed; the MQTT publish happens before the on-prem ClickHouse write
and never stops the poll loop.

##### Status throttle and heartbeat

`lan/devices/{id}/status` is no longer published every cycle. A device's status is published when:

1. the discrete signature changes (state, metadata, or the Checkmk staleness crossing 3.0), or
2. a gauge crosses its ok/warn/crit band, or
3. `CLOUD_METRICS_HEARTBEAT_S` seconds (default 300) have passed since its last publish, or
4. it is the first publish of that device after the poller starts.

`CLOUD_METRICS_HEARTBEAT_S=0` publishes every cycle. Each payload carries `heartbeat_s`, and the dashboard
widens its timestamp staleness fallback to `3 x max(15, heartbeat_s)` seconds. A state change still shows
within one poll cycle (about 15 s). `lan/poller/status` is still published every cycle. The on-prem gauges
refresh at the heartbeat as a consequence (decision D-09).

##### Retained re-send and the loss window

- A retained message is **not** re-sent when the bridge reconnects after a WAN outage (plan 17-01, A3: 0 re-sends
  observed). Queued QoS 1 messages are delivered (A6: 5 of 5). Retained topics therefore change on the cloud only
  when their content changes, which is also what the heartbeat and the history stream cover.
- Queue limits on the local broker: `max_queued_messages 20000` and `max_queued_bytes 104857600` (100 MB, roughly
  one hour of unthrottled history). During a WAN outage longer than that, Mosquitto drops the oldest queued
  messages; the gap reads as "no data" on the cloud side. The session itself survives for
  `bridge_session_expiry_interval 86400` (24 h). Device `status` is QoS 0 and is not queued across an outage
  (FA-10).

##### Cloud-ingest mode

`ANALYTICS_MODE=cloud-ingest` turns the analytics container into a history-only writer on the cloud side. It
subscribes to one site's `app/<SEN>/<site_id>/history/+` over MQTT v5 (persistent session, manual ack, client id
from `MQTT_CLIENT_ID`, expiry `MQTT_SESSION_EXPIRY_S`), validates rows against the poller's column schemas,
dedupes by `(topic, event_id)` over the last 4096 pairs, and inserts through an allow-listed ClickHouse writer.
Required env: `SITE_SEN`, `CMK_SITE_ID`, `MQTT_HOST`/`MQTT_PORT`/`MQTT_USERNAME`/`MQTT_PASSWORD`,
`CLICKHOUSE_URL` and the writer credentials. Run one instance per (SEN, site). It exits 2 on an invalid
`SITE_SEN`. It never publishes.

##### Flagged for review

- FA-1: `topic #` forwards throttled device status and the per-cycle `lan/poller/status` too; decision open: accept as the cloud liveness signal, or replace with per-subtree `topic` lines (template-only change).
- FA-2: the cloud feed is opt-in by `CLOUD_BROKER_HOST`; compose does not fail on an empty `SITE_SEN`.
- FA-3: queue limits are global per-client settings (up to about 100 MB per backlogged client), applied even without a bridge.
- FA-4: cloud and bridge passwords are limited to `[A-Za-z0-9_.~=+-]`, 1 to 256 characters.
- FA-5: the bridge remote username is the SEN; sites sharing a SEN share the login and differ by `remote_clientid`.
- FA-6: history is published every cycle, uncompressed, in 500-row chunks; reduction is for user review.
- FA-7: history publishing is switched on by a non-empty `SITE_SEN`.
- FA-8: `lan/events/recent` keeps its array shape; its event_id is a hash of the whole array, no per-event message.
- FA-9: browser commands carry no event_id; the poller's ack carries `<command id>-ack`.
- FA-10: device status stays QoS 0 and can be lost on the WAN until the next heartbeat.
- FA-11: on-prem gauges and the analytics in-memory status view refresh at the heartbeat except on band crossings.
- FA-12: `/config.json` `siteSen` is only a read-only header label; the dashboard stays on `sites/<site_id>/`.
- FA-13: cloud-ingest handles history only; events, incidents, needs and forecasts reach the archive through the bridge.
- FA-14: one cloud-ingest instance and database per (SEN, site); history tables gain no site or SEN column.
- FA-15: ingest dedupe is in-process only (4096 pairs); a restart forgets it (ClickHouse insert dedup was not verified, RESEARCH A7).
- FA-16: an insert failure is logged and the chunk is still acknowledged; the S3 archive is the replay source.
- FA-17: analytics tombstones use `<key>-cleared-<epoch>` with the deciding cycle's `now`.

## Appendix B: MQTT client data flow (cloud archive)

This document describes what a client application must publish and what happens to the message between the MQTT broker, local durable storage, and Amazon S3.

#### Executive summary

```text
Client application
  -> MQTT v5 PUBLISH to app/<SEN>/<site>/<topic...>
  -> MQTT broker
  -> fsu-mqtt subscription app/# (QoS 1)
  -> validate topic and create archive envelope
  -> append one JSON object plus newline to a local .jsonl.part file
  -> fsync the record to local storage
  -> acknowledge broker delivery
  -> finalize the batch as .jsonl
  -> upload the finalized file to S3
  -> delete the local file only after PutObject succeeds
```

The archive provides **at-least-once collection for QoS 1**, not exactly-once delivery. Clients that need event-level deduplication should publish a stable MQTT v5 user property named `event_id`.

> A `PUBACK` received by the publishing client confirms the broker accepted its QoS 1 publish. It does **not** confirm that the archive service has written the message or uploaded it to S3. The archive service's later acknowledgment is between the service and the broker.

#### Client publishing contract

##### MQTT protocol and QoS

- Use MQTT v5.
- Publish with **QoS 1** for messages that must be archived reliably.
- QoS 0 messages can be collected, but have no broker redelivery guarantee and should be treated as best effort.
- The service subscription is granted at QoS 1, so the archive contract is at-least-once rather than exactly-once.
- Retained publications are accepted and the original retain flag is recorded. Retained state can be delivered again when the broker creates a new subscription, for example after session loss or expiry.

##### Topic

Publish to:

```text
app/<SEN>/<site>/<topic...>
```

Example:

```text
app/123/SiteA/status/device-1
```

| Part                | Requirement                         | Archived value                                 |
|---------------------|-------------------------------------|------------------------------------------------|
| `app`               | Fixed literal                       | Included in `topic`                            |
| `SEN`               | Positive decimal integer            | Numeric `sen`, for example `123`               |
| `site`              | Non-empty site identifier           | String `site`, for example `SiteA`             |
| `topic...`          | One or more non-empty path segments | Full `subtopic`, for example `status/device-1` |
| First topic segment | Identifies the message type         | `base_topic`, for example `status`             |

Do not publish topics containing MQTT wildcards (`+` or `#`), null bytes, invalid UTF-8, empty path segments, or whitespace-only site/topic segments. Use a canonical SEN without leading zeros even though the receiver parses SEN numerically.

All valid topics under `app/#` are archived. The archive service does not filter messages to one configured SEN or site.

##### Event identity

Add this MQTT v5 user property when downstream systems need to recognize broker redelivery or application retries:

```text
event_id = <producer-generated-event-identifier>
```

The publisher should:

1. Generate an `event_id` for each logical event.
2. Keep it unchanged whenever that same event is retried.
3. Make it unique within `(SEN, site, subtopic)`.
4. Use a new ID for a distinct event, even if its payload is identical.

The property is optional and copied verbatim to JSONL. The service does not synthesize it from the payload, MQTT packet ID, or DUP flag.

The archive also generates `id`, but that is a **receipt ID**, not a producer event ID. A broker redelivery can therefore produce two records with different `id` values and the same `event_id`. Consumers should deduplicate identified events using:

```text
(sen, site, subtopic, event_id)
```

Messages without `event_id` remain valid, but consumers cannot reliably distinguish a redelivery from a separate event with the same payload.

##### Payload

The payload is kept opaque; no application payload schema is currently imposed:

- Valid UTF-8 bytes are stored unchanged as the JSON string `value`.
- Invalid UTF-8/binary bytes are Base64 encoded in `value` and the record includes `"encoding":"base64"`.
- An empty payload is valid and is stored as `"value":""`.
- `received_at` is the archive service's UTC receipt time, not a publisher event timestamp. Put event time inside the payload if the application requires it.

#### Archive record format

Each received message becomes one JSON object on one line of a JSONL/NDJSON file.

Example for a UTF-8 payload:

```json
{"id":"9fa32d15-ec4e-4d19-b4ea-f302722ddb31","topic":"app/123/SiteA/status/device-1","sen":123,"site":"SiteA","subtopic":"status/device-1","base_topic":"status","event_id":"producer-event-42","value":"online","received_at":"2026-09-02T10:11:12Z","qos":1,"retained":false}
```

Example for the binary bytes `ff 00 fe`:

```json
{"id":"e62aa924-ca68-4ff8-a134-2d2706b415ba","topic":"app/123/SiteA/raw","sen":123,"site":"SiteA","subtopic":"raw","base_topic":"raw","value":"/wD+","encoding":"base64","received_at":"2026-09-02T10:11:12Z","qos":1,"retained":false}
```

| Field         | Type               | Meaning                                                                             |
|---------------|--------------------|-------------------------------------------------------------------------------------|
| `id`          | string (UUID)      | Unique archived receipt; changes if the broker redelivers the message               |
| `topic`       | string             | Complete original MQTT topic                                                        |
| `sen`         | integer            | SEN parsed from the topic                                                           |
| `site`        | string             | Site parsed from the topic                                                          |
| `subtopic`    | string             | Everything after `app/<SEN>/<site>/`                                                |
| `base_topic`  | string             | First segment of `subtopic`                                                         |
| `event_id`    | string, optional   | Publisher's MQTT v5 `event_id` user property                                        |
| `value`       | string             | Original UTF-8 payload or Base64 text                                               |
| `encoding`    | string, optional   | Present as `base64` only for a non-UTF-8 payload                                    |
| `received_at` | RFC 3339 timestamp | Time the archive service received the broker delivery, normalized to UTC            |
| `qos`         | integer            | QoS of the delivery received by the archive service                                 |
| `retained`    | boolean            | Original MQTT retain flag                                                           |
| `data`        | object, optional   | Server-side topic-specific enrichment; no custom enrichment is currently registered |

Clients should tolerate optional fields being absent and additional `data` fields being introduced later.

#### Collection and acknowledgment sequence

For every broker delivery, the service:

1. Receives messages through its `app/#` subscription.
2. Validates and parses the topic.
3. Copies the payload and MQTT metadata into the archive envelope.
4. Generates a receipt UUID in `id`.
5. Appends the record and newline to the active local `.jsonl.part` batch.
6. Calls `fsync` for the record before acknowledging a QoS 1 delivery to the broker.
7. Finalizes the batch by syncing, closing, and atomically renaming it from `.jsonl.part` to `.jsonl`.

If the local append or sync fails, the service does not acknowledge the delivery and stops, allowing a persistent broker session to redeliver an unacknowledged QoS 1 message after recovery.

A message with an invalid topic, or one rejected by future custom validation, is logged and acknowledged without being archived. Publishers must therefore follow the topic contract; broker acceptance alone does not prove application-level validity.

The archive uses a stable MQTT client ID, a non-clean initial connection, and a non-zero session expiry (default 24 hours). These settings let the broker retain unacknowledged QoS 1 deliveries across ordinary reconnects, subject to broker configuration and the session not expiring.

#### Local batching and crash recovery

Files are partitioned by the record's service receipt hour in UTC:

```text
<local_path>/year=YYYY/month=MM/day=DD/hour=HH/<timestamp>-<uuid>.jsonl
```

Example:

```text
/monitoring/mqtt/year=2026/month=09/day=02/hour=10/20260902T101112.000000000Z-<uuid>.jsonl
```

The active file has an extra `.part` suffix and is not eligible for upload. It is finalized when any of these occurs:

- `batch_size` records have been appended (default `1000`);
- `batch_interval` seconds elapse (default `60`);
- a message belongs to a different UTC hour;
- the service shuts down cleanly.

On startup, interrupted `.jsonl.part` files are recovered. An incomplete trailing JSONL line is truncated, while all complete, potentially acknowledged lines are retained. A non-empty recovered file is then finalized to `.jsonl`.

In `local` storage mode, finalized files remain under `local_path` and are not sent to S3.

#### S3 delivery

In `s3` storage mode, `local_path` remains a required durable spool. The service never streams an active message directly to S3.

Only finalized `.jsonl` files are selected. For each file, the S3 object key is:

```text
<prefix>/<path relative to local_path>
```

For example, with bucket `example-archive`, prefix `mqtt`, and the file above:

```text
s3://example-archive/mqtt/year=2026/month=09/day=02/hour=10/20260902T101112.000000000Z-<uuid>.jsonl
```

Objects are uploaded with:

```text
Content-Type: application/x-ndjson
```

Pending-file scans happen:

- when the upload worker starts, so files left from an earlier run are retried;
- after each configured batch interval;
- once more during graceful shutdown, within the available shutdown deadline.

A `PutObject` failure leaves the finalized local file in place for a later scan. The local file is removed only after `PutObject` succeeds. If S3 succeeded but local deletion did not, the same path can be uploaded again to the same object key on a later scan.

Consequences for consumers:

- S3 arrival is asynchronous and eventual; there is no per-message S3 acknowledgment to the publisher.
- Do not assume object arrival order across batches or retries. Use record fields such as `received_at` and application event metadata instead.
- An active `.jsonl.part` file is intentionally invisible to S3 until rotation.
- The durable local spool needs enough disk capacity for an S3 outage.

The service uses the AWS SDK default credential chain. S3 mode requires a configured AWS region and bucket; the prefix is optional.

#### Recommended publisher checklist

- [ ] Connect using MQTT v5 and the broker credentials supplied for the deployment.
- [ ] Publish to `app/<positive-SEN>/<non-empty-site>/<non-empty-topic...>`.
- [ ] Use QoS 1 for reliable archiving.
- [ ] Attach a stable, producer-generated `event_id` user property when deduplication matters.
- [ ] Reuse the same `event_id` for retries of the same event; never infer identity from payload equality.
- [ ] Put producer event time and any domain schema inside the payload when needed.
- [ ] Treat publisher `PUBACK` as broker acceptance, not local-archive or S3 confirmation.
- [ ] Expect at-least-once records and make downstream processing idempotent.

#### Relevant implementation

- Topic parsing and JSONL envelope: `internal/fsu-hypercare/mqtt/handler.go`
- MQTT connection, event property extraction, persistence, and acknowledgment: `internal/fsu-hypercare/mqtt/main.go`
- Subscription behavior: `internal/fsu-hypercare/mqtt/subscribe.go`
- Local batching and recovery: `internal/fsu-hypercare/mqtt/writer.go`
- S3 key construction and upload: `internal/fsu-hypercare/mqtt/s3.go`
- Upload scheduling and shutdown: `internal/fsu-hypercare/mqtt/upload_worker.go`
- Configuration defaults and validation: `internal/fsu-hypercare/shared/config_mqtt.go`
