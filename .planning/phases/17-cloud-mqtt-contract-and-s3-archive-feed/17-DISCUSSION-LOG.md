# Phase 17: Cloud MQTT Contract and S3 Archive Feed - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-14
**Phase:** 17-cloud-mqtt-contract-and-s3-archive-feed
**Areas discussed:** Receiving end, Prefix remap, What gets archived (4G cost), MQTT v5 and event_id, SEN config and ACLs

---

## Receiving end (user-added question)

User asked whether all MQTT payloads are stored in S3 only, and how that fits the dashboard and ClickHouse.

| Option | Description | Selected |
|--------|-------------|----------|
| Publish to MQTT, cloud inserts | Poller publishes history batches; cloud analytics inserts; archiver is replay log | ✓ |
| Poller POSTs to cloud ClickHouse | Smallest change; CH exposed over WAN, no buffering | |
| Load ClickHouse from S3 | Batch latency; poller still has to publish rows | |

**User's choice:** Publish to MQTT, cloud inserts.
**Notes:** Archiver is a side-consumer; dashboard and analytics read the broker.

## Prefix remap

| Option | Description | Selected |
|--------|-------------|----------|
| Mosquitto bridge | Local namespace unchanged | ✓ |
| Poller publishes both | Dual publish in poller | |
| Switch everything to app/<SEN>/ | Reworks 14.3 | |

**User's choice:** Mosquitto bridge.

## What gets archived

| Option | Description | Selected |
|--------|-------------|----------|
| Discrete only | Events, incidents, services, topology, commands, history | ✓ (with refinement) |
| Everything incl. status | Largest volume | |
| Status downsampled | Change or slow heartbeat | |

**User's choice:** Discrete only, plus: publish status only on change, metrics (cpu, disk, ...) on a slower heartbeat, immediately when crossing warn/crit, to optimise 4G cost.
**Notes:** Follow-up asked where to apply the rule. Options: throttle shared topic / second cloud-leg topic (recommended) / bridge-side filter. User chose "Poller throttles the shared topic" over the recommended second topic. Consequence: local dashboard gauges refresh at heartbeat rate by default. Heartbeat: configurable, default 5 min.

## MQTT v5 and event_id

| Option | Description | Selected |
|--------|-------------|----------|
| Deterministic per message | Derived from message identity | ✓ |
| Random UUID per publish | Defeats dedup after crash | |
| Only history batches | | |

**User's choice:** Deterministic per message.

## SEN config

| Option | Description | Selected |
|--------|-------------|----------|
| deploy/.env, required | Next to CMK_SITE_ID | |
| Optional, off by default | | |
| Wizard prompts for it | Wizard asks during site bring-up | ✓ |

**User's choice:** Wizard prompts for it.
**Notes:** SEN-to-site cardinality unknown; stay flexible.

## Claude's Discretion

Env var names, bridge settings, event_id formats, history batch topic naming, tombstone handling, ACL tightening.

## Deferred Ideas

Cloud edit-mode command topic; ClickHouse backfill from S3; multi-site dashboard views.
