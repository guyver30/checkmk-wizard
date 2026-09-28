---
phase: 14-fleet-intelligence
plan: 09
subsystem: docs
tags: [docs, live-verification, checkpoint, criticality]
status: complete

# Dependency graph
requires:
  - phase: 14-fleet-intelligence (plan 14-06)
    provides: "?kiosk=1 KioskView/useKioskRotation, DASH-17"
  - phase: 14-fleet-intelligence (plan 14-07)
    provides: "poller label read path (CRITICALITY_LABEL/SERVICE_CRITICALITY_LABEL/DEPENDS_ON_LABEL, parsers, topology_nodes), PLR-16"
  - phase: 14-fleet-intelligence (plan 14-08)
    provides: "CriticalityEditor panel and checkmkWrite.ts label writers, DASH-16"
provides:
  - "Deployment doc: topology row payload lists criticality/service_criticality/depends_on; 'Criticality and dependency labels (Phase 14)' paragraph; 'Kiosk / wall screen (Phase 14)' section with chromium --kiosk example"
  - "dashboard-react/README.md: '5d. Criticality & dependencies' and '5e. Kiosk mode' sections"
affects: []

tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
    - "dashboard-react/README.md"

key-decisions:
  - "Kiosk mode (DASH-17) descoped by the operator; the 14-06 code and docs were removed in 9f9bbe8"
  - "Per-service criticality list limited to the services the host details view shows (dd10079)"
  - "Criticality/dependency model parked for redesign after step 6 (todo 2026-09-28-revisit-criticality-and-dependency-model)"
  - "Deploy docs: run the dev server in a node:22-alpine container; never restart a single compose service (it cut Checkmk off from the LAN)"

requirements-completed: [PLR-16, DASH-16]  # DASH-17 (kiosk) descoped 2026-09-28; the D-15 dependent weighting was live-exercised but parked for redesign (todo 2026-09-28-revisit-criticality-and-dependency-model)

duration: "2 sessions (docs 2026-09-26, live UAT 2026-09-28)"
completed: 2026-09-28
---

# Phase 14 Plan 09: Documentation and Live Verification of Criticality/Dependency Labels and Kiosk Mode 

**Docs written (Task 1) and live-verified by the operator on 2026-09-28 (Task 2). The label editing and poller read path pass. Kiosk mode was descoped and removed. The dependent-weighting behaviour works as coded but is parked for redesign.**

## Performance

- **Tasks:** 2 of 2 completed
- **Files modified:** 2

## Accomplishments (Task 1)

- Deployment doc's `lan/devices/topology` row now lists `criticality`, `service_criticality`, `depends_on` in both its trigger text and payload key list, matching `scripts/mqtt_poller.py`'s `topology_nodes()`/`topology_signature()` (plan 14-07).
- New "Criticality and dependency labels (Phase 14)" paragraph documents the three label keys (`criticality`, `service_criticality`, `depends_on`), their exact vocabulary/delimiters/caps (200 `service_criticality` entries, 50 `depends_on` ids — matching `_MAX_SERVICE_CRITICALITY_ENTRIES`/`_MAX_DEPENDS_ON_ENTRIES` in `scripts/mqtt_poller.py`), the never-raising parser posture, that they're written by the dashboard's edit mode with the existing `topology_editor` credential (no new permission), go live only after "Apply changes", and can equally be hand-edited in Checkmk (Setup > Hosts > host > Labels). Confirms `worst_criticality` uses host-level `criticality` only, not `service_criticality`.
- New "### Kiosk / wall screen (Phase 14)" section documents `/?kiosk=1`, the in-page "Enter full screen" button's user-gesture requirement, and a `chromium --kiosk "http://<HOST_IP>:<port>/?kiosk=1"` launch example for permanent signage, plus the trusted-LAN caveat (the SPA bundle embeds the `topology_editor` secret even though the kiosk route never renders edit controls).
- `dashboard-react/README.md` gained "## 5d. Criticality & dependencies" (panel behaviour: device picker + map-click selection, Host criticality / Per-service criticality with "Default" removing the override / Depends on with a remove confirmation, auto-write per field with no per-field button, single shared "Apply changes", badge palette) and "## 5e. Kiosk mode" (`?kiosk=1`, 20s rotation, no nav/tree/history/edit controls, fullscreen button gesture/10s-timeout behaviour, `chromium --kiosk` cross-reference).
- Every statement was checked against the implemented code before writing: `scripts/mqtt_poller.py` (label constants, parsers, caps), `dashboard-react/src/lib/checkmkWrite.ts` (writers, codecs, validation), `dashboard-react/src/components/CriticalityEditor.tsx` (panel behaviour, no per-field button, confirm-on-remove), `dashboard-react/src/routes/KioskView.tsx` and `dashboard-react/src/hooks/useKioskRotation.ts` (rotation timing, fullscreen button gesture/timeout), `dashboard-react/src/routes/IndexRoute.tsx` (CriticalityEditor mount gated on `editMode && isTopologyEditingConfigured()`).

## Task Commits

1. **Task 1: Document criticality/dependency labels and kiosk mode** - `63e662e` (docs)

2. **Task 2: Live verification** — operator UAT 2026-09-28. Follow-up commits: `dd10079` (per-service list fix + deploy doc fixes), `1fc28a4` and `8fa862f` (todos), `9f9bbe8` (kiosk removal)

## Files Created/Modified

- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` — topology row payload/trigger update; new "Criticality and dependency labels (Phase 14)" paragraph; new "### Kiosk / wall screen (Phase 14)" section
- `dashboard-react/README.md` — new "## 5d. Criticality & dependencies" and "## 5e. Kiosk mode" sections

## Decisions Made

None beyond following the plan's `<action>` content requirements exactly; every claim was verified against source before writing, no interpretation calls were needed.

## Deviations from Plan

- The per-service criticality list originally offered every service the poller publishes. The operator wanted only the services shown on the host details view. Fixed in `dd10079` with `displayedServices()` in `lib/agentDetail.ts`.
- Kiosk mode (DASH-17, plan 14-06) was descoped by the operator. `KioskView`, `useKioskRotation`, the `?kiosk=1` branch, the `kiosk-progress` keyframes, IncidentList's unused `fill` variant and all kiosk docs were removed in `9f9bbe8`. The Task 1 kiosk docs listed above no longer exist.
- The live dev server actually runs as `podman run ... node:22-alpine npm --prefix dashboard-react run dev -- --host`. That is now documented in `dashboard-react/README.md` §3 and in the incident demo runbook.

## Issues Encountered

- **Every host went DOWN after step 1.** At 03:22:34 UTC, `podman compose restart poller` re-created the poller's link on `cmk_net` (rootless Podman 4.9.3, slirp4netns). Seven seconds later the checkmk container had lost all LAN traffic, ICMP and TCP alike (`rta nan, lost 100%` on every host). A full `podman compose down && podman compose up -d` fixed it. The deployment doc §5.1 now has an "A third signature" paragraph, and the restart instructions use a full down/up. Seen once, not reproduced. `scripts/smoke_test_poller.py` and `scripts/smoke_test_broker.py` still default to single-service restart commands.

## Live Verification Results (Task 2, operator, 2026-09-28)

| Step | Check | Result |
| --- | --- | --- |
| 1 | Restart stack, run dev server | Done (see Issues Encountered) |
| 2 | Host criticality → Critical, pending count +1 | Pass |
| 3 | Per-service tier; add/remove depends_on with confirm prompt | Pass. The service list was too broad; fixed in `dd10079` |
| 4 | Long `depends_on` label (13 hosts) stored unmodified in Checkmk | Pass: no truncation, no rejection |
| 5 | Poller publishes `criticality`/`service_criticality`/`depends_on` | Pass (`192.168.0.203`: 13 depends_on, `service_criticality {PING: high}`) |
| 6 | D-15 worst-criticality with a still-UP dependent | Behaves as coded, but the operator finds the model unclear. `.200` (critical, UP) depends on `.204` (also critical), `.204` faked DOWN → card `critical` from `.204`'s own tier, `.200` listed as dependent, no map/tree marker (by D-15). Parked: `.planning/todos/pending/2026-09-28-revisit-criticality-and-dependency-model.md` |
| 7 | Kiosk mode | Not run. Descoped and removed (`9f9bbe8`) |

Automated checks (dev machine): dashboard 469/469 after the fix and 455/455 after the kiosk removal, typecheck clean; `tests/test_mqtt_poller.py` 209 passed.

## User Setup Required

None.
