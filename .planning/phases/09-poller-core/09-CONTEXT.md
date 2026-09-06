# Phase 9: Poller Core - Context

**Gathered:** 2026-09-06
**Status:** Ready for planning

<domain>
## Phase Boundary

A long-running poller queries Checkmk Livestatus over TCP on an interval, diffs against Livestatus's live current state each cycle (not its own in-memory history), and publishes retained MQTT messages per the topic contract: `lan/devices/{id}/status` (every cycle), `lan/devices/topology` (change-only), `lan/devices/{id}/history` and `lan/events/recent` (bounded, transition-only), and `lan/poller/status` (birth/LWT liveness). No Checkmk tagging, no dashboard code in this phase.

</domain>

<decisions>
## Implementation Decisions

### Packaging & Launch
- **D-01:** The poller is a **standalone script**, not a module inside the installable `checkmk_wizard` package — user's explicit reasoning: it must run independently of the wizard and be deployable to sites where the wizard isn't needed/installed. Do not add it as `src/checkmk_wizard/*.py` or wire it into the `checkmk-wizard` console script.
- **D-02:** The poller gets its own **dedicated `poller` compose service** in `deploy/compose.yaml` (not reusing the `worker` container's idle `tail -f /dev/null` process), with `restart: unless-stopped` for automatic crash recovery independent of the worker container's interactive wizard usage.

### Poll Interval & Configuration
- **D-03:** Default poll interval is **60 seconds**.
- **D-04:** All poller runtime settings are configured via **environment variables** on the new `poller` compose service — same pattern as `worker`'s existing `MQTT_HOST`/`MQTT_PORT`. At minimum: poll interval, MQTT broker host/port/credentials (the `poller` user from `deploy/mosquitto.passwd` / `deploy/mosquitto.acl`), and Livestatus host/port.

### History/Events Retention Bounds
- **D-05:** `lan/devices/{id}/history` (per-device bounded transition log) is capped by a `HISTORY_MAX_ENTRIES` env var, **default 20**.
- **D-06:** `lan/events/recent` (bounded global transition feed) is capped by an `EVENTS_MAX_ENTRIES` env var, **default 50**.

### Status Payload Shape
- **D-07:** Downtime/acknowledgement fields on `lan/devices/{id}/status` are named **`in_downtime`** and **`acknowledged`** — chosen to mirror Livestatus's own column naming (`scheduled_downtime_depth > 0` → `in_downtime`, `acknowledged`) so the payload traces back cleanly to source columns.
- **D-08:** Overall per-host status is computed via **worst-of aggregation across the host and all its services** (CRIT beats WARN beats UNKNOWN beats OK; a host-level DOWN/UNREACHABLE always wins outright) — this is what preserves PLR-03's explicit requirement for full OK/WARN/CRIT/UNKNOWN/DOWN granularity rather than collapsing to plain up/down.

### Claude's Discretion
- Exact script filename/location and internal module layout (still expected to follow this codebase's established conventions: dataclasses for structured data, typed exceptions, no silent broad `except`, explicit `from __future__ import annotations`)
- Exact env var names beyond those specified above (e.g. `MQTT_USERNAME`, `MQTT_PASSWORD`, `LIVESTATUS_HOST`, `LIVESTATUS_PORT`, `POLL_INTERVAL_SECONDS`)
- Restart/reconciliation strategy for rebuilding "previously known device IDs" after a poller restart (startup diff against live Livestatus vs. re-subscribing to the broker's own retained topics) — SUMMARY.md's Research Flags explicitly calls this out as needing a research pass during planning, not a user decision
- Per-topic QoS choices (research recommends QoS 0 for the every-cycle status topic, QoS 1 for change-only topics: topology/tombstones/history/events)
- Exact JSON payload field layout beyond the named fields above (e.g. whether history/events entries are objects or strings, exact timestamp format)
- Whether/how the poller reads a `device_type` tag (must be defensive with a safe default, since the tag itself doesn't exist until Phase 10)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Poller architecture & topic contract
- `.planning/research/ARCHITECTURE.md` — poller component design, topic/payload contract, Build Order Implications
- `.planning/research/PITFALLS.md` — Pitfalls 1, 2, 7, 10 (tombstone gap, in-memory-only diff state, per-topic QoS misuse, folder-path VLAN parsing) — directly govern this phase's resilience requirements
- `.planning/research/STACK.md` — `paho-mqtt` 2.1.0 version/API baseline (`CallbackAPIVersion.VERSION2`, `Client.loop_start()`, `reconnect_delay_set()`)
- `.planning/research/SUMMARY.md` — "Phase B: Poller core" section and "Research Flags" (reconciliation strategy needs a research-phase pass)
- `.planning/ROADMAP.md` — Phase 9 section (locked success criteria, depends on Phase 8)
- `.planning/REQUIREMENTS.md` — PLR-01 through PLR-08 requirement text

### Broker/deployment integration (from Phase 8, already built)
- `deploy/compose.yaml` — existing 4-service stack this phase adds a `poller` service to; `worker` service's env-var pattern to mirror
- `deploy/mosquitto.conf` / `deploy/mosquitto.acl` / `deploy/mosquitto.passwd` — the `poller` user's credentials and its `readwrite #` ACL grant that this phase's MQTT client must authenticate with
- `.planning/phases/08-broker-infrastructure-hardening/08-CONTEXT.md` — Phase 8's decisions on config file locations and credential handling conventions

### Existing code patterns to follow
- `src/checkmk_wizard/livestatus.py` — this project's existing minimal hand-rolled Livestatus TCP client (one-shot connect/query/close pattern); the poller's Livestatus querying should follow this same style, extended with more columns (service state summary, tags, parent/folder, downtime/acknowledgement)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/checkmk_wizard/livestatus.py` — the existing `query_host_states()` function demonstrates the one-shot connect/send-LQL-query/read-CSV-response pattern; the poller needs a richer version querying more columns and both `hosts` and `services` tables, but should stay stylistically consistent (plain `socket`, no persistent connection, CSV output format).

### Established Patterns
- Project convention: `@dataclass` for structured records, module-specific exception types ending in `Error`, `from __future__ import annotations` at the top of every module, narrow `except (TimeoutError, OSError)` for real network conditions.
- Project convention: default/disposable credentials documented plainly in-doc rather than hidden — the poller's MQTT credentials come from `deploy/mosquitto.passwd`'s existing `poller` user (Phase 8 already provisioned this).
- Project convention: config via environment variables at the compose-service level (see `worker`'s `CMK_REST_API`, `MQTT_HOST`, `MQTT_PORT`, etc.) rather than config files — this phase's poller settings follow the same pattern.

### Integration Points
- `deploy/compose.yaml`'s `mosquitto` service — the poller connects to it on port 1883 using the `poller` user's credentials already provisioned in `deploy/mosquitto.passwd`/`deploy/mosquitto.acl` (`topic readwrite #`).
- `deploy/compose.yaml`'s `checkmk` service — the poller connects to it via Livestatus-over-TCP (port 6557, per the existing `livestatus.py` convention), not via REST API and not via filesystem access.
- This phase's topic/payload contract becomes the fixed interface Phase 11's dashboard is built against — get field names and structure right now.

</code_context>

<specifics>
## Specific Ideas

- User's own reasoning for the standalone-script decision: "It needs to be a standalone script because it runs independently from the wizard and can also be deployed to a site where the wizard is not needed" — this is a portability/deployment requirement, not just a style preference.

</specifics>

<deferred>
## Deferred Ideas

- Device-type tagging in the wizard's onboarding flow ("assign each scanned host a tag like 'PC', 'switch', etc. for use in MQTT/UI") — **not deferred to backlog, already scoped as Phase 10 (Checkmk Tag-Group & Onboarding Integration, TAG-01/02/03)**. This phase's poller should read the resulting tag defensively with a safe default once Phase 10 lands, but assigning/prompting for the tag itself happens in Phase 10, not here.

</deferred>

---

*Phase: 09-poller-core*
*Context gathered: 2026-09-06*
