# checkmk-wizard

## What This Is

An interactive terminal wizard that configures a fresh Checkmk Community Edition site from scratch — network discovery, host onboarding, agent installation, and activation — running either directly on a Checkmk host or from a separate "worker" container alongside a containerized Checkmk deployment. This milestone extends the project with a live MQTT bridge and a lightweight web dashboard that visualizes the resulting Checkmk-monitored network topology and device status in real time.

## Core Value

A single Python-based toolchain takes a bare Checkmk install all the way to a fully onboarded, monitored network — and now also to a live, at-a-glance visual picture of that network's topology and health, without needing to duplicate Checkmk's own UI.

## Requirements

### Validated

- ✓ Interactive 7-phase wizard provisions a Checkmk site end-to-end (site bringup → folders → network discovery → host classification → host onboarding with SSH automation → service discovery → activation) — existing
- ✓ Auto-detects host-native vs. container deployment mode (presence of `omd` on `PATH`) and adapts credential bootstrap accordingly — existing
- ✓ Async Checkmk REST API client with best-effort bootstrap of `automation`/`agent_registration` credentials — existing
- ✓ Async TCP network scanner discovers live hosts across configured subnets — existing
- ✓ SSH-based remote automation (firewall rules, agent install/registration, OS-compatibility checks) for Linux targets, with manual-instruction fallback for Windows and SNMP-only devices — existing
- ✓ Minimal Livestatus-over-TCP client performs a post-activation host-state health check, proven to work from a separate container (no local OMD filesystem access needed) — existing
- ✓ Final run produces a JSON config snapshot for reference — existing

### Active

- [ ] A long-running Python poller (in the `worker` container) queries Checkmk Livestatus over TCP on an interval and detects host/topology state changes
- [ ] Poller publishes to MQTT using a per-device topic contract: `lan/devices/topology` (retained, republished only on topology change), `lan/devices/{id}/status` (retained, republished every poll cycle), `lan/devices/{id}/history` (retained, bounded transition log), `lan/events/recent` (retained, bounded global transition feed)
- [ ] `mosquitto.conf` gains a WebSockets listener so browser-based MQTT clients (`mqtt.js`) can subscribe directly
- [ ] A new Checkmk host tag group captures device type from a config-driven, site-specific choice list; the wizard's Phase 4 classification flow prompts for it and Phase 5 onboarding sets it per host
- [ ] Topology links (`parent`) come from Livestatus's `parents` column; a location/group label is derived from the host's Checkmk folder association — no new Checkmk configuration needed for either
- [ ] A 3-page static HTML/CSS/JS dashboard (no build step, no backend) — `index.html` (live topology map via vis-network + an at-a-glance stats strip), `devices.html` (live sortable device table + recent-events panel), `details.html` (per-device drill-down with a bounded status-history strip) — served by a new nginx container added to `compose.yaml`
- [ ] Dashboard shows a connection-status indicator with exponential-backoff MQTT reconnect, and merges incoming updates into existing UI state rather than re-rendering from scratch

### Out of Scope

- MAC address collection for topology nodes — not reliably available without Checkmk's HW/SW inventory plugin; would add a new subsystem dependency for marginal value
- Checkmk notification rules as the live-update mechanism — would require deploying scripts into the `checkmk` container's own OMD filesystem, breaking the worker/checkmk boundary the container-mode architecture is built around
- Duplicating Checkmk's own per-service drill-down UI in the new dashboard — link out to Checkmk's UI for full service-level detail instead
- Time-series graphing/historical dashboards beyond a simple bounded per-device transition-history strip — no time-series database

## Context

- Deployment architecture: a rootless Podman Compose stack (`checkmk`, `mosquitto`, `minio`, `worker` containers on a shared `cmk_net` bridge network) — documented in `docs/Podman setup for checkmk, minio, mosquitto, worker.md`. `checkmk-wizard` already runs from the `worker` container in "container mode," touching Checkmk only via its REST API and Livestatus-over-TCP port (6557), never the `checkmk` container's filesystem. This milestone's new poller/dashboard preserve that same boundary.
- Two existing reference scripts (`docs/src/mqtt_publisher_changes.py`, `docs/src/mqtt_notify.py`) are documentation-only prototypes — not part of the installable package — demonstrating a Checkmk-to-MQTT bridge via local Livestatus socket + notification-script hooks. This milestone reuses their change-detection *logic* and the TCP-Livestatus pattern already proven in `src/checkmk_wizard/livestatus.py`, but redesigns the MQTT topic/payload contract (per-device topics rather than full-blob republishes) and drops the notification-rule delivery path.
- Target dashboard UX was scoped against how PRTG-style network monitoring tools present live status: a map + sortable-list duality, an at-a-glance stats strip, and a compact event/history log — deliberately minimal, not a Checkmk UI replacement.
- Target Checkmk version: Community Edition 2.4.0p35 (per existing wizard code's live-verification baseline).

## Constraints

- **Tech stack**: Python 3.11+, managed via `uv` (per repo convention — `uv run`/`uv add`/`uv sync`, never bare `python`/`pip`) — matches the existing wizard codebase
- **No new backend for the dashboard**: static HTML/CSS/JS only, no build step, no server-side application — state comes entirely from MQTT retained messages
- **Container boundary**: the poller/publisher must not require filesystem access to the `checkmk` container — Livestatus-over-TCP and the REST API are the only touchpoints, consistent with existing container-mode design
- **Compatibility**: new Checkmk host tag group and folder-based VLAN derivation must not break the existing 7-phase wizard flow or its tests

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Poll Livestatus over TCP instead of using Checkmk notification rules | Preserves the worker/checkmk filesystem boundary; a poller can also answer "what's the current full state" on demand, which notifications alone cannot | — Pending |
| Redesign MQTT contract around per-device topics (`lan/devices/{id}/...`) instead of reusing the old scripts' full-blob `checkmk/*` topics | Matches the frontend's "merge, don't rebuild" requirement; avoids republishing the entire host/service list on every poll | — Pending |
| Add a new Checkmk host tag group for device type, set during the wizard's Phase 5 onboarding | No existing tag captures this; onboarding time is the natural point to collect it | — Pending |
| Drop MAC address from v1 topology data | Not reliably available without Checkmk's inventory plugin; avoids adding a new dependency for one field | — Pending |
| Serve the dashboard via a new nginx container in `compose.yaml` | Consistent with the rest of the containerized stack; simplest way to make it reachable from any LAN device | — Pending |
| Keep the dashboard to 3 pages, folding a stats strip and recent-events panel into existing pages rather than adding new ones | Matches explicit ask to stay simple/effective and not duplicate Checkmk's own UI | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/bm:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/bm:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-09-05 after initialization*
