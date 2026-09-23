# Deferred Items — Phase 13

Out-of-scope discoveries found during plan execution, logged but not fixed (per deviation
Scope Boundary rule).

## From plan 13-02

- **`dashboard-react/src/components/GroupingControls.test.tsx`** — 2 pre-existing test
  failures (`checking 'Order by severity' reorders groups...` and `...leaves both groups
  expanded`), observed while running the full `npm --prefix dashboard-react test` suite
  during plan 13-02 execution (2026-09-23). Neither test touches any file plan 13-02 modifies
  (`mapIcons.ts`, `topologyLayout.ts`, `types.ts`'s new `TopologyNode` interface, or the
  vendored SVGs). The fixture data in that test file uses a fixed `NOW_MS` constant
  (`Date.parse("2026-09-21T12:00:00Z")`) as a *timestamp source* for device payloads, but
  appears to rely on a component path that reads the real system clock (`Date.now()`)
  elsewhere for staleness computation — as real time advances past the fixture's fixed date,
  devices that were "fresh" at authoring time now read as stale, breaking the "worst state"
  ordering assertions. Out of scope for plan 13-02 (does not touch
  `GroupingControls.tsx`/`IndexRoute.tsx`/`grouping.ts`); flagged here for whoever next
  touches that test file's clock-injection pattern.
