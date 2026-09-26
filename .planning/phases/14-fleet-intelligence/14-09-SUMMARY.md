---
phase: 14-fleet-intelligence
plan: 09
subsystem: docs
tags: [docs, live-verification, checkpoint, kiosk, criticality]
status: paused

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

key-decisions: []

requirements-completed: []  # Task 1 (docs) is done; PLR-16/DASH-16/DASH-17 remain pending Task 2's live checkpoint below before they can be marked complete.

duration: "Task 1 only, in progress"
completed: null
---

# Phase 14 Plan 09: Documentation and Live Verification of Criticality/Dependency Labels and Kiosk Mode (PAUSED)

**Task 1 (documentation) is complete and committed; Task 2 is a blocking `checkpoint:human-verify` awaiting an operator to run the live verification steps against the deployed stack — this plan is paused, not finished.**

## Performance

- **Tasks:** 1 of 2 completed (Task 2 is the checkpoint below, not yet run)
- **Files modified:** 2

## Accomplishments (Task 1)

- Deployment doc's `lan/devices/topology` row now lists `criticality`, `service_criticality`, `depends_on` in both its trigger text and payload key list, matching `scripts/mqtt_poller.py`'s `topology_nodes()`/`topology_signature()` (plan 14-07).
- New "Criticality and dependency labels (Phase 14)" paragraph documents the three label keys (`criticality`, `service_criticality`, `depends_on`), their exact vocabulary/delimiters/caps (200 `service_criticality` entries, 50 `depends_on` ids — matching `_MAX_SERVICE_CRITICALITY_ENTRIES`/`_MAX_DEPENDS_ON_ENTRIES` in `scripts/mqtt_poller.py`), the never-raising parser posture, that they're written by the dashboard's edit mode with the existing `topology_editor` credential (no new permission), go live only after "Apply changes", and can equally be hand-edited in Checkmk (Setup > Hosts > host > Labels). Confirms `worst_criticality` uses host-level `criticality` only, not `service_criticality`.
- New "### Kiosk / wall screen (Phase 14)" section documents `/?kiosk=1`, the in-page "Enter full screen" button's user-gesture requirement, and a `chromium --kiosk "http://<HOST_IP>:<port>/?kiosk=1"` launch example for permanent signage, plus the trusted-LAN caveat (the SPA bundle embeds the `topology_editor` secret even though the kiosk route never renders edit controls).
- `dashboard-react/README.md` gained "## 5d. Criticality & dependencies" (panel behaviour: device picker + map-click selection, Host criticality / Per-service criticality with "Default" removing the override / Depends on with a remove confirmation, auto-write per field with no per-field button, single shared "Apply changes", badge palette) and "## 5e. Kiosk mode" (`?kiosk=1`, 20s rotation, no nav/tree/history/edit controls, fullscreen button gesture/10s-timeout behaviour, `chromium --kiosk` cross-reference).
- Every statement was checked against the implemented code before writing: `scripts/mqtt_poller.py` (label constants, parsers, caps), `dashboard-react/src/lib/checkmkWrite.ts` (writers, codecs, validation), `dashboard-react/src/components/CriticalityEditor.tsx` (panel behaviour, no per-field button, confirm-on-remove), `dashboard-react/src/routes/KioskView.tsx` and `dashboard-react/src/hooks/useKioskRotation.ts` (rotation timing, fullscreen button gesture/timeout), `dashboard-react/src/routes/IndexRoute.tsx` (CriticalityEditor mount gated on `editMode && isTopologyEditingConfigured()`).

## Task Commits

1. **Task 1: Document criticality/dependency labels and kiosk mode** - `63e662e` (docs)

Task 2 has not run yet — no commit for it.

## Files Created/Modified

- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` — topology row payload/trigger update; new "Criticality and dependency labels (Phase 14)" paragraph; new "### Kiosk / wall screen (Phase 14)" section
- `dashboard-react/README.md` — new "## 5d. Criticality & dependencies" and "## 5e. Kiosk mode" sections

## Decisions Made

None beyond following the plan's `<action>` content requirements exactly; every claim was verified against source before writing, no interpretation calls were needed.

## Deviations from Plan

None — Task 1 executed exactly as written. No auto-fixes were required.

## Issues Encountered

None.

## User Setup Required

Task 2's live checkpoint requires an operator with access to the live deployed stack (Checkmk 2.4.0p36.cre, site `dmc`) — see the checkpoint returned to the orchestrator for the exact steps.

---

## CHECKPOINT REACHED (Task 2 — not yet run)

**Type:** human-verify (`gate="blocking"`)
**Plan:** 14-09
**Progress:** 1/2 tasks complete

### Completed Tasks

| Task | Name | Commit | Files |
| --- | --- | --- | --- |
| 1 | Document criticality/dependency labels and kiosk mode | `63e662e` | `docs/Podman setup for checkmk, minio, mosquitto, worker.md`, `dashboard-react/README.md` |

### Current Task

**Task 2:** Live verification of criticality/dependency editing and kiosk mode
**Status:** blocked — awaiting operator to run the steps below against the live deployed stack
**Blocked by:** requires a real browser session against the live Checkmk site, live MQTT subscription, and visual/interaction confirmation — none of which can be fabricated or simulated by the executor

### Checkpoint Details

**What was built (by prior plans, verified present in code during Task 1):** poller label carriage (plan 14-07: `CRITICALITY_LABEL`/`SERVICE_CRITICALITY_LABEL`/`DEPENDS_ON_LABEL` read into `topology_nodes()`), the criticality/dependency editor (plan 14-08: `CriticalityEditor.tsx` + `checkmkWrite.ts` writers), kiosk mode (plan 14-06: `KioskView.tsx`/`useKioskRotation.ts`), and this plan's Task 1 docs.

**How to verify (copy-pasteable, run in order):**

1. Restart the poller on the deploy host and run the React dashboard as in plan 14-05:
   ```bash
   cd deploy && podman compose restart poller
   cd ../dashboard-react && npm run dev
   ```
   (Per the context notes, the operator has previously run this at `192.168.97.129:5173` proxying `/checkmk-api` to Checkmk. If the dashboard write gets a 401, the `topology_editor` secret in `dashboard-react/src/lib/config.ts` is stale — re-provision per the deployment doc's "Note on the topology editor credential" and re-run `scripts/provision_topology_editor.py`.)

2. In the dashboard, turn on **"Edit topology"**, then click a host on the map. Confirm the **"Criticality & dependencies"** panel shows that host. Set **Host criticality** to **Critical**; confirm the pending-changes banner count goes up by exactly one.

3. For a Linux agent host, set one systemd service's **Per-service criticality** to **High**. For a screen-like host (or any host with at least two other hosts to depend on), add two **"Depends on"** hosts; then remove one and confirm the **"Remove this dependency?"** prompt appears — cancel once (confirm nothing changed), then accept (confirm the id is dropped and a write happens).

4. **Label length spot-check (D-XX from 14-RESEARCH.md):** on one host, add `depends_on` links to 10+ other hosts so the label value is long. Press **"Apply changes"**. In Checkmk (Setup > Hosts > *that host* > Labels) confirm `criticality:critical`, `service_criticality:<name>=high`, and the full `depends_on:` list are all stored **unmodified** — no truncation, no rejection/error. This is the proof that the unchanged `topology_editor` role (no new Checkmk permission) can write labels at this length.
   - **If step 4 shows any truncation or rejection:** record the exact limit observed here and STOP — this needs gap-closure planning, not an in-place patch.

5. Confirm the poller picked it up:
   ```bash
   mosquitto_sub -u wsreader -P wsreader -t lan/devices/topology -C 1 -W 5
   ```
   Expect the new `criticality`/`service_criticality`/`depends_on` keys on the edited nodes within about two poll cycles (poller restarted in step 1, then Apply in step 4 — allow up to ~2 minutes after Apply).

6. **Incident worst-criticality propagation (D-15):** provoke an incident on a host that the critical-tier screen/host depends on. Use the Livestatus method from `docs/Incident demo with fake check results.md` (NOT Checkmk's GUI "Fake check results" — it self-reverts within ~1 poll cycle):
   ```bash
   cmk() { podman exec checkmk su - dmc -c "lq 'COMMAND [$(date +%s)] $1'"; }
   cmk "DISABLE_HOST_CHECK;<host-the-critical-host-depends-on>"
   cmk "PROCESS_HOST_CHECK_RESULT;<that-host>;1;faked down"
   ```
   Confirm the incident card shows **worst criticality "high"** (the dependent host is still UP, so it counts one tier below "critical" per D-15) and, under **"View devices"**, a **"Dependent devices: ..."** line lists the dependent host. Then restore:
   ```bash
   cmk "PROCESS_HOST_CHECK_RESULT;<that-host>;0;faked up"
   cmk "ENABLE_HOST_CHECK;<that-host>"
   ```

7. Open `/?kiosk=1`. Confirm: no nav bar, no device tree, no event history, no edit toggle; the view alternates Incidents/Topology roughly every 20 seconds; the "Enter full screen" button works on click (and disappears after being clicked), or disappears on its own after ~10 seconds if untouched.

**Automated checks to also run and report** (do not skip — report pass/fail and counts, not an assumption):
```bash
cd dashboard-react && npm test
cd /home/kone/checkmk-wizard && uv run pytest tests/test_mqtt_poller.py -q
```

### Awaiting

Report back, per step:
- Step 2: pass/fail — did the panel show, did Host criticality set to Critical, did the pending count go up by 1?
- Step 3: pass/fail — did per-service High save; did the cancel-then-accept confirm dialog behave as described?
- Step 4: pass/fail, **and the observed depends_on label length/content** stored in Checkmk after Apply (exact string, or a description of any truncation/rejection).
- Step 5: pass/fail — did the mosquitto_sub output show the new keys?
- Step 6: pass/fail — did the incident card show worst criticality "high" and the "Dependent devices" line; was cleanup done?
- Step 7: pass/fail — kiosk chrome-free rotation and fullscreen button behaviour.
- The two automated command outputs (test counts / pass-fail).

**Resume signal:** Type `"approved"` if every step passed (a resumed agent will then complete this SUMMARY, mark PLR-16/DASH-16/DASH-17 requirements-complete, and finalize the plan), or describe exactly which step failed and what was observed (a resumed agent will record the gap and stop for gap-closure planning per Task 2's own instructions, rather than patching in place).

---
*Phase: 14-fleet-intelligence*
*Status: paused at Task 2 checkpoint*
