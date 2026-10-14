# Phase 17: Cloud MQTT Contract and S3 Archive Feed - Research

**Researched:** 2026-10-14
**Domain:** Mosquitto bridge remap, MQTT v5 user properties (paho-mqtt 2.1), publish throttling, history-over-MQTT, shared-broker ACLs
**Confidence:** MEDIUM (bridge syntax HIGH from official man page; user-property pass-through through a bridge and retained/tombstone behaviour across reconnects are source-read or inferred and MUST be proven by a live smoke test)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** The archiver is one side-consumer of the broker, not the live path. Dashboard and analytics keep reading retained state from the broker; S3 is a durable raw log and replay source only.
- **D-02:** History rows (`history.host_state`, `history.service_state`, `history.metrics`) are published by the poller as discrete MQTT messages. The cloud analytics container subscribes and inserts into ClickHouse. The poller holds no ClickHouse credentials in cloud mode. The archiver captures the same messages in S3 as the replay log.
- **D-03:** Each history batch carries a deterministic `event_id` so the cloud writer can deduplicate at-least-once redelivery.
- **D-04:** A Mosquitto bridge remaps `sites/<site_id>/` to `app/<SEN>/<site_id>/` on the way out. The local namespace, ACLs, dashboard and tests from Phase 14.3 stay unchanged. Prefix mapping support in bridge `topic` lines is believed but not verified; research must confirm from the Mosquitto docs.
- **D-05:** Both `<SEN>` and `<site_id>` are real keys. Nothing derives one from the other, so one-or-many sites per SEN keeps working.
- **D-06:** Only discrete messages are archived (events, incidents, services, topology, commands and acks, history batches). Per-cycle status samples are not archived as a stream.
- **D-07:** The poller throttles the shared `lan/devices/{id}/status` topic itself: publish on state change; publish metric fields (cpu, ram, disk and similar gauges) on a slower heartbeat; publish immediately when a metric crosses a warn or crit threshold. The bridge forwards whatever the local broker receives.
- **D-08:** The metrics heartbeat is configurable via env (name to be chosen in planning, e.g. `CLOUD_METRICS_HEARTBEAT_S`), default 5 minutes.
- **D-09 (consequence to carry into planning):** Because D-07 throttles the shared topic, the on-prem dashboard's gauges also refresh at the heartbeat rate by default, not every 15 s. A site that wants fresher local gauges lowers the heartbeat setting. Hosts whose state is not changing still need a liveness signal, so `lan/poller/status` stays per cycle and staleness handling must be re-checked against the dashboard.
- **D-10:** The poller moves to MQTT v5 (today paho defaults, v3.1.1: `scripts/mqtt_poller.py:2802`, `analytics/service.py:209`). `event_id` is sent as an MQTT v5 user property.
- **D-11:** `event_id` is deterministic from message identity (incident id plus revision, event key, history batch id from cycle timestamp and site), so retries reuse it without persisting anything.
- **D-12:** The wizard prompts for SEN during site bring-up and writes it to the deployment env file as `SITE_SEN`. Validated as a positive integer without leading zeros. Poller, analytics and the dashboard `config.json` all read it. Where the wizard (which runs from the worker container) can write the compose env file is an open item for research.

### Claude's Discretion
- Exact env var names, bridge connection settings (clean session, queueing during WAN outage, QoS per topic), the `event_id` formats, and the history batch topic name and size splitting.
- How tombstones (empty retained payloads for closed incidents) and retained re-delivery are handled across the bridge and in the archive.
- Cloud ACL shape: per-SEN user on `app/<SEN>/#` is the starting point, tightening to `app/<SEN>/<site_id>/#` only if needed.

### Deferred Ideas (OUT OF SCOPE)
- Edit-mode writes to Checkmk REST (`/checkmk-api`) from the cloud (needs a command topic and an on-prem agent).
- Cloud-side ClickHouse loading from S3 JSONL as an alternative or backfill path.
- Multi-site dashboard views over several `app/<SEN>/<site_id>/` subtrees.
</user_constraints>

## Summary

The remap is a one-line job in a Mosquitto bridge: `topic # out 1 sites/<site_id>/ app/<SEN>/<site_id>/` (pattern, direction, QoS, local-prefix, remote-prefix). The man page documents this prefix form and the `topic # both 2 local/topic/ remote/topic/` remap example, so D-04 is confirmed. The bridge must be a v5 bridge (`bridge_protocol_version mqttv50`) for user properties to be meaningful on the cloud leg. Reading the Mosquitto source (`database.c`), properties stored with a message are passed unchanged to `send__publish` and nothing strips them for bridge clients; so `event_id` set by a v5 poller should survive the bridge. That is source-read, not live-verified, so the plan needs a live smoke test as its first gate (poller v5 publish with user property, local broker, bridge, cloud broker, `mosquitto_sub -F %j`/paho v5 subscriber sees `event_id`).

Three things in the current code make this phase bigger than "add a bridge": (1) the history tables are plain `MergeTree` with no site/SEN column and TTL `GROUP BY` rollups that sum `samples`, so a redelivered batch silently double-counts and a shared cloud ClickHouse cannot tell sites apart; (2) `analytics/topics.py` hard-codes `sites/<CMK_SITE_ID>/` as its only subscription prefix, so a cloud analytics container reading `app/<SEN>/<site>/...` needs a configurable prefix; (3) `lan/events/recent` is a retained whole array of up to ~127 KB that the bridge will resend on every change AND on every bridge reconnect (retained re-queue), which is exactly what D-06/D-07 are trying to avoid on 4G.

Wizard writing `SITE_SEN`: the worker container bind-mounts the whole checkout (`../..:/app:z`, rw), so `deploy/.env` is writable from the wizard at `/app/checkmk-wizard/deploy/.env`. Caveat: compose reads `.env` only at container creation, so the new value needs a full `down/up`, the same constraint the wizard already documents for `CMK_REST_SECRET`.

**Primary recommendation:** Render a bridge config fragment at mosquitto container start (same pattern as `render-mosquitto-acl.sh`), use `topic # out 1 sites/<id>/ app/<SEN>/<id>/` with `bridge_protocol_version mqttv50`, `cleansession false`, a stable `remote_clientid`, and add a v5 `event_id` helper in `_publish_json`; gate the whole phase on a live end-to-end smoke test of user-property and tombstone pass-through before building anything on top.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Prefix remap `sites/<id>/` to `app/<SEN>/<id>/` | Local broker (Mosquitto bridge) | none | Keeps poller, ACLs, dashboard unchanged (D-04) |
| `event_id` generation | Poller / analytics (publishers) | none | Only the producer knows event identity (D-11) |
| Change-only / heartbeat throttling | Poller | none | Bridge is dumb; throttle must happen before local publish (D-07) |
| History rows to ClickHouse | Cloud analytics container | Poller (publish only) | Poller holds no CH creds in cloud mode (D-02) |
| Dedup of redelivered batches | Cloud analytics container | ClickHouse | At-least-once on every hop |
| Per-SEN authorization | Cloud broker ACL | Bridge remote credentials | `%u`-pattern ACL on shared broker |
| SEN config | Wizard / `deploy/.env` | compose, dashboard nginx | One value, read by poller, analytics, bridge render, config.json |
| S3 landing | Archiver (`fsu-mqtt`, not ours) | none | Out of scope; we only meet its topic contract |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| eclipse-mosquitto | `2` image tag already in `deploy/compose.yaml:60` | Local broker with outbound bridge | Bridge, `bridge_protocol_version mqttv50`, per-topic prefix remap are in 2.0 `[CITED: mosquitto.org/man/mosquitto-conf-5.html]` |
| paho-mqtt | 2.1.0 (locked in `uv.lock`, `pyproject.toml:14`) | v5 publish with `Properties` | Already the project client; v5 via `protocol=mqtt.MQTTv5` `[ASSUMED: paho 2.x API, verify with ctx7 at plan time]` |

### Supporting
None new. No new packages are required, so the package legitimacy gate is not triggered.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Mosquitto bridge | Poller dual-publishes to a second (cloud) client | Violates "local contract, ACLs, tests untouched", loses broker-side queueing; rejected by D-04 |
| Bridge | Separate relay process | New service to ship; the bridge already does queue + reconnect |

**Installation:** none. Version verification: not applicable (no new dependency; `eclipse-mosquitto:2` floats, so pin a patch tag at deploy time if bridge behaviour is found to differ).

## Package Legitimacy Audit

No new external packages. Packages removed due to [SLOP]: none. Flagged [SUS]: none.

## Architecture Patterns

### System Architecture Diagram

```
 Checkmk (Livestatus)            on-prem host (podman)                         cloud
        |                                                                                    
        v                                                                                    
  +-----------+  v5 publish, QoS 0/1, event_id user prop       +-----------------+          
  |  poller   |-----------------------------------------------> | local mosquitto |          
  | throttle: |  sites/<id>/lan/**, sites/<id>/history/<tbl>    |  ACL (unchanged |          
  | state chg |                                                 |  + user bridge) |          
  | + heartbt |<--admin/cmd, needs/triage/cmd------------------ |                 |          
  +-----------+                                                 +---+---------+---+          
        ^                          dashboard (ws, wsreader/wsadmin/wstriage)  |              
        |                          analytics (local, unchanged) -------------+ |              
        |                                                                      v              
        |                                              bridge "cloud-<SEN>-<id>"             
        |                                              topic # out 1 sites/<id>/ app/<SEN>/<id>/
        |                                              v5, cleansession false, TLS           
        |                                                      |  4G link                    
        |                                                      v                            
        |                                             +-----------------+   app/#  QoS1   +----------+ JSONL  +----+
        |                                             | cloud mosquitto |----------------->| fsu-mqtt |------->| S3 |
        |                                             | ACL: app/%u/#   |                  +----------+        +----+
        |                                             +--------+--------+                                         
        |                                                      | app/<SEN>/<id>/history/#  (persistent session) 
        |                                                      v                                                 
        |                                             cloud analytics --dedupe(event_id)--> ClickHouse          
```

### Recommended Project Structure
```
deploy/
├── mosquitto.conf                    # add: include_dir for rendered bridge fragment
├── mosquitto.bridge.template         # NEW: @SITE_ID@ @SITE_SEN@ @CLOUD_*@ placeholders
├── render-mosquitto-bridge.sh        # NEW: validates + sed, mirrors render-mosquitto-acl.sh
├── mosquitto.acl.template            # add `user bridge` (read sites/@SITE_ID@/#), `user` history reader
├── mosquitto.cloud-acl.example       # NEW: pattern app/%u/# per-SEN, archive read app/#
├── compose.yaml                      # SITE_SEN + CLOUD_* env to mosquitto/poller/analytics/dashboard
└── init-env.sh                       # optional: SITE_SEN prompt for non-wizard installs
scripts/mqtt_poller.py                # v5 client, event_id helper, status throttle, history publish
analytics/                            # v5 client, configurable topic prefix, history subscriber + dedupe
src/checkmk_wizard/wizard.py          # SITE_SEN prompt + write to deploy/.env
```

### Pattern 1: Bridge fragment (rendered at start)
**What:** one `connection` block per site, topic remap via prefixes.
**Example:**
```
# Source: mosquitto.org/man/mosquitto-conf-5.html (topic syntax, prefix example, bridge settings)
connection cloud-@SITE_SEN@-@SITE_ID@
address @CLOUD_BROKER_HOST@:8883
bridge_protocol_version mqttv50
bridge_cafile /mosquitto/certs/cloud-ca.pem
remote_clientid bridge-@SITE_SEN@-@SITE_ID@
remote_username @SITE_SEN@
remote_password @CLOUD_BROKER_PASSWORD@
local_username bridge
local_password @MQTT_BRIDGE_PASSWORD@
cleansession false
bridge_session_expiry_interval 86400
keepalive_interval 60
notifications false
topic # out 1 sites/@SITE_ID@/ app/@SITE_SEN@/@SITE_ID@/
```
Notes: direction `out` only (nothing flows back, so no loop risk; `no_local` is set by the broker on the local subscription). `remote_clientid` must be stable so the cloud broker keeps the queued session (default is `name.hostname`, which changes if the container hostname changes `[CITED: man page]`). `notifications false` avoids the bridge publishing its state under `$SYS/...` on the cloud broker where the per-SEN ACL would deny it. Mosquitto config has no env expansion (existing template comments already note this), hence rendering. `include_dir` is a documented mosquitto.conf directive `[ASSUMED: confirm in man page at plan time]`; the alternative is to render the whole `mosquitto.conf` at start.

### Pattern 2: v5 publish with `event_id` in `_publish_json`
```python
# Source: paho-mqtt 2.x v5 API [ASSUMED: verify via context7 `paho-mqtt` at plan time]
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
...
def _publish_json(client, topic, payload, qos, retain, event_id=None):
    props = None
    if event_id:
        props = Properties(PacketTypes.PUBLISH)
        props.UserProperty = [("event_id", event_id)]
    client.publish(topic, json.dumps(payload), qos=qos, retain=retain, properties=props)
```
v5 migration deltas in this codebase: `connect()` uses `clean_start=` (not `clean_session`); `on_connect`/`on_disconnect` VERSION2 signatures already match; subscribers that must survive a restart need `clean_start=False` plus a `SessionExpiryInterval` connect property, because a v5 session expiry defaults to 0. The analytics client today is clean-session with no persistence (`analytics/service.py:204-216`), contrary to the walkthrough's "persistent session" wording; the history subscriber needs this changed.

### Pattern 3: Deterministic `event_id` (D-11)
Must be unique within `(SEN, site, subtopic)` `[CITED: docs/MQTT_CLIENT_DATA_FLOW.md]` and reused on retry. Recommended formats:

| Message | event_id | Why |
|---------|----------|-----|
| history batch chunk | `<cycle_epoch_s>-<table>-<chunk_idx>` | Same cycle and chunking produce the same id on retry; subtopic already carries the table and (via prefix) the site |
| incident status | `<incident_id>-<since_epoch>-<sha1(payload)[:8]>` | Revision = content signature the poller already computes |
| events recent (whole array) | `sha1(payload)[:16]` | Content-addressed; identical rewrite dedupes |
| tombstone | `<incident_id>-closed-<since_epoch>` | Distinct from the open revision |
| services / topology | `sha1(payload)[:16]` | Same |
| admin/cmd, triage cmd | the command's own `id` field (`cmd-...`) | Already unique and stable |
| status (throttled) | omit | Retained whole-state, no dedupe need; avoids per-cycle ids |

Never use wall-clock `now()` at publish time; derive from the cycle timestamp or content so a retry computes the same value.

### Pattern 4: Poller status throttle (D-07)
Per device, keep `last_published_discrete = (state, host_state_raw, in_downtime, acknowledged, services-failure flags)` and `last_gauge_publish_ts`. Publish when the discrete tuple changes, when `now - last_gauge_publish_ts >= CLOUD_METRICS_HEARTBEAT_S`, or when any gauge crosses its own `*_warn`/`*_crit` (compare band before/after: ok/warn/crit). State lives in `PollerState` (already holds `last_status`). On restart the throttle state is empty, so every host publishes once, which is also what the retained re-seed needs.

Gotcha for D-09: the dashboard's staleness check uses the per-host `status` `timestamp`/`staleness`; once status becomes rare, every healthy host reads STALE. The planner must pick one fix and put it in a task: (a) have the dashboard use `lan/poller/status` (per cycle, already published) as the freshness source, or (b) keep Checkmk's `staleness` value but make the payload `timestamp` refresh only at heartbeat and widen the threshold. Option (a) matches CONTEXT D-09 ("`lan/poller/status` stays per cycle and staleness handling must be re-checked"). Touches `dashboard-react/src/lib/staleness.ts` (`isPollerStale` exists but is unused) and Part 3 of the walkthrough.

### Pattern 5: History over MQTT (D-02/D-03)
- Topic: `sites/<id>/history/<table>` with table in `host_state|service_state|metrics` (outside `lan/`, so `wsreader` cannot read it; same rationale as the walkthrough's ACL note). Cloud form: `app/<SEN>/<id>/history/<table>`. The archive's `base_topic` becomes `history`.
- QoS 1, not retained (a retained batch would be re-sent on every bridge reconnect and re-inserted).
- Payload: `{"ts": "...", "rows": [...]}` (rows exactly as `build_history_rows` emits, so that function is untouched). Rows carry no site/SEN column; the cloud writer adds it from the topic.
- Size: broker `message_size_limit` is 2 MB (`deploy/mosquitto.conf`); the walkthrough estimates ~380 KB per cycle for 2400 rows `[CITED: walkthrough Part 4, unmeasured]`. Split into chunks of at most ~500 rows (~80 KB) so a 4G drop mid-batch loses little and no message approaches the limit.
- Sending every 15 s cycle is the dominant 4G cost (~2.2 GB/day raw estimated). The decision log (Part 4) recommends gzip and 1-minute aggregation; D-02 as written does not. Recommend the planner add a bounded, config-driven knob (`HISTORY_PUBLISH_INTERVAL_S`, default one batch per minute taking the latest cycle, or aggregate to the existing `value_min/max/sum/count` columns) and flag it in Open Questions. The archive stores payload as a JSON string, so gzip would arrive base64-encoded `[CITED: MQTT_CLIENT_DATA_FLOW.md payload section]` and be unreadable in S3 without a decoder; weigh that.
- Failure posture: today a ClickHouse outage drops rows (D-47). Over MQTT the local broker queues for the bridge; default `max_queued_messages` is 1000 per client `[ASSUMED: mosquitto default]`, so a long 4G outage drops oldest/newest silently. Set `max_queued_messages` and `max_queued_bytes` explicitly in `mosquitto.conf` (global, not per-bridge `[CITED: man page]`) and document the loss window.

### Pattern 6: Cloud ACL on a shared broker
Mosquitto `pattern` supports `%u` and `%c` only `[CITED: existing deploy/mosquitto.acl.template header, mosquitto-conf(5)]`. If the cloud login username equals the SEN (digits), one static block covers all SENs:
```
pattern readwrite app/%u/#
user fsu-mqtt
topic read app/#
user analytics-cloud
topic read app/#
```
`readwrite` is needed only because a bridge may also be checked on subscribe; `write` alone suffices for `out`-only. Use `write app/%u/#`. This still allows SEN 123 to write `app/123/<any-site>/...`; tightening to a specific site needs one user per (SEN, site), which D-05's one-or-many model makes awkward, so keep `app/%u/#` (Claude's-discretion default). Do not let the bridge user have read on `app/#` (a compromised site could read other tenants).

### Anti-Patterns to Avoid
- **Archiving the throttled status stream implicitly:** `topic #` forwards `lan/devices/+/status` too, so "status not archived" (D-06) is only true insofar as D-07 makes it rare. If the archive must not hold status at all, split the bridge into explicit `topic lan/devices/+/services out 1 ...`, `lan/events/#`, etc., or exclude with narrower topic lines. Planner decision (see Open Questions).
- **Wall-clock event ids**, or ids containing `/`, `+`, `#`.
- **Putting SEN into the local namespace** (breaks 14.3 ACL/tests, defeats D-04).
- **Dropping v3.1.1 compatibility checks on the dashboard:** browser clients (mqtt.js) can stay v3.1.1; the broker serves both on the same listener.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Prefix remap and WAN queueing | A relay script | Mosquitto bridge `topic` prefixes + persistent session | Reconnect, QoS 1 inflight, queue already solved |
| Redelivery dedupe key | Payload-equality heuristics | Deterministic `event_id` + `(sen, site, subtopic, event_id)` | Contract says the archive never synthesizes it |
| Per-tenant ACL | Per-SEN rendered ACL files | `pattern ... %u` | One static rule for all SENs |
| TLS to cloud | Custom tunnel | `bridge_cafile` / `bridge_tls_version` | Built in |

## Runtime State Inventory

Not a rename phase, but two persistence facts matter:

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | Retained messages under `sites/<id>/` on local broker (`mosquitto_data` volume) stay valid; cloud broker will hold retained copies under `app/<SEN>/<id>/` | None for local. Cloud: retained copies persist after a site is removed; tombstones must be forwarded (see Pitfall 2) |
| Live service config | ClickHouse history tables have no site/SEN column | Migration: add `site`/`sen` (or per-site databases) before a shared cloud ClickHouse; local single-site stays as is |
| OS-registered state | None | None |
| Secrets/env vars | New: `SITE_SEN`, cloud broker host/CA/password, `MQTT_BRIDGE_PASSWORD`, `CLOUD_METRICS_HEARTBEAT_S` | `init-env.sh` generates bridge local password; wizard writes `SITE_SEN`; document in `deploy/.env.example` |
| Build artifacts | `dashboard` image bakes nginx envsubst from env at container start | `/config.json` change needs container recreate only |

## Common Pitfalls

### Pitfall 1: Bridge resends every retained message on each reconnect
**What goes wrong:** On every bridge (re)connect Mosquitto queues retained messages matching the outbound local subscription (`retain__queue` in `bridge__on_connect` `[CITED: github.com/eclipse-mosquitto/mosquitto src/bridge.c, read via fetch, not run]`). A 4G flap re-sends `lan/events/recent` (~127 KB) plus every device status/services/topology, and the archiver records each as a new receipt.
**Why:** the bridge is a client re-subscribing to local topics.
**Avoid:** keep retained payloads small (per-event messages is the proper fix, out of scope), rely on `event_id` content-hash so duplicates are recognisable, set `keepalive_interval` and a TCP-friendly `restart_timeout` (jittered default 5/30 s). Measure retained bytes on the live stack before committing.
**Warning signs:** cloud ingest volume rising with every WAN flap.

### Pitfall 2: Tombstones across the bridge
**What goes wrong:** closed incidents/removed hosts are empty retained payloads. The bridge source drops no empty payloads `[CITED: bridge.c read]` and keeps retain via `RETAIN_AS_PUBLISHED`, so they should clear the cloud retained copy, but the man page "does not explicitly say" `[CITED: man page fetch]`.
**Avoid:** include tombstone forwarding in the live smoke test. Archive side: an empty payload is valid and lands as `"value":""` with `retained:true` `[CITED: MQTT_CLIENT_DATA_FLOW.md]`; downstream readers must treat that record as "closed". Give tombstones their own `event_id` (table above) so they are not deduped against the open record.

### Pitfall 3: Redelivery double-counts history
`history.*` are plain `MergeTree` whose TTL `GROUP BY` sums `samples`/`value_count`, so a duplicate batch inflates counts permanently `[VERIFIED: deploy/clickhouse-config/initdb/01-schema.sql:36-120]`. Dedupe in the analytics subscriber (bounded seen-set of recent `event_id`s, rebuilt on restart is lossy) and/or ClickHouse insert dedup token `[ASSUMED: non-replicated MergeTree needs non_replicated_deduplication_window > 0; verify against the pinned ClickHouse version]`. Poller already does an in-memory dedup for events in analytics (`fetch_recent_event_keys`); mirror that approach with a `recent batch ids` query only if a column carries the id, otherwise use the token.

### Pitfall 4: Subscriber topic prefix is hard-coded
`analytics/topics.py` builds only `sites/<id>/`. Cloud analytics reading `app/<SEN>/<site>/history/#` (and the lan topics) needs `MQTT_TOPIC_PREFIX` (default `sites/<id>/`), or a second client. `tests/test_analytics_topics.py` equality-tests these helpers against the poller copy, so change both.

### Pitfall 5: Archive silently drops invalid topics
The archiver logs and acks (discarding) any topic not matching `app/<positive SEN>/<non-empty site>/<non-empty segments>`; SEN with leading zeros or empty segments vanish without error `[CITED: MQTT_CLIENT_DATA_FLOW.md]`. Validate `SITE_SEN` (`^[1-9][0-9]*$`) in the wizard, `init-env.sh`, the render script and poller startup. Device ids are already filtered by `is_publishable_device_id`; confirm that function also rejects empty/whitespace-only segments (it does for empty/blank).

### Pitfall 6: Compose does not pick up a new `.env` value without recreate
The wizard can write `deploy/.env` (rw bind mount of the checkout) but running containers keep the old environment. The wizard must tell the operator to `podman compose down && up -d`, matching the existing `CMK_REST_SECRET` guidance. Also the wizard in container mode only sees `os.environ`, so it must read the file for the current value.

### Pitfall 7: v5 session semantics differ
v5 session expiry default is 0, `clean_session` is not accepted, and paho reconnect with `clean_start=FIRST_ONLY` keeps default behaviour only if expiry is set. Reconcile client (`mqtt_poller.py:3343`) is short-lived and also builds its own `mqtt.Client`; convert all three client constructors or the tests that mock `mqtt.Client` will drift. `scripts/smoke_test_broker.py` is the repo's proven live reference; extend it.

### Pitfall 8: QoS downgrade by bridge subscription
Bridge topic QoS 1 delivers each message at `min(published QoS, 1)`; throttled status stays QoS 0 and is not guaranteed on the WAN. Acceptable for gauges; do not rely on it for state changes. Consider publishing status state-change transitions at QoS 1 (small change in `publish_device_status`).

## Code Examples

### Env/SEN validation (shared by wizard, init-env.sh, poller)
```python
# Contract: positive decimal integer, canonical (no leading zeros) [CITED: MQTT_CLIENT_DATA_FLOW.md]
_SEN_RE = re.compile(r"[1-9][0-9]{0,17}")  # bound length to keep it a sane int
def valid_sen(value: str) -> bool:
    return bool(_SEN_RE.fullmatch(value))
```

### Wizard write of SITE_SEN
Wizard path (container mode): read/write `/app/checkmk-wizard/deploy/.env` located relative to `_SMARTMONTOOLS_DIR`'s repo root (`Path(__file__).resolve().parents[2] / "deploy" / ".env"`, same source-checkout assumption the code already makes `[VERIFIED: wizard.py:40]`). Replace an existing `SITE_SEN=` line or append; never print other secrets. Host mode: same relative path.

### Local status throttle skeleton
```python
def should_publish_status(prev, cur, now, heartbeat_s):
    if prev is None or prev.discrete != cur.discrete:
        return True
    if cur.band != prev.band:            # ok/warn/crit crossing on any gauge
        return True
    return (now - prev.gauge_ts) >= heartbeat_s
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Bridges "do not use MQTT v5" (2019 test release note) | `bridge_protocol_version mqttv50`, `bridge_session_expiry_interval`, `bridge_receive_maximum` | Mosquitto 2.0 | v5 end to end is possible `[CITED: man page]` |
| Mosquitto v3.1.1 default bridge | `mqttv311` is still the bridge default | n/a | Must set mqttv50 explicitly |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | User properties set by a v5 publisher on the local broker are forwarded unchanged by an mqttv50 bridge (read in `database.c`; `send_publish.c` could not be fetched) | Summary, Pattern 3 | `event_id` never reaches the archive; fallback: carry `event_id` inside the JSON payload as well (cheap, recommended as belt and braces) |
| A2 | Empty retained payloads (tombstones) are forwarded and clear the cloud retained copy | Pitfall 2 | Removed hosts/incidents stay on a cloud dashboard |
| A3 | Bridge re-sends all retained local messages on each reconnect | Pitfall 1 | 4G volume estimate off; only improves if false |
| A4 | `include_dir` is available in the shipped mosquitto.conf | Pattern 1 | Render whole mosquitto.conf instead |
| A5 | paho-mqtt 2.1 v5 API names (`MQTTv5`, `Properties`, `UserProperty`, `clean_start`) as written | Pattern 2 | Test failures only; verify with context7 |
| A6 | Default `max_queued_messages` 1000 per client | Pattern 5 | Different loss window |
| A7 | ClickHouse non-replicated insert dedup needs a window setting | Pitfall 3 | Use app-level dedupe only |
| A8 | Cloud broker is also Mosquitto (or supports `%u` ACLs) | Pattern 6 | ACL syntax differs; the phase's cloud side is not ours to build |

## Open Questions (RESOLVED)

1. **Is status archived or not?**
   - Known: D-06 says no stream; D-07 throttles the shared topic; `topic #` forwards it anyway.
   - Unclear: whether throttled status is acceptable in S3, or must be excluded at the bridge.
   - Recommendation: forward it (throttled, QoS 0, small), mention in docs. If excluded, replace `topic #` with explicit lines for services, topology, events, incidents, poller status, history, admin, needs.
   - RESOLVED: plan 17-02 FA-1 (forward everything with `topic #`, including throttled status and the per-cycle `lan/poller/status`; flagged for user decision, documented in plan 17-08).
2. **History volume vs D-02 as written.** 15 s full batches are the biggest 4G cost. Recommend a publish-interval knob and chunking; ask whether to add gzip (readability in S3 versus bytes).
   - RESOLVED: plan 17-03 FA-6 (every cycle, uncompressed, 500-row chunks; reduction flagged for user review).
3. **`lan/events/recent` over the bridge.** Whole 127 KB array rewritten per change; the walkthrough's per-event topic proposal is out of scope here. D-06 lists "events" as archived, so decide whether this phase also adds a small per-event non-retained message (`lan/events/item`) with `event_id`; recommended, because it is what gives the archiver a true per-event record.
   - RESOLVED: plan 17-03 FA-8 (array shape unchanged, content-hash event_id; per-event message not added; flagged for user review).
4. **Multi-site cloud ClickHouse.** History tables lack site/SEN; decide per-site database vs added column (analytics-owned migration).
   - RESOLVED: plan 17-06 FA-14 (one cloud-ingest instance and database per (SEN, site); no schema change this phase).
5. **Dashboard staleness fix** (Pattern 4) must be chosen before throttling ships, or all hosts show STALE.
   - RESOLVED: plans 17-04 (heartbeat_s payload key, republish on staleness band crossing) and 17-05 (fallback widened by heartbeat_s).
6. **Where bridge secrets live** (cloud password, CA): `deploy/.env` plus a bind-mounted CA file; the wizard should not prompt for these.
   - RESOLVED: plan 17-02 (deploy/.env via init-env.sh and compose, CA file bind-mounted; the wizard prompts only for SEN, plan 17-07).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| docker CLI | local experiments | yes | 29.7.2 | podman (deploy host) |
| podman | deploy stack | not in this shell | - | docker for a throwaway two-broker test |
| mosquitto binaries | live smoke test | not on host | - | run `eclipse-mosquitto:2` containers (two brokers + bridge) |
| Cloud broker + archiver | end-to-end | not available | - | a second local `eclipse-mosquitto:2` standing in for the cloud broker; archiver contract is checked with a paho v5 subscriber |

**Missing with no fallback:** access to the real cloud broker/archiver (final acceptance depends on the operator).

## Validation Architecture

`workflow.nyquist_validation` is `false` in `.planning/config.json`; section skipped per instructions. Planner note: existing tests to extend are `tests/test_mqtt_poller.py`, `tests/test_analytics_service.py`, `tests/test_analytics_topics.py`, `tests/test_mosquitto_acl.py`, `tests/test_wizard.py`, `tests/test_smoke_test_broker.py`; add `tests/test_mosquitto_bridge_render.py` (render script guard, mirrors ACL render test).

## Security Domain

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Per-SEN broker credential (`remote_username`/`remote_password`), TLS to cloud (`bridge_cafile`, `bridge_tls_version tlsv1.3` where supported) |
| V3 Session Management | no | n/a |
| V4 Access Control | yes | Cloud ACL `pattern write app/%u/#`; bridge local user read-only on `sites/<id>/#` |
| V5 Input Validation | yes | SEN regex at every entry point; render script rejects bad characters before `sed` (same posture as `render-mosquitto-acl.sh`) |
| V6 Cryptography | yes | TLS only; never plaintext 1883 over WAN |

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Site publishes into another SEN's namespace | Spoofing/Tampering | Remote ACL `app/%u/#` + bridge remap fixes prefix |
| Cloud password in `mosquitto.conf` on disk | Information disclosure | Render to a 0700 file as the passwd/ACL already are |
| `wsadmin`/`wstriage` open creds now reach the cloud via `admin/cmd` | Elevation | These topics are forwarded `out` only; nothing from the cloud can write them locally (no `in` line) |
| Config injection through SITE_SEN / site id | Tampering | Regex validate before sed |
| Unauthenticated writes to cloud from bridge on compromised LAN host | Tampering | Per-site cloud credential, rotate via `.env` |

## Project Constraints (from CLAUDE.md)
- Python via `uv` only (`uv run`, `uv add`, never bare python/pip).
- No custom server-side app for the dashboard; no new backend.
- Poller/publisher must not need filesystem access to the checkmk container; Livestatus and REST only.
- Must not break the existing 7-phase wizard flow or its tests.
- Every new module starts with `from __future__ import annotations`; dated why-comments citing verification source; errors via module-specific exception types, best-effort calls must not abort the loop.
- After features, update the relevant docs (`docs/MQTT-CONTRACT-WALKTHROUGH.md`, Podman setup doc, WIZARD-OPERATION.md) and log prompts in `PROMPT_LOG.md`.
- GSD workflow enforcement: edits go through a GSD command.

## Sources

### Primary (HIGH confidence)
- mosquitto.org/man/mosquitto-conf-5.html: bridge `topic` syntax with local/remote prefixes, `bridge_protocol_version`, `cleansession`, `remote_clientid`, `bridge_session_expiry_interval`, `notifications`, `try_private`, queue settings are global.
- `docs/MQTT_CLIENT_DATA_FLOW.md`: archive contract (topic, QoS 1, `event_id`, silent drop of invalid topics).
- Repository files read: `deploy/mosquitto.conf`, `deploy/mosquitto.acl.template`, `deploy/render-mosquitto-acl.sh`, `deploy/compose.yaml`, `deploy/init-env.sh`, `scripts/mqtt_poller.py`, `analytics/service.py`, `analytics/topics.py`, `deploy/clickhouse-config/initdb/01-schema.sql`.

### Secondary (MEDIUM confidence)
- github.com/eclipse-mosquitto/mosquitto `src/database.c` and `src/bridge.c` (read via page fetch summary): properties passed unchanged, no stripping for bridges, retained re-queue on bridge connect, no empty-payload filter. `send_publish.c` returned 404, so the final hop was not read.

### Tertiary (LOW confidence)
- mosquitto.org 2019 mqtt5 test release note (bridges and v5), outdated.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH, nothing new beyond Mosquitto and paho already in use.
- Architecture: MEDIUM, depends on A1/A2 live verification.
- Pitfalls: MEDIUM, bridge reconnect/retained behaviour read from source not run.

**Research date:** 2026-10-14
**Valid until:** 2026-11-14 (Mosquitto 2.x stable; re-check if image tag changes)
