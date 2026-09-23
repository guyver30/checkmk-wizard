---
phase: 12-agent-metrics-and-service-status
reviewed: 2026-09-23T00:00:00Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - dashboard-react/src/App.test.tsx
  - dashboard-react/src/components/GroupingControls.test.tsx
  - dashboard-react/src/components/StaleStability.test.tsx
  - dashboard-react/src/components/Tree.test.tsx
  - dashboard-react/src/components/TreeNode.tsx
  - dashboard-react/src/lib/gauges.test.ts
  - dashboard-react/src/lib/gauges.ts
  - dashboard-react/src/lib/serviceSort.test.ts
  - dashboard-react/src/lib/serviceSort.ts
  - dashboard-react/src/lib/types.ts
  - dashboard-react/src/routes/DetailsRoute.test.tsx
  - dashboard-react/src/routes/DetailsRoute.tsx
  - dashboard-react/src/store/mqttClient.test.ts
  - dashboard-react/src/store/mqttClient.ts
  - dashboard-react/src/store/selectors.test.ts
  - dashboard-react/src/store/useAppStore.test.ts
  - dashboard-react/src/store/useAppStore.ts
  - docs/Podman setup for checkmk, minio, mosquitto, worker.md
  - scripts/mqtt_poller.py
  - tests/test_mqtt_poller.py
findings:
  critical: 0
  warning: 4
  info: 3
  total: 7
status: issues_found
---

# Phase 12: Code Review Report

**Reviewed:** 2026-09-23T00:00:00Z
**Depth:** standard
**Files Reviewed:** 19 (of 20 listed; `App.test.tsx` was read for context but only exercises pre-existing/Phase-13-stub behavior)
**Status:** issues_found

## Summary

This phase (12-01 through 12-05) adds agent gauges (CPU/RAM/disk/SMART) and per-service status/history to the dashboard, both on the Python poller side (`scripts/mqtt_poller.py`) and the React dashboard side (`DetailsRoute.tsx`, `gauges.ts`, `serviceSort.ts`, `useAppStore.ts`, `mqttClient.ts`). The code is unusually well-documented (dated bug-fix comments, live-verification citations, explicit design-decision references) and the test suites are broad and mostly precise mirrors of the implementation — most of the obvious defect classes (malformed JSON, wrong-shape payloads, missing columns, tombstone edge cases, backoff math) are both handled defensively and independently tested.

No BLOCKER-level defects were found: nothing crashes the app, no injection/XSS/secret-handling issues were introduced, and the state machine (Zustand store, MQTT reconnect backoff, poller reconcile-on-restart) behaves correctly for every path the tests exercise. The findings below are narrower correctness/robustness gaps that sit outside what the existing tests cover — real bugs in under-tested corners, not stylistic nitpicks.

## Warnings

### WR-01: SMART/Other-mounts badges are unreachable whenever a device has no CPU/RAM/Disk gauge reading

**File:** `dashboard-react/src/routes/DetailsRoute.tsx:92-95, 100-123, 140-193`

**Issue:** `gauges.ts`'s own design comment states the SMART badge is an independent signal — "D-06: null/undefined/zero `total` means this host has no SMART-monitored disks -- hide the badge entirely ... rather than show a misleading N/A" — implying it should appear whenever `smart_total > 0`, regardless of the CPU/RAM/disk gauges. In `DetailsRoute.tsx`, however:

- `hasAnyGauge` (lines 92-95) only checks `cpu_percent`/`ram_percent`/`disk_percent`, never `smart_total` or `disk_other_worst_percent`. If all three are `null` (e.g. a device whose `Filesystem /` service isn't present but that does have a SMART health service), the entire gauge `<section>` is replaced by `<p>{NO_METRICS_TEXT}</p>` (line 192), so the SMART badge can never render at all — even though `smart_total`/`smart_failing` are populated.
- Even when `hasAnyGauge` is true because `cpu_percent`/`ram_percent` have values, `diskExtra` (the div containing both the "Other mounts" badge and the SMART badge, lines 100-123) is only spliced into the JSX inside the `isPercent(device.disk_percent) && (...)` block (line 186, inside the block spanning 173-188). If `disk_percent` is `null` but `smart_total`/`disk_other_worst_percent` are populated, neither badge renders, because the block that would render them is gated on an unrelated field.

No existing test exercises "SMART/other-mounts data present, disk_percent absent" (`DetailsRoute.test.tsx`'s SMART/Other-mounts tests all include `disk_percent: 10`), so this gap is untested as well as unhandled.

**Fix:** Include `smart_total`/`disk_other_worst_percent` in `hasAnyGauge`'s truthiness check, and move `diskExtra` out from under the `isPercent(device.disk_percent)` guard (e.g. render it in the flex row unconditionally, or guard it on `otherMountsText || smart` alone, which is already the check `diskExtra`'s own ternary uses):

```tsx
const hasAnyGauge =
  typeof device.cpu_percent === "number" ||
  typeof device.ram_percent === "number" ||
  typeof device.disk_percent === "number" ||
  typeof device.smart_total === "number" ||
  typeof device.disk_other_worst_percent === "number";
```
and render `{diskExtra}` alongside the gauge row rather than nested inside the disk-gauge-only block.

---

### WR-02: `ServiceSnapshot.description` is never type-checked before being matched against a regex / sorted

**File:** `scripts/mqtt_poller.py:1043-1047` (extraction), `567` and `608-618` (`classify_host_services` consumption)

**Issue:** `query_services()` extracts `description` with only an `IndexError`/`TypeError` guard around the row-index lookup:

```python
try:
    description = row[index["description"]]
except (IndexError, TypeError):
    _logger.warning("Skipping malformed services row: %r", row)
    continue
```

Unlike every other extracted field in this same function (`plugin_output` — line 1060, `perf_data` — line 1067) and unlike `host_name`'s validation via `is_publishable_device_id()`, the *value* of `description` is never validated as a `str`. If Livestatus ever returns a non-string (`null`, a number, a list) for this column — the same kind of defensive scenario this module explicitly designs around elsewhere (T-09-03, T-12-01/T-12-02) — `classify_host_services()`'s `SMART_HEALTH_SERVICE_RE.match(s.description)` (line 567) raises `TypeError: expected string or bytes-like object`, uncaught by any try/except in `run_cycle()`/`classify_host_services()`, crash-looping that poll cycle (or the whole `--once` run). `sorted(..., key=lambda row: row["description"])` (line 617) would similarly raise or produce inconsistent ordering against mixed types.

**Fix:** Coerce/validate the same way `plugin_output` already is:
```python
try:
    description = row[index["description"]]
except (IndexError, TypeError):
    _logger.warning("Skipping malformed services row: %r", row)
    continue
if not isinstance(description, str):
    _logger.warning("Skipping service row with non-string description: %r", row)
    continue
```

---

### WR-03: Tombstone ordering race can leave an orphaned empty-array slice behind for a removed device

**File:** `dashboard-react/src/store/useAppStore.ts:117-198`

**Issue:** The poller's `publish_tombstone()` (`scripts/mqtt_poller.py:1199-1223`) tombstones `status`, `history`, `services` and `service_history` as four independent MQTT publishes with no ordering guarantee between them. `useAppStore.handleMessage()`'s `status`-tombstone branch (lines 123-138) proactively deletes all four in-store slices as soon as the `status` tombstone arrives, anticipating that the others "may arrive before the services/service_history ones" (comment at lines 126-128). But the reverse race isn't handled: if the `status` tombstone is processed *first* (deleting `devices[id]`/`history[id]`/`services[id]`/`serviceHistory[id]`), and one of the other three topics' own zero-length tombstone arrives *afterward*, that handler (e.g. the `history` branch, lines 153-156) unconditionally does `set({ history: { ...get().history, [id]: [] } })` — which **re-adds** an empty-array entry for an id that was just deleted. The device itself (`devices[id]`) stays deleted so the UI is unaffected (`DetailsRoute` and the tree both key off `devices`), but the store accumulates a stray, permanently-orphaned `history[id] = []` / `services[id] = []` / `serviceHistory[id] = []` entry for every removed device whose per-topic tombstones arrive after its status tombstone — exactly the "leak memory on a long-lived kiosk tab" failure mode the module's own header comment (lines 9-12) says this replace-not-append design exists to avoid.

**Fix:** Guard the non-status tombstone branches with an existence check against `devices`, e.g.:
```ts
if (parsed.value === null) {
  if (!(id in get().devices)) return; // already tombstoned via the status topic
  set({ history: { ...get().history, [id]: [] } });
  return;
}
```
(applied to the `history`/`services`/`service_history` branches).

---

### WR-04: `close` and `offline` mqtt.js listeners can race and leave `connection.phase` inconsistent with the actual reconnect countdown

**File:** `dashboard-react/src/store/mqttClient.ts:98-102`

**Issue:** `scheduleReconnect()` (invoked from the `close` listener) sets `connection.phase` to `"reconnecting"` with a `delayMs`. The separate `offline` listener unconditionally sets `connection.phase` to `"disconnected"` with no `delayMs`. mqtt.js documents both `close` and `offline` as firing around a lost connection, but their relative order (and whether both always fire) isn't part of the documented/tested contract here — `mqttClient.test.ts` only asserts each event in isolation (`fake.emit("close")` and `fake.emit("offline")` are never combined in one test). If a real broker drop emits `offline` after `close`, the UI's reconnect countdown (driven by `connection.delayMs`) would be silently overwritten by a plain "Disconnected" state with no indication a retry is already scheduled and in flight.

**Fix:** Either derive `"disconnected"` vs `"reconnecting"` from a single source of truth (e.g. only the `close` handler's `scheduleReconnect()` writes connection state, and `offline` becomes a no-op / debug log), or make the `offline` handler defer to the current phase if a reconnect is already scheduled. At minimum, add a test that fires both events in the order a real mqtt.js client would to pin the intended behavior.

## Info

### IN-01: `SUBSCRIBE_TOPICS` test description is stale ("five topics") for a seven-topic list

**File:** `dashboard-react/src/store/mqttClient.test.ts:73`, cross-referenced against `dashboard-react/src/store/mqttClient.ts:29-37`

**Issue:** The test `"subscribes to all five topics and sets phase to connected on connect, resetting attempt"` asserts against the full `SUBSCRIBE_TOPICS` array, which now has seven entries (`status`, `history`, `services`, `service_history`, `topology`, `lan/events/recent`, `lan/poller/status`). The assertion itself is correct (`toHaveBeenCalledWith(SUBSCRIBE_TOPICS)`), but the test name/description undercounts by two, likely left over from before Phase 12 added the `services`/`service_history` wildcard topics.

**Fix:** Rename to `"subscribes to every configured topic..."` or update the count to seven so the test's stated intent doesn't drift from what it verifies.

### IN-02: `isFinitePositiveThreshold` doesn't actually check positivity

**File:** `dashboard-react/src/lib/gauges.ts:12-14`

**Issue:** The helper is named `isFinitePositiveThreshold` but only checks `typeof value === "number" && Number.isFinite(value)` — it never checks `value > 0` (or `>= 0`). In practice warn/crit thresholds are always non-negative percentages from Checkmk, so this has no observed functional impact, but the name over-promises what the guard does, which could mislead a future maintainer into assuming negative thresholds are already excluded.

**Fix:** Either rename to `isFiniteThreshold` (matching actual behavior) or add the positivity check if it's actually intended.

### IN-03: Conventions checker unavailable in this environment

**Issue:** Per the review instructions, the standalone conventions rule-pack (`bin/gsd-tools.cjs verify conventions`) should run against the changed `.ts`/`.tsx` files to emit CONVENTION-tier findings. The `gsd-plugin` cache directory (`$CLAUDE_PLUGIN_ROOT` / `~/.claude/plugins/cache/gsd-plugin/bm/*/`) does not exist in this environment, so the tool could not be located or invoked. Per the tool's documented never-throws/skip contract, no CONVENTION-tier findings are emitted this run — this is a tooling-availability gap, not a statement that the code has no convention deviations.

---

_Reviewed: 2026-09-23T00:00:00Z_
_Reviewer: Claude (bm-code-reviewer)_
_Depth: standard_
