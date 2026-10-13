---
phase: quick-261013-iyq
plan: 01
subsystem: dashboard-react
tags: [dashboard, unmanaged-switch, display-state]
requires: []
provides:
  - "displayState()/stateLabel()/UNMANAGED_STATE in lib/display.ts"
  - "unmanagedIdsFromTopology()/unmanagedChildrenHint() in lib/topologyLayout.ts"
key-files:
  modified:
    - dashboard-react/src/lib/display.ts
    - dashboard-react/src/lib/stateMapping.ts
    - dashboard-react/src/lib/mapIcons.ts
    - dashboard-react/src/lib/topologyLayout.ts
    - dashboard-react/src/lib/grouping.ts
    - dashboard-react/src/lib/treeModel.ts
    - dashboard-react/src/store/selectors.ts
    - dashboard-react/src/components/TopologyMap.tsx
    - dashboard-react/src/components/StateBadge.tsx
    - dashboard-react/src/components/StatsStrip.tsx
    - dashboard-react/src/components/HostDetails.tsx
    - dashboard-react/src/routes/IndexRoute.tsx
    - dashboard-react/README.md
    - docs/Incident demo with fake check results.md
decisions:
  - "Unmanaged mapping is front-end only; poller inferred-root rule and MQTT contract untouched"
  - "Staleness is not applied to a quiet unmanaged switch (UNKNOWN/OK); a stale DOWN still reads STALE"
completed: 2026-10-13
---

# Quick 261013-iyq: Show unmanaged switches as Unmanaged

An unmanaged switch (topology `unmanaged === true`) whose own state is UNKNOWN or OK now
renders as a neutral grey "Unmanaged" on the map, tree, state badge, host details and header
stats, with a hint derived from its direct children ("3 of 4 devices behind it are up" /
"No devices connected"). DOWN/UNREACH and the inferred-root styling are unchanged.

## What "all its children are down" yields today

Front-end only; `scripts/mqtt_poller.py` was not touched (`git diff --stat -- scripts` empty).
Under the poller's inferred-root rule (>= 2 direct children DOWN/UNREACH, at least one DOWN):

- Switch with two or more children all down: the poller opens an inferred incident rooted at
  the switch. The map keeps the dashed warning border and the title "Inferred root cause, not
  confirmed" (inferred-root emphasis and title take precedence over the Unmanaged styling and
  hint). The tree row/badge still shows the switch's own state, i.e. "Unmanaged" (its Checkmk
  state is UP/UNKNOWN), with the inferred-root marker; consequences stay dimmed as before.
- Switch with exactly one child, and it is DOWN: NOT inferred (a lone non-OK child is its own
  root). The switch shows plain "Unmanaged" with hint "0 of 1 device behind it is up".

## Decisions

- **Icon class:** `icon-minus-circle-filled` (stateIcon and badge), distinct from UNKNOWN's
  question mark, UNREACH's unavailable glyph and STALE's clock. The map uses neutral grey
  `#96969f` (the existing NEUTRAL_400 tone), 2px solid border. Note: no stylesheet in this
  repo or in `kone-design-system/dist/style.css` defines any `icon-*` class (they are supplied
  by the host page), so I could not confirm this class name exists in the icon set; the badge
  text "Unmanaged" carries the meaning if the glyph is missing.
- **STALE decision:** staleness is NOT applied when an unmanaged switch is UNKNOWN/OK. A
  check-free switch has no checks, so Checkmk's `staleness` grows while it is merely quiet and
  STALE would be as misleading as UNKNOWN; poller liveness is already shown by
  PollerOfflineBanner. A stale DOWN/UNREACH unmanaged switch still reads STALE (same as any
  host). Non-unmanaged hosts follow today's rule exactly.
- Group roll-up: UNMANAGED has severity rank 0 (like OK/PEND) and is excluded from nonOkCount.
- Stats strip: new neutral "Unmanaged N" badge (shown only when N > 0, last in order).
- Lag-fix work intact: no new per-message store subscriptions. HostDetails selectors return a
  boolean and a string; header counts keep the single shallow-compared selector; map sync and
  store coalescing untouched.

## Verification (real output)

- `npm test`: 67 files, 1002 tests passed.
- `npm run typecheck`: clean (exit 0).
- `npm run lint` (oxlint): exit 0, 10 warnings, all in code this change did not introduce
  (StateBadge's `Date.now()` default parameter warning pre-existed).
- Commits: 3d10490 (map/helpers), cd9e8e3 (tree/stats/badge/details), 9a05d59 (docs). Not
  pushed.

## Checked and left unchanged

Event history (EventRow shows the poller's recorded from/to transitions verbatim, a historic
record), incidents, needs/narration, AlertsPane, AdminBar/adminMode faked set and cascade
preview, history/forecast charts, optimistic Add-Node path (still PEND with the plain title).

## Deviations from Plan

None of consequence. Minor: the existing optimistic Add-Node node literal and two
`MapNode` test literals gained `hint: null` for the new required field.

## Not verified

- Not seen in a browser: the grey colour, the icon glyph rendering and the tooltip text were
  only exercised through jsdom/vitest (vis-network is mocked in the TopologyMap tests).
- No live check with a real unmanaged switch, an admin fake DOWN then UP, or an actual
  inferred incident against the broker.
- The `icon-minus-circle-filled` class existence (see above).

## Self-Check: PASSED

Commits 3d10490, cd9e8e3, 9a05d59 exist on master; listed files modified.
