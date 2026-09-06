---
phase: quick
plan: 260906-mm9
subsystem: infra
tags: [mosquitto, config, broker]

# Dependency graph
requires: []
provides:
  - "A `deploy/mosquitto.conf` that parses cleanly under mosquitto 2.1.2 (no column-0 comment/parser violations)"
affects: [broker-infrastructure-hardening]

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified: [deploy/mosquitto.conf]

key-decisions:
  - "Rationale for autosave_interval 60 moved to a two-line column-0 comment block above the directive, matching the existing 'global settings' comment convention in the same file"

patterns-established: []

requirements-completed: [QUICK-260906-mm9]

# Metrics
duration: 6min
completed: 2026-09-06
---

# Quick Task 260906-mm9: Fix mosquitto.conf syntax bug (indented comment) Summary

**Moved the autosave_interval rationale from a trailing inline/indented comment to a column-0 comment block, fixing the parser crash that took mosquitto fully offline.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-09-06T08:15:00Z
- **Completed:** 2026-09-06T08:21:41Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Removed the sole instance of mosquitto's "trailing inline comment / indented continuation" bug class from `deploy/mosquitto.conf` (previously lines 19-20)
- `autosave_interval 60` is now a bare directive with no trailing comment, preceded by a two-line column-0 comment block preserving the original rationale
- Confirmed via a full-file grep audit (per the plan's pre-audit) that this was the only occurrence of the bug class in the file — no other fixes were needed or made

## Task Commits

Each task was committed atomically:

1. **Task 1: Replace the inline/indented comment on autosave_interval with a column-0 comment block** - `2eff022` (fix)

**Plan metadata:** (recorded by orchestrator in the docs commit that follows this summary)

## Files Created/Modified
- `deploy/mosquitto.conf` - Lines 19-20 (inline comment + indented continuation after `autosave_interval 60`) replaced with a two-line column-0 comment block followed by the bare `autosave_interval 60` directive. No other lines touched.

## Decisions Made
- Kept the post-mortem/rationale explanation out of the config file itself and recorded it here instead, per the plan's explicit instruction — CLAUDE.md's dated-post-mortem comment convention applies to Python source, not to `mosquitto.conf`, and adding prose there would add parser surface area for no benefit.

## Verification Path Used

**Structural check only — no real mosquitto parse was available in this sandbox.**

Ran `command -v podman docker mosquitto mosquitto_passwd` before making the fix: none of the four were found on `PATH` in this execution environment, so the plan's `<real-parse-if-available>` step was not applicable and was skipped. Verification relied entirely on the structural fallback command:

```
grep -nE "^[[:space:]]+#" deploy/mosquitto.conf        # expect: no match (indented comment)
grep -nE "^[[:space:]]*[^#[:space:]].*#" deploy/mosquitto.conf  # expect: no match (trailing inline comment)
grep -qxF "autosave_interval 60" deploy/mosquitto.conf  # expect: match (bare directive present)
grep -nP "\r" deploy/mosquitto.conf                     # expect: no match (no CR contamination)
```

All four checks passed; output was `PASS (structural)`. This does NOT confirm mosquitto's actual parser accepts the file — it only confirms the two specific syntax patterns that caused the reported crash (`Error found at ...:20` / `Unknown configuration variable '#'`) are absent, and that no other line in the file exhibits the same pattern. If a real mosquitto binary or container runtime becomes available, re-running `mosquitto -c deploy/mosquitto.conf` (or the eclipse-mosquitto:2 container variant described in the plan) is recommended before considering this fix fully proven end-to-end.

## Pre-Audit Confirmation

Per the plan's `<pre_audit>` block, lines 19-20 (pre-fix) were confirmed as the sole instance of this bug class in the file — one indented comment line, one directive with a trailing inline `#`. The post-fix structural check (see above) re-confirms zero remaining instances of either pattern anywhere in the file. No other lines were modified, reflowed, or re-indented.

## Out-of-Scope Observation (flagged, not acted on)

The plan noted that the reported smoke-test failure mentions port 9002, while `deploy/mosquitto.conf` declares the websockets listener on port 9001. This discrepancy was not investigated or changed as part of this fix — it is out of scope for a mosquitto.conf parser bug and belongs to `scripts/smoke_test_broker.py` or its caller, if it is a real issue at all. Flagging here per the plan's instruction; no action taken on either side.

## Deviations from Plan

None - plan executed exactly as written. The single task (replace lines 19-20 with a column-0 comment block) was applied verbatim per the plan's specified content, and the scope boundary (no changes to `mosquitto.acl`, `compose.yaml`, `mosquitto.passwd`, `gen-mosquitto-passwd.sh`, `smoke_test_broker.py`, or the Podman setup doc) was respected — `git status --short` after the commit shows a clean tree with no other files touched.

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `deploy/mosquitto.conf` should now allow the broker to start without the `Error found at ... Unknown configuration variable '#'` parse failure, assuming the fix addresses the actual root cause reported.
- This fix has not been verified against a live mosquitto binary or container in this sandbox (none available) — the Phase 08 broker-infrastructure-hardening plan's paused human-verify checkpoint (Plan 08-03 Task 3) on a real deployment host would be a good place to confirm the broker now starts cleanly with this change in place.
- The 9001-vs-9002 port discrepancy noted above remains unresolved and unexamined; if it turns out to be a real bug, it needs to be tracked separately.

---
*Phase: quick*
*Completed: 2026-09-06*

## Self-Check: PASSED

- FOUND: deploy/mosquitto.conf
- FOUND: 2eff022 (Task 1 commit, present in `git log --oneline --all`)
- FOUND: .planning/quick/260906-mm9-fix-mosquitto-conf-syntax-bug-indented-c/260906-mm9-SUMMARY.md
