---
phase: 13-wizard-parents-support-and-topology-map
plan: 08
subsystem: docs
tags: [docs, live-verification, uat]
status: paused

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
  - "The exact 13-step live UAT checklist, still to be run by the developer on the real deployment host"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - dashboard-react/README.md
    - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
    - .planning/PROJECT.md
    - README.md

key-decisions:
  - "Task 2 (blocking live UAT) cannot be executed from this environment -- no podman, no broker, no Checkmk site reachable. Per the objective's explicit instruction, no verification step was simulated, fabricated or inferred; the plan is left paused at the checkpoint for the developer to run by hand."

requirements-completed: []

# Metrics
duration: ~35min (Task 1 only; Task 2 not run)
completed: 2026-09-23
---

# Phase 13 Plan 08: Docs Update and Live UAT Summary

**Task 1 (documentation) is done and committed. Task 2 is a blocking `checkpoint:human-verify` -- a 13-step live end-to-end UAT that only the developer can run, on the real deployment host, since this execution environment has no podman, no MQTT broker and no reachable Checkmk site.**

## Performance

- **Tasks:** 1 of 2 completed (Task 1 done; Task 2 paused, not executed)
- **Files modified:** 4 (`dashboard-react/README.md`, the deployment doc, `.planning/PROJECT.md`, root `README.md`)

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
  instruction, where to paste the secret, and the blast-radius sentence (can edit/add hosts and activate its
  own changes; cannot manage users/rules/global settings, and critically cannot activate another operator's
  foreign changes). Added a condensed "Topology map check (Phase 13)" section after "Dashboard check
  (Phase 11)".
- **`PROJECT.md`**: appended dated `Revised 2026-09-23, Phase 13` notes to the dashboard Requirements bullet
  (topology map + edit mode built) and to the "No new backend for the dashboard" constraint (topology edit
  mode writes directly to Checkmk's REST API from the browser via a same-origin forwarding rule -- still no
  new backend/API). Narrowed the Out of Scope write-actions bullet to name topology editing as the one
  exception.
- **Root `README.md`**: added one sentence pointing from the deployed static dashboard's "Live dashboard"
  section to `dashboard-react/README.md`'s new topology-map section, since the deployed `dashboard/` itself
  has no map (the map only exists in the not-yet-cut-over `dashboard-react/`).

### Verification (actually run)

- `grep -q "Edit topology" dashboard-react/README.md` -> match
- `grep -q "checkmk-api" dashboard-react/README.md` -> match
- `grep -q "provision_topology_editor.py" "docs/Podman setup for checkmk, minio, mosquitto, worker.md"` -> match
- `grep -q "Phase 13" .planning/PROJECT.md` -> match
- `grep -q "CHECKMK_PROXY_TARGET" dashboard-react/README.md` -> match
- `grep -q "Apply changes" dashboard-react/README.md` -> match (fixed a markdown line-wrap that had initially
  split the literal string across two lines)
- `grep -n "placeholder" dashboard-react/README.md` -> only the pre-existing `CHECKMK_BASE_URL`/
  `TOPOLOGY_EDITOR_SECRET` placeholder-value lines remain; the one new occurrence describes the map as
  *replacing* the earlier placeholder, not describing the map itself as a placeholder
- `grep -n "Topology map check (Phase 13)"` in the deployment doc -> match
- `grep -n "Revised 2026-09-23, Phase 13"` in `PROJECT.md` -> two matches (dashboard bullet and the
  constraint)
- `grep -n "CHECKMK_REST_ORIGIN" dashboard-react/src/lib/config.ts` -> confirms the constant documented in
  the README actually exists in the code
- `git diff --diff-filter=D --name-only HEAD~1 HEAD` after the commit -> no output, no unexpected deletions
- `git status --short` after the commit -> clean

### Task Commit

1. **Task 1: Update README, deployment doc and PROJECT.md** - `67fb850` (docs)

## Task 2: Live end-to-end verification on the deployment host -- PAUSED (blocking checkpoint)

**This task was not executed.** It is a `type="checkpoint:human-verify" gate="blocking"` task whose
`<action>` explicitly instructs: "Pause and hand the steps below to the developer, who runs them on the
real deployment host... Do not simulate or infer the results." This execution environment has no `podman`,
no MQTT broker, and no reachable Checkmk site -- there is no way to run any of the 13 steps from here, and
per the objective's explicit instruction, none of them were simulated, fabricated, or inferred.

### What must happen next

The developer must run the following on the real deployment host (pull the repo first, including this
plan's Task 1 doc commit `67fb850`), and report a pass/fail verdict **for every numbered step, verbatim**,
so a follow-up session can record the results and close out this plan:

1. Provision the credential: `podman exec -it automation-worker bash -c "cd /app/checkmk-wizard && python3 scripts/provision_topology_editor.py"`. If it prints a manual WATO role procedure, do that, then re-run it. Paste the printed secret into `TOPOLOGY_EDITOR_SECRET` in `dashboard-react/src/lib/config.ts` (local edit, do not commit). Report whether the role step was REST or manual.
2. Restart the poller so it runs the new code: `cd deploy && podman compose up -d --force-recreate poller`. Then run `podman exec mosquitto mosquitto_sub -u wsreader -P wsreader -t lan/devices/topology -C 1 -W 5` and confirm each device node now has `map_position` and `unmanaged` keys. Paste one node.
3. Start the dashboard on this host so the broker (derived from the page's hostname) and Checkmk are both reachable: `npm --prefix design-system run build && CHECKMK_PROXY_TARGET=http://localhost:8080 npm --prefix dashboard-react run dev -- --host`. Open `http://<HOST_IP>:5173/` from a LAN browser (browser A) and a second browser or device (browser B).
4. DASH-07: confirm the map replaces the old placeholder under the stats strip, icons are coloured by state, and clicking a node opens `/details?id=...`. Confirm hosts start in a grid, not piled up.
5. Confirm "Edit topology" is off on load, and in read-only mode dragging a node does nothing.
6. In A, turn on Edit topology. Use the toolbar's "Add Edge" to draw from a switch/router host to a child host. Confirm "1 change not yet applied" (or a higher count if other changes were already pending). Press "Apply changes" and confirm "Applying…" then "Topology updated".
7. Within about 2 poll cycles (~2 minutes), confirm the arrow appears in browser B without reloading, and in Checkmk (Setup > Hosts > child > Parents).
8. In A, drag a node, Apply, then reload B and confirm the node sits where you dropped it.
9. In A, use "Add Node" to add an unmanaged switch named e.g. `sw-test`, then draw an edge from it to a host and Apply. In Checkmk, confirm `sw-test` exists, is UP, and has ZERO services (no PING), and that after a few minutes it never goes WARN/CRIT (D-06). In the dashboard, hovering it shows "Unmanaged switch (not monitored)".
10. Delete an edge: confirm the "Remove this connection?" dialog appears, then Apply, and the edge disappears in B after the next poll.
11. Failure path: in Checkmk, create any unrelated pending change as `cmkadmin` (e.g. edit a host alias without activating). Then make one map edit and press Apply in A. Confirm "Saved, but not live yet" appears and stays, because the scoped user must not activate foreign changes. Activate in Checkmk afterwards.
12. Leave A in edit mode untouched for 5 minutes and confirm it switches off with "Edit topology turned off after 5 minutes of inactivity".
13. Clean up: delete `sw-test` in Checkmk's own UI and activate.

**Acceptance criteria for Task 2** (from the plan): a result reported for every one of steps 1-13; steps 2,
4, 6, 7, 8 and 9 (the core DASH-07/DASH-12/DASH-13 and PLR-13 truths) must pass, and any failure must be
recorded as a gap with expected vs. observed against the decision it relates to (D-xx / DASH-xx).

### Resume instructions

A follow-up executor (or the developer directly) should:
1. Run the 13 steps above against the real deployment.
2. Append the per-step verdicts to this SUMMARY (or a follow-up note), including any gaps found.
3. If all of steps 2/4/6/7/8/9 pass, the phase's success criteria are met; `DASH-13` can then be marked
   `Complete` in `.planning/REQUIREMENTS.md` (it is currently `Pending` -- deliberately left untouched by this
   plan, since only a passing live UAT justifies marking it complete).
4. If any step fails, record it as a gap (expected vs. observed, decision reference) rather than silently
   reattempting a fix -- per the plan's own instruction, Task 2 is verification-only and "fix nothing inside
   this task."

## Deviations from Plan

None for Task 1 -- executed as written. Task 2 was not a deviation; it is the plan's own designed pause
point, reached and reported as instructed, not skipped or worked around.

## Issues Encountered

None for Task 1. Task 2 is blocked structurally (no live infrastructure reachable from this execution
environment), as anticipated by the plan's own objective ("since no Checkmk site is reachable from the
development machine").

## User Setup Required

The entire 13-step checklist above is the outstanding user (developer) action -- see "What must happen
next."

## Next Phase Readiness

**Not ready to close.** This is the last plan in Phase 13 (`wave: 5`, no plans depend on it). The phase
cannot be marked complete until Task 2's live UAT has been run and its results recorded. Documentation
(Task 1) is done and matches the implemented code.

## Self-Check

- `dashboard-react/README.md` contains "Edit topology": `FOUND`
- `dashboard-react/README.md` contains "location /checkmk-api/": `FOUND`
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` contains "Topology map check (Phase 13)": `FOUND`
- `.planning/PROJECT.md` contains "Revised 2026-09-23, Phase 13": `FOUND`
- Commit `67fb850` exists in history: `FOUND` (`git log --oneline -3` confirmed above)

## Self-Check: PASSED

---
*Phase: 13-wizard-parents-support-and-topology-map*
*Status: PAUSED at Task 2 (blocking checkpoint:human-verify) -- awaiting live UAT on the real deployment host*
