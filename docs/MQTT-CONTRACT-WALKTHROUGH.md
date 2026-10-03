# MQTT contract walkthrough and history-over-MQTT proposal

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
| `lan/devices/{id}/status` | every cycle, every host | 0 | yes |
| `lan/devices/{id}/services` | only when the service list changes | 1 | yes |
| `lan/devices/{id}/history` | only on a state transition of that host | 1 | yes |
| `lan/devices/{id}/service_history` | only on a per-service state transition | 1 | yes |
| `lan/events/recent` | only on any host's state change, add or remove | 1 | yes |
| `lan/incidents/{incident_id}/status` | only when an incident opens or its content changes | 1 | yes |
| `lan/devices/topology` | only when structure or a label changes | 1 | yes |
| `lan/poller/status` | birth, every cycle, last will | 1 | yes |

Things to know:

- It is all MQTT and mostly **retained whole-state**, not a stream of events. `history`, `service_history`
  and `events` are bounded arrays that are rewritten whole.
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

- Replace `write_history()`'s HTTP insert with a **publish** of the same rows, for example one message per
  cycle on `history/samples` (QoS 1, not retained). `build_history_rows()` itself does not change.
- Publish discrete messages for events and incident open/close on `history/events` and `history/incidents`
  (QoS 1, not retained). The retained `lan/events/recent` array is awkward for a database writer, because it
  is rewritten whole and would need deduplicating.
- The **analytics container** subscribes to `history/#` with a persistent session and inserts into
  ClickHouse over HTTP, locally. The poller then holds no ClickHouse credentials, and ClickHouse is never
  exposed to the internet. The poller's only outbound dependency becomes the broker.

Implications to plan for:

- **ACL.** The browser user `wsreader` can read `lan/#`. The `history/` prefix must sit outside it, so the
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
running next to ClickHouse and S3. Open question for Phase 14.2: move it in 14.2, or leave it in the poller
until the cloud migration.

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
  (published at startup and whenever a service state changes), plus `history` and `service_history` that
  only change on transitions. A steady `PING` OK produces nothing beyond the per-cycle `status`.

**12:00:00 and 12:00:15:** nothing changes. For all three hosts, only `status` (and the `lan/poller/status`
heartbeat) is published.

### 12:00:30: a service changes (`Systemd Service cron` goes OK to CRIT)

This is a service that is **not** CPU, RAM, disk or SMART. Four kinds of message follow in the same cycle.

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

2. **`lan/devices/linux1/service_history`**, QoS 1, retained. The whole bounded array, with the new entry
   appended:

   ```json
   [{"timestamp":"2026-10-03T04:00:30+00:00","description":"Systemd Service cron","from":"OK","to":"CRIT"}]
   ```

3. **`lan/devices/linux1/status`** now has `"state":"CRIT"`, because `cron` is a service the dashboard
   shows. The status topic is the only topic that carries the host-level result.

4. **`lan/devices/linux1/history`** (the host's own transitions) and **`lan/events/recent`** (the global
   feed):

   ```json
   // history (whole bounded array)
   [{"timestamp":"2026-10-03T04:00:30+00:00","from":"OK","to":"CRIT"}]
   // events (whole bounded array, up to 1000 entries; shown with one entry)
   [{"timestamp":"2026-10-03T04:00:30+00:00","device_id":"linux1","event":"state_change","from":"OK","to":"CRIT"}]
   ```

**No incident is created.** Incidents only come from host-level DOWN and UNREACH.

### 12:01:00: CPU, RAM, filesystem and SMART do not use `services`

`CPU utilization`, `Memory`, every `Filesystem *` and the `SMART ... Stats` services are excluded from the
`services` list, as is `Systemd Service Summary`. They appear on the **`status`** topic as the gauge keys
above. So when `/var` goes from 70% to 82%:

- The `status` payload's `disk_other_worst_percent` changes. That is all that is published for the numbers.
- If `/var` crosses its warning threshold the host state changes from OK to WARN, which publishes `history`
  and an `events` entry, exactly as in the `cron` example. But there is **no `service_history` entry and no
  `services` republish**, because those services are not in the list.

### 12:05:00: `sw1` goes DOWN, so `linux1` and `cam1` become UNREACH

Each of the three hosts has a state change, so each gets a `history` array update and an `events` entry. The
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

- `status`, `history` and `events` for each of the three hosts, back to `OK`/`UP`.
- The incident is **tombstoned**: an empty retained payload on `lan/incidents/incident-sw1/status`, QoS 1.
  A consumer never receives an "incident closed" message. It only sees the topic cleared, and only if it is
  connected at that moment.

### The other messages

- **`lan/devices/topology`**, QoS 1, retained, only when the structure or a label changes. A list of
  `{id, parents, device_type, folder, alias, map_position, unmanaged, criticality, service_criticality, depends_on}`.
- **`lan/poller/status`**, every cycle, QoS 1, retained:
  `{"status":"online","since":...,"last_poll":...,"device_count":N}`. A broker-side Last Will publishes
  `{"status":"offline"}` if the poller drops.
- **Host removal** tombstones the host's four retained topics (`status`, `history`, `services`,
  `service_history`) and adds an `events` entry with `"event":"removed"` and `"to":null`.

### What a cloud-side programmer must know

1. **Almost everything is retained and whole-state, not a stream.** A new subscriber gets the latest state per
   topic immediately. That is why `history`, `service_history` and `events` are rewritten as whole arrays:
   they are bounded, not append-only.
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
  Mosquitto share a host. The browser user is `wsreader` (read `lan/#` only), with the login read from the
  runtime `/config.json` that nginx serves from `deploy/.env`.
- **Clean session, no persistence on the client.** Everything the dashboard knows comes from the broker's
  retained messages, replayed when it subscribes. There is no cache-warming request of any kind.
- **Reconnects** use its own jittered exponential backoff (1 s up to 30 s), driven from the `close` event.
  mqtt.js's built-in fixed-interval retry is turned off.
- **On every (re)connect the incidents slice is cleared first**, then it subscribes, so the retained replay
  rebuilds incidents from scratch. Incidents are change-triggered and tombstoned on close, so a tombstone
  missed while disconnected would otherwise leave a closed incident on screen forever.
- **Admin mode only (`?admin=1`)** adds a second login (`wsadmin`), subscribes to `admin/ack` and
  `admin/faked`, and publishes commands on `admin/cmd` (QoS 1, not retained, so a command never replays after
  a poller restart).

### Subscriptions

```
lan/devices/+/status           lan/devices/+/history
lan/devices/+/services         lan/devices/+/service_history
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
  per-device slices (`history`, `services`, `service_history`) are removed together. On an incident
  tombstone the incident is removed.

### Which topic feeds which part of the screen

| Topic | Store slice | Where it is used |
|---|---|---|
| `lan/devices/{id}/status` | `devices` | The **device tree** (grouped by folder or by `device_type`, ordered by severity). The **map**: node colour and label (state, stale override, alias, address). The **header counts** (OK/WARN/CRIT/DOWN/STALE). The **host details pane**: state badge, address, and the CPU, RAM, disk and SMART gauges from the gauge keys. Display names in the event list and editors. |
| `lan/devices/topology` | `topology` | The **map layout**: nodes, parent links (edges), saved `map_position`, unmanaged-switch marker. The **criticality editor** (criticality, per-service criticality, `depends_on`). |
| `lan/devices/{id}/services` | `services` | The **host details pane**'s service tables. For an agent host it shows the chosen `Systemd Service` and `Service` entries, `TCP Port` checks, `Check_MK` (agent connected) and `Uptime`. For any other host it shows the full table. Also the editor's per-service criticality list (the same filtered set). |
| `lan/events/recent` | `events` | The **event history pane** (newest first, filtered to the open host, with a From/To date-time filter). |
| `lan/incidents/{id}/status` | `incidents` | The **incident pane** (cards ordered by criticality tier, then longest open) and the markers that dim or flag affected hosts in the tree and map. |
| `lan/devices/{id}/history` | `history` | **Stored, but no component reads it today.** |
| `lan/devices/{id}/service_history` | `serviceHistory` | **Stored, but no component reads it today.** |
| `lan/poller/status` | `pollerStatus`, `lastKnownPollerTimestamp` | **Stored, but not displayed.** `isPollerStale()` exists in `lib/staleness.ts` but only tests call it. |

The two per-device history topics and the poller heartbeat are published and kept in memory, but the UI
doesn't show them yet. A new dashboard can ignore them, or start using them.

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
5. **Initial load size.** On connect the client receives every retained message at once: one `status`,
   `services`, `history` and `service_history` per host, plus the topology, the events array (up to
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
| `lan/events/recent` | up to about 127 KB per republish | small normally, up to about 730 MB if it changes every cycle | A flapping fleet is the worst case. |
| Per-device `history` and `service_history` | 1.5 to 2.3 KB each, per transition | small | Not read by the UI at all (Part 3). |

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
   - Drop the per-device `history` and `service_history` topics from the WAN. The UI does not read them,
     and the durable copy is in ClickHouse.
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
   - A per-site namespace such as `sites/<site_id>/...` with an ACL per site user, so a dashboard
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

Add the **per-site namespace now**, because renaming topics later is painful. With these, the rough
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

