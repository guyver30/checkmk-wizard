---
phase: 14-fleet-intelligence
plan: 06
subsystem: dashboard
tags: [dashboard, kiosk, fullscreen, react-router]

requires:
  - phase: 14-fleet-intelligence (plan 14-04)
    provides: "IncidentList.tsx with a fill prop, built for kiosk reuse without modification"
provides:
  - "hooks/useKioskRotation.ts: KIOSK_ROTATION_MS = 20000, useKioskRotation() -> { view, cycle }, the second sanctioned periodic timer, mounted only under ?kiosk=1"
  - "routes/KioskView.tsx: full-bleed, chrome-free, auto-rotating, read-only incidents/topology view for unattended signage"
  - "App.tsx AppShell(): ?kiosk=1 rendering-mode branch on the existing / route, no new route path"
affects: []

tech-stack:
  added: []
  patterns:
    - "Second sanctioned periodic timer (useKioskRotation), gated so it only ever mounts under ?kiosk=1 -- useNowTick's own header comment ('the app's only periodic timer') is not violated because the two never coexist on the same route"
    - "Kiosk is a rendering mode of the existing / route (App.tsx AppShell), not a parallel route/page -- avoids a second incident/map implementation that could drift from the operator view"

key-files:
  created:
    - dashboard-react/src/hooks/useKioskRotation.ts
    - dashboard-react/src/hooks/useKioskRotation.test.ts
    - dashboard-react/src/routes/KioskView.tsx
    - dashboard-react/src/routes/KioskView.test.tsx
  modified:
    - dashboard-react/src/App.tsx
    - dashboard-react/src/App.test.tsx
    - dashboard-react/src/index.css

key-decisions:
  - "Kiosk branch lives in App.tsx (a new AppShell() component), not IndexRoute.tsx, per the plan's explicit file-overlap avoidance with the concurrent wave-4 plan 14-05 (which edits IndexRoute.tsx). AppShell decides what '/' renders (KioskView vs AppNav+Routes) before IndexRoute is ever reached, so this stays a rendering-mode branch of the same page rather than a second route, matching the UI-SPEC's intent even though the insertion point differs from UI-SPEC's literal 'IndexRoute' wording."
  - "KioskView derives its own devices/topology/incidents state directly from the store (mirroring IndexRoute's own derivation pattern) rather than importing IndexRoute's derived values, since KioskView is a sibling full-bleed view, not a child of IndexRoute."

requirements-completed: [DASH-17]

duration: ~20min
completed: 2026-09-26
---

# Phase 14 Plan 06: Kiosk / Wall Mode Summary

**A `?kiosk=1` URL entry on the existing `/` route renders a full-bleed, chrome-free, auto-rotating incidents/topology view (`KioskView`) driven by a new second sanctioned timer (`useKioskRotation`, 20s), with a gesture-gated "Enter full screen" button and defense-in-depth read-only construction that never renders edit controls.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-09-26
- **Tasks:** 2 completed
- **Files modified:** 7 (4 created, 3 modified)

## Accomplishments

- `useKioskRotation.ts`: `KIOSK_ROTATION_MS = 20000`, `useKioskRotation()` cycles `{ view: "incidents" | "topology", cycle }` every 20s via `setState`+`setInterval`+cleanup (same shape as `useNowTick`), explicitly documented as the app's second sanctioned periodic timer.
- `KioskView.tsx`: full-bleed (`h-screen w-screen`) layout at `text-[1.15em]` kiosk font scale, crossfading `IncidentList` (`fill`) and a read-only `TopologyMap` (`editMode={false}`, no `onEditSaved`/`onEditFailed`, `TopologyToolbar` never imported) via `opacity-100`/`opacity-0 pointer-events-none` + `aria-hidden`, an `aria-live="polite"` "Incidents"/"Topology" label, a bottom-edge accent progress bar keyed by `cycle` (restarts its CSS animation each rotation), and a one-time "Enter full screen" `Button` that calls `document.documentElement.requestFullscreen()` only from its `onClick` handler and self-hides after being pressed or after 10s.
- `App.tsx`: introduced `AppShell()`, rendered inside `BrowserRouter`, which checks `location.pathname === "/" && searchParams.get("kiosk") === "1"` and returns `<KioskView />` alone in that case, otherwise the existing `AppNav` + `Routes` unchanged — kiosk is a rendering mode of `/`, not a second route.
- `index.css`: added `@keyframes kiosk-progress` (0%→100% width) for the progress bar's `animation` style.

## Task Commits

1. **Task 1: useKioskRotation hook and KioskView** - RED `bbf48d9` (test), RED `a2eaa6b` (test), GREEN `6311ded` (feat)
2. **Task 2: ?kiosk=1 branch in App.tsx** - RED `35fa681` (test), GREEN `77ee9a9` (feat)

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified

- `dashboard-react/src/hooks/useKioskRotation.ts` - 20s rotation timer hook (new)
- `dashboard-react/src/hooks/useKioskRotation.test.ts` - 4 tests covering constant, initial state, rotation, unmount cleanup (new)
- `dashboard-react/src/routes/KioskView.tsx` - full-bleed rotating incidents/topology view (new)
- `dashboard-react/src/routes/KioskView.test.tsx` - 7 tests covering rotation/dimming, aria-live label, absence of edit controls, read-only map, fullscreen button gesture/timeout, progress bar remount (new)
- `dashboard-react/src/App.tsx` - `AppShell()` component with the `?kiosk=1` branch
- `dashboard-react/src/App.test.tsx` - 4 new tests (kiosk entry, `/` unchanged, `?kiosk=0`, `/details?kiosk=1`)
- `dashboard-react/src/index.css` - `@keyframes kiosk-progress`

## Decisions Made

- Kiosk branch placed in `App.tsx` rather than `IndexRoute.tsx`, per the plan's stated rationale (no file overlap with concurrent plan 14-05, which edits `IndexRoute.tsx`). `AppShell()` intercepts before `IndexRoute` mounts at all under `?kiosk=1`, preserving the UI-SPEC's actual intent ("a rendering mode of the same page, so kiosk and operator views can never drift into two different incident/map implementations") even though the insertion point differs textually from UI-SPEC's "IndexRoute (or a thin wrapper component)" phrasing — the UI-SPEC itself anticipated a wrapper-component alternative.
- `KioskView.test.tsx`'s "read-only TopologyMap" assertion checks only that `topology-map` renders (the real, globally-mocked-`vis-network` `TopologyMap` component has no `data-edit-mode` DOM attribute — that attribute exists only in `IndexRoute.test.tsx`'s own mock of `TopologyMap`). `editMode={false}` and the absence of `TopologyToolbar` are verified at the source level instead (acceptance-criteria greps), which is the literal, always-true guarantee defense-in-depth requires.

## Deviations from Plan

None — plan executed exactly as written, including the file-overlap-avoidance instruction (kiosk branch in `App.tsx`, not `IndexRoute.tsx`). No auto-fixes were required.

## Issues Encountered

- `dashboard-react/node_modules` and `design-system/kone-design-system-0.1.0.tgz` were absent in this worktree (not shared across worktrees). Copied the prebuilt tarball from the main checkout's `design-system/` directory and ran `npm install` before any test/typecheck/lint/build command, per the orchestrator's environment-setup instructions. Baseline `npm test` confirmed 417/417 green before starting; full suite is 432/432 green after this plan's additions (15 new tests).
- One initial test assertion (`data-edit-mode` attribute) was written against a pattern that only exists in a sibling test file's mock, not the real component — caught immediately when the GREEN run showed 1 unexpected failure, fixed inline (test-only change, not a deviation from the plan's behavior) before re-verifying GREEN.
- `npm run lint` reports 5 pre-existing warnings (`StateBadge.tsx`, `GroupingControls.tsx`, `IndexRoute.tsx` x2, `TopologyMap.tsx`) — none in this plan's files, unchanged from baseline.
- `npm run build`'s "chunks larger than 500 kB" notice is pre-existing (unrelated to this plan's ~4KB of new code) and out of scope per the plan's file list.

## User Setup Required

None — no external service configuration required. The deployment doc for launching a browser in OS-level kiosk mode (`chromium --kiosk <url>?kiosk=1`) is plan 14-09's responsibility, per the UI-SPEC.

## Next Phase Readiness

- DASH-17 (kiosk/wall mode) is implemented and unit-tested: `/?kiosk=1` enters kiosk mode; every other URL (`/`, `/?kiosk=0`, `/details?kiosk=1`) renders exactly as before.
- Plan 14-09's deployment documentation can now reference this concrete `?kiosk=1` entry point and its `chromium --kiosk` launch recommendation.
- No file overlap with 14-05 (which edits `IndexRoute.tsx`); both wave-4 plans can merge without conflict.

---
*Phase: 14-fleet-intelligence*
*Completed: 2026-09-26*

## Self-Check: PASSED

All created/modified files verified present (`useKioskRotation.ts`, `useKioskRotation.test.ts`,
`KioskView.tsx`, `KioskView.test.tsx`, `App.tsx`, `App.test.tsx`, `index.css`); all six commits
(`bbf48d9`, `a2eaa6b`, `6311ded`, `35fa681`, `77ee9a9`, `3b35de2`) verified present in
`git log --oneline --all`; full `npm test` suite 432/432 passed, `npm run typecheck` exit 0,
`npm run lint` exit 0 (5 pre-existing warnings only, no new ones), `npm run build` exit 0.
