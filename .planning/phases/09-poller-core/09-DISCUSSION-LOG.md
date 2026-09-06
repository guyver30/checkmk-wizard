# Phase 9: Poller Core - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-06
**Phase:** 09-poller-core
**Areas discussed:** Poller packaging & launch, Poll interval & config, History/events retention bounds, Status payload shape

---

## Poller packaging & launch

| Option | Description | Selected |
|--------|-------------|----------|
| New module in src/checkmk_wizard/ | New console-script entry point, matches single-package convention, gets test coverage | |
| Standalone script under app/ | Mounted into worker container only, mirrors docs/src/mqtt_notify.py precedent | ✓ |
| You decide | Claude picks based on research/codebase fit | |

**User's choice:** Standalone script under app/
**Notes:** "It needs to be a standalone script because it runs Independently from the wizard and can also be deployed to site where wizard is not needed" — a deployment/portability requirement, not a style preference.

| Option | Description | Selected |
|--------|-------------|----------|
| New dedicated `poller` compose service | Own container with restart:unless-stopped, independent of worker | ✓ |
| Runs as worker's foreground process | Replaces worker's `tail -f /dev/null`, reuses existing container | |
| You decide | Claude picks based on research/codebase fit | |

**User's choice:** New dedicated `poller` compose service

---

## Poll interval & config

| Option | Description | Selected |
|--------|-------------|----------|
| 30 seconds | Faster freshness, more chatter | |
| 60 seconds | Research's suggested default, lower overhead | ✓ |
| Other | Specify own value | |

**User's choice:** 60 seconds

| Option | Description | Selected |
|--------|-------------|----------|
| Env vars, matching existing pattern | New vars like POLL_INTERVAL_SECONDS, MQTT_HOST, etc. in deploy/compose.yaml's new poller service | ✓ |
| You decide | Claude picks based on research/codebase fit | |

**User's choice:** Env vars, matching existing pattern

---

## History/events retention bounds

| Option | Description | Selected |
|--------|-------------|----------|
| Last 20 | Short recent-trend view, smaller retained payload | |
| Last 50 | More depth, larger payload | |
| Other | Specify own count | ✓ (via env var) |

**User's choice:** "Can we put this in env as well" — made env-configurable instead of a fixed literal choice.
**Notes:** Followed up with a default-lock-in question: HISTORY_MAX_ENTRIES=20, EVENTS_MAX_ENTRIES=50 — user confirmed "Yes, 20 / 50".

| Option | Description | Selected |
|--------|-------------|----------|
| Last 50 | Typical dashboard panel size | |
| Last 100 | More scrollback, larger payload | |
| Other | Specify own count | ✓ (via env var) |

**User's choice:** "Let's put in env" — same as above, default confirmed at 50.

---

## Status payload shape

| Option | Description | Selected |
|--------|-------------|----------|
| downtime / acknowledged | Flat, simple booleans | |
| in_downtime / acknowledged | Mirrors Livestatus's own column naming | ✓ |
| You decide | Claude picks based on research/codebase fit | |

**User's choice:** in_downtime / acknowledged

| Option | Description | Selected |
|--------|-------------|----------|
| Worst-of aggregation across host + services | CRIT beats WARN beats UNKNOWN beats OK; host DOWN/UNREACHABLE always wins | ✓ |
| Host state column only | UP/DOWN/UNREACHABLE only, ignoring service states | |
| You decide | Claude picks based on research/codebase fit | |

**User's choice:** Worst-of aggregation across host + services
**Notes:** Matches PLR-03's explicit requirement for full OK/WARN/CRIT/UNKNOWN/DOWN granularity.

---

## Claude's Discretion

- Exact script filename/location and internal module layout
- Exact env var names beyond those explicitly specified (MQTT_USERNAME, MQTT_PASSWORD, LIVESTATUS_HOST, LIVESTATUS_PORT, POLL_INTERVAL_SECONDS)
- Restart/reconciliation strategy for rebuilding "previously known device IDs" (flagged by research SUMMARY.md as needing a dedicated research pass)
- Per-topic QoS choices
- Exact JSON payload field layout beyond the named fields
- How the poller defensively reads a not-yet-existing `device_type` tag

## Deferred Ideas

- Device-type tagging in the wizard's onboarding flow — raised by the user during the gray-area selection prompt, but redirected: this is already scoped as Phase 10 (Checkmk Tag-Group & Onboarding Integration, TAG-01/02/03), not new scope for Phase 9.
