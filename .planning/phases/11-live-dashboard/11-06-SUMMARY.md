---
phase: 11-live-dashboard
plan: 06
subsystem: ui
tags: [vanilla-js, mqtt, pushstate-router, dashboard, dom]

# Dependency graph
requires:
  - phase: 11-live-dashboard (11-03)
    provides: index.html/devices.html/details.html shell markup, dashboard.css tokens/classes, the DOM id contract
  - phase: 11-live-dashboard (11-04)
    provides: staleness.js, display.js, grouping.js pure helpers
  - phase: 11-live-dashboard (11-05)
    provides: state-store.js (store), mqtt-connection.js (connection)
provides:
  - render-shell.js: connection indicator, poller-offline banner, tag-group-missing banner, grouped sidebar tree, always-mounted event history panel
  - shell.js: entry point wiring store/connection/shell together, pushState router swapping only #main
  - The ViewModules registration contract (mount/update/unmount) that 11-07 and 11-08 implement
affects: [11-07-index-and-devices-views, 11-08-details-view]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "renderShell exposes render*() methods only; shell.js owns all routing/wiring and calls into renderShell, never the reverse"
    - "Per-device patch-in-place: renderTreeDevice() replaces one row + patches its group header, never rebuilds the whole tree"
    - "pushState + popstate router keyed off location.pathname's filename, with click interception on [data-host] and same-origin <a> elements"

key-files:
  created:
    - dashboard/js/render-shell.js
    - dashboard/js/shell.js
  modified: []

key-decisions:
  - "Connection dot color is set via inline style (element.style.backgroundColor), not a `.state-*` class — dashboard.css's `.connection-dot` rule already sets background-color and would win over a same-specificity `.state-ok`-style sibling class on cascade order, silently breaking the color change"
  - "Poller-stale propagation to the tree is a full renderTree() on poller-status change only (not per device message) — infrequent event, correctness over micro-optimization"
  - "Event-row and state-chip markup (event-row, event-state-chip, event-transition, event-arrow, tree-group, tree-group-header, tree-host-row classes) has no CSS defined yet — explicitly left to Claude's Discretion per 11-CONTEXT.md ('Event-panel row formatting and timestamp rendering')"

patterns-established:
  - "Icon elements are built through a shared ensureIcon()/iconElement() helper that adds the icon class plus role=img/title/aria-label together, so no icon-only element can be created without its accessible name"

requirements-completed: [DASH-02, DASH-04, DASH-05, DASH-06]

# Metrics
duration: ~20min
completed: 2026-09-16
---

# Phase 11 Plan 06: Dashboard Shell Chrome and Router Summary

**Persistent shell chrome (connection indicator, both banners, grouped sidebar tree, event history) plus a pushState router that swaps only `#main`, keeping the event panel mounted across navigation.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-09-16
- **Tasks:** 2 completed
- **Files modified:** 2 (both newly created)

## Accomplishments
- `render-shell.js`: connection indicator covering all four DASH-05 phases (dot + text always paired, spinning `.icon-refresh` with a live per-second countdown during reconnect), the D-13/D-14 poller-offline banner and D-16 tag-group-missing banner with locked copy and KONE icons, the D-05/D-06/D-07/D-15 grouped sidebar tree (device_type/folder toggle persisted in `localStorage`, worst-of roll-up, stale hatch composition), and the always-mounted D-22/D-23 event history panel rendered newest-first.
- `shell.js`: single entry point registering `ViewModules`, subscribing to every `store` slot and fanning changes out to both the shell and the active view module's `update()`, wiring `connection.onStatus`/`connection.connect()` (called exactly once), and a `pushState`/`popstate` router that intercepts in-app anchor and `[data-host]` clicks so only `#main` swaps.
- Sanitizes the `?id=` query value (strips `+`, `#`, `/`) before it is ever used, per the T-11-17 mitigation.

## Task Commits

Each task was committed atomically:

1. **Task 1: dashboard/js/render-shell.js** - `241a3ad` (feat)
2. **Task 2: dashboard/js/shell.js — entry point and pushState router** - `c25051d` (feat)

**Plan metadata:** (pending — final docs commit follows this summary)

## Files Created/Modified
- `dashboard/js/render-shell.js` - Connection indicator, poller/tag-group banners, grouped sidebar tree, event panel; owns everything outside `#main`
- `dashboard/js/shell.js` - Entry point: store/connection wiring, `ViewModules` dispatch, pushState router

## Decisions Made
- Connection dot recoloring uses an inline `style.backgroundColor` set instead of a `.state-*` class, to sidestep a same-specificity CSS cascade conflict with `.connection-dot`'s own `background-color` rule in `dashboard.css` (documented inline in `render-shell.js`).
- `renderPollerBanner()` triggers a full `renderTree()` only when the poller-stale flag actually *changes* value (not on every poller-status message), since D-14's hatch must propagate to every row/group but a full tree rebuild is unnecessary on every unchanged reading.
- Event-row and tree-row/tree-group CSS classes (`event-row`, `event-state-chip`, `tree-group`, `tree-group-header`, `tree-host-row`, etc.) are new class names with no matching CSS yet — acceptable per 11-CONTEXT.md's "Claude's Discretion" list ("Event-panel row formatting and timestamp rendering"); they render unstyled-but-functional pending a future styling pass, which is out of this plan's `files_modified` scope (`dashboard/js/render-shell.js`, `dashboard/js/shell.js` only — no CSS file).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug avoidance] Reworded a comment to stop tripping the `innerHTML` acceptance grep**
- **Found during:** Task 1 verification
- **Issue:** The module's header comment explained the "never assign innerHTML" hard rendering rule by name, which made `grep -c 'innerHTML' dashboard/js/render-shell.js` return 1 instead of the required 0 — the check is a literal substring search with no awareness of comment-vs-code context.
- **Fix:** Reworded the sentence to describe the same rule ("never assign raw markup built from an interpolated string") without using the literal word `innerHTML`. No behavioral change; the prose is arguably just as clear.
- **Files modified:** `dashboard/js/render-shell.js` (comment only)
- **Verification:** `grep -c 'innerHTML' dashboard/js/render-shell.js` now returns `0`; the full verify harness (`node --check` + assertion script) still passes.
- **Committed in:** `241a3ad` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (comment wording only, per the "observed pattern worth avoiding" guidance — no code behavior was weakened to satisfy the grep)
**Impact on plan:** None on behavior. No scope creep.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The `ViewModules.index`/`ViewModules.devices`/`ViewModules.details` contract (`mount(mainEl, params)`, `update(changeKind, arg)`, `unmount()`) is defined and consumed by `shell.js`'s router; plans 11-07 (index/devices views) and 11-08 (details view) can implement against it directly.
- `renderShell.pollerStale` is exposed as a getter for the view modules to reuse the same D-14 hatch logic on their own rows/tiles.
- No blockers. This plan's automated verification (`node --check` plus both grep-assertion harnesses) is the only verification actually run in this environment — no browser, no live broker, and no podman stack were available to exercise the DOM/MQTT paths end-to-end. The acceptance criteria describing browser behavior ("Loaded in a browser with the broker stopped...", "clicking a host row...") were not executed against a real browser; they were validated by code review against the documented `connection.onStatus`/`store.subscribe` contracts only.

---
*Phase: 11-live-dashboard*
*Completed: 2026-09-16*

## Self-Check: PASSED

- FOUND: dashboard/js/render-shell.js
- FOUND: dashboard/js/shell.js
- FOUND commit: 241a3ad
- FOUND commit: c25051d
