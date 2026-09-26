---
phase: 14-fleet-intelligence
plan: 08
subsystem: dashboard
tags: [dashboard, checkmk-rest, labels, edit-mode, criticality]

requires:
  - phase: 14-fleet-intelligence (plan 14-02)
    provides: "CRITICALITY_TIERS/CriticalityTier/isCriticalityTier from lib/incidents.ts; TopologyNode.criticality/service_criticality/depends_on fields"
  - phase: 14-fleet-intelligence (plan 14-03)
    provides: "TopologyMap's editModeRef/onEditSavedRef pattern, click-handler gating on editMode"
  - phase: 14-fleet-intelligence (plan 14-05)
    provides: "live-verified label write path precedent (Phase 13 map_position/unmanaged_switch labels) this plan generalizes"
provides:
  - "checkmkWrite.ts: CRITICALITY_LABEL/SERVICE_CRITICALITY_LABEL/DEPENDS_ON_LABEL, shared updateLabels() GET->merge->PUT helper, setCriticality/setServiceCriticality/updateDependsOn writers, parse/format codecs for the service_criticality and depends_on label value formats"
  - "CriticalityEditor.tsx: edit-mode panel for host criticality, per-service criticality, and depends-on links, feeding the existing pendingCount/Apply flow"
  - "TopologyMap.tsx onSelectHost prop: a map-node click in edit mode selects a host for the panel instead of the old bare no-op"
  - "IndexRoute.tsx: mounts CriticalityEditor under TopologyToolbar while editing and configured; wires selectedHost/hostIds/serviceNames/nameFor"
affects: [14-09]

tech-stack:
  added: []
  patterns:
    - "Render-time prop->state reset (https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes) instead of a useEffect for CriticalityEditor's optimistic-state reset, to avoid oxlint's react(set-state-in-effect) warning while still resetting only on an actual value change, not on every re-render"

key-files:
  created:
    - dashboard-react/src/components/CriticalityEditor.tsx
    - dashboard-react/src/components/CriticalityEditor.test.tsx
  modified:
    - dashboard-react/src/lib/checkmkWrite.ts
    - dashboard-react/src/lib/checkmkWrite.test.ts
    - dashboard-react/src/components/TopologyMap.tsx
    - dashboard-react/src/components/TopologyMap.test.tsx
    - dashboard-react/src/routes/IndexRoute.tsx
    - dashboard-react/src/routes/IndexRoute.test.tsx

key-decisions:
  - "No per-field Set/Save button: every Select/MultiSelect change auto-writes immediately (optimistic local state), exactly like a map drag auto-writes; the one primary action remains 'Apply changes' (locked by the plan's own objective, D-06/D-07)"
  - "Depends-on removal confirms once per removed id inside a single MultiSelect onChange call; a declined confirm makes no write at all (not a partial write) and leaves local state untouched, so the declined id stays selected"

requirements-completed: [DASH-16]

duration: ~40min
completed: 2026-09-26
---

# Phase 14 Plan 08: Criticality and Dependency Editor Summary

**Operators can now set a host's business-criticality tier, per-service criticality, and depends-on links from the existing "Edit topology" mode — every field write goes through a new shared `updateLabels()` GET-merge-PUT helper in `checkmkWrite.ts` and feeds the same pending-changes counter and single "Apply changes" flow the map's own edits already use.**

## Performance

- **Duration:** ~40 min
- **Completed:** 2026-09-26
- **Tasks:** 2 completed
- **Files modified:** 8 (2 created, 6 modified)

## Accomplishments

- `checkmkWrite.ts`: `CRITICALITY_LABEL`/`SERVICE_CRITICALITY_LABEL`/`DEPENDS_ON_LABEL` constants; a private `updateLabels(host, mutate)` helper generalizing the GET→merge→PUT pattern (`setMapPosition` refactored onto it, behavior unchanged); exported `setCriticality`/`setServiceCriticality`/`updateDependsOn` writers, each synchronously validated (host name, tier vocabulary, service-name charset) before touching the network, and each wrapped in the existing `serialize()` write queue; exported pure codecs `parseServiceCriticalityLabel`/`formatServiceCriticality`/`parseDependsOnLabel`/`formatDependsOn` mirroring the poller's label format (`name=tier;name=tier`, `host,host`) byte-for-byte per the plan's locked label contract.
- `CriticalityEditor.tsx`: a collapsible "Criticality & dependencies" panel — a "Device" `Select` (works with or without a host selected), then once a host is selected: "Host criticality" `Select` (Low/Medium/High/Critical), one "Per-service criticality" row per service (union of the store's service rows and any stale `service_criticality` key so a stale entry can still be cleared), and a "Depends on" `MultiSelect`. Every change is optimistic (updates local state immediately) and best-effort against the network — a failed write reverts the optimistic value and calls the same "Couldn't save that" failure copy Phase 13's map edits use. Removing a depends-on link confirms via `window.confirm` with the exact UI-SPEC copy; a declined confirm makes no write and leaves the link selected.
- `TopologyMap.tsx`: new optional `onSelectHost?: (id: string) => void` prop, read through a ref like the existing `onEditSaved`/`onEditFailed` pattern; a node click while `editMode` is on now calls `onSelectHost` instead of silently no-op'ing.
- `IndexRoute.tsx`: new `selectedHost` state (reset to `null` when edit mode turns off), `hostIds`/`selectedNode`/`serviceNames`/`nameFor` derivations, and `CriticalityEditor` mounted between `TopologyToolbar` and the map container, shown only while `editMode && isTopologyEditingConfigured()`; its `onSaved`/`onFailed` are the same `onEditSaved`/`onEditFailed` callbacks the map already uses, so a criticality edit increments the identical "N change(s) not yet applied" banner.

## Task Commits

1. **Task 1: Label write helpers in checkmkWrite.ts** - `0fc4e26` (feat)
2. **Task 2: CriticalityEditor panel, map host selection in edit mode, IndexRoute wiring** - `c09248e` (feat)

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified

- `dashboard-react/src/lib/checkmkWrite.ts` - label constants, `updateLabels` helper, `setCriticality`/`setServiceCriticality`/`updateDependsOn`, codecs; `setMapPosition` refactored onto `updateLabels`
- `dashboard-react/src/lib/checkmkWrite.test.ts` - 20 new tests covering every Task 1 behavior bullet (validation-before-fetch, label merge/deletion, sort order, serialize-queue ordering)
- `dashboard-react/src/components/CriticalityEditor.tsx` - the edit-mode panel (new)
- `dashboard-react/src/components/CriticalityEditor.test.tsx` - 11 tests covering selection, prefill, write/revert-on-failure, service-row union, and depends-on add/remove-with-confirm (new)
- `dashboard-react/src/components/TopologyMap.tsx` - `onSelectHost` prop and ref, click-handler wiring
- `dashboard-react/src/components/TopologyMap.test.tsx` - 2 new tests (calls `onSelectHost` in edit mode, does not call it outside edit mode)
- `dashboard-react/src/routes/IndexRoute.tsx` - `selectedHost` state, `hostIds`/`selectedNode`/`serviceNames`/`nameFor` derivations, `CriticalityEditor` mount
- `dashboard-react/src/routes/IndexRoute.test.tsx` - 3 new tests (panel absent with edit mode off, panel + host selection via the map, a successful editor write increments the shared pending-count banner)

## Decisions Made

- No per-field Set/Save button anywhere in the panel — every field change writes immediately (optimistic), and the only primary action stays the pre-existing "Apply changes" button; this was locked by the plan's own objective (D-06/D-07) and verified by an acceptance-criteria grep (`<Button` count 0, `Apply changes` text count 1 — only inside the depends-on removal confirm text).
- `CriticalityEditor`'s optimistic-state reset (when the selected host changes, or the topology's own persisted values for it change) is implemented as a render-time comparison rather than a `useEffect`, per React's own "adjusting state when a prop changes" guidance — this also avoids oxlint's `set-state-in-effect` warning that a straightforward `useEffect(() => setState(...), [deps])` triggered here (the very first version of this file was fixed this way; see Deviations).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Own render-time reset introduced a first-mount bug where seeded initial state was never applied**
- **Found during:** Task 2 verification (`npm test -- src/components/CriticalityEditor.test.tsx`)
- **Issue:** After switching the optimistic-state reset from a `useEffect` to a render-time `if (resetKey !== lastResetKey)` comparison (to satisfy oxlint's `set-state-in-effect` warning), the `lastResetKey` state was itself initialized from the same `resetKey` computed on the very first render, so the comparison was always false on mount and the panel's `criticality`/`serviceCriticality`/`dependsOn` state stayed at their hardcoded defaults (`"low"`/`{}`/`[]`) instead of the node's real values.
- **Fix:** Seeded the three `useState` calls directly from the derived `nodeCriticality`/`nodeServiceCriticalityKey`/`nodeDependsOnKey` values (via a lazy initializer for the two JSON-parsed ones), so the first render already reflects the node's real values; the render-time comparison now only ever fires on a later prop change, as intended.
- **Files modified:** `dashboard-react/src/components/CriticalityEditor.tsx`
- **Verification:** `npm test -- src/components/CriticalityEditor.test.tsx` — 11/11 passed; full suite re-run 467/467 passed afterward.
- **Committed in:** `c09248e` (part of Task 2 commit — found and fixed before the commit, not a follow-up)

---

**Total deviations:** 1 auto-fixed (Rule 1, a bug in this plan's own new code, fixed before commit). No scope creep — the fix only touched the file this plan already creates.

## Issues Encountered

- `dashboard-react/node_modules` and `design-system/kone-design-system-0.1.0.tgz` were absent in this worktree (not shared across worktrees; the tarball is a gitignored build artifact). Copied the prebuilt tarball from the main checkout's `design-system/` directory and ran `npm install` before any test/typecheck/lint/build command, per the orchestrator's environment-setup instructions. Baseline `npm test` was confirmed 433/433 green before starting (matching the stated baseline).
- `scripts/mqtt_poller.py`'s own criticality/depends_on label-reading side (plan 14-07) had not yet landed in this worktree when this plan ran (14-07 executes in parallel, on poller files this plan never touches) — the label byte-for-byte contract (`criticality`/`service_criticality`/`depends_on` keys, `name=tier;name=tier` and `host,host` value formats, tier vocabulary) was taken directly from the plan's own `<interfaces>` block rather than read from the poller source, since that source wasn't authoritative yet in this worktree. No other deviation resulted from this — the contract described in the plan was precise enough to implement and test against directly.
- No pre-existing failures found in the full suite at either the baseline or the post-change checkpoint (467/467 passed after this plan's additions) — nothing new to log in `deferred-items.md`.

## User Setup Required

None — no external service configuration required. The panel reuses the existing `topology_editor` credential and `isTopologyEditingConfigured()` gate; no new Checkmk permission is requested (per the plan's own threat-model disposition T-14-25).

## Assumption Drift (advisory)

None — implementation matched the plan's `<action>` prose and the UI-SPEC's locked copy/behavior throughout; no material drift to record.

## Next Phase Readiness

- DASH-16 is implemented and unit-tested (checkmkWrite writers, panel behavior, map selection, route wiring); plan 14-09's live-verification checkpoint can now exercise the real round-trip (write a criticality/dependency label from the browser, Apply, confirm the poller picks it up and republishes `worst_criticality`/`dependents` — plan 14-07's consumer side) against a live Checkmk site.
- The label contract this plan implements client-side (`criticality`/`service_criticality`/`depends_on` keys and value formats) must still be live-verified byte-for-byte against plan 14-07's poller-side parsers once both land on the same branch — flagged here since 14-07 ran in parallel and wasn't available to cross-check against directly during this plan's execution.

---
*Phase: 14-fleet-intelligence*
*Completed: 2026-09-26*

## Self-Check: PASSED

All created/modified files verified present (`checkmkWrite.ts`, `checkmkWrite.test.ts`,
`CriticalityEditor.tsx`, `CriticalityEditor.test.tsx`, `TopologyMap.tsx`, `TopologyMap.test.tsx`,
`IndexRoute.tsx`, `IndexRoute.test.tsx`); both task commits (`0fc4e26`, `c09248e`) verified present
in `git log --oneline --all`; full `npm test` suite 467/467 passed, `npm run typecheck` exit 0,
`npm run lint` exit 0 (pre-existing warnings only, no new ones), `npm run build` exit 0.
