---
id: SEED-001
status: dormant
planted: 2026-09-21
planted_during: v1.0 / Phase 12 (Agent Metrics and Service Status)
trigger_when: when the dashboard moves to a cloud deployment, or when a reporting/analytics requirement surfaces that needs history older than the current bounded window
scope: medium
---

# SEED-001: Persist MQTT history to a real database for long-range reporting

## Why This Matters

Today all "history" in this project — device status transitions
(`lan/devices/{id}/history`), the global recent-events feed (`lan/events/recent`), and
(as of Phase 12) per-service transitions (`lan/devices/{id}/service_history`) — is a
**bounded, retained-message array on the MQTT broker**. There is no database. Durability
comes entirely from the broker's own disk-backed retained-message store
(`deploy/mosquitto.conf`'s `persistence true`), and the poller itself keeps zero on-disk
state (`PollerState` is explicitly "Never persisted — rebuilt via `reconcile_state` on
restart", `scripts/mqtt_poller.py:835`).

This works well for the current on-prem, single-site design goal (self-heal across
restarts with no persisted local state, per Phase 8's architecture decision), but it has a
hard ceiling: the bounded array (e.g. `DEFAULT_HISTORY_MAX_ENTRIES = 20`) only ever holds
the *most recent* N transitions. There is no way to ask "what happened to this device last
month" or build any trend/reporting view — the data simply doesn't exist past the bounded
window.

When this project moves to a cloud deployment, that ceiling becomes a real gap: cloud
deployments typically imply multi-tenant or longer-lived operational visibility, and
reporting/analysis needs (SLA tracking, incident history, capacity trends) require
querying history far beyond a 20-entry ring buffer.

The fix is straightforward in shape, just out of scope for the current milestone: add an
MQTT subscriber (separate from the poller and the dashboard) that consumes the same
retained/live topics and writes every transition into a real database (time-series or
relational), so historical queries aren't bounded by what fits in a retained MQTT message.

## When to Surface

**Trigger:** When the dashboard moves to a cloud deployment, OR when a reporting/analytics
requirement surfaces that needs history older than the current bounded window.

This seed will surface during `/bm:new-milestone` when the milestone scope matches either
condition above.

## Scope Estimate

**Medium** — a phase or two. Rough shape:
- A new standalone MQTT subscriber service (does not touch the poller or dashboard code
  paths — keeps the existing "poller/publisher must not require filesystem access" and
  "no new backend for the dashboard" constraints intact, since this is a *new*, separate
  component, not a modification of either existing one).
- A database choice and schema for transition/event records (time-series DB is a natural
  fit given the access pattern — "give me this device's/service's history between two
  timestamps" — but a relational table also works at this scale).
- Some reporting/query surface (could be a new dashboard route, a separate reporting tool,
  or direct DB access for now) — deliberately not scoped here.
- Does NOT require changing `mqtt_poller.py`'s bounded in-memory/retained-message design;
  the new subscriber is an additive consumer of the same topics, not a replacement.

## Breadcrumbs

- `scripts/mqtt_poller.py:835` — `PollerState` docstring: "In-process poll-cycle state.
  Never persisted -- rebuilt via `reconcile_state` on restart."
- `scripts/mqtt_poller.py:380` — `append_bounded()`, the bounded-history helper whose
  `max_entries` cap this seed's database would remove for long-range queries.
- `scripts/mqtt_poller.py:768-775` — `publish_history()` / `publish_events()`, the
  functions a new subscriber would consume in parallel with the dashboard.
- `deploy/mosquitto.conf:17-18` — `persistence true` / `persistence_location
  /mosquitto/data/` — today's only durability layer, which this seed supplements rather
  than replaces.
- `.planning/phases/12-agent-metrics-and-service-status/` — Phase 12 (Agent Metrics and
  Service Status) is where this question was raised, while discussing D-14's new
  `lan/devices/{id}/service_history` topic and how per-device/per-service history is
  managed with no database in the picture.
- `CLAUDE.md` §Constraints — "No new backend for the dashboard: no server-side
  application — state comes entirely from MQTT retained messages." This seed's subscriber
  is a new, separate backend component for reporting, not a backend for the dashboard
  itself — the distinction matters for scoping the eventual phase correctly.

## Notes

Raised by the user directly while reviewing Phase 12's per-device history design: "later on
this dashboard is going to move to cloud and will likely need a database where messages are
stored by a mqtt subscriber into a database, so it will be possible to get historical events
for long time in the past, for reporting, analysis, etc." Captured verbatim as the trigger
condition and scope rationale above.
