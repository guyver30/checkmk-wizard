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
- [ ] A dashboard (no new backend) — topology/overview view (at-a-glance stats strip + map), a live sortable device table with recent-events panel, and a per-device drill-down with a bounded status-history strip — served by a new nginx container added to `compose.yaml`. *(Revised 2026-09-21: rebuilt as a React SPA against `kone-design-system`, superseding the original "3 static HTML files, no build step" description — see Constraints and Phase 11.1's CONTEXT.md. Validated in Phase 11.1: three-pane layout, KONE light palette, resizable/collapsible panes, device tree with grouping, stats strip, and event history are built and tested — DASH-01/DASH-06. The topology map itself is still a placeholder pending Phase 13 (DASH-07). Revised 2026-09-23, Phase 12: the per-device drill-down is now built and reachable — `/details?id=` shows live CPU/RAM/disk/SMART gauges and a read-only per-service status list from a new Livestatus `services` query, plus the bounded status-history strip, with the fleet tree wired to navigate into it (DASH-08 through DASH-11, DASH-03 partial). The "live sortable device table" (a distinct list-view page) remains unbuilt. Revised 2026-09-23, Phase 13: the topology map itself is now built (DASH-07) — a live vis-network graph with parent→child edges and saved positions, replacing the earlier placeholder. An "Edit topology" mode lets an operator draw/reconnect/delete links, drag positions and add unmanaged switches, batched behind a single "Apply changes" activation (DASH-12/DASH-13).)*
- [ ] Dashboard shows a connection-status indicator with exponential-backoff MQTT reconnect, and merges incoming updates into existing UI state rather than re-rendering from scratch

### Out of Scope

- MAC address collection for topology nodes — not reliably available without Checkmk's HW/SW inventory plugin; would add a new subsystem dependency for marginal value
- Checkmk notification rules as the live-update mechanism — would require deploying scripts into the `checkmk` container's own OMD filesystem, breaking the worker/checkmk boundary the container-mode architecture is built around
- Duplicating Checkmk's per-service *configuration/administration* UI in the new dashboard — narrowed 2026-09-21 (Phase 12, DASH-08 through DASH-10): a read-only per-service status list and agent-metric gauges are in scope, because "why is this host red" could not be answered without them. Narrowed again 2026-09-23 (Phase 13, DASH-12/DASH-13): topology editing (drawing/reconnecting/deleting parent-child links, dragging positions, adding unmanaged switches) is now the one write/administration exception, gated behind an explicit "Edit topology" mode and a scoped credential that cannot activate another operator's foreign changes. Still out of scope: rule editing, downtime scheduling, acknowledgement, service discovery, host deletion, and every other write/administration action — those remain Checkmk's own UI's job. The external deep link into Checkmk's UI for full service-level detail (D-17) remains unbuilt; `CHECKMK_BASE_URL` already exists in `dashboard-react/src/lib/config.ts` for whenever it is
- Time-series graphing/historical dashboards beyond a simple bounded per-device transition-history strip — no time-series database

## Context

- Deployment architecture: a rootless Podman Compose stack (`checkmk`, `mosquitto`, `minio`, `worker` containers on a shared `cmk_net` bridge network) — documented in `docs/Podman setup for checkmk, minio, mosquitto, worker.md`. `checkmk-wizard` already runs from the `worker` container in "container mode," touching Checkmk only via its REST API and Livestatus-over-TCP port (6557), never the `checkmk` container's filesystem. This milestone's new poller/dashboard preserve that same boundary.
- Two existing reference scripts (`docs/src/mqtt_publisher_changes.py`, `docs/src/mqtt_notify.py`) are documentation-only prototypes — not part of the installable package — demonstrating a Checkmk-to-MQTT bridge via local Livestatus socket + notification-script hooks. This milestone reuses their change-detection *logic* and the TCP-Livestatus pattern already proven in `src/checkmk_wizard/livestatus.py`, but redesigns the MQTT topic/payload contract (per-device topics rather than full-blob republishes) and drops the notification-rule delivery path.
- Target dashboard UX was scoped against how PRTG-style network monitoring tools present live status: a map + sortable-list duality, an at-a-glance stats strip, and a compact event/history log — deliberately minimal, not a Checkmk UI replacement.
- Target Checkmk version: Community Edition 2.4.0p35 (per existing wizard code's live-verification baseline).

## Constraints

- **Tech stack**: Python 3.11+, managed via `uv` (per repo convention — `uv run`/`uv add`/`uv sync`, never bare `python`/`pip`) — matches the existing wizard codebase
- **No new backend for the dashboard**: no server-side application — state comes entirely from MQTT retained messages. *(Revised 2026-09-21, Phase 11.1 D-40: the "static HTML/CSS/JS only, no build step" half is retired — the dashboard is being rewritten as a React + TypeScript + Tailwind SPA against the company's own `kone-design-system` component library, built to static assets and served by the same nginx container. No new backend/API is added; this is a build-tooling change, not an architecture change. See `.planning/phases/11.1-dashboard-layout-and-light-palette/11.1-CONTEXT.md`.)* *(Revised 2026-09-23, Phase 13 D-04: still no server-side application — topology edit mode writes directly to Checkmk's own REST API from the browser, using a narrowly-scoped `topology_editor` credential embedded client-side, reached via a same-origin forwarding rule (`/checkmk-api`, the Vite dev/preview proxy today, one nginx `location` block post-cutover). No new backend/API is added; Checkmk's own REST API is the only write surface. See `.planning/phases/13-wizard-parents-support-and-topology-map/13-CONTEXT.md`.)*
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
*Last updated: 2026-09-23 after Phase 12 (Agent Metrics and Service Status) completion*
