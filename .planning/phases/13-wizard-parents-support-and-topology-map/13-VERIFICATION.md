---
phase: 13-wizard-parents-support-and-topology-map
verified: 2026-09-23T22:30:00Z
status: passed
score: 8/8 must-haves verified
has_blocking_gaps: false
overrides_applied: 0
---

# Phase 13: Wizard Parents Support and Topology Map Verification Report

**Phase Goal:** Checkmk's `parents` host attribute is populated by the wizard, so the dashboard can render a real, auto-derived topology map instead of a hand-maintained diagram
**Verified:** 2026-09-23
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

Note on scope: 13-CONTEXT.md's Scope Revision (confirmed in ROADMAP.md's own "Scope revision (2026-09-23)" line) legitimately superseded the original wizard-CLI approach to populating `parents` with a dashboard-embedded topology editor that writes `parents` directly to Checkmk's REST API. This is a locked, documented pivot, not an unauthorized deviation — verified against it, not the original wizard-CLI wording.

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A live REST-capability probe closes every unverified Checkmk-REST assumption (roles, permissions, unmanaged-switch tag shape, labels, CORS) against the real deployment before any dependent code is trusted | VERIFIED | `scripts/probe_topology_rest.py` (700 lines) exists with 9 dated `VERDICT V-*` lines in its module docstring (V-ROLE, V-PERMS, V-SWITCH, V-PARENTS, V-LABELS, V-LABELS-IN-COLLECTION, V-CORS, V-CUSTOMATTR, V-TAGPUT), each citing verbatim output from a real run against Checkmk 2.4.0p35/p36 CE (13-01-SUMMARY.md). No `activate-changes/invoke` call anywhere in the script (grep confirms). A later live-UAT correction to V-PERMS is recorded in the same docstring (see Truth 8) |
| 2 | The dashboard renders a live vis-network topology map with state-coloured nodes and parent→child edges, replacing the placeholder, merging updates via `DataSet.update()` (DASH-07) | VERIFIED | `dashboard-react/src/components/TopologyMap.tsx` (510 lines) uses `shape: "circularImage"`, `nodes.update()`/`edges.update()` for merges, `stabilizationIterationsDone` → freeze physics; `network.setData` is never called (grep -0). `MapPlaceholder.tsx` is deleted. `IndexRoute.tsx` imports and renders `<TopologyMap .../>` fed by the store's `topology` slot. Click navigates to `/details?id={id}` (`navigate(\`/details?id=...\`)` present) |
| 3 | The poller carries each host's saved map position and unmanaged-switch marker to every viewer via the existing once-per-cycle host_config REST GET, with no second REST call (PLR-13) | VERIFIED | `scripts/mqtt_poller.py` has `fetch_host_config()` reading `extensions.attributes.labels` for `map_position`/`unmanaged_switch`; `topology_nodes()`/`topology_signature()` carry both fields; `_normalise_restored_node()` backfills for older retained payloads (13-04-SUMMARY.md, confirmed by grep in the live file) |
| 4 | An operator can enter an explicit, off-by-default "Edit topology" mode and draw/reconnect/delete parent↔child links and drag positions, each writing to Checkmk's REST API, going live only via one "Apply changes" action (DASH-12) | VERIFIED | `TopologyMap.tsx` implements `addEdge`/`editEdge`/`deleteEdge`/dragEnd, all calling `checkmkWrite.updateParents`/`setMapPosition`. `TopologyToolbar.tsx` + `IndexRoute.tsx` implement the Switch (`useState(false)` — off by default), pending-count Banner, and single `activateChanges()` call per Apply press (`grep -c "activateChanges(" IndexRoute.tsx` → 1 per 13-07-SUMMARY.md, re-confirmed present in the live file) |
| 5 | From edit mode, an operator can add an unmanaged LAN switch as a real, check-free Checkmk host that still carries parents/map position (DASH-13) | VERIFIED | `TopologyMap.tsx`'s `addNode` calls `checkmkWrite.createUnmanagedSwitch`; `checkmkWrite.ts` exports `UNMANAGED_SWITCH_ATTRIBUTES` and `createUnmanagedSwitch()`. The exact no-check attribute shape (`tag_address_family: no-ip`, `tag_agent: no-agent`, `tag_snmp_ds: no-snmp`, `tag_device_type: NetworkDevice`) was live-verified in 13-01 (V-SWITCH) and re-confirmed live in 13-08's UAT step 9 (PASS: "zero services, never WARN/CRIT") |
| 6 | The browser writer is a single-choke-point, GET→merge→PUT-with-ETag REST client that never leaks its credential, serializes writes, and batches activation once per Apply | VERIFIED | `checkmkWrite.ts` (303 lines): one `request()`/`fetch(` choke point, `If-Match` header present, `activateChanges()` present with polling. Verified by direct grep and by 13-05-SUMMARY.md's own acceptance-criteria grep evidence (exactly 1 `fetch(` call site) |
| 7 | Documentation reflects what was actually built (README, deployment doc, PROJECT.md) | VERIFIED | `dashboard-react/README.md` contains "Edit topology", `TOPOLOGY_EDITOR_SECRET`/`TOPOLOGY_EDITOR_USER` rows, and the `location /checkmk-api/` nginx cutover block. `docs/Podman setup for checkmk, minio, mosquitto, worker.md` contains `provision_topology_editor.py` invocation and a "Topology map check (Phase 13)" section. All confirmed present by direct grep on the live files, not just SUMMARY claims |
| 8 | The full chain (credential → write → Apply → Livestatus → poller → every viewer) was proven end-to-end on the real deployment, not just unit-tested | VERIFIED | 13-08-SUMMARY.md records a 13-step live UAT, all PASS, run by the developer on the real deployment host (per this task's explicit instruction to trust that record). Five real bugs were found and fixed live, each with its own commit and regression test — all 5 commit hashes (`e89ff0b`, `2206789`, `b0b2267`, `6341287`, `219fcc6`) independently confirmed present in `git log` by this verification. The V-PERMS correction (`wato.see_all_folders` added) is reflected in both `scripts/probe_topology_rest.py`'s docstring and `scripts/provision_topology_editor.py`'s `REQUIRED_PERMISSIONS` tuple, confirmed by direct file read |

**Score:** 8/8 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scripts/probe_topology_rest.py` | Live REST capability probe + findings | VERIFIED | 700 lines, 9 VERDICT lines, never activates changes |
| `scripts/provision_topology_editor.py` | Scoped role/user provisioning | VERIFIED | 399 lines, `REQUIRED_PERMISSIONS` includes corrected `wato.see_all_folders`, no `roles: ["admin"]` |
| `scripts/mqtt_poller.py` | `fetch_host_config`, map_position/unmanaged in payload | VERIFIED | Present, exercised by 152 passing poller tests |
| `dashboard-react/src/lib/mapIcons.ts` | State-coloured icon builder | VERIFIED | 107 lines, exports `STATE_HEX`/`deviceTypeSvg`/`recoloredDataUri`/`nodeVisual` |
| `dashboard-react/src/lib/topologyLayout.ts` | buildMapModel, grid placement | VERIFIED | 148 lines |
| `dashboard-react/src/lib/checkmkWrite.ts` | Browser REST writer | VERIFIED | 303 lines, single choke point, ETag PUT, activation polling |
| `dashboard-react/src/components/TopologyMap.tsx` | Live editable map | VERIFIED | 510 lines, wired into IndexRoute, all manipulation callbacks present |
| `dashboard-react/src/components/TopologyToolbar.tsx` | Edit toggle/Apply UI | VERIFIED | 55 lines, wired into IndexRoute |
| `dashboard-react/src/hooks/useEditIdleTimeout.ts` | 5-min idle auto-exit | VERIFIED | 58 lines, wired into IndexRoute |
| `dashboard-react/src/components/MapPlaceholder.tsx` | (should be removed) | VERIFIED REMOVED | File absent, confirming genuine replacement not additive stub |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `IndexRoute.tsx` | `TopologyMap` | `<TopologyMap topologyDevices=... editMode=... onEditSaved=... onEditFailed=.../>` | WIRED | Confirmed by grep in live file |
| `IndexRoute.tsx` | `TopologyToolbar` | `<TopologyToolbar editMode=.../>` | WIRED | Confirmed by grep in live file |
| `IndexRoute.tsx` | `checkmkWrite.activateChanges`/`countPendingChanges` | `import { activateChanges, countPendingChanges } from "../lib/checkmkWrite"` | WIRED | Confirmed by grep in live file |
| `TopologyMap.tsx` manipulation callbacks | `checkmkWrite.updateParents`/`setMapPosition`/`createUnmanagedSwitch` | direct call | WIRED | Confirmed by grep in live file |
| `scripts/mqtt_poller.py` | Checkmk `host_config` REST | `fetch_host_config()` | WIRED | Confirmed present, 152 poller tests passing |
| `dashboard-react/README.md` cutover checklist | nginx `location /checkmk-api/` | documented config block | WIRED | Confirmed present in live file |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Python test suite passes (poller, provisioning script) | `uv run pytest -q` | `473 passed` | PASS |
| Dashboard test suite passes (map, writer, toolbar, idle-timeout) | `npm test -- --run` (dashboard-react) | `317 passed, 2 failed` (2 failures are pre-existing, documented, unrelated `GroupingControls.test.tsx` clock-drift issue — confirmed present before Phase 13's earliest commit via `git log` on that test file, and explicitly logged in `deferred-items.md` from plan 13-02 onward) | PASS (Phase-13 scope) |
| Probe never activates Checkmk changes | `grep -n "activate-changes/invoke" scripts/probe_topology_rest.py` | no match | PASS |
| No debt markers in Phase 13 source files | `grep -n "TBD\|FIXME\|XXX"` across `TopologyMap.tsx`, `checkmkWrite.ts`, `provision_topology_editor.py`, `mqtt_poller.py`, `TopologyToolbar.tsx` | no matches | PASS |

### Probe Execution

Not applicable in the `scripts/*/tests/probe-*.sh` sense — this phase's "probe" is `scripts/probe_topology_rest.py`, a one-shot live-capability script meant to be run once against the real deployment (not a repeatable regression probe). Its Task 2 execution is documented as a human-run checkpoint in 13-01-SUMMARY.md with verbatim pasted stdout; this verifier could not and did not re-run it (no reachable Checkmk site from this environment), consistent with this task's explicit instruction to trust the recorded live-UAT/probe results rather than re-run live infrastructure.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| DASH-07 | 13-02, 13-03 | Live vis-network topology map, DataSet.update merge | SATISFIED | REQUIREMENTS.md marked `[x]`/Complete; TopologyMap.tsx verified above |
| DASH-12 | 13-01, 13-04, 13-05, 13-06, 13-07 | Edit-mode write-back with batched Apply | SATISFIED | REQUIREMENTS.md marked `[x]`/Complete; full write+Apply chain verified above and live-UAT-proven |
| DASH-13 | 13-01, 13-04, 13-05, 13-06 | Unmanaged switch as check-free host | SATISFIED | REQUIREMENTS.md marked `[x]`/Complete; live-UAT step 9 confirmed zero services/no WARN-CRIT |
| PLR-13 | 13-01, 13-04 | Poller carries map_position/unmanaged | SATISFIED | REQUIREMENTS.md marked `[x]`/Complete; fetch_host_config() verified in live file |

No orphaned requirements found — REQUIREMENTS.md's Phase 13 traceability table lists exactly these four IDs, all mapped to plans in this phase's plan set, all marked Complete.

### Anti-Patterns Found

None blocking. Code review (13-REVIEW.md, standard depth, 29 files) found 0 critical, 3 warnings, 3 info findings — all robustness/defense-in-depth gaps, not functional defects:

- **WR-01** (`TopologyMap.tsx:177-245`): a multi-network-call edit sequence (`editEdge` cross-child branch, `deleteEdge` multi-edge loop) doesn't record already-applied partial mutations in the pending overlay on a mid-sequence failure. Real but narrow-window robustness gap, not a phase-goal blocker.
- **WR-02** (`config.ts:66-68`, `provision_topology_editor.py:363-368`): the write-capable `TOPOLOGY_EDITOR_SECRET` is pasted into a git-tracked file with no gitignored local-override mechanism, unlike the read-only `WS_USERNAME`/`WS_PASSWORD` precedent it's modeled on. Verified as a genuine design-shortcut risk (the tracked file currently ships the harmless placeholder, confirmed by direct read — no live secret is actually committed at this time — but the mechanism invites accidental future commits). This is a security hygiene warning already flagged by the phase's own code review, not a functional gap in the phase goal.
- **WR-03** (`tests/test_provision_topology_editor.py`): the provisioning script's network-facing functions (`ensure_role`, `ensure_user`, `activate_own_changes`, `_rest`) have no mocked-REST test coverage, unlike the poller's equivalent code. A real gap in regression safety, not in phase-goal achievement — the script was proven to work by the live UAT itself (13-08).

These three warnings do not block phase-goal achievement (the map renders, edits write and go live, unmanaged switches work — all proven live) but are legitimate follow-up items. Recommend logging as backlog items rather than blocking this phase.

### Human Verification Required

None. The phase's blocking human-verify checkpoint (13-08 Task 2's 13-step live UAT) was already completed by the developer on the real deployment host, with all 13 steps PASS and five real bugs found/fixed/re-verified in the process, per this task's explicit briefing. No further human verification items were identified by this pass.

### Gaps Summary

No blocking gaps found. All four requirement IDs (DASH-07, DASH-12, DASH-13, PLR-13) are implemented, wired, tested (473 Python tests + 317/319 dashboard tests, the 2 failures being pre-existing and unrelated), documented, and live-UAT-proven on the real deployment. The three code-review warnings (WR-01/WR-02/WR-03) are legitimate but non-blocking robustness/security-hygiene follow-ups, not goal-blocking gaps — recommended for backlog, not a required closure plan.

---

_Verified: 2026-09-23_
_Verifier: Claude (bm-verifier)_
