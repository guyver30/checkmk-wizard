# Phase 17: Cloud MQTT Contract and S3 Archive Feed - Context

**Gathered:** 2026-10-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Each site's MQTT messages reach the cloud broker under the archive contract `app/<SEN>/<site_id>/<suffix>`, so the S3 archive service (`fsu-mqtt`, described in `docs/MQTT_CLIENT_DATA_FLOW.md`) can land them as JSONL. SEN is the site equipment number and uniquely identifies a site. Whether one SEN hosts one or several Checkmk sites is not known, so both stay supported.

In scope: `SITE_SEN` configuration, the prefix remap from the local `sites/<site_id>/` namespace, MQTT v5 with a deterministic `event_id` on discrete messages, publishing history rows over MQTT for a cloud ClickHouse writer, a change-only / slow-heartbeat publishing rule for the 4G link, and per-SEN ACLs on a shared cloud broker.

Out of scope: building the cloud deployment itself, the archiver service (it exists and is not ours), a new dashboard.
</domain>

<decisions>
## Implementation Decisions

### Receiving end (cloud)
- **D-01:** The archiver is one side-consumer of the broker, not the live path. Dashboard and analytics keep reading retained state from the broker; S3 is a durable raw log and replay source only.
- **D-02:** History rows (`history.host_state`, `history.service_state`, `history.metrics`) are published by the poller as discrete MQTT messages. The cloud analytics container subscribes and inserts into ClickHouse. The poller holds no ClickHouse credentials in cloud mode. The archiver captures the same messages in S3 as the replay log.
- **D-03:** Each history batch carries a deterministic `event_id` so the cloud writer can deduplicate at-least-once redelivery.

### Prefix remap
- **D-04:** A Mosquitto bridge remaps `sites/<site_id>/` to `app/<SEN>/<site_id>/` on the way out. The local namespace, ACLs, dashboard and tests from Phase 14.3 stay unchanged. Prefix mapping support in bridge `topic` lines is believed but not verified; research must confirm from the Mosquitto docs.
- **D-05:** Both `<SEN>` and `<site_id>` are real keys. Nothing derives one from the other, so one-or-many sites per SEN keeps working.

### What crosses the 4G link
- **D-06:** Only discrete messages are archived (events, incidents, services, topology, commands and acks, history batches). Per-cycle status samples are not archived as a stream.
- **D-07:** The poller throttles the shared `lan/devices/{id}/status` topic itself: publish on state change; publish metric fields (cpu, ram, disk and similar gauges) on a slower heartbeat; publish immediately when a metric crosses a warn or crit threshold. The bridge forwards whatever the local broker receives.
- **D-08:** The metrics heartbeat is configurable via env (name to be chosen in planning, e.g. `CLOUD_METRICS_HEARTBEAT_S`), default 5 minutes.
- **D-09 (consequence to carry into planning):** Because D-07 throttles the shared topic, the on-prem dashboard's gauges also refresh at the heartbeat rate by default, not every 15 s. A site that wants fresher local gauges lowers the heartbeat setting. Hosts whose state is not changing still need a liveness signal, so `lan/poller/status` stays per cycle and staleness handling must be re-checked against the dashboard.

### MQTT v5 and event_id
- **D-10:** The poller moves to MQTT v5 (today paho defaults, v3.1.1: `scripts/mqtt_poller.py:2802`, `analytics/service.py:209`). `event_id` is sent as an MQTT v5 user property.
- **D-11:** `event_id` is deterministic from message identity (incident id plus revision, event key, history batch id from cycle timestamp and site), so retries reuse it without persisting anything.

### SEN configuration
- **D-12:** The wizard prompts for SEN during site bring-up and writes it to the deployment env file as `SITE_SEN`. Validated as a positive integer without leading zeros. Poller, analytics and the dashboard `config.json` all read it. Where the wizard (which runs from the worker container) can write the compose env file is an open item for research.

### Claude's Discretion
- Exact env var names, bridge connection settings (clean session, queueing during WAN outage, QoS per topic), the `event_id` formats, and the history batch topic name and size splitting.
- How tombstones (empty retained payloads for closed incidents) and retained re-delivery are handled across the bridge and in the archive.
- Cloud ACL shape: per-SEN user on `app/<SEN>/#` is the starting point, tightening to `app/<SEN>/<site_id>/#` only if needed.
</decisions>

<specifics>
## Specific Ideas

- Cost on the 4G link is a first-class driver: "publish only on status change, metrics on a slower heartbeat, immediately if they cross a warn/critical threshold."
- Stay flexible on SEN-to-site cardinality.
</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### MQTT contract and archive
- `docs/MQTT_CLIENT_DATA_FLOW.md` — the archive service contract: topic shape, QoS 1, `event_id`, JSONL envelope, S3 layout, redelivery and ack semantics.
- `docs/MQTT-CONTRACT-WALKTHROUGH.md` — current poller topics, QoS and retention table, history-over-MQTT proposal (Part 1), bandwidth options (Part 4).
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` — formal topic table and deployment.

### Prior phase decisions
- `.planning/phases/14.3-per-site-mqtt-namespace/14.3-CONTEXT.md` — `sites/<site_id>/` namespace, per-site ACL rendering.
- `.planning/phases/14.2-fleet-failure-prediction-and-incident-narration/14.2-CONTEXT.md` — analytics container, ingestion topics, ClickHouse tables.
- `.planning/phases/14.1-fleet-history-store-availability-rollups-and-grafana/14.1-CONTEXT.md` — history schema and the poller as sole history writer.

### Code
- `scripts/mqtt_poller.py` — publishers (`_publish_json`, `site_topic`, `run_cycle`, `write_history`, `build_history_rows`).
- `analytics/service.py` — analytics MQTT client.
- `deploy/mosquitto.conf`, `deploy/mosquitto.acl.template`, `deploy/render-mosquitto-acl.sh` — broker config and ACL rendering.
- `deploy/init-env.sh`, `deploy/compose.yaml` — environment and container wiring.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `site_topic()` / `device_status_topic()` in `scripts/mqtt_poller.py` — single place topic prefixes are built.
- `build_history_rows()` — already assembles history rows; publishing them instead of POSTing does not change it (per the walkthrough).
- `deploy/render-mosquitto-acl.sh` — template rendering to extend for per-SEN users.

### Established Patterns
- Retained whole-state topics, tombstoned on removal; QoS 0 for status, QoS 1 for everything else.
- `_publish_json` is the one choke point for publishing.
- Config via `deploy/.env` rendered by `init-env.sh`.

### Integration Points
- Poller publish path (throttling and event_id), analytics subscriber (history insert), Mosquitto config (bridge), wizard site bring-up (SEN prompt), dashboard `config.json` (SEN).
</code_context>

<deferred>
## Deferred Ideas

- Edit-mode writes to Checkmk REST (`/checkmk-api`) cannot work from the cloud; they need a command topic and an on-prem agent (noted in the walkthrough). Separate phase.
- Cloud-side ClickHouse loading from S3 JSONL as an alternative or backfill path.
- Multi-site dashboard views over several `app/<SEN>/<site_id>/` subtrees.
</deferred>

---

*Phase: 17-cloud-mqtt-contract-and-s3-archive-feed*
*Context gathered: 2026-10-14*
