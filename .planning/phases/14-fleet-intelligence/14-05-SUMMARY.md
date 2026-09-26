---
phase: 14-fleet-intelligence
plan: 05
subsystem: docs
tags: [docs, live-verification, checkpoint, mqtt, incidents]
status: complete

# Dependency graph
requires:
  - phase: 14-fleet-intelligence (plan 14-01)
    provides: "compute_incidents()/publish_incident()/publish_incident_tombstone() and the final lan/incidents/{incident_id}/status payload contract"
  - phase: 14-fleet-intelligence (plan 14-04)
    provides: "IncidentCard/IncidentList rendering and live incidentLookup wiring into IndexRoute (tree/map dimming)"
provides:
  - "Deployment doc's incident topic contract row, corrected topology-row payload keys, and Phase 14 grouping/behaviour paragraph"
  - "Deployment doc 'Incident check (Phase 14)' verification section, corrected to use Livestatus external commands instead of the GUI's self-reverting 'Fake check results'"
  - "dashboard-react/README.md '5c. Incidents' section"
  - "docs/Incident demo with fake check results.md — operator-requested stakeholder demo runbook"
  - "Dated live-verification result for last_state_change in scripts/mqtt_poller.py"
  - "D-06 gate passed: live evidence that root-cause collapse, dimming, and inferred-root marking work on a real 2.4.0p36.cre site"
affects: [14-06, 14-07, 14-08]

tech-stack:
  added: []
  patterns:
    - "Livestatus external commands (DISABLE_HOST_CHECK / PROCESS_HOST_CHECK_RESULT / ENABLE_HOST_CHECK) via `podman exec checkmk su - dmc -c \"lq 'COMMAND ...'\"` as the reliable way to force a host state for a demo, in place of Checkmk's GUI 'Fake check results' (which self-reverts within ~1 poll cycle)"

key-files:
  created:
    - "docs/Incident demo with fake check results.md"
  modified:
    - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
    - "dashboard-react/README.md"
    - "scripts/mqtt_poller.py"

key-decisions:
  - "last_state_change is present on the live 2.4.0p36.cre site (confirmed via --check-columns on 2026-09-26); incident duration displays real values instead of 'duration unknown'"
  - "Checkmk's GUI 'Fake check results' is unsuitable for demos/UAT on this Checkmk version: it is overwritten by the host's own next real active check (~1 minute for a no-IP host, whose real check always returns UP), which can revert a fake between two 60s poller reads. Documented method going forward: Livestatus external commands, DISABLE_HOST_CHECK before PROCESS_HOST_CHECK_RESULT, ENABLE_HOST_CHECK to restore."

requirements-completed: [PLR-14, PLR-15, PLR-16, DASH-14, DASH-15]

# Metrics
duration: ~45min across two sessions (Task 1 in prior session; Task 2 completion, runbook, doc fix, and this summary in current session)
completed: 2026-09-26
---

# Phase 14 Plan 05: Incident Docs and Live D-06 Gate Summary

**The D-06 gate is passed: an operator confirmed on a live Checkmk 2.4.0p36.cre deployment that root-cause incident collapse, dimming, and inferred-root marking all work exactly as documented — plain single-host incidents, managed-switch UNREACH collapse, unmanaged-switch inferred roots (including the split-on-partial-recovery case), poller-restart survival, and full incident-topic cleanup all passed. A stakeholder-facing demo runbook was written per the operator's request, and the deployment doc's incident-provocation guidance was corrected after live testing showed the GUI method it previously recommended reverts on its own.**

## Performance

- **Tasks:** 2 (Task 1 docs; Task 2 live-verification checkpoint + operator-requested runbook + doc fix)
- **Files modified:** 4 (`scripts/mqtt_poller.py`, `docs/Podman setup for checkmk, minio, mosquitto, worker.md`, `dashboard-react/README.md`, plus new `docs/Incident demo with fake check results.md`)

## Accomplishments

- Deployment doc and dashboard README document the incident MQTT contract, grouping rules, and card/dimming behaviour exactly as implemented by plans 14-01..14-04 (Task 1, prior session).
- Live D-06 gate passed on a real 2.4.0p36.cre site: `--check-columns` confirms `last_state_change` is present; single-host, managed-switch, and unmanaged/inferred-switch incident scenarios all rendered correctly, including the split case (restoring one of two down children collapses the inferred card back to a plain single-host card with no "Inferred" marker) and poller-restart survival (no ghost/duplicate cards).
- Live UAT surfaced and fixed a real map-rendering bug (opacity not resetting on recovery) — fixed and committed separately (`51d50df`, orchestrator-side, prior to this continuation) with a regression test.
- Operator-requested demo runbook (`docs/Incident demo with fake check results.md`) documents all five fake-check scenarios as a copy-pasteable stakeholder demo script, including the operational workaround (Livestatus commands instead of the GUI) discovered during UAT.
- Corrected the deployment doc's "Incident check (Phase 14)" step 3, which previously recommended the now-known-unreliable GUI "Fake check results" method.

## Task Commits

Each task was committed atomically:

1. **Task 1: Document the incident topic contract and incident behaviour** - `83c856e` (docs, prior session)
2. **Task 2: Live verification — record dated `last_state_change` result** - `17e0927` (docs)
3. **Task 2 follow-up: demo runbook + Incident-check doc correction** - `fda3589` (docs)

Related, already-committed by the orchestrator before this continuation: `51d50df` (fix(14-03): restore full map opacity when a consequence node's incident closes — found during this plan's live UAT).

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified

- `scripts/mqtt_poller.py` — `OPTIONAL_HOST_COLUMNS`'s `last_state_change` entry comment now records the dated 2026-09-26 live-verification result (present; duration shows real values) instead of "NOT yet live-probed"
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` — incident topic contract row, corrected topology row payload keys, Phase 14 grouping paragraph, "Incident check (Phase 14)" section (Task 1); step 3 corrected to point at the new runbook instead of the GUI method (Task 2 follow-up)
- `dashboard-react/README.md` — "5c. Incidents" section (Task 1)
- `docs/Incident demo with fake check results.md` — new stakeholder demo runbook (Task 2 follow-up, operator-requested)

## Decisions Made

- `last_state_change` is live-verified present on 2.4.0p36.cre — see key-decisions above.
- Checkmk's GUI "Fake check results" is documented as unreliable for this Checkmk version's demo/UAT purposes; the Livestatus external-command method (`DISABLE_HOST_CHECK` / `PROCESS_HOST_CHECK_RESULT` / `ENABLE_HOST_CHECK`) is now the documented standard, in both the deployment doc and the new runbook.

## Live D-06 Gate Results (operator-run, 2026-09-26, Checkmk 2.4.0p36.cre)

| Check | Result |
| --- | --- |
| `--check-columns` | ALL columns present, including `last_state_change`. Incident duration shows real values (e.g. "192.168.0.203 — 9 h 56 min"). |
| Plain single-host root (unmanaged switch DOWN, no other observers) | Exactly one card for the down device; cleared on recovery. Its UP children correctly did not change state (Checkmk only marks a child UNREACH when the child's own check also fails). PASS. |
| Unmanaged/inferred case (2 children of unmanaged `switchxxx` faked DOWN) | ONE card "switchxxx — 1 min", "Inferred, not confirmed", "2 not observable"; both children dimmed in tree with "See incident"; faded on map; switch got dashed orange inferred-root border. A separate, genuinely-down host (192.168.0.203) kept its own independent card. PASS. |
| Split (restore one of two down children) | Card became single-host "192.168.0.222 — 4 min" with no "Inferred" marker; switch border returned to normal. PASS. |
| Clear (restore the remaining child) | Card disappeared; only the unrelated genuinely-down host's card remained. PASS — but this step's first run exposed the map-opacity bug (below), now fixed. |
| Poller restart / no-ghost-card, managed-root case | Operator ran both and approved. PASS. |

**Bug found and fixed during this UAT:** recovered hosts stayed faded on the topology map until a manual page reload — `nodeVisual()` omitted `opacity` for normal nodes, and vis-network's `nodes.update()` merges rather than replaces, so a previously-dimmed node's stale opacity value was never cleared. Fixed in `51d50df` (orchestrator-applied, prior to this continuation): `nodeVisual()` now always sets `opacity` explicitly (0.4 dimmed / 1 otherwise), with a regression test added.

**Operational findings recorded for future UAT/demo sessions (now folded into the new runbook and doc fix):**
- The `topology_editor` credential can go stale after a site rebuild (the user no longer exists), producing HTTP 401 on every dashboard write; fixed by re-running `scripts/provision_topology_editor.py` and pasting the new secret into `config.ts`.
- Checkmk's GUI "Fake check results" is overwritten by the host's next real check (~1 min; a no-IP host's real check always returns UP) — not durable enough for demo timing. The reliable method is Livestatus external commands (`DISABLE_HOST_CHECK` before `PROCESS_HOST_CHECK_RESULT`, `ENABLE_HOST_CHECK` to restore), run via `podman exec checkmk su - dmc -c "lq 'COMMAND ...'"`.
- A host left with active checks disabled for a while goes STALE in the dashboard (a distinct, neutral badge) while its incident card persists independently — expected, since the poller groups incidents on `host_state_raw`, not on staleness; not a product bug.

## Deviations from Plan

None — Task 2 executed exactly as specified once the operator's checkpoint response arrived. The demo runbook and the deployment-doc correction were both explicit operator requests made alongside the "approved" checkpoint response, not autonomous scope additions; they are recorded here as additional deliverables rather than deviations.

## Issues Encountered

None beyond the map-opacity bug already documented above (found during live UAT, fixed and committed separately as `51d50df` before this continuation began).

## User Setup Required

None — no external service configuration required beyond what's already documented (`TOPOLOGY_EDITOR_SECRET` provisioning, already covered by the deployment doc and now cross-referenced from the new runbook).

## Next Phase Readiness

The D-06 gate is passed: evidence framing (root-cause collapse, inferred roots, incident cards, dimming) is verified live and documented. Plans 14-07 (criticality) and 14-08 (dependency editing) can now proceed — both build directly on the incident grouping and rendering verified here.

---
*Phase: 14-fleet-intelligence*
*Completed: 2026-09-26*
