---
phase: 11-live-dashboard
plan: 04
subsystem: ui
tags: [dashboard, staleness, grouping, worst-of, kone-icons, pure-functions]

# Dependency graph
requires:
  - phase: 11-live-dashboard (plan 01)
    provides: "lan/devices/{id}/status.staleness and .host_state_raw fields on the MQTT payload"
  - phase: 11-live-dashboard (plan 02)
    provides: "dashboard/js/config.js globals (POLL_INTERVAL_SECONDS, STALENESS_FACTOR, HISTORY_MAX_ENTRIES)"
provides:
  - "isDeviceStale(), isPollerStale(), pollerOfflineSince() (dashboard/js/staleness.js)"
  - "displayName(), effectiveState(), stateClass(), stateIcon(), deviceTypeIcon(), isTagGroupMissing(), formatRelativeTime(), formatClock() (dashboard/js/display.js)"
  - "SEVERITY_RANK, groupKeyFor(), buildGroupIndex(), rollUpGroup(), sortedGroupKeys() (dashboard/js/grouping.js)"
affects: ["11-06 (shell/render modules that consume these pure functions)"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure classic-script modules defining only top-level functions/consts as globals, no DOM/localStorage/MQTT/fetch access, verifiable from a plain node vm.runInThisContext harness"
    - "Prefer-authoritative-value-with-fallback: Checkmk's own staleness value is trusted first, timestamp-age comparison is the fallback path, both exercised by tests"
    - "groupKey -> Set<hostname> index built once per topology/mode change rather than recomputed per message, to avoid an O(fleet) scan per incoming status update"

key-files:
  created:
    - dashboard/js/staleness.js
    - dashboard/js/display.js
    - dashboard/js/grouping.js
  modified: []

key-decisions:
  - "D-17's staleness column is confirmed present on the live site (wave-1 probe result), but isDeviceStale() still implements and exercises the timestamp-age fallback branch as a required path, not dead code, per the upstream instruction not to weaken it on the strength of the probe"

patterns-established:
  - "Pattern 1 (staleness.js): prefer-authoritative-value-with-fallback for any future Checkmk-sourced field that has a browser-side derived equivalent"
  - "Pattern 2 (grouping.js): maintain a secondary group-membership index instead of filtering the full device map per message"

requirements-completed: [DASH-04, DASH-06]

# Metrics
duration: ~25min
completed: 2026-09-16
---

# Phase 11 Plan 04: Staleness, display and grouping pure-function modules Summary

Three classic-script modules with zero DOM/MQTT/storage access — `staleness.js` prefers Checkmk's own `staleness` value with a required timestamp-age fallback, `display.js` derives UNREACH from `host_state_raw` (never from `state`) and maps state/device-type to the locked KONE icon class names, and `grouping.js` implements the worst-of group roll-up that excludes stale children from the color computation while still marking the group hatched.

## Performance

- **Duration:** ~25 min
- **Started:** 2026-09-16 (session start)
- **Completed:** 2026-09-16T03:09:35Z
- **Tasks:** 2
- **Files modified:** 3 (all newly created)

## Accomplishments
- `staleness.js`: `isDeviceStale()` compares Checkmk's own `staleness` value against `STALENESS_FACTOR` when present, and falls back to `(now - timestamp)` age against the same factor when it is null/undefined — both paths are exercised by the verify harness, not just the preferred one. `isPollerStale()` treats an absent payload or `status: "offline"` as stale immediately (LWT case), treats a null `last_poll` as "not yet stale" (birth message), and otherwise applies the same factor to `last_poll` age. `pollerOfflineSince()` returns the Date for D-14's banner string.
- `display.js`: `displayName()` implements D-18's alias-else-hostname preference (trimming whitespace-only aliases to empty). `effectiveState()` returns `"UNREACH"` only when `host_state_raw === "UNREACH"`, documented against Pitfall 6 (the `state` field structurally cannot contain `"UNREACH"` because `compute_overall_state()` in `scripts/mqtt_poller.py` collapses raw host states 1/2 into `"DOWN"`). `stateIcon()`/`deviceTypeIcon()` return only the locked KONE `.icon-*` class name strings from the plan's interfaces block — no emoji anywhere. `formatRelativeTime()`/`formatClock()` degrade to a neutral placeholder instead of `NaN` on unparseable input.
- `grouping.js`: `SEVERITY_RANK` mirrors `compute_overall_state()`'s worst-of ordering with a comment stating the two tables must be kept in step by hand. `groupKeyFor()` supports `"folder"` and `"device_type"` (default) modes, collapsing `device_type: "unknown"` to a single `"untyped"` group per D-16. `buildGroupIndex()` builds a `groupKey -> Set<hostname>` index once per topology/mode change rather than per message (Pitfall 5), with a comment stating why. `rollUpGroup()` skips stale children in the worst-of computation but still sets `hatched = true`, so a group with 1 CRIT + 3 stale children renders both facts (worst = CRIT, hatched = true) simultaneously (D-15); it reads `effectiveState()`, never the raw `state` key, so UNREACH ranks correctly (rank 3, same as CRIT) instead of collapsing into DOWN.
- Every function in all three modules tolerates a missing/malformed payload (no `staleness`, no `host_state_raw`, missing `timestamp`, non-iterable `deviceIds`, etc.) and returns a safe default instead of throwing.

## Task Commits

Each task was committed atomically:

1. **Task 1: dashboard/js/staleness.js and dashboard/js/display.js** - `4e2fafc` (feat)
2. **Task 2: dashboard/js/grouping.js** - `3e43827` (feat)

**Plan metadata:** (this commit, made after this SUMMARY.md)

## Files Created/Modified
- `dashboard/js/staleness.js` - `isDeviceStale()`, `isPollerStale()`, `pollerOfflineSince()` — D-12/D-13/D-14/D-17 staleness derivation
- `dashboard/js/display.js` - `displayName()`, `effectiveState()`, `stateClass()`, `stateIcon()`, `deviceTypeIcon()`, `isTagGroupMissing()`, `formatRelativeTime()`, `formatClock()` — D-16/D-18/Pitfall 6 display and classification helpers
- `dashboard/js/grouping.js` - `SEVERITY_RANK`, `groupKeyFor()`, `buildGroupIndex()`, `rollUpGroup()`, `sortedGroupKeys()` — D-05/D-06/D-07/D-15/D-16 grouping and worst-of roll-up

## Decisions Made
- Kept the timestamp-age fallback branch in `isDeviceStale()` fully implemented and asserted by the verify harness even though wave-1's live probe confirmed the `staleness` column is present on the target site — the probe proved the column exists, not that every row is always non-null, per the explicit upstream instruction not to weaken or skip the fallback on the strength of that result.
- Worded the "no DOM/MQTT/storage/fetch access" header comments to avoid literally containing the substrings `document.`, `window.`, `localStorage`, `mqtt.`, or `fetch(`, since the acceptance-criteria grep for those patterns matches comment text as well as code — the comments now describe the same guarantee without the literal trigger strings.

## Deviations from Plan

None — plan executed exactly as written. One self-correction during Task 1: an initial draft of `display.js` included the literal `⛔` character (in a comment noting it is superseded) and a "no DOM/MQTT/localStorage/fetch" comment whose own wording contained the substring `localStorage`, both of which tripped the task's own acceptance-criteria greps (`grep -c '⛔'` and the DOM/MQTT/storage/fetch grep respectively). Both were caught by running the acceptance criteria immediately after writing the files, fixed by rewording, and re-verified before committing — no plan-level scope change, just getting the acceptance greps to pass on the first committed version.

## Issues Encountered
None beyond the self-correction above, which was resolved before any commit was made.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `dashboard/js/staleness.js`, `dashboard/js/display.js` and `dashboard/js/grouping.js` are ready for plan 11-06's render/shell modules to consume as globals (classic scripts, no module system).
- These three modules are pure and have no dependency on `dashboard/js/state-store.js` or `dashboard/js/mqtt-connection.js`, which plan 11-05 is building concurrently in a sibling worktree — no merge conflicts expected at the file level, and no import/call dependency exists in either direction.
- No blockers for wave 3.

---
*Phase: 11-live-dashboard*
*Completed: 2026-09-16*
