---
phase: quick-261004-kbt
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - scripts/mqtt_poller.py
  - tests/test_mqtt_poller.py
  - scripts/smoke_test_poller.py
  - deploy/compose.yaml
  - dashboard-react/src/lib/topics.ts
  - dashboard-react/src/lib/types.ts
  - dashboard-react/src/lib/config.ts
  - dashboard-react/src/store/useAppStore.ts
  - dashboard-react/src/store/useAppStore.test.ts
  - dashboard-react/src/store/selectors.test.ts
  - dashboard-react/src/store/mqttClient.test.ts
  - dashboard-react/src/components/HostDetails.test.tsx
  - dashboard-react/README.md
  - docs/MQTT-CONTRACT-WALKTHROUGH.md
  - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
  - .planning/PROJECT.md
autonomous: true
requirements: [PLR-05, PLR-06, PLR-12]

must_haves:
  truths:
    - "A poll cycle with a host state change and a service state change publishes nothing on any `.../lan/devices/{id}/history` or `.../lan/devices/{id}/service_history` topic, and still publishes `lan/events/recent`, `status` and `services` as before"
    - "ClickHouse writes (`build_history_rows()` / `write_history()`) are unchanged and remain the only host/service transition history"
    - "On startup, every retained non-empty `sites/<site_id>/lan/devices/+/history` and `+/service_history` topic is cleared once by the existing `allow_stale_sweep` legacy sweep, with no events emitted and no live `status`/`services` topic touched"
    - "Removing a host still tombstones its `status`, `services`, and (legacy, for one release) `history` and `service_history` topics"
    - "The dashboard no longer subscribes to or stores history/service_history; a status tombstone still removes the device and its services"
  artifacts:
    - path: "scripts/mqtt_poller.py"
      provides: "Poller without per-device history publishing; legacy history topics swept and tombstoned"
    - path: "tests/test_mqtt_poller.py"
      provides: "No-history-publish test and retained-history sweep test"
    - path: "dashboard-react/src/store/useAppStore.ts"
      provides: "Store without history/serviceHistory slices"
  key_links:
    - from: "scripts/mqtt_poller.py::reconcile_state"
      to: "PollerState.legacy_retained_topics"
      via: "on_message records retained non-empty site-namespaced history/service_history topics"
      pattern: "legacy_topics.add"
    - from: "scripts/mqtt_poller.py::run_cycle (allow_stale_sweep)"
      to: "publish_raw_tombstone"
      via: "existing one-time legacy sweep loop"
      pattern: "publish_raw_tombstone\\(client, legacy_topic\\)"
---

<objective>
Remove the per-device `history` and `service_history` MQTT topics end to end (poller, dashboard, docs).
ClickHouse (`history.host_state`, `history.service_state`, written every cycle by `build_history_rows()` /
`write_history()`) becomes the only source of transition history. User's words: "No need to publish more
mqtt from the poller. Keep it simple, lean and easy to troubleshoot."

Purpose: fewer retained topics, less poller state, nothing on MQTT that no UI component reads.
Output: leaner poller + tests, dashboard without the dead store slices, docs that describe the real contract.

Established facts (verified by orchestrator, do not re-litigate): no dashboard component reads the
`history`/`serviceHistory` store slices; `lan/events/recent` is computed from `last_status` independently
and must stay; `history_max_entries` is used ONLY for per-device history (events use `events_max_entries`);
`last_service_states` only feeds service_history transitions; `append_bounded` is used only by the two
history paths (events are bounded by slicing), so it becomes an orphan and is removed with its test.
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/templates/summary.md
</execution_context>

<context>
@./CLAUDE.md
@.planning/STATE.md
@.planning/phases/14.3-per-site-mqtt-namespace/14.3-04-SUMMARY.md

<interfaces>
Current poller pieces to change (scripts/mqtt_poller.py, line numbers as of planning):
- L1-4 module docstring lists `.../lan/devices/{id}/history` among published topics.
- L69 `DEFAULT_HISTORY_MAX_ENTRIES = 20`; L73-77 `DEFAULT_SERVICE_HISTORY_MAX_ENTRIES = 20` + comment.
- `PollerConfig` (L~395): `history_max_entries: int` is a REQUIRED field (no default) between
  `poll_interval_seconds` and `events_max_entries`; `service_history_max_entries: int = ...` with a default;
  both appear in `__repr__` (L457-458) and `from_env` (L490-493, env HISTORY_MAX_ENTRIES /
  SERVICE_HISTORY_MAX_ENTRIES). No positional `PollerConfig(...)` call exists (tests use `**defaults`).
- L742 `device_history_topic`, L750 `device_service_history_topic`.
- L856 `append_bounded(entries, entry, max_entries)` -- only callers are the two history paths.
- L3673 `publish_history`, L3686 `publish_service_history`.
- L3699 `publish_raw_tombstone(client, full_topic)`: refuses anything starting with `sites/`.
- L3719 `publish_tombstone(client, device_id)`: clears status, history, services, service_history.
- L3811 `PollerState`: `previous_nodes, last_status, history, events, since` (positional, no defaults),
  then `previous_services`, `last_service_states`, `service_history`, `retained_ids`, `admin_faked`,
  `legacy_retained_topics: set[str]`, `previous_incidents`, ...
- L4024 `parse_events_payload` (docstring/warning mention per-device history; still used for events).
- L4042 `reconcile_state`: `history_payloads`, `service_history_payloads`; `retained_ids` collects ids from
  4-segment `status|history|services|service_history`; legacy branch (`rel is None`) adds retained non-empty
  `lan/...`/`admin/faked` full topics to `legacy_topics`; subscribes `site_topic("lan/devices/+/history")`
  and `+/service_history` before the topology subscription (which must stay LAST -- barrier).
- L4229 `run_cycle`: service transition block L4306-4325; removed-ids loop L4336-4354 pops history/
  last_service_states/service_history; stale sweep L4356-4382 (same pops, then legacy sweep loop
  `for legacy_topic in sorted(state.legacy_retained_topics): publish_raw_tombstone(client, legacy_topic)`);
  host state-change block L4395-4413 appends events AND history.
- `relative_topic(full_topic)` returns the site-relative topic or `None` when not under this site's prefix.

scripts/smoke_test_poller.py L497-517: ghost_tombstone check reads
`mqtt_poller.device_history_topic(GHOST_DEVICE_ID)` and requires `not history_payload`.

Tests (tests/test_mqtt_poller.py): `_make_config` L2536 sets `"history_max_entries": 2`; `_poller_state`
L3140 takes `history=`; `PollerState(previous_nodes={}, last_status={}, history={}, events=[], since="t")`
at L3945/L3970; helpers `_published(client, topic)`, `_tombstones(client)`, `_reconcile_with_messages`,
`_make_message`, `_snapshot`, `_LEGACY_SET` exist.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Poller stops publishing history/service_history; legacy topics swept and tombstoned (poller, tests, smoke, compose)</name>
  <files>scripts/mqtt_poller.py, tests/test_mqtt_poller.py, scripts/smoke_test_poller.py, deploy/compose.yaml</files>
  <behavior>
    - New test: state with last_status {"a": "OK"} and previous services for "a"; a cycle where "a" goes CRIT and one service changes OK->CRIT publishes NO topic ending in `/history` or `/service_history` (inspect every `client.publish` call), still publishes `sites/testsite/lan/events/recent` with a `state_change` entry, and still republishes `sites/testsite/lan/devices/a/services`.
    - New test: `_reconcile_with_messages` with retained non-empty `sites/testsite/lan/devices/web1/history` and `sites/testsite/lan/devices/web1/service_history` (plus an empty-payload one and a non-retained one, both ignored) puts exactly the two non-empty retained topics into `state.legacy_retained_topics`; then `run_cycle(..., [_snapshot("web1")], allow_stale_sweep=True)` publishes a None-payload retained tombstone to both, does NOT tombstone `sites/testsite/lan/devices/web1/status` or `/services`, emits no event for them, and leaves `legacy_retained_topics` empty. With `allow_stale_sweep=False` nothing is cleared and the set is kept.
    - `publish_raw_tombstone` still refuses `sites/testsite/lan/devices/x/status` (existing test) and also refuses another site's history topic such as `sites/othersite/lan/devices/x/history` (new assertion); it accepts `sites/testsite/lan/devices/x/history`.
    - `publish_tombstone` still clears the same four topic strings (existing test stays green unchanged).
    - `reconcile_state` still subscribes `sites/testsite/lan/devices/+/history` and `+/service_history`, still before the topology subscription (existing ordering test stays valid).
  </behavior>
  <action>
In scripts/mqtt_poller.py, delete: `device_history_topic`, `device_service_history_topic`, `publish_history`, `publish_service_history`, `append_bounded`, `DEFAULT_HISTORY_MAX_ENTRIES`, `DEFAULT_SERVICE_HISTORY_MAX_ENTRIES` (and its comment), the `PollerConfig` fields `history_max_entries` and `service_history_max_entries` (and their `__repr__` entries and `from_env` env reads), and the `PollerState` fields `history`, `last_service_states` and `service_history` (keep `previous_services`; trim the dated Phase 12 comment so it only describes `previous_services`). Fix the comments that say "Appended after service_history_max_entries" so they still read correctly. In `run_cycle`, delete the per-service transition block (keep the `services_signature` change-only `publish_services` logic), delete the `append_bounded`/`publish_history` lines in the host state-change loop (keep the `state_change` event append exactly as is), and drop every `state.history` / `state.last_service_states` / `state.service_history` pop in the removed-ids loop and the stale sweep. Update the `run_cycle` and `reconcile_state` docstrings and the module docstring (L1-4) so they no longer claim history/service_history are published or reconciled; keep `parse_events_payload` (still used for events) but make its docstring/warning say events only.

`reconcile_state`: remove `history_payloads`, `service_history_payloads`, their elif branches and the post-loop dict comprehensions, and stop passing `history=`/`service_history=` to `PollerState`. Keep both `site_topic("lan/devices/+/history")` and `site_topic("lan/devices/+/service_history")` subscriptions where they are (before topology, which stays last). In `on_message`'s namespaced branch, when the relative topic is exactly 4 segments `lan/devices/<id>/history` or `lan/devices/<id>/service_history` and the message is retained (`getattr(msg, "retain", False)`) with a non-empty payload, add the FULL `msg.topic` to the existing `legacy_topics` set (same one-time sweep set Plan 14.3-04 added; no new state field, no new mechanism). Remove `history` and `service_history` from the `retained_ids` tuple (those topics are now cleared by the sweep set, so ghost-id collection only needs `status` and `services`). Add a dated comment there: "2026-10-04 (quick 261004-kbt): the poller no longer publishes per-device history/service_history (ClickHouse holds transition history); already-retained ones are cleared once via legacy_retained_topics. Remove this and the two subscriptions together after one release."

`publish_raw_tombstone`: keep refusing `sites/` topics EXCEPT a topic whose `relative_topic(full_topic)` is 4 segments `lan/devices/<id>/history|service_history` (i.e. this site's retired topics only); extend the docstring with the same dated note. Do not change the legacy `lan/...` path.

`publish_tombstone`: keep clearing four topics, but build the two retired ones inline as `site_topic(f"lan/devices/{device_id}/history")` and `site_topic(f"lan/devices/{device_id}/service_history")`, with the dated comment "legacy since 2026-10-04 (quick 261004-kbt): no longer published; tombstoned for one release so hosts removed right after the upgrade leave no retained ghost; drop later." Update its docstring summary line.

tests/test_mqtt_poller.py: delete `test_publish_history_publishes_full_array`, `test_publish_service_history_uses_qos1_and_bare_array`, the `append_bounded` test(s), `test_run_cycle_service_state_change_republishes_services_and_appends_one_history_entry` (or reduce it to its services-republish assertion if it is the only services-change coverage), `test_run_cycle_service_history_bounded_to_configured_max_entries`; rewrite `test_run_cycle_truncates_history_and_events_to_configured_bounds` to assert only the events bound; update `test_run_cycle_state_change_appends_history_and_event_and_publishes_both_topics` / `test_run_cycle_removed_device_tombstones_status_and_history_and_events` / `test_run_cycle_no_changes_publishes_no_history_or_events` to drop history-state assertions (tombstone of the four topics on removal stays asserted); drop `history_max_entries` from `_make_config` and the `config.history_max_entries == 20` assertion (L658) plus any SERVICE_HISTORY_MAX_ENTRIES env test; drop `history=` from `_poller_state` and from the two direct `PollerState(...)` constructions; change `test_reconcile_state_collects_retained_ids_from_per_device_topics` to expect `{"x", "y"}` and also assert the z/w history topics landed in `legacy_retained_topics`; remove any `state.history == {}` assertion (L4155) or replace with the equivalent site-state check. Add the two new tests from `<behavior>`. Rename any test whose name now lies.

scripts/smoke_test_poller.py ghost_tombstone: drop the `history_payload` read and its condition (ghost is gone when status is empty and topology no longer lists it). deploy/compose.yaml: delete the `HISTORY_MAX_ENTRIES=20` line from the poller environment (SERVICE_HISTORY_MAX_ENTRIES is not set there). No ClickHouse, ACL or events code changes.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && uv run pytest -q && uvx ruff check --no-cache scripts && test "$(grep -cE 'def (publish_history|publish_service_history|device_history_topic|device_service_history_topic|append_bounded)\b|history_max_entries|HISTORY_MAX_ENTRIES|last_service_states|state\.history|state\.service_history' scripts/mqtt_poller.py scripts/smoke_test_poller.py tests/test_mqtt_poller.py deploy/compose.yaml | awk -F: '{s+=$NF} END {print s}')" = "0"</automated>
  </verify>
  <done>Full pytest suite and ruff pass; no history publisher, config field, env var or state slice remains; `grep -n "service_history\|/history" scripts/mqtt_poller.py` shows only the publish_tombstone legacy lines, the publish_raw_tombstone allowance, and the reconcile_state subscriptions/collection with their dated comments.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Dashboard drops history/serviceHistory subscriptions, slices and types</name>
  <files>dashboard-react/src/lib/topics.ts, dashboard-react/src/lib/types.ts, dashboard-react/src/lib/config.ts, dashboard-react/src/store/useAppStore.ts, dashboard-react/src/store/useAppStore.test.ts, dashboard-react/src/store/selectors.test.ts, dashboard-react/src/store/mqttClient.test.ts, dashboard-react/src/components/HostDetails.test.tsx</files>
  <behavior>
    - `RELATIVE_SUBSCRIBE_TOPICS` contains `lan/devices/+/services` and does NOT contain `lan/devices/+/history` or `lan/devices/+/service_history` (mqttClient.test.ts test rewritten accordingly).
    - A zero-length payload on `lan/devices/h1/status` still deletes `devices.h1` and `services.h1` (useAppStore.test.ts tombstone tests keep this, minus history assertions).
    - A message on `lan/devices/h1/history` or `.../service_history` is ignored (store state unchanged, no throw).
  </behavior>
  <action>
In topics.ts remove the two entries `"lan/devices/+/history"` and `"lan/devices/+/service_history"`. In types.ts delete `HistoryEntry` and `ServiceHistoryEntry`. In config.ts delete `HISTORY_MAX_ENTRIES` (grep confirms no consumer) and fix the L23-24 comment to mention only POLL_INTERVAL_SECONDS. In useAppStore.ts remove the `history` and `serviceHistory` state fields, their initial values, the two `handleMessage` branches for `parts[3] === "history"` / `"service_history"`, the type imports, and the history/serviceHistory lines in the status-tombstone branch (it must still delete `devices[id]` and `services[id]`; reword its comment to "services"); update the header comment at L5 that names `publish_history()`. Update tests: selectors.test.ts drop `history: {}`/`serviceHistory: {}` from the state fixture; useAppStore.test.ts delete the `handleMessage - service_history` describe block and history assertions from the tombstone tests (keep device/services removal assertions) and add one test that history/service_history messages leave state unchanged; HostDetails.test.tsx stop feeding `lan/devices/web1/history` messages but keep the "no History section" assertions. Do not touch any component other than the listed files.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard/dashboard-react && npm test && npm run typecheck && npm run lint && test -z "$(grep -rnE 'serviceHistory|HistoryEntry|HISTORY_MAX_ENTRIES|lan/devices/\+/(history|service_history)' src --include='*.ts' --include='*.tsx' --exclude='*.test.ts' --exclude='*.test.tsx')"</automated>
  </verify>
  <done>Dashboard tests, typecheck and lint pass; no non-test source references history/serviceHistory topics, slices, types or HISTORY_MAX_ENTRIES.</done>
</task>

<task type="auto">
  <name>Task 3: Docs describe the leaner contract (ClickHouse is the history source)</name>
  <files>docs/MQTT-CONTRACT-WALKTHROUGH.md, docs/Podman setup for checkmk, minio, mosquitto, worker.md, dashboard-react/README.md, .planning/PROJECT.md</files>
  <action>
docs/MQTT-CONTRACT-WALKTHROUGH.md: remove the `history` and `service_history` rows from the Part 1 topic table (L38-39) and add one line under it: "Removed 2026-10-04 (quick 261004-kbt): per-device `history` and `service_history` are no longer published; host/service transition history comes only from ClickHouse (`history.host_state`, `history.service_state`). Already-retained copies are cleared once at poller startup." Fix the Part 1 bullets (~L47) and the worked timeline (~L157-L264: drop the `service_history`/`history` publish steps and payload examples, keep `services`, `status`, `events`; host removal now tombstones `status` and `services`, plus the two legacy paths for one release). Part 3 (~L307-337): drop the two wildcards from the subscription list and the two "Stored, but no component reads it" table rows. Part 4 (~L394, L414-416, L451-452): mark the "drop per-device history topics" proposal item as done on 2026-10-04 instead of proposed; leave the rest of the history-over-MQTT proposal text as is.

"docs/Podman setup for checkmk, minio, mosquitto, worker.md": delete the `history` and `service_history` rows (L483, L485); reword L490 to say removal tombstones `status` and `services` (and, for one release, the retired `history`/`service_history` paths), and that startup also clears any retained `history`/`service_history` topic once; fix L498 so it no longer calls `service_history` a topic; there is no HISTORY_MAX_ENTRIES env-var list entry beyond the table, but grep and remove any remaining mention.

dashboard-react/README.md: delete the `HISTORY_MAX_ENTRIES` bullet (L92-93); leave the "Event history" pane text (that is `lan/events/recent`).

.planning/PROJECT.md L27: remove `` `lan/devices/{id}/history` (retained, bounded transition log), `` from the contract list and append "(per-device `history`/`service_history` removed 2026-10-04, quick 261004-kbt; transition history lives in ClickHouse)". Do not edit .planning/phases, .planning/quick, REQUIREMENTS.md, ROADMAP.md (records), docs/src/*.py (unrelated reference scripts with their own topic scheme) or the untracked docs/Retrieving-Checkmk-Event-History.md.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && ! grep -nE 'HISTORY_MAX_ENTRIES|\{id\}/(history|service_history)` \|' docs/MQTT-CONTRACT-WALKTHROUGH.md "docs/Podman setup for checkmk, minio, mosquitto, worker.md" dashboard-react/README.md .planning/PROJECT.md && grep -c "261004-kbt" docs/MQTT-CONTRACT-WALKTHROUGH.md .planning/PROJECT.md</automated>
  </verify>
  <done>No doc lists history/service_history as a live topic or HISTORY_MAX_ENTRIES as a setting; walkthrough and PROJECT.md carry the dated removal note pointing at ClickHouse.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| broker -> poller (reconcile) | retained topic names from Mosquitto drive which topics get tombstoned |
| poller -> broker (sweep) | retained-clear publishes under the site namespace |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-q261004-01 | Tampering | publish_raw_tombstone allowance | mitigate | allow `sites/` only when `relative_topic()` resolves under THIS site and is exactly 4 segments ending `history`/`service_history`; tests assert `status`, `services` and another site's topic are refused |
| T-q261004-02 | Denial of Service | sweep clearing live data | mitigate | sweep stays behind existing `allow_stale_sweep` gate; test asserts live host `status`/`services` untouched |
| T-q261004-03 | Repudiation | loss of MQTT history | accept | ClickHouse `history.host_state`/`service_state` already records every cycle; no UI read these topics |
</threat_model>

<verification>
- `uv run pytest -q` green; `uvx ruff check --no-cache scripts` clean.
- `cd dashboard-react && npm test && npm run typecheck && npm run lint` green.
- Final grep, expected hits only in the intentional legacy lines of scripts/mqtt_poller.py (publish_tombstone, publish_raw_tombstone allowance, reconcile_state subscriptions/collection) and tests: `grep -rnE "service_history|/history\b|serviceHistory|HistoryEntry|HISTORY_MAX_ENTRIES" scripts dashboard-react/src deploy --include='*.py' --include='*.ts' --include='*.tsx' --include='*.yaml'`.
- No live redeploy is part of this task. If the operator redeploys, use a full `podman compose down && podman compose up -d` (single-container restart breaks Checkmk egress).
</verification>

<success_criteria>
- Poller publishes no per-device history/service_history; ClickHouse writes and `lan/events/recent` unchanged.
- Already-retained history/service_history topics are cleared once via the existing legacy sweep; host removal still tombstones them for one release.
- Dashboard has no history/serviceHistory subscriptions, slices or types; status tombstones still remove devices and services.
- Docs and PROJECT.md describe the removal with a dated note.
</success_criteria>

<output>
Create `.planning/quick/261004-kbt-remove-history-and-service-history-mqtt-/261004-kbt-SUMMARY.md` when done
</output>
