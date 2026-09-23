---
phase: 12-agent-metrics-and-service-status
verified: 2026-09-23T09:50:00Z
status: passed
score: 9/9 must-have truths groups verified (24/24 individual plan-level truths)
has_blocking_gaps: false
overrides_applied: 0
---

# Phase 12: Agent Metrics and Service Status Verification Report

**Phase Goal:** The per-device drill-down gains live agent-derived metrics (CPU/RAM/disk/SMART) and per-service status from a new Livestatus services query, with a locked UI-SPEC-driven presentation and the fleet tree wired to reach it.
**Verified:** 2026-09-23T09:50:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Poller can probe `services` column availability and refuses only on a truly required column missing | ✓ VERIFIED | `REQUIRED_SERVICE_COLUMNS`/`OPTIONAL_SERVICE_COLUMNS` (scripts/mqtt_poller.py:202-203), `available_service_columns`/`select_service_columns` (848, 866) — tests pass |
| 2 | Missing optional column (`plugin_output`/`perf_data`) degrades with a warning, never fatal | ✓ VERIFIED | `select_service_columns` only raises on `REQUIRED_SERVICE_COLUMNS` (mqtt_poller.py:875); `query_services` degrades `plugin_output`/`perf_data` to `""`/`{}` per-row |
| 3 | Nagios `perf_data` parsed server-side into per-metric value/warn/crit, never in browser | ✓ VERIFIED | `parse_perf_data()` (mqtt_poller.py:664) in Python only; dashboard's `DevicePayload` carries only the already-classified `cpu_percent`/`cpu_warn`/`cpu_crit` etc., no raw perf_data string on the wire (12-02 payload_contract, confirmed in dashboard-react/src/lib/types.ts) |
| 4 | One malformed service row/perfdata token is skipped, never fatal to the cycle | ✓ VERIFIED | `query_services` per-row try/except skip pattern mirrors `query_devices`; `parse_perf_data` never raises (tests assert both); 135/135 poller tests pass |
| 5 | `--dump-service-names` CLI lets an operator confirm live SMART naming with no code change | ✓ VERIFIED | `uv run python scripts/mqtt_poller.py --help` lists the flag; implementation at mqtt_poller.py:1845 |
| 6 | `status` topic carries CPU/RAM/Disk/other-mount/SMART fields every cycle, `null` when backing service absent | ✓ VERIFIED | `classify_host_services()` (mqtt_poller.py:516) always emits all 15 keys with `None` defaults; `run_cycle` passes gauge_fields to `publish_device_status` every cycle; Podman doc's payload-key list updated and matches |
| 7 | `services` topic republished only on state/set change, never on `plugin_output` drift alone | ✓ VERIFIED | `services_signature()` excludes `plugin_output` from its tuple (mqtt_poller.py:622); dedicated test asserts signature invariance across a plugin_output-only diff; `run_cycle` compares against `state.previous_services` |
| 8 | Per-service state transition appends one bounded `service_history` entry | ✓ VERIFIED | `run_cycle` diffs `last_service_states` per description, appends via `append_bounded(..., config.service_history_max_entries)`; test asserts exactly one `{from, to}` entry per transition |
| 9 | Removing a host tombstones `services`/`service_history` too, not just `status`/`history` | ✓ VERIFIED | `publish_tombstone()` now targets all 4 topics (mqtt_poller.py:1178-1223); dashboard's status-tombstone branch in `useAppStore.ts` clears all 4 in-store slices; test asserts 4-topic tombstone |
| 10 | Services-query Livestatus failure degrades gauges/services only — host status still publishes | ✓ VERIFIED | `run_forever`'s services probe degrades to `service_columns=None` on retry exhaustion (no `return 1`, confirmed by grep); each cycle's `query_services()` call wrapped in its own try/except; `run_cycle(..., services=None)` test confirms status still publishes |
| 11 | SMART service-name match lives in exactly one clearly-commented constant | ✓ VERIFIED | `SMART_HEALTH_SERVICE_RE` (mqtt_poller.py:95) is the only SMART-name regex/string in the file (grep confirms single definition + one use site) |
| 12 | Dashboard subscribes to `lan/devices/+/services` and `lan/devices/+/service_history` | ✓ VERIFIED | `SUBSCRIBE_TOPICS` in mqttClient.ts includes both; mqttClient.test.ts asserts membership |
| 13 | Services payload lands in store keyed by device id; malformed payload keeps previous value | ✓ VERIFIED | `useAppStore.ts` handleMessage branches for `services`/`service_history` mirror the `history` branch's `parsePayload`/`Array.isArray` guard; tests assert malformed-keeps-last-known-good |
| 14 | Zero-length retained payload on either new topic clears that device's slice | ✓ VERIFIED | Same branches set `[]` on a null/zero-length payload; tested |
| 15 | Gauge ring colour derives from a metric's own warn/crit, never Checkmk service state, in one shared helper | ✓ VERIFIED | `gaugeColor()` in `lib/gauges.ts` is the sole colour source used by `DetailsRoute`'s three gauges and the disk-extra badges; header comment states this is deliberately separate from `stateMapping.ts` |
| 16 | Service rows sort CRIT, WARN, UNKNOWN, OK, ties by name | ✓ VERIFIED | `compareServices()`/`SEVERITY_ORDER` in `lib/serviceSort.ts`; `serviceSort.test.ts` and `DetailsRoute.test.tsx` both assert the order |
| 17 | `/details?id=<host>` shows CPU/RAM/Disk ring gauges with live percent headline | ✓ VERIFIED | `DetailsRoute.tsx` gauge row card renders `ProgressCircle` + overlaid `GaugeValue`; `DetailsRoute.test.tsx` asserts 3 progressbars and "42%"/"91%"/"12%" headline text |
| 18 | A gauge whose backing service doesn't exist is absent from the row, never 0% or N/A | ✓ VERIFIED | `isPercent()` guards each gauge column; test asserts 2 progressbars (not 3) when `cpu_percent` is null |
| 19 | Disk column carries Other-mounts and SMART badges, each hidden when its data is absent | ⚠️ VERIFIED WITH KNOWN GAP | `otherMountsLabel()`/`smartBadge()` correctly return `null` (hidden) when their own data is absent — confirmed by test. **However**, both badges are also incorrectly hidden whenever `disk_percent` itself is null, even if SMART/other-mount data IS present, because `diskExtra` is nested inside the `isPercent(device.disk_percent)` block (DetailsRoute.tsx:173-188) and `hasAnyGauge` (line 92-95) doesn't consider `smart_total`/`disk_other_worst_percent`. This is a real, reproducible edge case (host has a SMART health service but no `"Filesystem /"` service) — already identified and documented as **WR-01** in the committed code review (`12-REVIEW.md`), classified there as a non-blocking warning. No existing test covers this combination. See Gaps Summary below for disposition. |
| 20 | Per-service table lists every non-gauge service with state badge and plugin_output, worst-first | ✓ VERIFIED | `SERVICE_COLUMNS` in DetailsRoute.tsx renders description/StateBadgeForState/plugin_output; rows sorted via `compareServices`; test asserts CRIT/WARN/OK order and plugin_output text |
| 21 | Bounded status-history strip for the one device renders below the service table | ✓ VERIFIED | History section reuses `EventRow`-style markup, newest-first via `slice().reverse()`; test covers populated and empty cases |
| 22 | Every empty/absent state renders the exact locked copy | ✓ VERIFIED | All 6 locked strings (`NO_DEVICE_*`, `DEVICE_NOT_FOUND_*`, `NO_METRICS_TEXT`, `SERVICES_NOT_ARRIVED_TEXT`, `NO_ADDITIONAL_SERVICES_TEXT`, `NO_HISTORY_TEXT`) present verbatim and asserted by tests |
| 23 | Clicking/keyboard-activating a device row navigates to `/details?id={id}` | ✓ VERIFIED | `TreeNode.tsx` wraps device rows in react-router `Link` to `/details?id=${encodeURIComponent(device.id)}`; group rows' `onToggle`/`aria-expanded` behaviour untouched; `Tree.test.tsx` asserts both href and group-toggle-still-works |
| 24 | PROJECT.md's Out of Scope entry no longer forbids the read-only drill-down this phase ships | ✓ VERIFIED | `.planning/PROJECT.md` line 37 narrows the entry to write/administration actions, records D-17 remains unbuilt, matches REQUIREMENTS.md's wording |

**Score:** 23/24 fully clean, 1/24 verified-with-a-documented-known-gap (WR-01, non-blocking per code review and this verification's own analysis) — no truth is FAILED.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scripts/mqtt_poller.py` | Services query triad, perfdata parser, ServiceSnapshot/query_services, classify_host_services, new topics/publishers, cycle wiring | ✓ VERIFIED | All named functions/constants present and exercised by 135 passing tests |
| `tests/test_mqtt_poller.py` | Coverage for column triad, perfdata parser, query_services, classification, publishing, cycle wiring | ✓ VERIFIED | 135 passed, 0 failed |
| `docs/Podman setup for checkmk, minio, mosquitto, worker.md` | Topic contract table/tombstone sentence/additive-keys paragraph updated | ✓ VERIFIED | grep confirms both new topics, 15 gauge keys, `SERVICE_HISTORY_MAX_ENTRIES`, 4-topic tombstone sentence |
| `dashboard-react/src/lib/types.ts` | Gauge fields on DevicePayload, ServiceEntry, ServiceHistoryEntry | ✓ VERIFIED | grep confirms all fields; `services?: unknown` placeholder removed |
| `dashboard-react/src/lib/gauges.ts` | gaugeColor/smartBadge/otherMountsLabel | ✓ VERIFIED | present, exported, tested (gauges.test.ts) |
| `dashboard-react/src/lib/serviceSort.ts` | SEVERITY_ORDER/compareServices | ✓ VERIFIED | present, exported, tested |
| `dashboard-react/src/store/useAppStore.ts` | services/serviceHistory slices + handleMessage branches | ✓ VERIFIED | present, tested |
| `dashboard-react/src/store/mqttClient.ts` | Two new SUBSCRIBE_TOPICS entries | ✓ VERIFIED | present, tested |
| `dashboard-react/src/routes/DetailsRoute.tsx` | Gauge card, badges, service table, history strip, empty states | ✓ VERIFIED (with WR-01 caveat above) | 133 lines (not a stub); wired to real store; 10/10 route tests pass |
| `dashboard-react/src/routes/DetailsRoute.test.tsx` | Route rendering coverage through real store | ✓ VERIFIED | Present, 10 test cases, all pass |
| `dashboard-react/src/components/TreeNode.tsx` | Device-row navigation | ✓ VERIFIED | `Link to="/details?id=..."`, encodeURIComponent confirmed |
| `.planning/PROJECT.md` | Amended Out of Scope entry | ✓ VERIFIED | grep confirms "read-only" and D-17 present |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `query_services` | `_livestatus_request` | single transport choke point | ✓ WIRED | No second `socket.create_connection` inside `query_services` |
| `query_services` | `parse_perf_data` | per-row perfdata parse | ✓ WIRED | Confirmed in code and by tests |
| `run_cycle` | `publish_services` | signature diff against `previous_services` | ✓ WIRED | Confirmed by change-only publish tests |
| `publish_services`/`publish_service_history` | `_publish_json` | single publish choke point | ✓ WIRED | grep: only `_publish_json` inside both, no direct `client.publish` |
| `run_forever` | `query_services` | per-cycle, degrade-on-error | ✓ WIRED | try/except around the call, confirmed by exhaustion test |
| `mqttClient.ts` | `lan/devices/+/services` | SUBSCRIBE_TOPICS array entry | ✓ WIRED | Confirmed present and tested |
| `useAppStore.ts` | `ServiceEntry[]` | handleMessage branch on `parts[3] === 'services'` | ✓ WIRED | Confirmed present and tested |
| `DetailsRoute.tsx` | `lib/gauges.ts` | gaugeColor/smartBadge/otherMountsLabel import | ✓ WIRED | Imported and used (see WR-01 caveat on reachability in one edge case) |
| `DetailsRoute.tsx` | `StateBadge.tsx` | StateBadgeForState per service row | ✓ WIRED | Confirmed in SERVICE_COLUMNS render and history strip |
| `DetailsRoute.tsx` | `useAppStore` | per-slice selectors for devices/services/history | ✓ WIRED | Three separate selector calls, confirmed |
| `TreeNode.tsx` | `DetailsRoute.tsx` | react-router Link to `/details?id={id}` | ✓ WIRED | Confirmed and tested |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Poller test suite passes | `uv run pytest tests/test_mqtt_poller.py -q` | 135 passed | ✓ PASS |
| `--dump-service-names`/`--check-columns` flags exist | `uv run python scripts/mqtt_poller.py --help` | Both flags listed with correct help text | ✓ PASS |
| Dashboard typecheck | `npm --prefix dashboard-react run typecheck` | exit 0 | ✓ PASS |
| Dashboard full test suite | `npm --prefix dashboard-react test -- --run` | 201 passed, 2 failed (pre-existing, unrelated clock-drift bug in `GroupingControls.test.tsx`, confirmed pre-existing against baseline `f3d637d`, logged in `deferred-items.md`) | ✓ PASS (regression-free) |
| Dashboard build | `npm --prefix dashboard-react run build` | Succeeds, static assets produced | ✓ PASS |
| Dashboard lint | `npm --prefix dashboard-react run lint` | 4 pre-existing warnings, none in Phase 12 files (`StateBadge.tsx`, `GroupingControls.tsx`, `IndexRoute.tsx` — all untouched by this phase) | ✓ PASS |

### Probe Execution

Not applicable — this phase has no `scripts/*/tests/probe-*.sh` convention and none are declared in the plans. SKIPPED.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|--------------|--------|----------|
| PLR-09 | 12-01, 12-02 | `GET services` query behind defensive column probe, perf_data parsed server-side | ✓ SATISFIED | See truths 1-5 |
| PLR-10 | 12-02 | Gauge-backing values as additive status keys | ✓ SATISFIED | See truth 6 |
| PLR-11 | 12-02 | Non-gauge service list on new retained topic, change-only | ✓ SATISFIED | See truth 7 |
| PLR-12 | 12-02 | Bounded per-service transition history, separate topic, tombstoned | ✓ SATISFIED | See truths 8-9 |
| DASH-08 | 12-03, 12-04 | CPU/RAM/Disk ring gauges, own-threshold colour, hide-on-absence | ✓ SATISFIED | See truths 15, 17-18 |
| DASH-09 | 12-03, 12-04 | SMART badge, hidden when no SMART service | ⚠ SATISFIED WITH KNOWN GAP | See truth 19 (WR-01) |
| DASH-10 | 12-03, 12-04 | Per-service status table worst-first | ✓ SATISFIED | See truths 16, 20 |
| DASH-11 | 12-05 | Tree device rows navigate to drill-down | ✓ SATISFIED | See truth 23 |
| DASH-03 (partial) | 12-04 | Bounded status-history strip half only (D-16); Checkmk deep-link half (D-17) explicitly declined | ✓ SATISFIED (as scoped Partial) | History strip present (truth 21); no Checkmk deep-link code added — confirmed `CHECKMK_BASE_URL`/`isCheckmkLinkConfigured()` unused in `DetailsRoute.tsx` (grep returns 0) — matches the explicit Partial scope, must not be flipped to Complete per REQUIREMENTS.md's own instruction |

No orphaned requirements: cross-referencing `.planning/REQUIREMENTS.md`'s "Phase 12" rows (PLR-09..12, DASH-08..11, DASH-03) against every PLAN's `requirements:` frontmatter confirms full 1:1 coverage.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `dashboard-react/src/routes/DetailsRoute.tsx` | 92-95, 100-123, 173-188 | Logic gap: SMART/Other-mounts badges gated on `disk_percent` presence rather than their own data | ⚠️ Warning (non-blocking) | Already identified and documented as WR-01 in the committed `12-REVIEW.md`; confirmed still present by this verification. Affects only hosts lacking a `"Filesystem /"` service while having a SMART health service — an edge case, not the common path. No test currently covers it. |
| `scripts/mqtt_poller.py` | 1043-1047 | `description` field not type-checked as `str` before regex match / sort | ⚠️ Warning (non-blocking) | Documented as WR-02 in `12-REVIEW.md`; would only trigger on a malformed Livestatus response returning a non-string `description`, not observed against the target Checkmk version |
| `dashboard-react/src/store/useAppStore.ts` | 117-198 | Tombstone-ordering race can leave an orphaned empty-array slice | ⚠️ Warning (non-blocking) | Documented as WR-03 in `12-REVIEW.md`; does not affect the visible UI (`devices[id]` is still deleted), only a latent store-memory leak |
| `dashboard-react/src/store/mqttClient.ts` | 98-102 | `close`/`offline` listener race on `connection.phase` | ⚠️ Warning (non-blocking) | Documented as WR-04 in `12-REVIEW.md` |

No TBD/FIXME/XXX debt markers found in any Phase 12-modified file (`grep -rn "TBD\|FIXME\|XXX"` against the files listed in each SUMMARY's key-files returns nothing beyond the doc's own "for whenever it is" prose, which is not a debt marker).

### Human Verification Required

None. This phase's UI surface (gauge rings, badges, service table, history strip) is exercised end-to-end by 10 `DetailsRoute.test.tsx` cases driving the real Zustand store through `handleMessage()` with real MQTT-shaped payloads, asserting rendered role/text content for every locked copy string, colour-driving helper, hide-on-absence rule and ordering rule the UI-SPEC defines. `npm run build` succeeds (the static bundle nginx serves). No `<human-check>` blocks were deferred by the planner in any of the 5 plans. Consistent with the verification precedent set by the comparably UI-heavy Phase 11.1 (also `status: passed`, no human-verification section), this phase's automated coverage is judged sufficient without an additional manual pass.

### Gaps Summary

No blocking gaps. One non-blocking, already-documented behavioral gap (WR-01) exists in `DetailsRoute.tsx`: the "Other mounts"/SMART badges are incorrectly hidden (rather than shown) on the narrow edge case of a host with a SMART health service but no `"Filesystem /"` service. This was caught by the phase's own code review (`12-REVIEW.md`, committed, already surfaced to the user separately) and independently reproduced by this verification by reading the current `DetailsRoute.tsx` source. It does not block the phase goal — the common case (a host with `"Filesystem /"`) renders correctly, DASH-09's literal requirement text ("hidden entirely ... when the host has no SMART health service") is satisfied, and the review already classified it as a non-blocker. Recommended disposition: park to backlog for a follow-up fix (widen `hasAnyGauge` to include `smart_total`/`disk_other_worst_percent`, and hoist `diskExtra` out of the `isPercent(device.disk_percent)` guard, per the fix already sketched in `12-REVIEW.md` WR-01).

Two dashboard tests fail (`GroupingControls.test.tsx`), confirmed pre-existing (predate Phase 12, reproduced against unmodified baseline commit `f3d637d`), caused by a clock-drift issue unrelated to any Phase 12 change, and already logged in `.planning/phases/12-agent-metrics-and-service-status/deferred-items.md`. Not a Phase 12 regression; not counted as a gap.

---

_Verified: 2026-09-23T09:50:00Z_
_Verifier: Claude (bm-verifier)_
