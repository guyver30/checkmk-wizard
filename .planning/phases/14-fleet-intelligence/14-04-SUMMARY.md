---
phase: 14-fleet-intelligence
plan: 04
subsystem: dashboard
tags: [dashboard, incidents, kone-design-system, tree, topology-map]

requires:
  - phase: 14-fleet-intelligence (plan 14-02)
    provides: "Incident, selectOpenIncidents, buildIncidentLookup, formatIncidentDuration, consequenceSummary, incidentStatus from lib/incidents.ts; incidents store slice"
  - phase: 14-fleet-intelligence (plan 14-03)
    provides: "BuildTreeOptions.incidentLookup, TopologyMapProps.incidentLookup (dimming already wired, just needed a live lookup)"
provides:
  - "IncidentCard.tsx: one Message-based incident card (status/title/description/expand)"
  - "IncidentList.tsx: ordered card list, empty state, ?incident= highlight+scroll"
  - "IndexRoute.tsx: IncidentList mounted above StatsStrip; incidentLookup threaded into buildTree and TopologyMap, making DASH-15 dimming live end to end"
affects: [14-05]

tech-stack:
  added: []
  patterns:
    - "Message (kone-design-system) as the incident-card primitive, wrapped in a plain div carrying data-incident-id/data-status for test/DOM hooks the library itself doesn't expose"
    - "CSS.escape-guarded, try/catch-wrapped querySelector for a user-controllable ?incident= deep link (T-14-12)"

key-files:
  created:
    - dashboard-react/src/components/IncidentCard.tsx
    - dashboard-react/src/components/IncidentList.tsx
    - dashboard-react/src/components/IncidentList.test.tsx
  modified:
    - dashboard-react/src/routes/IndexRoute.tsx
    - dashboard-react/src/routes/IndexRoute.test.tsx

key-decisions:
  - "IncidentCard's expandable 'View devices' section and its nested Confirmed down/Not observable/Dependent devices groups render as <span> elements (not <div>), since Message's own description slot is a <p> and block elements would be invalid HTML nested inside it — an inline-safe structure avoids relying on React's direct-DOM (non-HTML-parsed) rendering as the only thing keeping the nesting valid"
  - "The wrapper div's data-status attribute (not a Message-internal class) is the stable test/inspection hook for status, since Message's compiled output ties status only to an internal icon-background class name, not a semantic attribute"

requirements-completed: [DASH-14, DASH-15]

duration: ~15min
completed: 2026-09-26
---

# Phase 14 Plan 04: Incident Card List and Live Dimming Wiring Summary

**`IncidentCard`/`IncidentList` render DASH-14's ordered, evidence-respecting incident cards above the stats strip, and `IndexRoute` now threads a live `incidentLookup` (derived from the `incidents` store slice) into both `buildTree` and `TopologyMap`, making the tree/map dimming plan 14-03 built now driven by real incident data end to end.**

## Performance

- **Duration:** ~15 min
- **Completed:** 2026-09-26
- **Tasks:** 2 completed
- **Files modified:** 5 (3 created, 2 modified)

## Accomplishments

- `IncidentCard.tsx`: a `Message`-wrapped card — `status` via `incidentStatus()` (danger only with confirmed-down evidence or a non-inferred DOWN root), title `"{rootLabel} — {duration}"` with an "Inferred, not confirmed" `Badge` when applicable, description with `consequenceSummary()` text and a criticality `Badge` (`neutral/outline` → `neutral/soft` → `purple/soft` → `purple/solid` for low/medium/high/critical, per the UI-SPEC's state-palette-independent palette), and a plain toggle button ("View devices") expanding confirmed-down/not-observable device links (to `/details?id=...`) plus a "Dependent devices: …" line when present. Never renders "not operating" (D-04).
- `IncidentList.tsx`: renders incidents in the order given (never re-sorts — that's `selectOpenIncidents`'s job), the locked empty-state copy when there are none, a `max-h-[35vh] overflow-y-auto` cap in the default (non-kiosk) layout with a `fill` variant for future kiosk use, and a `?incident=` deep-link highlight (ring class + one-time `scrollIntoView`, `CSS.escape`+try/catch guarded per threat T-14-12).
- `IndexRoute.tsx`: subscribes to the `incidents` store slice, derives `incidents = selectOpenIncidents(...)` and `incidentLookup = buildIncidentLookup(...)`, reads `?incident=` via `useSearchParams()`, mounts `<IncidentList>` as the new outermost-top element in `centreTop` (above `<StatsStrip>`), and passes `incidentLookup` into both the existing `buildTree(...)` call and `<TopologyMap>` — the dimming plan 14-03 built is now live, not just unit-tested against synthetic lookups.

## Task Commits

1. **Task 1: IncidentCard and IncidentList components** - `a50d148` (feat)
2. **Task 2: Wire incidents into IndexRoute** - `e65f41f` (feat)

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified

- `dashboard-react/src/components/IncidentCard.tsx` - one incident's card (new)
- `dashboard-react/src/components/IncidentList.tsx` - ordered list + empty state + highlight (new)
- `dashboard-react/src/components/IncidentList.test.tsx` - 12 tests covering every behavior bullet (new)
- `dashboard-react/src/routes/IndexRoute.tsx` - incident derivation, `IncidentList` mount, `incidentLookup` threading, updated D-25 comment
- `dashboard-react/src/routes/IndexRoute.test.tsx` - 4 new tests (DOM order, empty state, `?incident=` highlight, `TopologyMap` lookup wiring) plus an extended `TopologyMap` mock exposing `incidentLookup.size`

## Decisions Made

- Expandable device-group content inside `IncidentCard`'s `description` uses `<span>` wrappers throughout (never `<div>`), because `kone-design-system`'s `Message` renders `description` inside a `<p>` element and block-level children there would be invalid HTML content-model nesting — kept inline-safe rather than relying on React's direct-DOM rendering (which doesn't parse/auto-close HTML) papering over the mismatch.
- `data-status` on the card's own wrapper `<div>` (not a `Message`-internal selector) is the stable hook for asserting danger/warning — confirmed by reading the compiled `Message` output, which only exposes status via an internal icon-background class name (`iconBgClasses[status]`), not a semantic attribute or role.

## Deviations from Plan

None — plan executed exactly as written. No auto-fixes were required; the full test/typecheck/lint/build verification commands all passed on the first run after implementation.

## Issues Encountered

- `dashboard-react/node_modules` and `design-system/kone-design-system-0.1.0.tgz` were absent in this worktree (not shared across worktrees; the tarball is a gitignored build artifact). Copied the prebuilt tarball from the main checkout's `design-system/` directory and ran `npm install` before any test/typecheck/lint/build command, per the orchestrator's environment-setup instructions. Baseline `npm test` was confirmed 401/401 green before starting.
- No pre-existing failures found in the full suite at either the baseline or post-change checkpoint (417/417 passed after this plan's additions) — nothing new to log in `deferred-items.md`.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- DASH-14 (incident card list) and DASH-15 (live dimming end to end) are both implemented and unit-tested; plan 14-05's live verification checkpoint can now exercise the real MQTT-driven incident flow against this UI.
- `IncidentList`'s `fill` prop and the underlying components are ready for kiosk/wall mode (DASH-17) to reuse without modification, per the plan's stated purpose.

---
*Phase: 14-fleet-intelligence*
*Completed: 2026-09-26*
