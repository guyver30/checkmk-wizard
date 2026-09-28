---
phase: 14-fleet-intelligence
reviewed: 2026-09-28T06:13:59Z
depth: standard
files_reviewed: 37
files_reviewed_list:
  - dashboard-react/src/App.tsx
  - dashboard-react/src/App.test.tsx
  - dashboard-react/src/components/CriticalityEditor.tsx
  - dashboard-react/src/components/CriticalityEditor.test.tsx
  - dashboard-react/src/components/IncidentCard.tsx
  - dashboard-react/src/components/IncidentList.tsx
  - dashboard-react/src/components/IncidentList.test.tsx
  - dashboard-react/src/components/TopologyMap.tsx
  - dashboard-react/src/components/TopologyMap.test.tsx
  - dashboard-react/src/components/TreeNode.tsx
  - dashboard-react/src/components/Tree.test.tsx
  - dashboard-react/src/index.css
  - dashboard-react/src/lib/agentDetail.ts
  - dashboard-react/src/lib/agentDetail.test.ts
  - dashboard-react/src/lib/checkmkWrite.ts
  - dashboard-react/src/lib/checkmkWrite.test.ts
  - dashboard-react/src/lib/incidents.ts
  - dashboard-react/src/lib/incidents.test.ts
  - dashboard-react/src/lib/mapIcons.ts
  - dashboard-react/src/lib/mapIcons.test.ts
  - dashboard-react/src/lib/topologyLayout.ts
  - dashboard-react/src/lib/topologyLayout.test.ts
  - dashboard-react/src/lib/treeModel.ts
  - dashboard-react/src/lib/treeModel.test.ts
  - dashboard-react/src/lib/types.ts
  - dashboard-react/src/routes/IndexRoute.tsx
  - dashboard-react/src/routes/IndexRoute.test.tsx
  - dashboard-react/src/store/mqttClient.ts
  - dashboard-react/src/store/mqttClient.test.ts
  - dashboard-react/src/store/selectors.test.ts
  - dashboard-react/src/store/useAppStore.ts
  - dashboard-react/src/store/useAppStore.test.ts
  - scripts/mqtt_poller.py
  - tests/test_mqtt_poller.py
  - dashboard-react/README.md
  - docs/Incident demo with fake check results.md
  - docs/Podman setup for checkmk, minio, mosquitto, worker.md
findings:
  critical: 2
  warning: 7
  info: 7
  total: 16
status: issues_found
---

# Phase 14: Code Review Report

**Reviewed:** 2026-09-28T06:13:59Z
**Depth:** standard
**Files Reviewed:** 37
**Status:** issues_found

## Summary

I reviewed the Phase 14 diff (`d078fc8^..HEAD`). It covers the poller's root-cause incident engine (`compute_incidents`, incident publish/tombstone/reconcile, and the criticality/depends_on label parsers), the dashboard incident store slice, the incident cards, consequence dimming in the tree and map, the `CriticalityEditor` panel and its label writers, the `displayedServices()` limit from dd10079, and the kiosk removal (9f9bbe8).

Baseline: `uv run pytest tests/test_mqtt_poller.py` passes (209 tests), `npx vitest run` passes (455 tests), and `tsc -b` is clean. Passing tests are not evidence of correctness here. None of the findings below is covered by a test.

Main concerns:
- The incident grouping algorithm splits one outage into several incidents when three or more DOWN hosts form a chain. I reproduced this by running `compute_incidents` directly.
- The dashboard never clears incidents it holds in memory when it reconnects to the broker. An incident that closed while the tab was disconnected stays on screen as a ghost card, and its hosts stay dimmed, until the page is reloaded.
- Smaller defects in the editor's rollback logic, in how the TypeScript and Python label parsers diverge, in the `?incident=` deep link, and in the demo runbook's documented output.

Kiosk removal: no functional kiosk code is left. `KioskView`, `useKioskRotation`, the `?kiosk=1` branch, the keyframes and the `fill` prop are all gone. Three cosmetic leftovers remain (IN-01): the pass-through `AppShell` wrapper, an `afterEach` history reset in `App.test.tsx`, and a stray trailing blank line in `index.css`.

## Critical Issues

### CR-01: A chain of three or more DOWN roots is split into separate incidents

**File:** `scripts/mqtt_poller.py:842-849`
**Issue:** `_reachable_roots_from()` stops at the first root it reaches. So `reachable_from_root[r2]` for the chain `r0 (DOWN) <- r1 (DOWN) <- r2 (DOWN)` is `{r1}`, not `{r0}`. The fallback loop then promotes every nested root whose reachable set contains no *top* root. `r1` is nested, not top, so `r2` is wrongly promoted to a top root. The fallback was meant only for parent cycles, but it fires for any nested chain deeper than two.

Reproduced by calling `compute_incidents` directly:
```
snaps = [r0 DOWN, r1 DOWN parent r0, r2 DOWN parent r1, c UNREACH parent r2]
-> incident-r0 {confirmed_down: [r1]}
-> incident-r2 {not_observable: [c]}      # should be one incident rooted at r0
```
A cascade where downstream hosts report DOWN before Checkmk marks them UNREACH (core -> distribution -> access switch) therefore produces two or more cards for one outage. It also under-counts consequences and understates `worst_criticality` on the real root's card. This violates the docstring's step 4 and the deployment doc's rule "DOWN hosts reachable through a contiguous chain of non-OK hosts join the topmost root". The existing test (`test_compute_incidents_nested_down_folds_into_upstream_incident`) only covers a two-level chain.
**Fix:** Resolve nested roots transitively instead of checking one hop. For example, walk from each root through traversable parents *without* stopping at intermediate roots (pass `roots=set()` and collect every root in `visited`), and treat a root as top only when no other root is reachable. Keep the cycle fallback only for roots whose reachable set lies entirely within their own strongly connected group:
```python
def _all_reachable_roots(start_id, roots, traversable, by_id):
    reached, visited = set(), set()
    frontier = [p for p in by_id[start_id].parents if p in by_id]
    while frontier:
        c = frontier.pop()
        if c in visited or c not in traversable:
            continue
        visited.add(c)
        if c in roots:
            reached.add(c)
        frontier.extend(p for p in by_id[c].parents if p in by_id)  # keep walking past roots
    return reached
```
Add a regression test for a DOWN chain of three hosts, plus an UNREACH leaf.

### CR-02: Incidents that close while the dashboard is disconnected never leave the store (ghost incident cards)

**File:** `dashboard-react/src/store/useAppStore.ts:122-140`, `dashboard-react/src/store/mqttClient.ts:86-98`
**Issue:** The `incidents` slice is only ever *removed from* by a zero-length retained tombstone delivered on `lan/incidents/{id}/status`. The client connects with `clean: true`. While the tab is disconnected (broker restart, Wi-Fi blip, laptop sleep), a tombstone published by the poller is never delivered to it. After reconnect, the broker replays only the retained messages that still exist, and a cleared topic has nothing to replay. On `connect`, nothing purges incidents that are absent from the replay. The closed incident therefore stays on the focal "Open incidents" list indefinitely, and its consequence hosts stay dimmed in the tree and on the map ("part of an open incident"), until a full page reload.

For a live at-a-glance display this is wrong information on the most prominent surface. Device status self-corrects on the next per-cycle publish. Incidents are change-triggered only, so they never self-correct.
**Fix:** Reset the incident slice at the start of every (re)subscribe so the retained replay rebuilds it:
```ts
client.on("connect", () => {
  ...
  useAppStore.getState().resetIncidents(); // set({ incidents: {} })
  client?.subscribe(SUBSCRIBE_TOPICS);
});
```
Add a store/mqttClient test: incident present, then reconnect with no replay for it, then incident gone.

## Warnings

### WR-01: A failed optimistic write rolls back into the wrong host's panel, or clobbers a later successful write

**File:** `dashboard-react/src/components/CriticalityEditor.tsx:117-179`
**Issue:** Each handler captures `previous` from the current closure and restores it in `.catch()`. The component is not keyed per host, so two cases go wrong:
1. The operator changes host A's tier, then selects host B before the write settles. If A's write fails, `setCriticalityState(previousOfA)` writes A's old value into B's panel. B's displayed tier is now wrong, and the next edit starts from wrong local state.
2. Two quick edits on the same field (low->high, then high->critical) are serialized by `checkmkWrite`. If the first fails and the second succeeds, the rollback sets `low` while Checkmk holds `critical`.

The same applies to `serviceCriticality` and `dependsOn`.
**Fix:** Key the panel by host (`<CriticalityEditor key={selectedHost ?? "none"} …/>`) so rollbacks from a previous host land in an unmounted instance. Roll back only when the value being reverted is still the one this write set, for example with a per-field write sequence number:
```ts
const seq = ++writeSeq.current;
setCriticality(host, tier).catch(() => { if (seq === writeSeq.current) setCriticalityState(previous); onFailed(...) });
```

### WR-02: The TypeScript `service_criticality` parser silently deletes entries the poller accepts

**File:** `dashboard-react/src/lib/checkmkWrite.ts:195-212` (vs `scripts/mqtt_poller.py:427-437`)
**Issue:** The Python parser `.strip()`s the name and tier. `parseServiceCriticalityLabel` does not. A hand-edited label such as `Service sshd = critical` (the docs invite hand-editing in Setup > Hosts > Labels) is honoured by the poller and shown in the editor as an override. But `setServiceCriticality` for *any* service on that host re-parses the label, drops the untrimmed entry (`" critical"` is not a tier), and writes the label back without it. That is silent data loss of an operator's override. The TypeScript parser also skips Python's 200-entry cap, so the two parsers disagree in both directions despite the "mirrors" comment.
**Fix:** Trim both halves and skip empty names, exactly like Python:
```ts
const name = entry.slice(0, eq).trim();
const tier = entry.slice(eq + 1).trim();
if (name && !name.includes(":") && isCriticalityTier(tier)) result[name] = tier;
```
Add a round-trip test: a label with whitespace, then setting another service, keeps the first entry.

### WR-03: The editor offers service rows the writer always rejects, with a misleading error

**File:** `dashboard-react/src/components/CriticalityEditor.tsx:182,227-240`, `dashboard-react/src/lib/checkmkWrite.ts:50,257-259`
**Issue:** `serviceRows` includes every displayed service. `setServiceCriticality` rejects any name containing `:`, `;` or `=` before any request is made. For a non-agent host, `displayedServices()` returns the full table (for example SNMP interface or filesystem names such as `Filesystem C:/`), so those rows render a working-looking Select that always fails. The failure Snackbar says "Checkmk rejected the update. Check that the device still exists", which is false: Checkmk was never contacted.
**Fix:** Filter or disable rows whose name matches `INVALID_SERVICE_NAME_CHARS_RE`, exported from `checkmkWrite.ts`. Alternatively, show a specific message ("This service name can't carry a criticality override") in place of `COULD_NOT_SAVE`.

### WR-04: The `?incident=` deep link never scrolls on a fresh page load

**File:** `dashboard-react/src/components/IncidentList.tsx:23-37`
**Issue:** The scroll effect depends only on `[highlightedId]`. On a fresh load of `/?incident=incident-x`, the first render has no incidents yet because retained messages arrive after SUBACK. The component returns the empty-state `<div>` without `sectionRef`, so the effect exits early. When the incidents arrive, `highlightedId` has not changed, so the effect never re-runs and the card is never scrolled into view. The README (§5c) documents that this deep link "scrolls the matching card into view". Clicking the same "See incident" link twice also does not re-scroll.
**Fix:** Depend on the presence of the target as well:
```ts
const hasTarget = incidents.some((i) => i.id === highlightedId);
useEffect(() => { ... }, [highlightedId, hasTarget]);
```

### WR-05: The "not live until Apply" claim is likely false for criticality and depends_on labels (verify live)

**File:** `dashboard-react/src/components/CriticalityEditor.tsx:165`, `dashboard-react/README.md:243-246`, `docs/Podman setup for checkmk, minio, mosquitto, worker.md` (criticality labels paragraph)
**Issue:** The poller reads these labels from the REST `host_config` collection (`fetch_host_config`, `scripts/mqtt_poller.py:1226`), not from Livestatus. The REST Setup objects reflect the stored (WATO) configuration, which as far as I know includes unactivated pending changes. So a criticality or depends_on edit probably reaches `worst_criticality`, the topology topic and every viewer on the next poll cycle, *before* Apply. That contradicts the confirm dialog ("This won't take effect until you press Apply changes") and both docs. The operator is told a removal is safe to stage when it is already live. The same REST read path already applies to Phase 13 `map_position`.
**Fix:** Live-verify. Write a label without activating, then check the next `lan/devices/topology` payload. If it is confirmed, correct the confirm text and docs ("takes effect on the dashboard at the next poll; Apply activates it in Checkmk").

### WR-06: A REST failure on the first cycle after startup republishes topology and incidents with every label defaulted

**File:** `scripts/mqtt_poller.py:2403, 2519-2556`
**Issue:** `last_host_config` starts as `{}`. If the first `fetch_host_config()` after a restart raises `RestError` (a transient Checkmk restart, the same race the Livestatus probe retries for), every snapshot gets `criticality="low"`, `depends_on=[]`, `service_criticality={}`, `map_position=None`, `unmanaged=False`. `topology_signature` then differs from the reconciled `previous_nodes`, so a topology is published that wipes every operator label for all viewers. `compute_incidents` also loses its inferred roots (no `unmanaged`) and its criticality. Critical incidents are republished as `low`, which reorders the D-12 list, and inferred incidents collapse into per-child incidents, until REST recovers. The reuse-on-failure comment at line 2393 covers only steady state, not cold start.
**Fix:** Seed `last_host_config` from the reconciled retained topology (`state.previous_nodes`, already normalised by `_normalise_restored_node`) before the loop:
```python
last_host_config = {
    node_id: HostConfigInfo(folder=n["folder"], map_position=n["map_position"], unmanaged=n["unmanaged"],
                            criticality=n["criticality"], service_criticality=dict(n["service_criticality"]),
                            depends_on=list(n["depends_on"]))
    for node_id, n in state.previous_nodes.items()
}
```

### WR-07: The demo runbook documents card descriptions the code never renders

**File:** `docs/Incident demo with fake check results.md:78-80, 105-108`
**Issue:** Scenario A says a lone DOWN host's card shows the description `"1 confirmed down"`. Scenario B says "the switch itself counts as confirmed down". `compute_incidents` never puts the root in `confirmed_down`, and `consequenceSummary()` returns `""` for a root-only incident (asserted by `incidents.test.ts:274-277`). The actual Scenario A card has no summary line at all, and Scenario B shows only `"{M} not observable"`. A stakeholder demo following this run-of-show will look like a bug.
**Fix:** Correct both scenarios to the real output. If the doc's wording is the intended UX, change the product instead, for example by counting a non-inferred DOWN root in the summary.

## Info

### IN-01: Kiosk-removal leftovers

**File:** `dashboard-react/src/App.tsx:27-38`, `dashboard-react/src/App.test.tsx:9-11`, `dashboard-react/src/index.css:49`
**Issue:** `AppShell` existed only to host the `?kiosk=1` branch and is now a pure pass-through wrapper. The `afterEach(() => window.history.pushState({}, "", "/"))` in `App.test.tsx` was added for the kiosk `pushState` tests, which are gone. `index.css` ends with a stray blank line, which is the phase's only net change to that file.
**Fix:** Inline `AppNav` and `Routes` back into `App`, drop the `afterEach` (and the `afterEach` import), and remove the trailing blank line.

### IN-02: `service_criticality` is written, parsed, published and signed, but nothing consumes it

**File:** `scripts/mqtt_poller.py:412-438, 652, 689`, `dashboard-react/src/components/CriticalityEditor.tsx:224-242`
**Issue:** The deployment doc confirms that per-service criticality "does not feed `worst_criticality` in Phase 14". The editor UI, the label writer, two parsers, topology payload bloat and a signature term all exist for a value with no effect. Operators can set it and see nothing change. That is speculative scope under CLAUDE.md's "Simplicity First" rule.
**Fix:** Either wire it into incident severity, or label the editor section "(not yet used for incident ranking)" so operators are not misled.

### IN-03: Unmanaged switch that is itself DOWN is reported as `inferred`

**File:** `scripts/mqtt_poller.py:822-830, 872-882`
**Issue:** An `unmanaged` host with at least two non-OK children lands in `inferred_roots` even when its own `host_state_raw` is DOWN. That can happen with a label edited by hand onto a monitored host. Its incident then reports every consequence as `not_observable` and shows "Inferred, not confirmed", although the root is observably DOWN.
**Fix:** Only infer when the unmanaged host's own state is UP (`snapshot.host_state_raw == "UP"`).

### IN-04: "No open incidents" empty state overclaims

**File:** `dashboard-react/src/components/IncidentList.tsx:41-47`
**Issue:** "Every device the poller can reach is reporting normally" is shown when there are CRIT or WARN services (these never create incidents), when an UNREACH host has no DOWN ancestor (excluded from incidents), and before the connection or retained replay has completed (for example while disconnected). All three contradict the D-04 "never overclaim" posture.
**Fix:** Use neutral copy ("No open host-level incidents"), and/or render nothing until the connection phase is `connected`.

### IN-05: Invalid or duplicate-prone DOM ids from service names

**File:** `dashboard-react/src/components/CriticalityEditor.tsx:231`
**Issue:** `id={`criticality-editor-service-${name}`}` embeds raw service names containing spaces and `/`. Whitespace in an `id` is invalid HTML, and label association and `getElementById` become unreliable.
**Fix:** Use the row index or a sanitised slug for the id, and keep `aria-label={name}`.

### IN-06: "View devices" toggle has no expanded state and can expand to nothing

**File:** `dashboard-react/src/components/IncidentCard.tsx:103-109`
**Issue:** The button lacks `aria-expanded`. For a root-only incident with no dependents it expands to an empty span.
**Fix:** Add `aria-expanded={expanded}`, and hide the button when all three lists are empty.

### IN-07: Garbled sentence in README §5d

**File:** `dashboard-react/README.md:236-237`
**Issue:** "Any stale label entry for a service no longer monitored, so a leftover override can still be cleared)" has an unmatched parenthesis and no verb. Part of the sentence was lost when dd10079 rewrote the bullet.
**Fix:** "…any other host lists all of its services (plus any stale label entry for a service no longer monitored, so a leftover override can still be cleared), each a `Select`…"

## Conventions

Output of `gsd-tools verify conventions --check` on the changed TS/TSX files:

- **CONVENTION** `dashboard-react/src/components/IncidentList.tsx:34`: the catch block swallows the error (empty, no rethrow). Derived convention: "architectural-split: error handling — swallowed catches hide failures". Suggested fix: keep the swallow, since it is deliberate for an untrusted query string, but add `// intentionally ignored` next to the existing comment, or narrow the try to the `querySelector` call. Advisory only.
- Suppressed as tool false positives: 10 "identifier-casing should be camel" findings on React components (`App`, `AppNav`, `AppShell`, `CriticalityEditor`, `DeviceLinkList`, `IncidentCard`, `IncidentList`, `TopologyMap`, `TreeNode`, `IndexRoute`). React requires PascalCase component names, and the rest of the codebase follows that. No action recommended.

---

_Reviewed: 2026-09-28T06:13:59Z_
_Reviewer: Claude (bm-code-reviewer)_
_Depth: standard_

## Fix Status (2026-09-28)

| Finding | Outcome |
| --- | --- |
| CR-01 | Fixed in `24b22f5`, with regression tests for a 3-level DOWN chain and a DOWN parent cycle |
| CR-02 | Fixed in `a1a73cf` (`resetIncidents()` on every connect), with a regression test |
| WR-04 | Fixed in `a1a73cf`, with a regression test |
| WR-06 | Fixed in `24b22f5` (`host_config_from_topology()` seeds the cache), with a test |
| WR-07 | Fixed in `a1a73cf` (runbook text) |
| IN-07 | Fixed in `c5ffc6a` |
| WR-01, WR-02, WR-03, WR-05, IN-02 | Deferred to `.planning/todos/pending/2026-09-28-revisit-criticality-and-dependency-model.md` (editor redesign) |
| IN-01, IN-03, IN-04, IN-05, IN-06 | Not fixed; minor, left as is |
