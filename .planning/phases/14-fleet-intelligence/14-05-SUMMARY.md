---
phase: 14-fleet-intelligence
plan: 05
subsystem: docs
tags: [docs, live-verification, checkpoint, mqtt, incidents]
status: paused

# Dependency graph
requires:
  - phase: 14-fleet-intelligence (plan 14-01)
    provides: "compute_incidents()/publish_incident()/publish_incident_tombstone() and the final lan/incidents/{incident_id}/status payload contract"
  - phase: 14-fleet-intelligence (plan 14-04)
    provides: "IncidentCard/IncidentList rendering and live incidentLookup wiring into IndexRoute (tree/map dimming)"
provides:
  - "Deployment doc's incident topic contract row, corrected topology-row payload keys, and Phase 14 grouping/behaviour paragraph"
  - "Deployment doc 'Incident check (Phase 14)' verification section"
  - "dashboard-react/README.md '5c. Incidents' section"
affects: [14-06, 14-07, 14-08]

tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
    - "dashboard-react/README.md"

key-decisions: []

requirements-completed: []  # PLR-14/15/16, DASH-14/15 already delivered by plans 14-01..14-04; this plan only documents them. Task 2 (the D-06 gate) is unresolved -- see Task Status below. Requirement IDs intentionally left unmarked-complete until the checkpoint closes.

duration: (in progress -- paused at checkpoint)
completed: (pending Task 2)
---

# Phase 14 Plan 05: Incident Docs and Live D-06 Gate Summary (PAUSED at Task 2 checkpoint)

**Task 1 (docs) is done and committed: the deployment doc and dashboard README now describe the incident topic contract, grouping rules, and card/dimming behaviour exactly as implemented by plans 14-01..14-04. Task 2 is a blocking human-verification checkpoint (the D-06 gate) that requires an operator with access to the live deployed stack — it is not resolved and no live-verification result has been fabricated.**

## Task Status

| Task | Name | Status | Commit |
| --- | --- | --- | --- |
| 1 | Document the incident topic contract and incident behaviour | DONE | `83c856e` |
| 2 | Live verification of last_state_change and incident rendering | **PAUSED — awaiting operator** | not yet committed |

## Task 1 — What was verified

All automated verification commands ran and passed:

```
grep -n "lan/incidents/{incident_id}/status" "docs/Podman setup for checkmk, minio, mosquitto, worker.md"   -> matches (topic table row + prose paragraph)
grep -n "### Incident check (Phase 14)" "docs/Podman setup for checkmk, minio, mosquitto, worker.md"        -> matches
grep -n "## 5c. Incidents" dashboard-react/README.md                                                        -> matches
grep -n "map_position.*unmanaged" "docs/Podman setup for checkmk, minio, mosquitto, worker.md"               -> matches (topology row payload corrected)
grep -rn "not operating" dashboard-react/README.md                                                          -> 0 matches (never used)
```

Every statement added was checked directly against the current implementation, not paraphrased from the plan text:

- The 10 incident payload keys (`id`, `root`, `root_state`, `inferred`, `confirmed_down`, `not_observable`, `dependents`, `worst_criticality`, `since`, `timestamp`) were read from `publish_incident()`/`compute_incidents()` in `scripts/mqtt_poller.py` (lines ~789-801, ~1627-1633).
- The topology row's corrected payload keys (`map_position`, `unmanaged`) were read from `topology_nodes()` (lines ~540-552).
- The "rebuilt every cycle, no poller-side file, self-heals from topic names only" claim was read from `reconcile_state()`'s docstring and `run_cycle()`'s incident tombstone/publish loop (lines ~1899-1908, ~2187-2197).
- The grouping-rule sentences were read from `compute_incidents()`'s own docstring (lines ~644-697), not reworded from 14-RESEARCH.md.
- The dashboard README's "5c. Incidents" section (ordering, D-04 copy rules, layout, dimming/deep-link, empty state, 35% viewport cap) was read from `lib/incidents.ts` (`sortIncidents`, `consequenceSummary`, `incidentStatus`, `formatIncidentDuration`), `IncidentCard.tsx`, `IncidentList.tsx`, and `TreeNode.tsx`/`TopologyMap.tsx`'s dimming/click-routing code (14-02/14-03/14-04).

## Task 2 — Why this is paused, not completed

Task 2 is `type="checkpoint:human-verify" gate="blocking"`. Its `<how-to-verify>` steps require:

1. Restarting the `poller` container on a **live deployed Podman stack** (`cd deploy && podman compose restart poller`) — this worktree has no running deployment.
2. Running `podman exec mqtt-poller python -u /scripts/mqtt_poller.py --check-columns` **against a real Checkmk 2.4.0p36.cre site** to observe whether `last_state_change` is actually present in that site's Livestatus schema. This cannot be simulated or guessed — plan 14-01's own summary explicitly left this unverified and deferred it to this plan.
3. Using Checkmk's own UI (Commands > "Fake check results") on real, currently-onboarded hosts to force DOWN/UNREACH states and visually confirm the resulting incident card, dimming, and map fading in a running dashboard build.
4. Restarting the poller mid-incident and mid-restart to confirm no ghost card survives — a live-timing observation.

None of this is available inside a git worktree with no deployed containers and no live Checkmk site. Per the objective's explicit instruction, **no live-verification result has been fabricated**. The `<action>` step (editing the dated comment on `OPTIONAL_HOST_COLUMNS`'s `last_state_change` entry in `scripts/mqtt_poller.py`) is deliberately left undone — it must record a real, operator-reported result, and doing it now would put an unverified claim into a comment whose entire purpose is to be a trustworthy live-verification record (matching this codebase's own documented comment convention).

`scripts/mqtt_poller.py` required no code changes for this plan — the `--check-columns` probe, `compute_incidents()`, and the publish/tombstone/self-heal path were all already built and tested by plan 14-01. There was nothing further to prepare in code; the only remaining work is the human-run verification itself and the one-line dated comment it produces.

## Deviations from Plan

None — Task 1 executed exactly as written. Task 2 has not been executed (paused at its own checkpoint, as designed); no auto-fix or deviation applies to it.

## Self-Check: PASSED (Task 1 only)

- FOUND: `docs/Podman setup for checkmk, minio, mosquitto, worker.md` (modified)
- FOUND: `dashboard-react/README.md` (modified)
- FOUND commit: `83c856e` (Task 1)
- Task 2: not yet executed — no commit to verify.

---
*Phase: 14-fleet-intelligence*
*Paused: 2026-09-26 (Task 2 checkpoint, awaiting operator)*
