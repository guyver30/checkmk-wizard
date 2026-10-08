# Quick 261008-d9k: Trend chart zoom in/out and pan Summary

Time-axis zoom and pan for the forecast chart (`ForecastChart.tsx`) with a pure helper `src/lib/chartZoom.ts`, no new dependencies.

## Commits
- 08e8a54 feat: pure zoom/pan helper and unit tests
- c5254d5 feat: zoom and pan in ForecastChart (toolbar, wheel, drag, keys, clipPath)
- docs commit: README paragraph and two dated 14.2-UI-SPEC amendments

## What was built
- `chartZoom.ts`: clampDomain, zoomAt, panBy, revealTime, isFullDomain, isMinSpan, MIN_SPAN_MS (4 h). 16 unit tests.
- `ForecastChart.tsx`: zoom state keyed to the full domain (resets on range/metric change; a reopened dialog remounts), toolbar (Zoom in / Zoom out / Reset zoom), native non-passive wheel listener zooming at the pointer, drag pan, double-click reset, keys + - = _ 0, Shift+Arrow pan, plain Arrow still steps the crosshair and the window follows it. Y axis rescales in-window when zoomed; plotted layers under a clipPath; out-of-window markers and today line not rendered; level lines outside the y domain not drawn.
- 10 new component tests (22 total in ForecastChart.test.tsx); the 12 pre-existing tests are unchanged and pass.

## Verification (actually run)
- `npx vitest run` chartZoom + ForecastChart: 38 passed.
- `npm test` (full dashboard suite): 865 passed.
- `npx tsc --noEmit`: exit 0.
- package.json unchanged.

## NOT verified in a browser
The executor did not see this in a browser. Pixel mapping (wheel anchor, drag distance), the grab cursor, clipping appearance and theming are untested beyond jsdom (where rect width is 0, so the pointer anchor falls back to the window centre).

Operator checklist (rebuild: `podman compose build dashboard`, then full `podman compose down && podman compose up -d` on the deploy host):
1. Open a trending metric's chart (Needs pane "View chart"): +, - and Reset show; - and Reset are disabled.
2. Wheel over the plot: zooms around the pointer; the dialog does not scroll.
3. Drag left and right: the window pans and stops at both ends.
4. Zoom in on the last few days: y axis rescales; nothing draws over the axes; the Warning/Critical markers disappear when outside the window.
5. Hover: crosshair and readout still track points inside the window.
6. Tab to the plot: Left/Right step the crosshair (window follows), Shift+Left/Right pan, + - 0 work, Escape still blurs.
7. Double-click resets; changing Range resets; closing and reopening the dialog starts at full view.
8. Light and dark themes: buttons and clipped lines look right.

## Deviations from Plan
None of substance. Notes:
- Plan said 11 existing tests; there were 12. All pass.
- Prettier was not run on ForecastChart.tsx; the today-line block inside the new `inView(nowMs) && (` wrapper keeps its old indentation.
- The worktree needed `dashboard-react/node_modules` symlinked (gitignored) and `uv run` created a `.venv` (untracked/ignored, not committed).

## Known Stubs
None.

## Threat Flags
None (client-side only, no new surface).
