# Deferred Items — Phase 14 (fleet-intelligence)

Out-of-scope discoveries logged during plan execution, not fixed per the Scope Boundary rule
(only auto-fix issues directly caused by the current task's changes).

## From plan 14-02

- **`dashboard-react/src/lib/mapIcons.test.ts` fails on the base commit, unrelated to this
  plan.** `npm test` (full suite) reports 2 failing assertions expecting
  `fill="#141414"` in `deviceTypeSvg("Api")`/`deviceTypeSvg("NetworkDevice")` output; the
  actual SVG markup does not contain that fill value. Neither `mapIcons.ts` nor
  `mapIcons.test.ts` is touched by plan 14-02 (last modified in commit `a427d92`, well before
  this plan's base). Not fixed here — out of scope for plan 14-02's incident data-layer work.
