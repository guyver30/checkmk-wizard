---
phase: 11-live-dashboard
verified: 2026-10-12T16:40:00Z
status: gaps_found
score: 6/8 must-haves verified
has_blocking_gaps: true
overrides_applied: 0
gaps:
  - truth: "DASH-02: a live sortable device table plus a recent-events panel, updating in place (originally devices.html)"
    status: failed
    severity: blocking
    reason: "No device table exists in the shipped React SPA. The /devices route and DevicesRoute.tsx were removed on 2026-09-25 by quick 260925-p7d (operator-directed 'Remove the Devices nav item/route'). The recent-events half survives (EventHistory pane); the sortable table half has no implementation anywhere in dashboard-react/src. REQUIREMENTS.md still lists DASH-02 as unchecked/Pending with no descoping or re-wording note, so the removal was never reconciled with the requirement."
    artifacts:
      - path: "dashboard-react/src/App.tsx"
        issue: "Route tree is only '/', '/details' (redirect to /?host=) and '*'; no /devices route, no Devices nav item"
      - path: ".planning/REQUIREMENTS.md"
        issue: "DASH-02 (line 50, table line 134) still Pending; no supersession note"
    missing:
      - "Either re-word/descope DASH-02 in REQUIREMENTS.md (operator decision) or accept an override; the device tree plus per-host details pane is the de-facto replacement"
  - truth: "DASH-03: per-device drill-down with a bounded status-history strip and a link out to Checkmk's own UI for that host"
    status: partial
    severity: minor
    reason: "Drill-down exists (HostDetails, ?host= pane). The dedicated status-history strip no longer exists: the dashboard history/serviceHistory slices were removed by quick 261004-kbt (ClickHouse is now the only transition history); the pane shows a bounded per-host filter of lan/events/recent plus metric/forecast history dialogs instead. The Checkmk link-out half was declined by Phase 12 D-17 and is still absent (CHECKMK_BASE_URL / isCheckmkLinkConfigured no longer appear anywhere in dashboard-react/src outside tests). Known and recorded as Partial in REQUIREMENTS.md; Phase 12 owns the history-strip half."
    artifacts:
      - path: "dashboard-react/src/components/HostDetails.tsx"
        issue: "No Checkmk link-out; no status-history strip"
    missing:
      - "Link out to the host's Checkmk page (deferred by 12 D-17, no later phase claims it)"
deferred: []
human_verification:
  - test: "Stop the poller container (or publish an offline will on sites/<site>/lan/poller/status) with the dashboard open and connected"
    expected: "A warning banner 'Poller offline since HH:MM — device states may be out of date' appears above the map; devices flip to STALE once their staleness exceeds the factor; banner disappears when the poller returns"
    why_human: "Banner is unit/route-tested only; no live run of the restored banner has been recorded"
  - test: "Restart the mosquitto container while the dashboard is open"
    expected: "Header indicator goes to 'Reconnecting in Ns...' with growing, jittered delays (about 1s, 2s, 4s ... capped at 30s) and returns to 'Connected' with the retained state repopulated"
    why_human: "Backoff arithmetic and state machine are unit-tested with injected random/timers; no recorded live run against a real broker"
---

# Phase 11: Live Dashboard Verification Report

**Phase Goal:** A static, backend-less dashboard renders live Checkmk-derived topology, device status, and history purely by consuming the poller's MQTT contract
**Verified:** 2026-10-12T16:40:00Z
**Status:** gaps_found
**Re-verification:** No - initial verification (first VERIFICATION.md for this phase; the 2026-10-12 milestone audit flagged it missing)

## Context: what Phase 11.1 superseded

Phase 11 was built as a vanilla-JS, three-page site (`dashboard/index.html`, `devices.html`, `details.html`, hand-rolled `shell.js`/`render-*.js`, vendored mqtt.js). Phase 11.1 (D-40..D-46) rewrote it as the React + TypeScript + Tailwind SPA in `dashboard-react/` and the vanilla `dashboard/` directory no longer exists in the tree. nginx (`deploy/dashboard-nginx.conf`) serves the SPA with a `try_files ... /index.html` fallback. Consequently every Phase 11 UI artifact is superseded; this report judges each requirement against the CURRENT code only.

| Phase 11 artifact / decision | Fate |
|---|---|
| `dashboard/js/render-index.js` grouped fleet overview (D-24) | Deleted (11.1 D-27); centre is now the topology map (Phase 13) |
| `dashboard/js/render-devices.js` + `devices.html` (DASH-02) | Not ported to React as a feature; `/devices` route added in 11.1-04 then removed 2026-09-25 (quick 260925-p7d). **Gap below** |
| `dashboard/js/render-details.js` + `details.html` (DASH-03) | Replaced by `HostDetails.tsx` in the `?host=` pane (quick 260928-l4h); `/details?id=` redirects |
| `dashboard/js/staleness.js`, `display.js`, `grouping.js` | Ported line-for-line to `src/lib/{staleness,display,grouping}.ts` (11.1-05) |
| `dashboard/js/mqtt-connection.js` hand-rolled backoff | Re-implemented in `src/store/mqttClient.ts` (11.1-05) |
| `render-shell.js` poller-offline banner (D-13/D-14) | Dropped in the 11.1 port; **restored 2026-10-12 by quick 261012-pst** (see truth 6 caveat) |
| Dark theme (D-22), grouped overview (D-24), dashboard.css | Formally superseded in `11-CONTEXT.md` by 11.1 D-36 |
| Per-device `history` / `service_history` MQTT topics (11-01/11-08 history strip data) | Retired by quick 261004-kbt (ClickHouse is the only history) |

Poller-side Phase 11 work (plan 11-01: additive `staleness` + `host_state_raw`) is not superseded and still stands.

## Goal Achievement

### Observable Truths

| # | Truth (source) | Status | Evidence |
|---|----------------|--------|----------|
| 1 | Counts-by-state strip, hosts merged in place without full re-render (SC1, DASH-01 re-worded) | VERIFIED | `StatsStrip.tsx` + `HeaderStats` (mounted in `App.tsx` `NavBar navExtra`, since 2026-09-28 header badges rather than tiles above the map); counts from `store/selectors.ts::makeSelectStateCounts` over `useAppStore().devices`, STALE counted separately; per-message update replaces one device slot; `StaleStability.test.tsx` proves DOM node identity survives. Placement moved from "above the primary view" to the header by operator request; strip + merge-in-place clauses hold |
| 2 | Hosts icon-coded by device type and grouped/coloured by folder-derived label or device type, runtime toggle (SC1, DASH-06) | VERIFIED | `TreeNode.tsx` renders `deviceTypeMaskUrl` icon + `StateBadge`; `grouping.ts::groupKeyFor` supports type and folder; `GroupingControls.tsx` select + severity checkbox; `Tree.test.tsx`, `treeModel.test.ts`, `grouping.test.ts`, `GroupingControls.test.tsx` pass |
| 3 | `devices.html`-equivalent: live sortable device table + recent-events panel (SC2, DASH-02) | FAILED | No table component, no `/devices` route (`App.tsx` routes: `/`, `/details`, `*`). Recent-events panel exists (`EventHistory.tsx`, newest-first, in the centre-bottom pane) so only half is met. Removed by operator-directed quick 260925-p7d, but REQUIREMENTS.md never reconciled |
| 4 | Per-device drill-down with bounded status-history strip and a link out to Checkmk (SC3, DASH-03) | PARTIAL | Drill-down: `HostDetails.tsx` (gauges, services, needs, trends) in the `?host=` pane. History: `EventHistory hostId=` shows that host's bounded events from `lan/events/recent`; the dedicated strip and `history` store slice are gone (quick 261004-kbt). Link-out: absent (declined 12 D-17). Consistent with REQUIREMENTS.md "Partial" |
| 5 | A device past the staleness threshold shows a distinct stale/unknown state separate from DOWN (SC4 first half, DASH-04) | VERIFIED | `lib/staleness.ts::isDeviceStale` (prefers Checkmk `staleness` x STALENESS_FACTOR, falls back to timestamp age); consumed by `StateBadge.tsx`, `selectors.ts`, `grouping.ts`; `stateMapping.ts` gives STALE a neutral/outline/clock look distinct from UNKNOWN and DOWN; `staleness.test.ts`, `StateBadge.test.tsx`, `StaleStability.test.tsx` pass |
| 6 | Poller's own liveness signal (`lan/poller/status`) stale/offline is surfaced (SC4 second half DASH-04, and the banner half of DASH-05) | VERIFIED (code + tests, UNCOMMITTED) | At verification time `components/PollerOfflineBanner.tsx` (+ test) is an untracked file and `IndexRoute.tsx`/`IndexRoute.test.tsx` carry uncommitted modifications (quick 261012-pst in flight; `git status` shows `??`/` M`). It reads `pollerStatus`, `lastKnownPollerTimestamp`, connection phase; shows when `isPollerStale()`; suppressed while MQTT is disconnected; mounted at `IndexRoute.tsx:392` above `DiscoveredHostsBanner`; `lan/poller/status` is subscribed (`topics.ts:17`) and stored (`useAppStore.ts:298`). 9 test files / 103 tests pass including `PollerOfflineBanner.test.tsx` and the `IndexRoute poller offline banner` suite. **Must be committed for this to be durable**; before this working-tree change the half was a genuine gap (`isPollerStale`/`pollerOfflineSince` had no runtime caller, per the milestone audit) |
| 7 | Connection-status indicator and jittered exponential-backoff reconnect (SC5, DASH-05) | VERIFIED | `ConnectionIndicator.tsx` (connected / reconnecting-in-Ns / disconnected / connecting) mounted in `NavBar actions`; `mqttClient.ts` sets `reconnectPeriod: 0` and schedules `min(30000, 1000 * 2**attempt) * (0.5 + rand*0.5)`, resets on connect; singleton guard against StrictMode double-connect; `mqttClient.test.ts`, `ConnectionIndicator.test.tsx` pass |
| 8 | Poller contract carries `staleness` and `host_state_raw` for DASH-04 (plan 11-01, D-17) | VERIFIED | `scripts/mqtt_poller.py:268-275` (`staleness` in OPTIONAL_HOST_COLUMNS), `:586` `staleness`, `:592` `host_state_raw`; live `--check-columns` probe on the deploy host recorded PRESENT in `11-01-SUMMARY.md` (operator-supplied, not sandbox) |

**Score:** 6/8 truths verified (truth 3 failed, truth 4 partial)

### Required Artifacts (current tree)

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `dashboard-react/src/components/StatsStrip.tsx` | counts-by-state | VERIFIED | Wired via `HeaderStats` in `App.tsx` |
| `dashboard-react/src/components/Tree.tsx`, `TreeNode.tsx`, `lib/treeModel.ts`, `lib/grouping.ts` | grouped, icon-coded tree | VERIFIED | Wired in `IndexRoute.tsx` |
| `dashboard-react/src/components/EventHistory.tsx` | recent events | VERIFIED | Newest-first, host filter, date-range filter |
| `dashboard-react/src/components/HostDetails.tsx` | drill-down | VERIFIED (partial vs DASH-03 text) | No link-out, no status-history strip |
| Device table component / `/devices` route | DASH-02 | MISSING | Removed 2026-09-25 |
| `dashboard-react/src/lib/staleness.ts` | staleness derivation | VERIFIED | Both device and poller functions now have runtime callers |
| `dashboard-react/src/components/PollerOfflineBanner.tsx` | poller-offline banner | VERIFIED but untracked | Uncommitted at verification time |
| `dashboard-react/src/store/mqttClient.ts`, `components/ConnectionIndicator.tsx` | backoff + indicator | VERIFIED | |
| `deploy/dashboard-nginx.conf` | static serving, SPA fallback | VERIFIED | `location / { try_files $uri $uri/ /index.html; }`; `/config.json` runtime config |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `App.tsx` | `mqttClient.connect()` | mount effect, module singleton | WIRED | |
| `mqttClient.ts` | `useAppStore.handleMessage` | `client.on('message')` after site-prefix strip | WIRED | non-site topics dropped |
| `useAppStore` (`pollerStatus`) | `PollerOfflineBanner` | selector | WIRED | working tree only |
| `useNowTick` | `selectors`/`StateBadge`/banner | `nowMs` threaded from `IndexRoute` | WIRED | single periodic clock |
| `HostDetails` | Checkmk UI | link-out | NOT_WIRED | deliberately declined (12 D-17) |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `StatsStrip` | `counts` | `useAppStore.devices` <- `lan/devices/+/status` retained | Yes | FLOWING |
| `Tree` | `groups` | `buildTree(devices, ...)` | Yes | FLOWING |
| `EventHistory` | `events` | `lan/events/recent` | Yes | FLOWING |
| `PollerOfflineBanner` | `pollerStatus` | `lan/poller/status` (poller birth/heartbeat/LWT) | Yes | FLOWING |
| `ConnectionIndicator` | `connection` | mqtt.js lifecycle events | Yes | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase-relevant React tests | `npx vitest run src/components/PollerOfflineBanner.test.tsx src/routes/IndexRoute.test.tsx src/lib/staleness.test.ts src/store/mqttClient.test.ts src/components/ConnectionIndicator.test.tsx src/components/StatsStrip.test.tsx src/components/EventHistory.test.tsx src/lib/grouping.test.ts src/components/StaleStability.test.tsx` | 9 files, 103 tests passed | PASS |
| Tree / details / tree model | `npx vitest run src/components/Tree.test.tsx src/components/HostDetails.test.tsx src/lib/treeModel.test.ts` | 3 files, 70 tests passed | PASS |
| Full suite / poller pytest / build | not re-run in this verification | - | SKIP |

### Probe Execution

SKIPPED: Phase 11 declares no probe scripts.

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|--------------|-------------|--------|----------|
| DASH-01 | 11-04, 11-06, 11-07 (rebuilt 11.1-07) | Stats strip of counts by state, merged in place; primary view is the map (DASH-07, Phase 13) | SATISFIED | Truth 1. Wording is re-worded (2026-09-16 note); strip now sits in the header, map owns the centre (Phase 13) |
| DASH-02 | 11-07 | Live sortable device table + recent-events panel | BLOCKED | Truth 3: table removed, events panel only. Needs an operator decision (descope/override) |
| DASH-03 | 11-08 (+ 12-04) | Drill-down with bounded status-history strip, link out to Checkmk | PARTIAL (by design) | Truth 4. Not to be flipped to Complete; history-strip half is now served by per-host events + ClickHouse dialogs, link-out half still open |
| DASH-04 | 11-01, 11-04, 11-06 | Distinct stale/unknown state when last-seen exceeds threshold or poller liveness is stale | SATISFIED (poller half uncommitted) | Truths 5, 6, 8 |
| DASH-05 | 11-05, 11-06 | Connection indicator + jittered exponential-backoff reconnect | SATISFIED | Truth 7; banner is truth 6 (it belongs to SC4/D-13 rather than the connection indicator itself) |
| DASH-06 | 11-04, 11-06 | Colour/icon by device type; group/colour by folder-derived label | SATISFIED | Truth 2 |

No orphaned requirements: ROADMAP lists DASH-01..06 and every plan frontmatter claims a subset. DASH-07 belongs to Phase 13 (split note 2026-09-12); DASH-08..09 belong to Phase 12.

### Anti-Patterns Found

None blocking. `dashboard-react/src` scanned for TBD/FIXME/XXX in files this phase's requirements touch: no unreferenced markers.

### Live vs code-only evidence

- Live: plan 11-01 staleness column probe on the real Checkmk site (operator-run). Later phases (12-14.x) and the milestone audit ran the React SPA against a real broker/poller, so the tree, event pane and indicator have been exercised in practice, but no document records a live check of reconnect backoff behaviour or of the poller-offline banner.
- Code/test only: everything else. Phase 11's own live checkpoint (11-09 Task 2) was never completed (summary is PAUSED, sandbox had no podman/browser) and its vanilla artifacts were replaced; 11.1-11 explicitly deferred "Connected" state and live event ordering to a real deployment.
- Consequently the two human-verification items in the frontmatter remain open but non-blocking.

### Human Verification Required

1. **Poller offline banner (live)** - stop the poller, observe banner and STALE flips, restart and observe recovery. Why human: no live run recorded.
2. **Broker restart / backoff (live)** - restart mosquitto with the dashboard open, observe "Reconnecting in Ns" delays growing and jittered and recovery to "Connected".

### Gaps Summary

One real gap and one known partial:

1. **DASH-02 is not met** (blocking by the default rule). The sortable device table was deliberately removed on 2026-09-25 (quick 260925-p7d) because the tree + host details pane replaced it, but the requirement text was never amended. This looks intentional. To accept it, add to this file's frontmatter (or amend REQUIREMENTS.md):

```yaml
overrides:
  - must_have: "DASH-02: a live sortable device table plus a recent-events panel, updating in place"
    reason: "Devices route removed by operator in quick 260925-p7d; device tree + per-host details pane + EventHistory replace it"
    accepted_by: "<operator>"
    accepted_at: "<ISO timestamp>"
```

2. **DASH-03 remains Partial** by decision (12 D-16/D-17); the Checkmk link-out has no owner in any later phase. Minor.

3. **Housekeeping:** the poller-offline banner (the previously open DASH-04/05 half) is present and passing tests in the working tree but is uncommitted. If quick 261012-pst is reverted or never committed, truth 6 reverts to FAILED. REQUIREMENTS.md traceability (DASH-04/05 still Pending, DASH-01 `[x]`, DASH-03 `[x]` in the checklist but Partial in the table) is stale and should be reconciled by the orchestrator, not by this verifier.

---

_Verified: 2026-10-12T16:40:00Z_
_Verifier: Claude (bm-verifier)_
