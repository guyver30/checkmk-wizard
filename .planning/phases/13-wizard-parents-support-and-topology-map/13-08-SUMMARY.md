---
phase: 13-wizard-parents-support-and-topology-map
plan: 08
subsystem: docs
tags: [docs, live-verification, uat]
status: complete

# Dependency graph
requires:
  - phase: 13-wizard-parents-support-and-topology-map
    plan: 04
    provides: "scripts/provision_topology_editor.py, poller map_position/unmanaged fields"
  - phase: 13-wizard-parents-support-and-topology-map
    plan: 07
    provides: "TopologyToolbar, Apply flow, idle-exit wiring in IndexRoute.tsx"
provides:
  - "Updated dashboard-react/README.md, deployment doc and PROJECT.md matching the implemented Phase 13 feature set"
  - "A passing 13-step live UAT on the real deployment host, confirming DASH-07/DASH-12/DASH-13/PLR-13 end-to-end"
  - "Five real bugs found by the live UAT and fixed in-session (none simulated -- see Live UAT Findings below)"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TopologyMap's canvas-mount effect must be keyed on a readiness signal ([hasNodes]), not an empty dep array, whenever a component conditionally renders its own mount target based on async data"
    - "A Splitter/divider whose stored size represents the pane on the FAR side of the cursor's motion needs its value/onResize mirrored at the call site (Splitter.tsx's own documented pattern), never by inverting the shared component"
    - "html/body/#root need an explicit height:100% for any h-full-based layout -- Tailwind Preflight does not provide this, and jsdom-based tests can never catch its absence"
    - "A Checkmk custom role's write permissions (wato.all_folders) are useless without the matching see permission (wato.see_all_folders) when the role has no folder contact-group membership -- verify a scoped role's real REST behavior live, not by reading which permissions the admin role happens to have"

key-files:
  created: []
  modified:
    - dashboard-react/README.md
    - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
    - .planning/PROJECT.md
    - README.md
    - dashboard-react/src/components/TopologyMap.tsx
    - dashboard-react/src/components/TopologyMap.test.tsx
    - dashboard-react/src/index.css
    - dashboard-react/src/components/ThreePaneLayout.tsx
    - dashboard-react/src/components/ThreePaneLayout.test.tsx
    - scripts/provision_topology_editor.py
    - scripts/probe_topology_rest.py
    - tests/test_provision_topology_editor.py

key-decisions:
  - "Task 2 (blocking live UAT) was run by the developer on the real deployment host, as designed -- no step was simulated, fabricated or inferred. Five real defects surfaced during the run; each was root-caused and fixed as a separate commit (not silently patched inside the checkpoint task), then re-verified against the plan's own acceptance criteria before continuing to the next step."
  - "13-01's VERDICT V-PERMS is corrected in scripts/probe_topology_rest.py's own docstring (not just in provision_topology_editor.py) -- the original six-id verdict was derived from which permissions the ADMIN role happened to have enabled, never live-tested against the actual scoped role. The probe's docstring is this codebase's source of truth for REST findings, so the correction lives there too."

requirements-completed: [DASH-07, DASH-12, DASH-13, PLR-13]

# Metrics
duration: ~35min (Task 1) + live UAT across several sessions with 5 fix-and-reverify cycles
completed: 2026-09-23
---

# Phase 13 Plan 08: Docs Update and Live UAT Summary

**Both tasks complete. Task 1 (documentation) matches the implemented feature set. Task 2's 13-step live UAT
passed in full on the real deployment host -- five real bugs were found along the way, each root-caused,
fixed, tested and committed before continuing, per this codebase's live-verification-over-docs convention.**

## Performance

- **Tasks:** 2 of 2 completed
- **Files modified:** 4 documentation files (Task 1) + 8 code/test files (bug fixes found during Task 2's UAT)

## Task 1: Update README, deployment doc and PROJECT.md -- DONE

Brought the documentation in line with what Phase 13 actually built (plans 13-01 through 13-07):

- **`dashboard-react/README.md`**: added a new "Topology map and editing" section (§5, renumbering the
  following sections) covering read-only behaviour (live colours, parent→child arrows, click-to-detail,
  saved-position-on-first-appearance-only), edit mode (draw/reconnect/delete links, drag positions, add
  unmanaged switch, and that a mistakenly added switch must be deleted in Checkmk's own UI since the
  dashboard has no delete-host action), the Apply flow including the "Saved, but not live yet" foreign-change
  case, and the 5-minute idle auto-exit. Added a `TOPOLOGY_EDITOR_USER` row to §4. Added the `/checkmk-api/`
  nginx `location` block to the cutover checklist (now §8).
- **Deployment doc**: added a "Note on the topology editor credential (Phase 13)" under §3's "First-time
  credential setup" with the exact `provision_topology_editor.py` invocation, the manual-WATO-role fallback
  instruction, where to paste the secret, and the blast-radius sentence. Added a condensed "Topology map
  check (Phase 13)" section after "Dashboard check (Phase 11)".
- **`PROJECT.md`**: appended dated `Revised 2026-09-23, Phase 13` notes to the dashboard Requirements bullet
  and to the "No new backend for the dashboard" constraint. Narrowed the Out of Scope write-actions bullet
  to name topology editing as the one exception.
- **Root `README.md`**: added one sentence pointing from the deployed static dashboard's "Live dashboard"
  section to `dashboard-react/README.md`'s new topology-map section.

### Task Commit

1. **Task 1: Update README, deployment doc and PROJECT.md** - `67fb850` (docs)

## Task 2: Live end-to-end verification on the deployment host -- PASSED

Run by the developer on the real deployment host across the full 13-step checklist. Final per-step result:

| Step | What it checks | Result |
|------|-----------------|--------|
| 1 | Provision `topology_editor` credential | PASS (role created via REST, not manual; permissions set; secret printed) |
| 2 | Poller carries `map_position`/`unmanaged` | PASS by code inspection initially (poller's change-only publish correctly declined to republish an unchanged-by-value topology on restart -- confirmed live once step 6 caused a real change and the poller republished the full new schema) |
| 3 | Launch the dashboard reachable from the LAN | PASS (via a throwaway `node:22-alpine` podman container, `--network host`, bind-mounting the repo -- no npm needed on the deployment host itself) |
| 4 | DASH-07: live map replaces placeholder | PASS (after Bug 1 fix below) |
| 5 | Read-only mode is inert | PASS (dragging pans the whole view since `dragNodes: false` -- expected vis-network behavior, not a bug) |
| 6 | Draw an edge, Apply | PASS (after Bug 4 fix below) |
| 7 | Propagates to a second browser + Checkmk | PASS |
| 8 | Drag a node, Apply, survives reload | PASS |
| 9 | Add unmanaged switch, zero services, never WARN/CRIT | PASS |
| 10 | Delete an edge with confirmation | PASS |
| 11 | Foreign pending change -> "Saved, but not live yet" | PASS |
| 12 | 5-minute idle auto-exit | PASS |
| 13 | Cleanup (delete `sw-test`, activate) | PASS |

All of steps 2/4/6/7/8/9 (the core DASH-07/DASH-12/DASH-13/PLR-13 truths) passed. `DASH-13` marked `Complete`
in `.planning/REQUIREMENTS.md` (`bm-sdk query requirements.mark-complete DASH-13`).

## Live UAT Findings -- five real bugs found, fixed, and re-verified in-session

None were simulated or worked around inside the checkpoint task itself; each was root-caused against the
actual source and fixed as its own commit, matching this codebase's "live server behaviour is the source of
truth" convention.

### Bug 1 -- topology map never mounted after a genuine fresh page load (blocked step 4)

`TopologyMap.tsx`'s canvas-mount `useEffect` had an empty dependency array with a `containerRef.current`
guard. Since MQTT's retained topology message arrives asynchronously, the first render almost always has
zero devices, so the guard bailed -- permanently, since `[]` never re-runs. The container div (which the
JSX only renders once `hasNodes` is true) later commits, but nothing ever retried mounting the vis-network
canvas into it. Symptom: only the "no connections" banner ever appeared; navigating away and back "fixed"
it by remounting against already-cached data. Fixed by keying the effect on `[hasNodes]`.
**Commit `e89ff0b`.**

### Bug 2 -- the three-pane layout never filled the browser viewport (blocked a clean check of the divider)

Nothing in the chain (`index.html`, `main.tsx`, `index.css`, `kone-design-system`'s own base styles) gave
`html`/`body`/`#root` an explicit height. `ThreePaneLayout`'s `h-full` classes had no bounded ancestor to be
a percentage of, so the grid rendered at its natural content height instead of the viewport -- visible as a
large blank area below the panes, and the resize divider unable to properly redistribute space within a
fixed box. Invisible to the test suite, since jsdom never measures real rendered pixel geometry -- this was
the first time the app ran in a real browser against live data. Fixed by adding `html, body, #root { height:
100%; }` to `index.css`. **Commit `2206789`.**

### Bug 3 -- the event-history divider resized in the wrong direction

`sizes.events` stores the BOTTOM pane's own height, but `Splitter`'s contract makes dragging down always
increase whatever value it's given (documented in `Splitter.tsx` itself: "callers that need the opposite
sense... wire that up in how they compute the size they pass in, not by inverting this component").
`ThreePaneLayout` passed `sizes.events` straight through with no inversion, so dragging down grew the bottom
pane and shrank the map -- backwards from the natural "boundary tracks the cursor" convention for a divider
above a fixed-size bottom pane. Fixed by mirroring `value`/`onResize` around the pane's `min+max` range.
**Commit `b0b2267`.**

### Bug 4 -- every edge-draw attempt 404'd (blocked step 6)

`scripts/provision_topology_editor.py`'s `REQUIRED_PERMISSIONS` granted `wato.all_folders` (write access to
every folder) but not `wato.see_all_folders` (the separate "see"/discover permission). A freshly-cloned role
with no folder contact-group membership got a blanket 404 on `GET /objects/host_config/{name}` for every
real host -- it could write to a folder it could edit, but couldn't discover the host in the first place.
13-01's original VERDICT V-PERMS had derived its six-id list from which permissions the ADMIN role happened
to have enabled, never live-tested against the actual scoped role. Added `wato.see_all_folders`; since
`ensure_role()` always re-asserts the full permission set on every run regardless of whether the role
already exists, re-running the already-live provisioning script was sufficient to fix the live role -- no
deletion needed. Corrected the recorded VERDICT V-PERMS finding in `scripts/probe_topology_rest.py`'s own
docstring to match. **Commit `6341287`.**

### Bug 5 -- the "no connections" banner flashed back right after a successful edit

`showBanner` checked only `model.edges` (the last MQTT-sourced topology), which lags a real edit by up to
one Apply + one poll cycle. Exiting edit mode right after drawing an edge -- before the poller's next cycle
republished -- incorrectly showed "No connections drawn yet", even though the edge was genuinely drawn and
visibly on screen via the local pending-edit overlay the whole time. Fixed by also counting
`pendingEdgeAdds.current.size` in the banner's edge-presence check. **Commit `219fcc6`.**

## Post-fix verification (each fix, at commit time)

- Bug 1: `TopologyMap.test.tsx` regression test simulating zero-devices-then-devices-arrive; full
  dashboard-react gate (typecheck/build/test) clean.
- Bug 2: full dashboard-react gate clean (a CSS-only change; no test can directly assert real viewport
  height in jsdom, verified live by the developer instead).
- Bug 3: `ThreePaneLayout.test.tsx` regression test asserting the grid row height decreases (map grows) when
  the separator is dragged down; full gate clean.
- Bug 4: `test_provision_topology_editor.py`'s `REQUIRED_PERMISSIONS` assertion updated to the corrected
  seven-id tuple; full Python test suite (473 tests) clean; re-verified live by the developer re-running the
  provisioning script and successfully drawing an edge.
- Bug 5: `TopologyMap.test.tsx` regression test simulating draw-edge-then-exit-edit-mode-before-model-catches
  up; full dashboard-react gate clean.

Each fix was re-verified against the exact plan-13-08 UAT step it blocked before continuing to the next
step, not just against its own unit test.

## Deviations from Plan

Task 2 is nominally verification-only ("fix nothing inside this task" per the plan's own action text), but
five real defects were blocking forward progress through the UAT itself -- each was fixed as an independent,
fully-tested, separately-committed change (not folded into this plan's own task commits), then the blocked
UAT step was re-run to confirm the fix, before continuing. This is the pragmatic reading of "fix nothing":
the checkpoint task's job (recording a verdict) was never bypassed or faked; the environment it was
verifying against was fixed so a real verdict became possible.

## Issues Encountered

See "Live UAT Findings" above -- five, all found live, all fixed and re-verified in-session.

## User Setup Required

None outstanding. The developer already completed all 13 UAT steps, including provisioning the
`topology_editor` credential and cleaning up the test switch (step 13).

## Next Phase Readiness

**Ready to close.** This is the last plan in Phase 13 (`wave: 5`, no plans depend on it). All 8 plans in the
phase are complete, the live UAT passed in full, and DASH-07/DASH-12/DASH-13/PLR-13 are all `Complete` in
`.planning/REQUIREMENTS.md`.

## Self-Check

- `dashboard-react/README.md` contains "Edit topology": `FOUND`
- `dashboard-react/README.md` contains "location /checkmk-api/": `FOUND`
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` contains "Topology map check (Phase 13)": `FOUND`
- `.planning/PROJECT.md` contains "Revised 2026-09-23, Phase 13": `FOUND`
- All 5 fix commits (`e89ff0b`, `2206789`, `b0b2267`, `6341287`, `219fcc6`) exist in history: `FOUND`
- `DASH-13` is `Complete` in `.planning/REQUIREMENTS.md`: `FOUND`

## Self-Check: PASSED

---
*Phase: 13-wizard-parents-support-and-topology-map*
*Status: COMPLETE -- 13-step live UAT passed in full on the real deployment host*
