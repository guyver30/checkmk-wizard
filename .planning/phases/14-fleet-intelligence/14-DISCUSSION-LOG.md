# Phase 14: Fleet Intelligence - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-26
**Phase:** 14-Fleet Intelligence
**Areas discussed:** Scope slicing, Impact & root-cause model, History store & Grafana, Prediction & AI narration

---

## Scope slicing

| Option | Description | Selected |
|--------|-------------|----------|
| Split into 3 phases | 14 presentation; 14.x history; 14.y prediction + AI | ✓ |
| Split in 2 | Presentation + availability; later TSDB/prediction/AI | |
| Keep one phase | All 7 together | |

**User's choice:** 3 phases. Availability rollups go with the history phase. Numbered 14 / 14.1 / 14.2; blocking decisions settled now and recorded as locked inputs.

---

## Impact & root-cause model

First question (define "service": device_type / new tag group / dashboard grouping) was rejected for clarification.

**User's clarification:** Impact isn't straightforward. An unreachable group controller may be behind a down unmanaged switch and still functioning (just unmonitorable), or really down (lift not operating, more serious). Some Linux services are critical, others not. A multimedia server offline matters more than a screen. Unsure how to approach.

| Option | Description | Selected |
|--------|-------------|----------|
| Evidence only | Incidents with "not observable" vs "confirmed down"; no criticality | |
| Evidence + criticality label | Per-host tier as Checkmk label | |
| Evidence + criticality + dependencies | Also depends-on links | ✓ |

| Storage option | Selected |
|----------------|----------|
| Checkmk labels, edited in dashboard | ✓ |
| Checkmk labels, edited in wizard | |
| Separate JSON/config file | |

| Incident rendering | Selected |
|--------------------|----------|
| Incident card + collapsed tree | ✓ |
| Only collapse in tree and map | |
| Incident list replaces alarm count | |

| DOWN behind unmanaged parent | Selected |
|------------------------------|----------|
| Suspect unmanaged parent (inferred) | ✓ |
| Always own incident | |
| Operator decides per incident | |

**Notes:** Chose the largest scope option despite my flagging its size; captured as D-06 with a wave-ordering recommendation.

---

## History store & Grafana

| Question | Selected |
|----------|----------|
| Grafana audience | Alongside, for analysts |
| Retention | 3 years, downsampled |
| Edition | Raw fixed, poller writes history |

**User's follow-up:** "where is the historical data stored, to be used eventually by Grafana (but also by the main dashboard)?" Explained TSDB on MinIO; dashboard has no history from retained MQTT.

| Dashboard history access | Selected |
|--------------------------|----------|
| Poller publishes summaries to MQTT (recommended) | |
| Dashboard queries TSDB over HTTP | ✓ |
| Both, phased | |

**Notes:** Amends the "no new backend" constraint (D-24). Access mechanism (nginx read-only proxy vs direct port) left to research.

---

## Prediction & AI narration

| Question | Selected |
|----------|----------|
| Data egress | No: local or template only |
| When to show prediction date | Immediately with confidence tag (recommended was per-metric minimum history) |
| Where computed/published | Separate analytics container (recommended was the poller) |

---

## Claude's Discretion

Tier vocabulary, label keys, topic names, kiosk details, incident card design.

## Deferred Ideas

Location-aware incident wording (Phase 15); operator-acknowledged root cause; local LLM narration; Checkmk-native export.
