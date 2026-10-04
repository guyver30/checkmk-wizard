# MQTT contract walkthrough and history-over-MQTT proposal

> **Update 2026-10-04 (Phase 14.3):** every topic now lives under `sites/<site_id>/`, where `site_id` is
> `CMK_SITE_ID`, and the broker ACL is rendered per deployment from `deploy/mosquitto.acl.template`. The
> worked examples below keep the relative suffixes for readability: read each `lan/...` or `admin/...` topic
> as `sites/<site_id>/lan/...` or `sites/<site_id>/admin/...`. The formal topic tables use the full form.

> **Update 2026-10-04 (Phase 14.2):** the analytics container now exists and publishes three more topics
> (needs, forecasts, incident narration) and consumes one (the triage command). They are documented in
> [Phase 14.2 analytics topics](#phase-142-analytics-topics) at the end of this file. The `history/#`
> proposal in Part 1 is superseded for 14.2 (see the note there).

Written 2026-10-03 during the Phase 14.2 discussion, for whoever builds the cloud side (broker, ClickHouse,
analytics container, new dashboard). It has three parts:

1. How the poller publishes today, how its history rows are assembled, and the proposal to move history
   writing onto MQTT (a proposal, not yet a locked decision).
2. A worked timeline showing exactly which messages the poller publishes when a host changes.
3. How the current dashboard consumes those topics, and what a different broker location would change.
4. Bandwidth options for a metered link (4G) with many sites feeding one cloud broker.

The examples were built from the code (`publish_*` and `compute_incidents` in `scripts/mqtt_poller.py`) and
the topic table in `docs/Podman setup for checkmk, minio, mosquitto, worker.md`. They were not captured from
a live broker, and timestamps are shortened. The Podman doc stays the reference for the formal topic table.

---

## Part 1: how the poller publishes, and the history proposal

### Target architecture (decided 2026-10-03)

- **On-prem:** Checkmk, the poller, the worker.
- **Cloud (own tenancy, which counts as inside the network):** broker, AWS S3, ClickHouse, a new dashboard,
  Grafana, and the analytics container.
- Local-first today (everything on one machine), split later with config-only changes where possible.

### What the poller publishes today (every 15 s cycle, `run_cycle`)

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

### The proposal: publish history over MQTT, write to ClickHouse from the cloud

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

### Consequence: the availability rollup has to move

The daily availability rollup runs in the poller. It reads ClickHouse and writes JSON and Parquet to MinIO.
Once the poller has no ClickHouse access, the rollup job **moves to the analytics container**: same code,
running next to ClickHouse and S3. Resolved in Phase 14.2 (D-04): the rollup moved in 14.2, and the poller
no longer has any rollup or S3 code.

### Other cloud-split items noted for later (not Phase 14.2)

- Topology edit mode writes straight to Checkmk's REST API through the dashboard's nginx (`/checkmk-api`).
  That cannot work from the cloud without exposing Checkmk. Edits would go through a command topic on the
  broker, executed by an on-prem agent, as admin mode (`admin/cmd`) already does.
- Admin-mode commands travel through the broker, so TLS and ACLs on the cloud broker become important.

---

## Part 2: worked timeline of the messages

**The cast:** `sw1`, a managed switch at 192.168.100.1. `linux1`, an agent host at .20 with `sw1` as its
parent. `cam1`, a ping-only host at .30, also behind `sw1`. The poll cycle is 15 s.

### Every cycle: one `status` per host, even when nothing changed

`lan/devices/linux1/status`, QoS 0, retained. A cycle where nothing changes still publishes this, plus the
`lan/poller/status` heartbeat, and nothing else:

```json
{"id":"linux1","state":"OK","in_downtime":false,"acknowledged":false,
 "device_type":"server","folder":"/vlan100","alias":"","address":"192.168.100.20",
 "staleness":0.4,"host_state_raw":"UP","timestamp":"2026-10-03T04:00:00+00:00",
 "cpu_percent":12.3,"cpu_warn":80,"cpu_crit":90,
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
 "ram_percent":null,"ram_warn":null,"ram_crit":null,
 "disk_percent":null,"disk_warn":null,"disk_crit":null,
 "disk_other_worst_percent":null,"disk_other_worst_warn":null,"disk_other_worst_crit":null,
 "disk_other_worst_mount":null,"smart_total":null,"smart_failing":null}
```

`lan/devices/cam1/status` has the same shape, with `"id":"cam1"`, `"device_type":"camera"` (or whatever
its `device_type` tag is), `"address":"192.168.100.30"` and the same fifteen `null` gauge keys.

What differs from `linux1`:

- **All fifteen gauge keys are present but `null`.** The poller sets a gauge key to `null` when its backing
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

### 12:00:30: a service changes (`Systemd Service cron` goes OK to CRIT)

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

3. **`lan/events/recent`** (the global feed):

   ```json
   // events (whole bounded array, up to 1000 entries; shown with one entry)
   [{"timestamp":"2026-10-03T04:00:30+00:00","device_id":"linux1","event":"state_change","from":"OK","to":"CRIT"}]
   ```

**No incident is created.** Incidents only come from host-level DOWN and UNREACH.

### 12:01:00: CPU, RAM, filesystem and SMART do not use `services`

`CPU utilization`, `Memory`, every `Filesystem *` and the `SMART ... Stats` services are excluded from the
`services` list, as is `Systemd Service Summary`. They appear on the **`status`** topic as the gauge keys
above. So when `/var` goes from 70% to 82%:

- The `status` payload's `disk_other_worst_percent` changes. That is all that is published for the numbers.
- If `/var` crosses its warning threshold the host state changes from OK to WARN, which publishes an `events`
  entry, exactly as in the `cron` example. But there is **no `services` republish**, because those services are not in the list.

### 12:05:00: `sw1` goes DOWN, so `linux1` and `cam1` become UNREACH

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

### 12:08:00: `sw1` recovers

- `status` and `events` for each of the three hosts, back to `OK`/`UP`.
- The incident is **tombstoned**: an empty retained payload on `lan/incidents/incident-sw1/status`, QoS 1.
  A consumer never receives an "incident closed" message. It only sees the topic cleared, and only if it is
  connected at that moment.

### The other messages

- **`lan/devices/topology`**, QoS 1, retained, only when the structure or a label changes. A list of
  `{id, parents, device_type, folder, alias, map_position, unmanaged, criticality, service_criticality, depends_on}`.
- **`lan/poller/status`**, every cycle, QoS 1, retained:
  `{"status":"online","since":...,"last_poll":...,"device_count":N}`. A broker-side Last Will publishes
  `{"status":"offline"}` if the poller drops.
- **Host removal** tombstones the host's retained `status` and `services` topics (plus, for one release, the
  retired `history` and `service_history` paths) and adds an `events` entry with `"event":"removed"` and `"to":null`.

### What a cloud-side programmer must know

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

## Part 3: how the current dashboard uses these topics

Source: `dashboard-react/src/store/mqttClient.ts` (connection), `store/useAppStore.ts` (message handling) and
the components that read the store. Verified by reading the code, not by running it.

### Connection

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

### Subscriptions

`mqttClient.ts` subscribes to `sites/<checkmkSite>/...`, with `checkmkSite` read from the runtime `/config.json`. It strips the prefix once, in `dashboard-react/src/lib/topics.ts`, so the store sees the relative topics below; a message outside this site's prefix is dropped.

```
lan/devices/+/status           lan/devices/+/services
lan/devices/topology           lan/events/recent
lan/poller/status              lan/incidents/+/status
```

### How a message becomes state

- The store (Zustand) **replaces** each slot with the latest message and never appends. Every topic is
  already a full snapshot (see Part 1), so appending would double-bound an already-bounded array and leak
  memory on a kiosk tab that stays open for days.
- A payload that fails to parse, or has the wrong shape, is dropped and the last good value stays. A bad
  message can't blank the page.
- A **zero-length retained payload is a tombstone.** On a `status` tombstone the device and all its
  per-device slices (`services`) are removed together. On an incident
  tombstone the incident is removed.

### Which topic feeds which part of the screen

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

### Staleness: why `status` is published every cycle

- A device is stale if Checkmk's own `staleness` value is at or above the configured factor, or, when that
  is `null`, if the payload `timestamp` is older than the factor times the poll interval.
- A stale device is shown and counted as **STALE** instead of its reported state.
- The dashboard re-evaluates this on a timer (`useNowTick`), so a host whose messages simply stop turns
  STALE with no new message. That is why the per-cycle QoS 0 `status` matters: it acts as the per-host
  heartbeat, and a retained `status` that never updates ages out.

### What the dashboard does **not** use MQTT for

- **Topology edits** go straight to Checkmk's REST API through the dashboard's nginx `/checkmk-api`
  location (nginx adds the `topology_editor` credential). Nothing on MQTT.
- **History and availability** are not shown yet. The nginx paths `/ch-api/` (read-only ClickHouse) and
  `/availability/` (rollup objects in MinIO) exist and are smoke-tested, but no dashboard view uses them
  (D-50). Grafana reads ClickHouse directly.

### What this means for a cloud broker or a new dashboard

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

## Part 4: bandwidth options for a metered link and many sites

Context (discussion 2026-10-03): the broker, ClickHouse and dashboard will move to the cloud, each site
may be on 4G, and one broker may receive tens of host updates from hundreds of sites. Today's contract
(Parts 1 to 3) was designed for a single LAN, so several choices that are free on a LAN are expensive here.

Every figure below is an **estimate**: payload sizes were measured from the example shapes in Part 2, and
the host, service and metric counts are assumptions. Replace them with live numbers before deciding
(see "Measure first" at the end).

### Where the bytes go (per site, per day, if today's design is moved as is)

| Traffic | Size | Per day | Notes |
|---|---|---|---|
| `status` every cycle, per host | about 590 bytes (gzip only halves it) | about 3.4 MB per host, about 100 MB for 30 hosts | Mostly unchanged data, 5760 times a day. |
| History samples over MQTT (the Part 1 proposal) | about 380 KB per cycle for an assumed 2400 rows (20 agent hosts x 40 services x 3 metrics) | about 2.2 GB raw, about 210 MB gzipped | By far the biggest. The test data was random, so real data likely compresses better. |
| `sites/<site_id>/lan/events/recent` | up to about 127 KB per republish | small normally, up to about 730 MB if it changes every cycle | A flapping fleet is the worst case. |
| Per-device `history` and `service_history` | none | none | Removed 2026-10-04 (quick 261004-kbt); transition history comes from ClickHouse. |

Downstream matters too: a cloud dashboard that pulls every retained message on connect would fetch tens of
MB when hundreds of sites share one broker.

### Options, by lever

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

### Recommendation (proposed, not yet decided)

Take three levers together:

- **1, samples:** only publish a sample row when `last_check` advances.
- **2:** events as small messages, no whole arrays, recent history read from ClickHouse.
- **3:** gzip, plus 1-minute aggregation.

The **per-site namespace** was added in Phase 14.3 (done), because renaming topics later is painful. With these, the rough
estimate is a few tens of MB per site per day instead of gigabytes.

Status-by-exception (lever 1, status) is the biggest change to the dashboard, so treat it as a second
step.

### Decisions (2026-10-03)

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

### Measure first

- Rows per cycle on the live stack:
  `SELECT count() FROM history.metrics WHERE ts = (SELECT max(ts) FROM history.metrics)`.
- Whether Checkmk really checks once a minute: add `last_check` to the services query and count how often
  it changes between 15 s polls for a typical service.

---

## Phase 14.2 analytics topics

The `analytics` container (`python -m analytics`, source in `analytics/`) added three published topics and
one consumed command topic. Every topic is shown with its full `sites/<site_id>/` prefix; the dashboard strips
the prefix once at its MQTT edge. Payload keys come from the implementation (`Need.to_payload` in
`analytics/rules.py`, `Fit.to_payload` in `analytics/fit.py`, `_publish_forecasts` and `_publish_narration`
in `analytics/service.py`, `parse_triage_command` in `analytics/triage.py`). The example values are
illustrative: they were not captured from a live broker. Every analytics publish is compact JSON, QoS 1.

| Topic | Writer | When published | QoS | Retained | Cleared by |
|---|---|---|---|---|---|
| `sites/<site_id>/lan/needs/{need_id}/status` | analytics | when a need appears or changes, after a triage command, and each evaluation cycle (default every 900 s) | 1 | yes | tombstone |
| `sites/<site_id>/lan/forecasts/{host}` | analytics | every evaluation cycle, for each host that has at least one fit | 1 | yes | tombstone |
| `sites/<site_id>/lan/incidents/{incident_id}/narration` | analytics | when an incident's narration text or tier changes | 1 | yes | tombstone |
| `sites/<site_id>/needs/triage/cmd` | dashboard, as `wstriage` | on an operator triage action | 1 | no | n/a |

`needs/triage/cmd` sits outside `lan/`, so the read-only `wsreader` login never receives it.

### Needs: `lan/needs/{need_id}/status`

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

### Forecasts: `lan/forecasts/{host}`

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

### Incident narration: `lan/incidents/{incident_id}/narration`

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

### Triage command: `needs/triage/cmd`

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

### ACL for the new logins

From `deploy/mosquitto.acl.template`:

| User | Grants |
|---|---|
| `analytics` | `read sites/<site_id>/lan/#`, `read sites/<site_id>/needs/triage/cmd`, `write sites/<site_id>/lan/needs/#`, `write sites/<site_id>/lan/forecasts/#`, `write sites/<site_id>/lan/incidents/+/narration` |
| `wstriage` | `write sites/<site_id>/needs/triage/cmd` only; no read |

`analytics` has no write on `lan/incidents/+/status`, which stays the poller's. `wstriage` is served openly on
`/triage-config.json` (like `wsadmin` on `/admin-config.json`), so it is for a closed network only. Its reach
is bounded: analytics validates every command, and a command can only change a need's tier.

