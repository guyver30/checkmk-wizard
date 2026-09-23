---
phase: 13-wizard-parents-support-and-topology-map
reviewed: 2026-09-23T00:00:00Z
depth: standard
files_reviewed: 29
files_reviewed_list:
  - dashboard-react/src/App.test.tsx
  - dashboard-react/src/components/StaleStability.test.tsx
  - dashboard-react/src/components/ThreePaneLayout.test.tsx
  - dashboard-react/src/components/ThreePaneLayout.tsx
  - dashboard-react/src/components/TopologyMap.test.tsx
  - dashboard-react/src/components/TopologyMap.tsx
  - dashboard-react/src/components/TopologyToolbar.test.tsx
  - dashboard-react/src/components/TopologyToolbar.tsx
  - dashboard-react/src/hooks/useEditIdleTimeout.test.ts
  - dashboard-react/src/hooks/useEditIdleTimeout.ts
  - dashboard-react/src/index.css
  - dashboard-react/src/lib/checkmkWrite.test.ts
  - dashboard-react/src/lib/checkmkWrite.ts
  - dashboard-react/src/lib/config.test.ts
  - dashboard-react/src/lib/config.ts
  - dashboard-react/src/lib/mapIcons.test.ts
  - dashboard-react/src/lib/mapIcons.ts
  - dashboard-react/src/lib/topologyLayout.test.ts
  - dashboard-react/src/lib/topologyLayout.ts
  - dashboard-react/src/lib/types.ts
  - dashboard-react/src/routes/IndexRoute.test.tsx
  - dashboard-react/src/routes/IndexRoute.tsx
  - dashboard-react/src/test/fakeVisNetwork.ts
  - dashboard-react/vite.config.ts
  - dashboard-react/vitest.setup.ts
  - scripts/probe_topology_rest.py
  - scripts/provision_topology_editor.py
  - scripts/mqtt_poller.py
  - tests/test_provision_topology_editor.py
  - tests/test_mqtt_poller.py
findings:
  critical: 0
  warning: 3
  info: 3
  total: 6
status: issues_found
---

# Phase 13: Code Review Report

**Reviewed:** 2026-09-23
**Depth:** standard
**Files Reviewed:** 29
**Status:** issues_found

## Summary

Reviewed the live-editable topology map (React + vis-network), the shared Checkmk write client
(`checkmkWrite.ts`), the poller's `map_position`/`unmanaged` additions (`scripts/mqtt_poller.py`),
and the `topology_editor` role-provisioning script, at standard depth. No blocking/critical
defects were found. The five already-fixed live-UAT bugs (canvas-mount race, missing
html/body/#root height chain, inverted resize-divider direction, missing
`wato.see_all_folders`, banner-flash-back) were each re-verified fresh against their surrounding
code and regression tests; all five fixes are sound on their own merits, not just "tests pass".

The issues below are new findings from this pass: two multi-network-call code paths in
`TopologyMap.tsx` (`editEdge`'s cross-child branch, `deleteEdge`'s multi-edge loop) that leave no
overlay bookkeeping on a mid-sequence failure, a write-capable credential design that (unlike this
file's own read-only precedent) is pasted into a tracked source file with no local-override
escape hatch, and a provisioning script whose only-network-facing functions have zero test
coverage. None of these are exploitable/crashing on their own; they're robustness and
defense-in-depth gaps worth closing.

## Warnings

### WR-01: `editEdge`'s two-call branch and `deleteEdge`'s multi-edge loop leave no overlay record on a mid-sequence failure

**File:** `dashboard-react/src/components/TopologyMap.tsx:177-245`

**Issue:** Both `editEdge` (when the edge's child changes, `oldEdge.to !== data.to`) and
`deleteEdge` (when multiple edges are selected) make more than one `updateParents()` REST call in
sequence inside a single `try`:

```ts
// editEdge, cross-child branch (lines 186-189)
await updateParents(oldEdge.to, (parents) => parents.filter((p) => p !== oldEdge.from));
await updateParents(data.to, (parents) => [...parents, data.from]);
```

```ts
// deleteEdge (lines 230-238)
for (const edgeId of edgeIds) {
  const edge = edgesRef.current?.get(edgeId) as unknown as { from: string; to: string } | null;
  if (!edge) continue;
  await updateParents(edge.to, (parents) => parents.filter((p) => p !== edge.from));
  pendingEdgeRemovals.current.add(edgeId);
  pendingEdgeAdds.current.delete(edgeId);
}
```

If the *first* call in either sequence succeeds and a *later* one throws, Checkmk's host
attributes have already been partially mutated (a parent link genuinely removed from
`oldEdge.to`, or an earlier edge in the batch genuinely removed), but the `catch` block only calls
`callback(null)` and fires the generic `CONNECTION_FAILURE` message — it never records the
already-applied mutation in `pendingEdgeAdds`/`pendingEdgeRemovals`. Until the model naturally
catches up (the next MQTT topology sync after an Apply + poll cycle reflects the real Checkmk
state), the map keeps showing the edge as if nothing happened, then it will disappear on its own
later with no attribution the user can connect to an action they took. The user is told "try
again", which for the already-succeeded half of the mutation is not actionable and not accurate.

This requires a specific failure window (a write succeeding, then a subsequent one in the same
user action failing) so it is not "every edit is broken", but it is a real, unhandled partial-
failure state for a feature whose entire value proposition is that "every write applies
immediately" (see the file's own header comment).

**Fix:** In the `catch` blocks of both `editEdge` and `deleteEdge`, apply the same
overlay-bookkeeping (`pendingEdgeRemovals.current.add(...)` for the leg(s) that are known to have
already succeeded) that the success path already does, so the map's optimistic overlay reflects
reality even on a partial failure — e.g. track which `updateParents` calls in the sequence
resolved before re-throwing, and reconcile the overlay accordingly. At minimum, the error copy
should distinguish "nothing was changed" from "part of this change was applied" so the user isn't
told to blindly retry a half-completed edit.

---

### WR-02: Write-capable `TOPOLOGY_EDITOR_SECRET` is pasted into a git-tracked file with no local-override mechanism

**File:** `dashboard-react/src/lib/config.ts:66-68`, `scripts/provision_topology_editor.py:363-368`

**Issue:** `provision_topology_editor.py` prints the freshly-generated automation secret once and
instructs the operator to paste it directly into `TOPOLOGY_EDITOR_SECRET` in
`dashboard-react/src/lib/config.ts` — a file that is tracked by git (`git log` shows it committed
at `c3f6bc9`) and is **not** listed in `.gitignore`. Unlike the file's own `WS_USERNAME`/
`WS_PASSWORD` precedent (deliberately-committed, read-only, topic-scoped-to-`lan/#`), this secret
is write-capable: it can edit/create Checkmk hosts and activate its own pending changes
(`checkmkWrite.ts`). An operator who edits this file in place and later runs `git add -A` /
`git commit` (a very natural next step after "edit this file per deployment") will commit a live
write-capable Checkmk credential into the repository's history, from which it cannot be
un-committed by a later edit.

The file's own header comment argues this is "acceptable under this project's existing
trusted-LAN, no-multi-user-accounts posture" — a reasonable design tradeoff already made at D-04
— but that argument was made for the *read-only* broker credential, and is being reused here to
justify a *write-capable* one without a corresponding mitigation (e.g. keeping it out of the
tracked file).

**Fix:** Consider splitting the write-capable secret out of the tracked `config.ts` into a
gitignored local file (e.g. `config.local.ts`, imported/merged at build time, with `config.ts`
importing a placeholder default when the local file is absent) — the same pattern most Vite/React
projects use for `.env.local`. This keeps the "operator pastes the secret in one obvious place"
UX while removing the single biggest way it ends up in git history.

---

### WR-03: `provision_topology_editor.py`'s only network-facing functions (`ensure_role`, `ensure_user`, `activate_own_changes`, `_rest`) have zero test coverage

**File:** `tests/test_provision_topology_editor.py`, `scripts/provision_topology_editor.py:233-370`

**Issue:** `tests/test_provision_topology_editor.py` only exercises pure helper functions
(`build_role_permissions`, `build_user_body`, `redact_auth_header`, `generate_secret`) and the
`CMK_REST_SECRET`-missing fast-fail path of `main()`. None of `ensure_role()`, `ensure_user()`,
`activate_own_changes()`, or `_rest()` — the functions that actually make the REST calls that
clone the role, set its `REQUIRED_PERMISSIONS`, create the automation user, and activate changes
— are exercised by any test (no `unittest.mock.patch` of `urllib.request.urlopen` anywhere in the
file, unlike `tests/test_mqtt_poller.py`'s equivalent REST-calling code, which is thoroughly
mocked). This is the script that provisions a least-privilege security boundary
(`REQUIRED_PERMISSIONS` deliberately excludes `wato.activateforeign` and every `wato.users`/
`wato.global`/`wato.rulesets` id) — a body-shape regression (e.g. a future Checkmk version
changing `EditUserRole`'s field name, or a typo in `build_user_body`'s `roles` key) would only be
caught by re-running this script against a live site, not by CI.

**Fix:** Add tests mocking `urllib.request.urlopen` (mirroring `tests/test_mqtt_poller.py`'s
`fetch_host_config`/`RestError` tests) for at least: `ensure_role()` skipping the clone when the
role already exists (200) vs. cloning it (404 then 200/201), `ensure_role()` returning `False` on
a rejected clone/permission-edit, `ensure_user()`'s "already exists" short-circuit, and
`activate_own_changes()`'s 401-means-foreign-changes-pending branch.

## Info

### IN-01: Stale comment claims `editMode` "starts out true" on first render

**File:** `dashboard-react/src/components/TopologyMap.tsx:373-374`

**Issue:** The comment above the edit-mode gating `useEffect` says: "Runs after the mount effect
above ... so networkRef.current is already set even on the very first render when editMode starts
out true." In the actual app, `IndexRoute.tsx:94` initializes `const [editMode, setEditMode] =
useState(false)`, and `TopologyMap`'s own prop default is `editMode = false`
(`TopologyMap.tsx:110`) — `editMode` never starts `true` on first render in this codebase. The
underlying claim (the mount effect runs before the gating effect due to declaration order, so
`networkRef.current` is always set by the time the gating effect reads it) is correct and
important; only the specific "starts out true" example is wrong, which will confuse a future
reader trying to verify the ordering claim against real call sites.

**Fix:** Reword to describe the general guarantee without asserting a specific initial value,
e.g. "...so `networkRef.current` is already set on the very first render regardless of what
`editMode` starts as."

### IN-02: `pendingCount` under-counts a two-call `editEdge` (cross-child) as a single change

**File:** `dashboard-react/src/routes/IndexRoute.tsx:115-118`, `dashboard-react/src/components/TopologyMap.tsx:186-189`

**Issue:** `onEditSaved` increments `pendingCount` by exactly 1 per manipulation callback
invocation. `editEdge`'s cross-child branch performs two separate host-attribute writes (removing
the parent from the old child, adding it to the new child) but calls `onEditSavedRef.current?.()`
only once on success, so the toolbar's "N changes not yet applied" banner under-counts by 1 for
this specific action relative to what Checkmk's own pending-changes count will show. This is a
display-accuracy nit, not a functional bug (the actual writes and the "Apply" flow both still work
correctly), but it is the one path in the file where a single user gesture maps to more than one
REST write, and it goes silently uncounted.

**Fix:** Either call `onEditSavedRef.current?.()` once per successful `updateParents` write in the
cross-child branch, or accept the current 1-per-gesture semantics but note the discrepancy in the
component's own header comment so it isn't mistaken for an exact mirror of Checkmk's pending count
elsewhere.

### IN-03: A transient empty `topologyDevices` payload would fully remount the vis-network canvas, dropping pan/zoom/edit state

**File:** `dashboard-react/src/components/TopologyMap.tsx:309-367`

**Issue:** The `[hasNodes]`-keyed mount effect (the live-UAT fix for the async-MQTT-data race) is,
by design, also torn down and rebuilt every time `hasNodes` transitions in either direction, not
just false→true on first load. If a genuinely empty `lan/devices/topology` payload were ever
retained/republished after the map already has nodes (e.g. a Livestatus hiccup that transiently
returns zero hosts, or a poller restart racing a subscriber before the first real snapshot lands),
the whole `Network` would be destroyed and recreated on the next non-empty update, discarding the
user's current pan/zoom and dropping out of edit mode's toolbar state. Nothing in
`scripts/mqtt_poller.py`'s reviewed code publishes an empty topology under normal operation
(`query_devices` returning zero rows would require Livestatus itself to report no hosts at all),
so this is a low-probability edge case, not a reproducible defect — flagged for awareness given
it sits directly adjacent to the bug this effect was already patched for once.

**Fix:** No action required unless a future report shows Livestatus/the poller can transiently
publish an empty device list on a healthy site; if so, consider keying the mount effect on "has
mounted at least once" (a ref) rather than the current live value of `hasNodes`, so a later true→
false→true flap doesn't force a remount.

## Convention

_Emitted by the shared `verify conventions` rule pack (conformance / verb-vs-body /
architectural-split), scoped to this phase's changed `.tsx`/`.ts` files. All five hits below are
the same rule (`identifier-casing should be camel`) firing on top-level exported React
component/props-interface names — `CollapsiblePane`, `ThreePaneLayout`, `TopologyMap`,
`TopologyToolbar`, `IndexRoute`. This is very likely tool noise rather than a real deviation:
PascalCase for exported React components is the dominant, expected convention in this codebase
(every other reviewed component — `Tree`, `StatsStrip`, `GroupingControls`, `EventHistory` — and
React itself follows it), not a departure from it. Included per the review's standing instruction
to always emit rule-pack output verbatim at CONVENTION tier; these do not block and no action is
recommended beyond confirming the rule pack's dominance heuristic accounts for React component
exports as their own axis.

- `dashboard-react/src/components/ThreePaneLayout.tsx:14` — `CollapsiblePane` — convention: identifier-casing should be camel — fix: rename to camel case (not recommended; PascalCase is correct for a React component).
- `dashboard-react/src/components/ThreePaneLayout.tsx:5` — `ThreePaneLayout` — same rule, same caveat.
- `dashboard-react/src/components/TopologyMap.tsx:32` — `TopologyMap` — same rule, same caveat.
- `dashboard-react/src/components/TopologyToolbar.tsx:11` — `TopologyToolbar` — same rule, same caveat.
- `dashboard-react/src/routes/IndexRoute.tsx:30` — `IndexRoute` — same rule, same caveat.

---

_Reviewed: 2026-09-23_
_Reviewer: Claude (bm-code-reviewer)_
_Depth: standard_
