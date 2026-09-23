# Deferred Items — Phase 12

Out-of-scope issues discovered during execution, logged rather than fixed (SCOPE BOUNDARY rule).

## From 12-05 (Device row navigation)

- **`GroupingControls.test.tsx` — 2 pre-existing failures, unrelated to 12-05's changes**
  - Tests: "checking 'Order by severity' reorders groups so the worst-state group is first" and
    "expanding two groups, then toggling 'Order by severity', leaves both groups expanded"
  - Confirmed pre-existing: reproduced against the unmodified baseline (`git show HEAD:...`)
    before any 12-05 edits were applied — same 2 failures, same assertion text.
  - Root cause (not investigated further, out of scope for 12-05): the tests build devices with
    a `FRESH_TIMESTAMP` fixed relative to a hardcoded `NOW_MS` of `2026-09-21T12:00:00Z`, but the
    staleness check appears to read the real wall clock rather than a fixed one in this render
    path. With the sandbox's system clock now past that fixed timestamp, the "ACS" group renders
    hatched/stale instead of the expected clean state, which shifts severity-sort output and
    breaks the assertions. Needs a fix in the test (or the component it exercises) to pin the
    clock the same way `StaleStability.test.tsx` does with `vi.useFakeTimers()` /
    `vi.setSystemTime()`.
