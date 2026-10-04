---
phase: quick-261004-lyz
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - deploy/mosquitto.acl.template
  - tests/test_mosquitto_acl.py
  - scripts/smoke_test_broker.py
  - scripts/mqtt_poller.py
  - tests/test_mqtt_poller.py
  - docs/Podman setup for checkmk, minio, mosquitto, worker.md
autonomous: true
requirements: [QUICK-261004-lyz]

must_haves:
  truths:
    - "The rendered broker ACL gives the poller exactly one grant: readwrite sites/<site_id>/#"
    - "The rendered ACL file no longer contains the site-id placeholder token anywhere, including the header comment"
    - "The poller no longer subscribes to un-namespaced lan/# or admin/faked, never records them, and never seeds admin_faked from them"
    - "Retained sites/<id>/lan/devices/+/history and +/service_history are still collected at startup and cleared once behind allow_stale_sweep"
    - "publish_raw_tombstone refuses every topic that is not this site's retired per-device history/service_history topic, including un-namespaced lan/... topics"
    - "smoke_test_broker.py no longer runs poller_legacy_write or the now-vacuous wsreader_cannot_read_legacy check"
    - "Docs say plainly that the pre-14.3 cleanup was removed on 2026-10-04 and what a stack still on pre-14.3 topics must do"
  artifacts:
    - path: "deploy/mosquitto.acl.template"
      provides: "Per-site ACL without the legacy poller grants"
      contains: "topic readwrite sites/@SITE_ID@/#"
    - path: "scripts/mqtt_poller.py"
      provides: "reconcile_state/run_cycle without the pre-14.3 sweep; retired history sweep kept"
      contains: "retired_history_topics"
    - path: "tests/test_mqtt_poller.py"
      provides: "History sweep tests kept; un-namespaced refusal test"
  key_links:
    - from: "scripts/mqtt_poller.py reconcile_state"
      to: "PollerState.retired_history_topics"
      via: "on_message records retained non-empty sites/<id>/lan/devices/<id>/history|service_history"
      pattern: "retired_history_topics"
    - from: "scripts/mqtt_poller.py run_cycle"
      to: "publish_raw_tombstone"
      via: "allow_stale_sweep gate"
      pattern: "publish_raw_tombstone\\(client"
---

<objective>
Remove the temporary pre-14.3 legacy namespace support now that its one-time sweep has run on the only deployment (dmc-server, site dmc_test: poller logged "Cleared 100 ... retained topics", and a retained query on `lan/#` + `admin/faked` returned nothing). Delete, don't add: drop the poller's `lan/#` and `admin/#` ACL grants, the legacy subscriptions/recording/admin_faked seed in the poller, the legacy smoke checks, and the doc text that describes them. Keep the quick-261004-kbt retired history/service_history sweep.

Purpose: lean, easy-to-troubleshoot broker ACL and poller; no dead migration code.
Output: edited ACL template, poller, tests, smoke test and Podman doc.
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/templates/summary.md
</execution_context>

<context>
@./CLAUDE.md
@.planning/STATE.md
@.planning/quick/261004-kbt-remove-history-and-service-history-mqtt-/261004-kbt-SUMMARY.md

Facts gathered during planning (line numbers as of commit 49cfd94; re-locate by grep, do not trust blindly):

- `deploy/mosquitto.acl.template`: header comment line 9 reads "deploy/render-mosquitto-acl.sh replaces @SITE_ID@" (the only comment occurrence of the token). Poller block lines 17-24: `topic readwrite sites/@SITE_ID@/#`, then a 5-line `# TEMPORARY ... # TODO ...` comment, then `topic readwrite lan/#` and `topic readwrite admin/#`. Non-comment `@SITE_ID@` lines = 6 today; deleting the two legacy lines (no placeholder) and rewording comment text keeps it at 6.
- `deploy/render-mosquitto-acl.sh` does `sed s/@SITE_ID@/$site/g` and then fails if `@SITE_ID@` remains; nothing counts placeholders. No change needed there.
- `tests/test_mosquitto_acl.py::test_rendered_grants_are_exact` (around line 57) expects poller grants `{("readwrite","sites/testsite/#"), ("readwrite","lan/#"), ("readwrite","admin/#")}`, and already asserts `"@SITE_ID@" not in text`.
- `scripts/mqtt_poller.py`:
  - `publish_raw_tombstone(client, full_topic)` ~line 3655: docstring talks about Phase 14.3 cutover and "temporary poller legacy ACL grants"; guard computes `retired_history` from `relative_topic(full_topic)` and refuses only `sites/...` topics that are not retired history.
  - `publish_tombstone` ~line 3706: comment "legacy since 2026-10-04 (quick 261004-kbt)" for the history/service_history tombstones -- this is the kbt mechanism, KEEP as is (it does not mention pre-14.3).
  - `PollerState.legacy_retained_topics: set[str]` ~line 3812 with a "2026-10-04 (Phase 14.3)" comment.
  - `reconcile_state` ~lines 4000-4170: docstring paragraph about `legacy_retained_topics`; locals `legacy_topics`, `legacy_admin_faked`; `on_message` branch `if rel is None:` that records un-prefixed `lan/...` and `admin/faked` and appends `legacy_admin_faked`; kbt branch recording history/service_history into `legacy_topics` (KEEP, renamed); subscriptions `client.subscribe("lan/#", qos=1)` and `client.subscribe(TOPIC_ADMIN_FAKED, qos=1)` with a "Legacy un-namespaced topics (Phase 14.3 cutover)" comment; admin_faked selection with `elif legacy_admin_faked:` and log "Seeded admin_faked from the legacy un-namespaced admin/faked topic"; `PollerState(... legacy_retained_topics=legacy_topics)`.
  - `run_cycle` docstring ~line 4208 mentions `state.legacy_retained_topics (pre-14.3 un-namespaced retained topics)`; sweep body ~lines 4285-4295 loops `state.legacy_retained_topics`, calls `publish_raw_tombstone`, logs "Cleared %d legacy retained topics".
- `tests/test_mqtt_poller.py`:
  - ~line 3960 (`test_reconcile_state_collects_retained_ids_from_per_device_topics`): asserts `state.legacy_retained_topics == {z/history, w/service_history}` -- keep, rename attribute.
  - Helper `_reconcile_with_messages` ~line 4043 -- keep.
  - Delete: `test_reconcile_state_collects_legacy_retained_topics`, `test_reconcile_state_ignores_non_retained_or_empty_legacy_messages`, `test_reconcile_state_subscribes_legacy_topics_before_topology_never_admin_wildcard`, `test_reconcile_state_admin_faked_prefers_new_namespace_over_legacy`, `test_reconcile_state_admin_faked_seeded_from_legacy_when_new_absent`, module constant `_LEGACY_SET`, `test_run_cycle_sweep_tombstones_legacy_topics_once`, `test_run_cycle_sweep_gate_off_keeps_legacy_topics`, `test_legacy_sweep_emits_no_event_and_no_sites_tombstone`.
  - Keep/adjust: `test_reconcile_state_legacy_messages_do_not_touch_site_state`, `test_publish_raw_tombstone_refuses_namespaced_topics`, `test_publish_raw_tombstone_accepts_this_sites_retired_history_topic`, `test_reconcile_collects_retained_history_topics_and_sweep_clears_them_once`.
  - Site-namespace admin_faked seeding is already covered by `test_reconcile_state_seeds_admin_faked_from_retained_topic` (~line 4853) and ordering by `test_reconcile_state_subscribes_topology_after_admin_faked`.
- `scripts/smoke_test_broker.py`: module docstring bullet (~lines 39-42) for `check_wsreader_cannot_read_legacy`, `check_poller_legacy_write`; functions at ~391 and ~417; calls in `main()` ~643-659; `_cleanup(host, site_id, seed, ...)` gained `seed` in commit 536e35a (14.3-02) solely for the `f"lan/smoketest/legacy-{seed}"` topic; call site ~line 677. Before 14.3-02 the signature was `_cleanup(host, tcp_port, user, password, timeout)`; `site_id` is still needed for the two `_site_topic(...)` entries.
- Only `docs/Podman setup for checkmk, minio, mosquitto, worker.md` mentions the legacy grants/sweep/seed (upgrade subsection ~321-341, ACL table/paragraph ~473-477, smoke list ~576-577). `docs/MQTT-CONTRACT-WALKTHROUGH.md`, `docs/DEPLOY-NEW-MACHINE.md`, `docs/WIZARD-OPERATION.md` have no such mentions (re-grep to confirm; no edit if still clean).
</context>

<tasks>

<task type="auto">
  <name>Task 1: Drop the legacy poller ACL grants and the legacy broker smoke checks</name>
  <files>deploy/mosquitto.acl.template, tests/test_mosquitto_acl.py, scripts/smoke_test_broker.py</files>
  <action>
ACL template: delete the 5-line TEMPORARY/TODO comment and the `topic readwrite lan/#` and `topic readwrite admin/#` lines, so `user poller` has only `topic readwrite sites/@SITE_ID@/#`. Reword the header comment on line 9 so it no longer contains the literal placeholder token (it currently renders as "replaces dmc_test with CMK_SITE_ID"), e.g. "deploy/render-mosquitto-acl.sh replaces the site-id placeholder with CMK_SITE_ID". Do not touch wsreader/wsadmin blocks or other comment text. Non-comment placeholder line count must stay 6.

tests/test_mosquitto_acl.py: in `test_rendered_grants_are_exact`, the expected poller set becomes `{("readwrite", "sites/testsite/#")}` only. No other change unless a test there referenced the legacy lines.

scripts/smoke_test_broker.py: delete `check_poller_legacy_write` and its call in `main()`. Also delete `check_wsreader_cannot_read_legacy` and its call: with the legacy grant gone the poller's publish to `lan/smoketest/...` is silently dropped by Mosquitto, so the check would pass without proving anything (vacuous); the static exact-grant test in tests/test_mosquitto_acl.py already proves wsreader has no un-namespaced grant. Remove the module-docstring bullet that describes both. Revert `_cleanup` to not take `seed`: signature `_cleanup(host, site_id, tcp_port, user, password, timeout)` (keep `site_id`, it is needed for the two `_site_topic` entries), drop the `f"lan/smoketest/legacy-{seed}"` entry, and update the call site. If `seed` then becomes unused anywhere else in `main()`, leave it (it is still passed to other checks); only remove what this change orphans.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && uv run pytest -q tests/test_mosquitto_acl.py && sh -n deploy/render-mosquitto-acl.sh && uvx ruff check --no-cache scripts/smoke_test_broker.py tests/test_mosquitto_acl.py && test "$(grep -v '^#' deploy/mosquitto.acl.template | grep -c '@SITE_ID@')" -eq 6 && test "$(grep '^#' deploy/mosquitto.acl.template | grep -c '@SITE_ID@')" -eq 0 && ! grep -nE 'legacy|lan/smoketest' scripts/smoke_test_broker.py</automated>
  </verify>
  <done>Template poller block has one grant and no TEMPORARY/TODO comment; header comment has no placeholder token; ACL test passes with the single poller grant; smoke script has no legacy checks, no legacy cleanup topic, and `_cleanup` no longer takes `seed`.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Remove the pre-14.3 sweep and admin_faked seed from the poller; keep the retired history sweep</name>
  <files>scripts/mqtt_poller.py, tests/test_mqtt_poller.py</files>
  <behavior>
    - reconcile_state subscribes only site-prefixed topics: no bare `lan/#`, no bare `admin/faked`; topology is still last.
    - A retained un-namespaced message (e.g. `lan/devices/x/status`, `admin/faked`) delivered anyway is ignored: no retained ids, no topology, no events, no incidents, no admin_faked, empty retired set.
    - Retained non-empty `sites/testsite/lan/devices/<id>/history|service_history` are collected into `retired_history_topics`; empty or non-retained ones are not; run_cycle clears them only when `allow_stale_sweep=True`, once, then empties the set (existing test, renamed attribute).
    - publish_raw_tombstone publishes a tombstone for `sites/testsite/lan/devices/x/history` and refuses (warning, no publish) `sites/testsite/lan/devices/x/status`, `sites/othersite/lan/devices/x/history`, `lan/devices/x/status`, `lan/devices/x/history`, and `admin/faked`.
  </behavior>
  <action>
Tests first (tests/test_mqtt_poller.py): delete the nine legacy tests and `_LEGACY_SET` listed in context. Rename `legacy_retained_topics` to `retired_history_topics` in the kept tests (~line 3960 and the history sweep test). Rename `test_reconcile_state_legacy_messages_do_not_touch_site_state` to `test_reconcile_state_ignores_unprefixed_messages`, add `_make_message("admin/faked", b'{"hosts": {"old": "DOWN"}}')` to its inputs, and additionally assert `state.admin_faked == {}` and `state.retired_history_topics == set()`. Add one assertion to `test_reconcile_state_subscribes_topology_after_admin_faked` (no new test): every subscribed topic starts with `poller.site_topic("")` (i.e. `sites/testsite/`). Extend `test_publish_raw_tombstone_refuses_namespaced_topics` (rename to `test_publish_raw_tombstone_refuses_everything_but_this_sites_retired_history`) with `lan/devices/x/status`, `lan/devices/x/history` and `admin/faked`. Run the tests; the un-namespaced refusal and the attribute rename must fail before the implementation change.

Implementation (scripts/mqtt_poller.py):
- `PollerState`: rename `legacy_retained_topics` to `retired_history_topics` (the set now holds only this site's retired history topics, so "legacy" is misleading). Replace its comment with a dated one: 2026-10-04 (quick 261004-kbt) full topic strings of this site's retained non-empty per-device history/service_history topics, cleared once by run_cycle behind `allow_stale_sweep`; the pre-14.3 un-namespaced sweep that shared this set was removed 2026-10-04 (quick 261004-lyz) after it ran on the only deployment.
- `reconcile_state`: delete `legacy_admin_faked`; rename local `legacy_topics` to `retired_history_topics`; make the `if rel is None:` branch just `return` (with a one-line comment: not under this site's prefix, ignored); delete the bare `client.subscribe("lan/#", ...)` and `client.subscribe(TOPIC_ADMIN_FAKED, ...)` lines and their comment; reduce admin_faked selection to `admin_faked_result[0] if admin_faked_result else b""` (no "Seeded admin_faked from the legacy..." log); pass `retired_history_topics=` to `PollerState`. Update the docstring sentence that names `legacy_retained_topics`. Keep the kbt history/service_history recording branch and its two `site_topic(...)` subscriptions; update its comment's attribute name only. Also fix the subscription-ordering comment only if it references the legacy wildcards.
- `publish_raw_tombstone`: simplify the guard to refuse anything that is NOT this site's retired per-device history/service_history topic (relative_topic not None, 4 parts, `lan`/`devices`, last part in history/service_history); keep the warning text "Refusing to tombstone ..." and the existing publish/except body. Rewrite the docstring: clears one of this site's retired history/service_history retained topics by full topic string (quick 261004-kbt); refuses everything else so the sweep can never clear live data; note the pre-14.3 un-namespaced use and its ACL grants were removed 2026-10-04 (quick 261004-lyz). Keep the function name.
- `run_cycle`: in the docstring replace the `legacy_retained_topics (pre-14.3 ...)` sentence with the retired history set; in the sweep body loop over `state.retired_history_topics`, log "Cleared %d retired history/service_history retained topics", reset the set, and replace the "Phase 14.3: the whole un-namespaced legacy tree..." comment with a short dated kbt comment.
- Leave `publish_tombstone`'s kbt comment, the line ~117 ACL comment, and the D-04 "legacy shape" docstring alone (unrelated).
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && uv run pytest -q tests/test_mqtt_poller.py && uvx ruff check --no-cache scripts/mqtt_poller.py tests/test_mqtt_poller.py && ! grep -nE 'legacy_retained_topics|legacy_admin_faked|Seeded admin_faked|subscribe\("lan/#"|_LEGACY_SET' scripts/mqtt_poller.py tests/test_mqtt_poller.py</automated>
  </verify>
  <done>Poller has no un-namespaced subscriptions, recording or admin_faked seed; retired history sweep still works behind allow_stale_sweep; publish_raw_tombstone accepts only this site's retired history topics; all poller tests pass.</done>
</task>

<task type="auto">
  <name>Task 3: Update the Podman doc and run the full verification</name>
  <files>docs/Podman setup for checkmk, minio, mosquitto, worker.md</files>
  <action>
In "Upgrading to the per-site namespace (Phase 14.3)": add a short plain note at the top that the poller's one-time cleanup of pre-14.3 topics and its temporary broker grants were removed on 2026-10-04 (quick 261004-lyz) after running on the only deployment; a stack still on pre-14.3 topics keeps its old retained `lan/*` and `admin/faked` data and must either clear it by hand (for each retained topic listed by `mosquitto_sub ... -t 'lan/#' -t 'admin/faked' --retained-only -v`, publish an empty retained payload with `mosquitto_pub -r -n -t <topic>` as a user that is granted that topic, i.e. temporarily add `topic readwrite lan/#` / `topic readwrite admin/#` to the poller block, or clear the mosquitto volume) or upgrade through a commit before 261004-lyz first. Remove step 1's sentence that the poller seeds `admin/faked` from the legacy topic (keep "run Restore All first", now as the only way fakes don't carry over), remove the "old retained lan/* topics and the legacy admin/faked are cleared on the first cycle" bullet, and the "Verify the sweep" paragraph plus its code block (the hand-clear note above already shows the query). Keep the rest of the subsection (rebuild, full down/up warning, expectations).

ACL section: poller row becomes `readwrite sites/<site_id>/#` only; delete the "temporary poller lan/# and admin/# grants" paragraph. Smoke check list: delete the `check_wsreader_cannot_read_legacy` and `check_poller_legacy_write` bullets. Grep the doc for "Cleared" / "Seeded" log lines and "legacy" and fix any remaining reference to the removed sweep/seed. Re-grep `docs/MQTT-CONTRACT-WALKTHROUGH.md`, `docs/DEPLOY-NEW-MACHINE.md`, `docs/WIZARD-OPERATION.md`; edit only if they mention the legacy grants/sweep/seed (planning found none).

Then run the full verification block below. Do not edit .planning/phases records (including 14.3-REVIEW.md) or .planning/quick records other than this task's SUMMARY. Do not touch `dashboard-react/src/lib/config.ts` (its stale `topic read lan/#` comment describes wsreader, out of scope; mention it in the SUMMARY as a follow-up candidate).
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && ! grep -nE 'poller_legacy_write|cannot_read_legacy|temporary .*grant|Seeded admin_faked|legacy admin/faked' "docs/Podman setup for checkmk, minio, mosquitto, worker.md" && grep -n '261004-lyz' "docs/Podman setup for checkmk, minio, mosquitto, worker.md"</automated>
  </verify>
  <done>Podman doc describes the single poller grant, states the 2026-10-04 removal and the manual path for pre-14.3 stacks, and lists no legacy smoke checks; full verification below passes.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| poller -> Mosquitto | Poller credential publishes retained state; ACL bounds what it can write |
| poller sweep -> retained store | Tombstones delete retained data; a wrong target would blank live dashboard state |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-q261004lyz-01 | Elevation of Privilege | deploy/mosquitto.acl.template poller block | mitigate | Remove `readwrite lan/#` and `readwrite admin/#`; `test_rendered_grants_are_exact` pins the poller to exactly `readwrite sites/<id>/#` |
| T-q261004lyz-02 | Tampering | publish_raw_tombstone | mitigate | Guard narrowed to this site's retired history/service_history topics only; refusal test covers live per-site, other-site and un-namespaced topics |
| T-q261004lyz-03 | Denial of Service | pre-14.3 stacks after upgrade | accept | Only deployment (dmc-server) already swept and verified empty; docs give the manual clear path |
</threat_model>

<verification>
Run from /home/kone/checkmk-wizard:

1. `uv run pytest -q` (whole suite passes).
2. `uvx ruff check --no-cache scripts tests/test_mosquitto_acl.py tests/test_mqtt_poller.py`
3. `sh -n deploy/render-mosquitto-acl.sh`
4. Render locally and show the poller block has exactly one grant (scratch dir, not /tmp):
   `CMK_SITE_ID=dmc_test sh deploy/render-mosquitto-acl.sh deploy/mosquitto.acl.template "$SCRATCH/acl" && cat "$SCRATCH/acl"` then confirm `awk '/^user poller/{p=1;next} /^user /{p=0} p && /^topic /' "$SCRATCH/acl"` prints exactly `topic readwrite sites/dmc_test/#`, and `grep -c dmc_test "$SCRATCH/acl"` equals the 6 grant lines (header comment no longer contains the site id).
5. Repo grep shows no remaining legacy grant/sweep/seed references outside records:
   `git grep -nE 'readwrite lan/#|readwrite admin/#|poller_legacy_write|cannot_read_legacy|Seeded admin_faked|legacy_retained_topics|legacy_admin_faked|pre-14\.3' -- ':!.planning/phases' ':!.planning/quick' ':!PROMPT_LOG.md'` returns only the intentional dated removal notes (mqtt_poller.py comments mentioning "pre-14.3 ... removed 2026-10-04 (quick 261004-lyz)" and the Podman doc note) and nothing else; list and justify each hit in the SUMMARY.

Deployment reminder (do NOT perform; for the SUMMARY's user-facing notes): on dmc-server pull, then a full `podman compose down && podman compose up -d` (never restart or stop a single container; that breaks Checkmk egress and turns all real hosts DOWN), then re-run `uv run python scripts/smoke_test_broker.py --skip-restart ...` (see the Podman doc invocation) and expect no legacy checks in its output.
</verification>

<success_criteria>
- Poller ACL grant set is exactly `readwrite sites/<site_id>/#`; rendered file has no site id in comments.
- Poller has no pre-14.3 code paths; the kbt retired history sweep still works and is tested.
- `publish_raw_tombstone` refuses un-namespaced `lan/...` topics (tested).
- smoke_test_broker.py has no legacy checks and `_cleanup` no longer takes `seed`.
- Podman doc reflects the removal with the 2026-10-04 date and manual fallback.
- Full pytest and ruff pass.
</success_criteria>

<output>
Create `.planning/quick/261004-lyz-remove-legacy-lan-and-admin-poller-grant/261004-lyz-SUMMARY.md` when done
</output>
