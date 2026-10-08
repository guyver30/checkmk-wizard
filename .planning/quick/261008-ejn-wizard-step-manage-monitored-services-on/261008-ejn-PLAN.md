---
phase: quick-261008-ejn
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/checkmk_wizard/api.py
  - tests/test_api.py
  - src/checkmk_wizard/wizard.py
  - tests/test_wizard.py
  - docs/WIZARD-OPERATION.md
  - README.md
autonomous: true
requirements: [QUICK-261008-EJN]

must_haves:
  truths:
    - "After Phase 4 the operator is asked once (default No) whether to change monitored services on already-onboarded hosts; answering No makes zero REST calls and the rest of run() is unchanged"
    - "For each chosen existing Linux agent host the operator sees a checkbox with currently monitored services pre-ticked, running services offered, and monitored-but-not-running services shown so they can be unticked"
    - "If SSH is unavailable the operator gets a free-text entry pre-filled with the currently monitored names"
    - "A per-host added/removed summary is shown and nothing is written unless a single confirm (default No) is answered Yes"
    - "Applying updates the host's existing discovery_systemd_units_services rule in place, creates one if none exists, deletes it when nothing remains, and never leaves two rules for the same host"
    - "Affected hosts are rediscovered (fix_all) by Phase 6 and the result activated by Phase 7: added services appear, removed services vanish"
    - "One host's REST failure prints a yellow warning and the other hosts are still processed"
  artifacts:
    - path: "src/checkmk_wizard/api.py"
      provides: "get_rule, update_rule, delete_rule on CheckmkClient via _request"
      contains: "async def update_rule"
    - path: "src/checkmk_wizard/wizard.py"
      provides: "manage_existing_host_services step + pure helpers, wired into run()"
      contains: "async def manage_existing_host_services"
    - path: "docs/WIZARD-OPERATION.md"
      provides: "Section for the new step, control-flow diagram updated, manual fallback note"
      contains: "Manage monitored services on existing hosts"
  key_links:
    - from: "run() in src/checkmk_wizard/wizard.py"
      to: "manage_existing_host_services"
      via: "awaited inside the WizardAborted try block right after phase4_classification; its return value is appended to the host list given to phase6_discovery only"
      pattern: "phase6_discovery\\(client, connection, onboarded \\+ "
    - from: "manage_existing_host_services"
      to: "CheckmkClient.update_rule / delete_rule / create_rule"
      via: "_apply_host_service_change"
      pattern: "update_rule\\(|delete_rule\\("
---

<objective>
Add an opt-in wizard step, "Manage monitored services on existing hosts", that lets the operator add or remove monitored systemd services on hosts that are already onboarded, by editing each host's "Systemd single services discovery" rule (`discovery_systemd_units_services`) through the REST API, then reusing Phase 6 (activate + fix_all discovery + expected-service verification) and Phase 7 (activation) for the affected hosts.

Purpose: today the only way to change an existing host's monitored services is to hand-edit the per-host rule in the Checkmk GUI, rediscover and activate.
Output: three new REST client methods, the new step and its pure helpers in wizard.py, tests, docs.
</objective>

<design_decisions>
These are the planner's resolved choices (operator delegated them). Executors implement them as written.

1. Insertion point: between Phase 4 and Phase 5, inside run()'s existing `try: ... except WizardAborted` block, right after `phase4_classification(...)`. Reasons: (a) operator asked for "after Phase 4"; (b) the step only edits Checkmk WATO rules (no remote-host changes), so Esc must stay enabled and `_handle_abort` can apply/revert its pending rule edits exactly like Phase 2-4 edits; (c) Phase 6 already activates pending changes before discovery and runs `fix_all` + `_verify_expected_services` per OnboardedHost, so passing lightweight `OnboardedHost` records for the affected hosts into `phase6_discovery` reuses that machinery with zero changes to Phase 6, and Phase 7's `_activate_pending_changes` then activates the discovery result. The step's records go to `phase6_discovery` ONLY, not `phase5_onboarding` (they must not be re-created/re-agented) and not `phase7_activation` (in `--demo` mode Phase 7 would put the always-up demo host-check rule on them and fake them UP).
2. Name: public function `manage_existing_host_services(client, *, exclude_names)`, console rule "Manage monitored services on existing hosts (optional)". Not numbered as a phase, so Phase 5-7 numbering and the docs' phase sections stay valid.
3. Scope: Linux (systemd) only. Windows is left out: an existing host record from `list_hosts()` carries no OS signal (`tag_agent: cmk-agent` is the same for both), the wizard never connects to Windows by design (no service scan possible), so supporting it would need an extra per-host OS prompt and a second parser for `inventory_services_rules`. A Windows host picked by mistake only gets an SSH failure and a systemd rule that matches nothing (harmless). Docs and the SUMMARY say so.
4. Candidate hosts: from `client.list_hosts()`, a host is a candidate when its explicit `attributes.tag_agent` is `"cmk-agent"` or `"all-agents"` (Phase 5 sets `tag_agent: "cmk-agent"` explicitly on every agent host; Phase 2 folders and Phase 3 placeholders set `"no-agent"`; an absent `tag_agent` is treated as not-a-candidate because it usually means an inherited folder `no-agent`). Hosts in `exclude_names` (this run's promoted hostnames and their scanned IPs) are skipped, mirroring `_retaggable_hosts`. IP for SSH = `attributes.ipaddress`, falling back to the host name.
5. Rule ownership: a rule belongs to a host when `extensions.folder == host folder` and `extensions.conditions.host_name.match_on == [hostname]` (exactly that one host; operator `one_of` or absent). Rules covering several hosts, or in other folders, are never touched. If more than one rule belongs to the host (duplicates from earlier runs or hand edits), the current set is their union; on apply the first is updated and the rest deleted, so the host ends with at most one rule.
6. Parsing `value_raw`: `ast.literal_eval` only (never eval), same defensive style as `_is_global_systemd_inactive_crit_rule`. An entry is "ours" when it starts with `~^`, ends with `$`, and the inner text round-trips (`re.escape(unescaped) == inner`, where unescaped = inner with each backslash-escape `\X` replaced by `X`). Non-round-tripping entries (hand-written regexes, bare exact names) are preserved verbatim on every write and listed as "kept unchanged" in the output; they are not offered for editing. Parse failure of a rule's value = that rule contributes no names and the host is reported with a yellow warning and skipped (never overwrite a rule we cannot read).
7. Write encoding: identical to `_create_service_discovery_rules` (`~^{re.escape(name.removesuffix('.service'))}$`, `json.dumps({"names": [...]})`), with preserved custom entries appended. Delete the rule only when both the selected names and the preserved custom entries are empty.
8. Update request: GET `/objects/rule/{rule_id}` for a fresh ETag, conditions and properties; PUT `/objects/rule/{rule_id}` with `value_raw`, `conditions` and `properties` copied from the GET response's `extensions` (the 2.4.0 `edit_rule` handler defaults omitted `conditions`/`properties` to `{}`, which would silently drop the host_name condition and turn the rule into a site-wide one; resending them is mandatory). If the GET response has no `ETag` header, send `If-Match: *` and say so in the docstring as unverified.
9. SSH: one credential prompt per step via the existing `_establish_ssh_access(first_chosen_host_ip)` (same batch-credentials flow as Phase 5). It returns None when the operator skips; then every host uses the free-text fallback. A per-host `remote.list_running_systemd_services` returning None also falls back to free text for that host.
10. Free-text fallback default is the comma-joined current names; blank means "monitor none of the editable names" (shown in the summary as removals, so the confirm gate protects against accidents).
</design_decisions>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/templates/summary.md
</execution_context>

<context>
@./CLAUDE.md
@.planning/STATE.md

<interfaces>
<!-- Extracted from the codebase. Use directly; no exploration needed. -->

From src/checkmk_wizard/api.py (CheckmkClient):
- `async def _request(self, method, path, *, json_body=None, params=None, extra_headers=None, expect=(200, 201)) -> httpx.Response` — 204 is always accepted; non-expected status raises CheckmkAPIError; httpx errors become CheckmkAPIError(status_code=0).
- `async def get_host(self, host_name) -> httpx.Response` (pattern for get_rule: return the raw Response so callers read `.headers["ETag"]` and `.json()`).
- `async def update_host_attributes(self, host_name, attributes, etag) -> dict` (pattern for update_rule: PUT with `extra_headers={"If-Match": etag}`, return `resp.json()`).
- `async def delete_host(self, host_name) -> None` (pattern for delete_rule: `await self._request("DELETE", ...)`).
- `async def create_rule(self, ruleset, folder, value_raw, conditions=None) -> dict` (POST /domain-types/rule/collections/all).
- `async def list_rules(self, ruleset_name) -> list[dict]` (GET /domain-types/rule/collections/all?ruleset_name=...; each item has `id` and `extensions.{folder, conditions, properties, value_raw}`).
- `async def list_hosts(self) -> list[dict]` (items: `id`, `extensions.folder`, `extensions.attributes`).
- `async def start_service_discovery(self, host_name, mode="refresh") -> dict`.

From src/checkmk_wizard/wizard.py:
- `@dataclass OnboardedHost(ip, hostname, folder, os_family, ..., expected_services: list[str] = [])` (line ~282).
- `async def _establish_ssh_access(test_host_ip: str) -> remote.SSHCredentials | None` (line ~2795).
- `async def _create_service_discovery_rules(client, host: OnboardedHost, service_names: list[str]) -> None` (line ~2469; best-effort, prints its own warning).
- `async def _ensure_systemd_inactive_crit_rule(client, host: OnboardedHost, service_names: list[str]) -> None` (line ~2544; no-op unless os_family == "linux" and names non-empty).
- `def _is_global_systemd_inactive_crit_rule(rule) -> bool` (line ~2526; the literal_eval parsing style to copy).
- `async def phase6_discovery(client, connection, hosts: list[OnboardedHost]) -> None` (line ~3257; activates, then fix_all per host, verifies `expected_services`).
- `async def phase7_activation(client, connection, hosts, *, demo=False)`.
- `async def run(*, demo=False)` (line ~3675): phases 2-4 in `try ... except WizardAborted: await _handle_abort(...)`, then phase5/6/7 with `onboarded`.
- `_retaggable_hosts(hosts, exclude_names)` (line ~1022): the `.get(...)`-chain filtering style to copy for candidate selection.

From src/checkmk_wizard/remote.py:
- `async def list_running_systemd_services(host: str, creds: SSHCredentials) -> list[str] | None` — names with `.service` stripped; None on SSH/command failure.

Checkmk 2.4.0 REST source (read for this plan, cmk/gui/openapi/endpoints/rule/__init__.py at tag 2.4.0, via raw.githubusercontent.com):
- show_rule: `GET /objects/rule/{rule_id}`, no etag declared in the decorator, 200 with the serialized rule.
- edit_rule: `PUT /objects/rule/{rule_id}`, `etag="both"`, request schema UpdateRuleObject; handler reads `body["value_raw"]` (required) and `body.get("conditions", {})`, `body.get("properties", {})`; returns 200 with the serialized rule.
- delete_rule: `DELETE /objects/rule/{rule_id}`, `output_empty=True`, 204 on success, 400 locked, 404 not found; no etag.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: REST client methods get_rule, update_rule, delete_rule</name>
  <files>src/checkmk_wizard/api.py, tests/test_api.py</files>
  <behavior>
    - get_rule("r1") sends GET {BASE}/objects/rule/r1 and returns the raw httpx.Response (ETag header readable)
    - update_rule("r1", value_raw=..., conditions=..., properties=..., etag='"abc"') sends PUT {BASE}/objects/rule/r1 with header If-Match '"abc"' and JSON body containing exactly value_raw, conditions, properties; returns the response JSON
    - delete_rule("r1") sends DELETE {BASE}/objects/rule/r1 and accepts 204
    - a 404 on delete_rule and a 412 on update_rule raise CheckmkAPIError (through _request)
  </behavior>
  <action>
Write the four tests first in tests/test_api.py next to the existing list_rules tests, using the file's respx + `CONN`/`BASE` + `@pytest.mark.asyncio` conventions; run them and see them fail. Then add three methods to CheckmkClient in api.py directly after `list_rules`, all going through `self._request` (never `self._client.request`), per the project's single-choke-point rule:
- `get_rule(self, rule_id: str) -> httpx.Response`: GET `/objects/rule/{rule_id}`.
- `update_rule(self, rule_id: str, *, value_raw: str, conditions: dict[str, Any], properties: dict[str, Any], etag: str) -> dict[str, Any]`: PUT `/objects/rule/{rule_id}`, json_body with the three keys, `extra_headers={"If-Match": etag}`, return `resp.json()`.
- `delete_rule(self, rule_id: str) -> None`: DELETE `/objects/rule/{rule_id}`.
Each gets a docstring in the project's citation style: "Verified by reading the Checkmk 2.4.0 source (cmk/gui/openapi/endpoints/rule/__init__.py: show_rule / edit_rule etag="both" / delete_rule output_empty 204). NOT live-verified against 2.4.0p35." The update_rule docstring must state WHY conditions and properties are mandatory arguments: edit_rule defaults omitted ones to {}, which would drop the host_name condition and make a per-host rule site-wide. The get_rule docstring notes show_rule declares no etag, so the ETag header may be absent and callers must cope (design decision 8).
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && uv run pytest tests/test_api.py -q -k "rule" && uvx ruff check src/checkmk_wizard/api.py tests/test_api.py</automated>
  </verify>
  <done>Three methods exist, routed through _request; four new tests pass; the full tests/test_api.py passes.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: manage_existing_host_services step, helpers, run() wiring, tests</name>
  <files>src/checkmk_wizard/wizard.py, tests/test_wizard.py</files>
  <behavior>
    - _service_candidate_hosts: keeps tag_agent cmk-agent/all-agents, drops no-agent, absent tag_agent, excluded names and entries without id; ip falls back to the host name when ipaddress is absent
    - _host_service_rules: matches only folder-equal rules whose host_name.match_on is exactly [hostname]; ignores multi-host rules, other folders, and rules without host_name
    - _parse_systemd_rule_names: "{'names': ['~^cron$', '~^nginx\\-proxy$']}" gives (["cron", "nginx-proxy"], []); a hand regex like "~ssh.*" lands in the custom list; garbage value_raw returns None
    - _systemd_rule_value_raw round-trips through _parse_systemd_rule_names and strips a trailing .service, custom entries appended verbatim
    - declining the opening confirm returns [] and makes no REST call (respx with no routes, assert_all_called not needed; any call would raise)
    - existing rule + changed selection: GET then PUT on /objects/rule/{id} with the original conditions and properties resent and the new names; returned OnboardedHost has os_family "linux" and expected_services == the added names only
    - no existing rule: one POST to the rules collection (create path), no PUT
    - every editable name unticked and no custom entries: DELETE of the rule, no PUT, no POST
    - two existing rules for the same host: first updated, second deleted (no duplicate left)
    - SSH skipped (_establish_ssh_access returns None) or list_running_systemd_services returns None: the free-text prompt is used and its default contains the current names
    - checkbox: currently monitored names are checked, a monitored-but-not-running name is still offered (labelled not running)
    - Apply confirm answered No: no PUT/POST/DELETE
    - a CheckmkAPIError on host A's update still applies host B and prints a yellow warning naming host A
    - no change for a host (selection equals current): host not in the summary and not returned
  </behavior>
  <action>
Write the tests first in tests/test_wizard.py (add the new names to the existing `from checkmk_wizard.wizard import (...)` list), following the file's conventions: respx routes on the REST paths (reuse the existing `_RULES_URL` constant for the collection; add a module constant for the object URL base), `monkeypatch.setattr(questionary.Question, "ask_async", ...)` with a scripted answer queue for prompts, monkeypatched `checkmk_wizard.wizard.remote.list_running_systemd_services` and `checkmk_wizard.wizard._establish_ssh_access`, and capsys for warnings. To assert checked/labelled choices, monkeypatch `questionary.checkbox` with a recorder that stores `choices` and returns an object whose ask_async yields the scripted selection (same idea as the existing fake_text pattern near line 137). Give the decline test and the duplicate-rule test a regression-style comment naming what they guard (existing flows unchanged; never two rules per host). Run, see failures.

Then implement in wizard.py, in a new section placed right after `_ensure_systemd_inactive_crit_rule` (before the Phase 5 SSH helpers), honouring every item in <design_decisions>:
- Module constant `_SYSTEMD_DISCOVERY_RULESET = "discovery_systemd_units_services"`. Do not change `_create_service_discovery_rules` (surgical); it keeps its own literal.
- `@dataclass ServiceEditPlan` with hostname, folder, ip, rules (list of rule dicts owned by the host), current (list[str]), custom (list[str]), selected (list[str]), and `added` / `removed` properties (sorted set differences selected minus current and current minus selected).
- Pure helpers `_service_candidate_hosts(hosts, exclude_names) -> list[tuple[str, str, str]]` (name, folder, ip), `_host_service_rules(rules, hostname, folder) -> list[dict]`, `_parse_systemd_rule_names(value_raw) -> tuple[list[str], list[str]] | None` (design decision 6), `_systemd_rule_value_raw(names, custom) -> str` (design decision 7).
- `async def _prompt_host_services(hostname, ip, current, ssh_creds) -> list[str]`: if ssh_creds, call `remote.list_running_systemd_services(ip, ssh_creds)`; on a list, show `questionary.checkbox` over sorted(set(running) | set(current)) with `checked=name in current` and a " (monitored, not running)" title suffix for current names not in running (Choice value stays the bare name); otherwise free-text `questionary.text` with default ", ".join(current), split on commas, strip, drop blanks, removesuffix(".service"). Same wording style as `_collect_expected_services`.
- `async def _apply_host_service_change(client, plan) -> bool`: best-effort, every CheckmkAPIError caught, yellow warning naming the host and pointing at the manual fallback (Setup > Services > Service discovery rules > "Systemd single services discovery"), returns False on failure. Logic: if plan.selected and plan.custom are both empty, delete every owned rule; elif owned rules exist, GET the first via `client.get_rule`, take `ETag` header or "*" (design decision 8), PUT via `client.update_rule` with `_systemd_rule_value_raw(plan.selected, plan.custom)` and the GET body's `extensions.conditions` / `extensions.properties` (fall back to the list entry's extensions if missing), then `delete_rule` every further owned rule; else call `_create_service_discovery_rules(client, OnboardedHost(ip, hostname, folder, "linux"), plan.selected)`. After a successful write with non-empty selected, call `_ensure_systemd_inactive_crit_rule(client, that OnboardedHost, plan.selected)`.
- `async def manage_existing_host_services(client, *, exclude_names: set[str]) -> list[OnboardedHost]`: console.rule "Manage monitored services on existing hosts (optional)"; FIRST `questionary.confirm("Change which services are monitored on hosts that are already onboarded (Linux/systemd)?", default=False)` and return [] on No before any REST call. Then list hosts (warn and return [] on CheckmkAPIError), build candidates (print "[dim]No existing agent hosts found.[/dim]" and return [] when none), checkbox to pick hosts labelled "name [folder] (ip)", return [] if none picked. List rules once via `client.list_rules(_SYSTEMD_DISCOVERY_RULESET)`; if that call fails, warn and return [] (cannot rule out duplicates, same reasoning as `_ensure_systemd_inactive_crit_rule`). `ssh_creds = await _establish_ssh_access(first picked ip)`. Per picked host: owned rules, parse each (skip host with warning if any owned rule is unparseable), union current names (order-preserving, deduped) and custom entries, print custom entries as "kept unchanged" in dim, prompt, build a ServiceEditPlan, keep it only if added or removed is non-empty. If no plans, print "No changes." and return []. Print a rich Table (Host, Folder, Add, Remove), then one `questionary.confirm("Apply these service changes?", default=False)`; No returns [] with a dim "nothing was written". Yes: apply each plan independently (one failure never stops the next) and return `OnboardedHost(ip=..., hostname=..., folder=..., os_family="linux", expected_services=plan.added)` for each successful one. Docstring explains why the step sits after Phase 4 and why its result goes to Phase 6 only (design decision 1), and that Windows is out of scope (design decision 3).
- run(): inside the existing try block, after `onboarded = await phase4_classification(...)`, add `service_hosts = await manage_existing_host_services(client, exclude_names={h.hostname for h in onboarded} | {h.ip for h in onboarded})`; change only the Phase 6 call to `await phase6_discovery(client, connection, onboarded + service_hosts)`. phase5 and phase7 calls stay exactly as they are. Add a one-line comment at the Phase 6 call explaining why phase7 does not get service_hosts (demo always-up rule).
- Add one run()-level test that monkeypatches phase1..phase7, `_provision_topology_editor`, `CheckmkClient` (or uses respx with no routes) and `manage_existing_host_services` to return one host, and asserts phase6 received onboarded + that host while phase5 and phase7 received only onboarded.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && uv run pytest tests/test_wizard.py -q && uv run pytest -q && uvx ruff check src/checkmk_wizard/wizard.py tests/test_wizard.py</automated>
  </verify>
  <done>All behaviours above have passing tests; the whole suite passes; ruff clean on touched files; run() calls the new step after Phase 4 inside the abort try block and feeds its hosts to Phase 6 only.</done>
</task>

<task type="auto">
  <name>Task 3: Document the step (WIZARD-OPERATION.md, README) with manual fallback</name>
  <files>docs/WIZARD-OPERATION.md, README.md</files>
  <action>
In docs/WIZARD-OPERATION.md: (a) in "Entry point and control flow", insert `→ manage_existing_host_services()  (optional, default No)` between phase4_classification() and phase5_onboarding() in the flow block, and note its hosts are passed to phase6_discovery only; (b) add a new section "## Manage monitored services on existing hosts (optional, between Phase 4 and Phase 5)" right before the Phase 5 section, covering: the opt-in prompt (default No, no REST calls when declined); which hosts are offered (explicit tag_agent cmk-agent/all-agents, this run's promoted hosts excluded); Linux/systemd only and why Windows is not included; SSH credential prompt shared like Phase 5, checkbox semantics (pre-ticked = monitored, "monitored, not running" entries, untick = stop, tick = start), free-text fallback; the summary table and Apply confirm (default No); exactly what changes in Checkmk (per-host `discovery_systemd_units_services` rule in the host's folder with a host_name condition: updated in place via GET + PUT /objects/rule/{id} resending conditions and properties, created when absent, deleted when empty, duplicates collapsed to one; hand-written regex entries kept unchanged; global "systemd inactive = CRIT" rule ensured); that Phase 6 activates, runs fix_all and verifies the added services, removed ones vanish as vanished services, and Phase 7 activates; Esc behaviour (inside the abortable range, pending rule edits handled by the abort prompt); the manual fallback kept as a note (Setup > Services > Service discovery rules > "Systemd single services discovery", edit the host's rule, then run service discovery on the host and activate changes); and that the rule GET/PUT/DELETE shapes and ETag handling are source-read only, not live-verified on 2.4.0p35. (c) In the Phase 6 section add one sentence that it also receives the hosts edited by the new step. In README.md, grep for where the wizard phases are listed (around the Phase 4/Phase 5 mentions near line 112-260); if a phase list or flow description exists, add a one-line mention of the optional step in the right place; if the README has no such list, leave README untouched and say so in the SUMMARY. Keep wording plain, no emojis, match existing heading style.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && grep -c "Manage monitored services on existing hosts" docs/WIZARD-OPERATION.md && grep -c "manage_existing_host_services" docs/WIZARD-OPERATION.md && grep -c "Systemd single services discovery" docs/WIZARD-OPERATION.md</automated>
  </verify>
  <done>Docs describe the step, its position, what it writes in Checkmk, the Windows exclusion, the unverified REST shapes and the manual fallback; flow diagram updated; README updated only if it lists the flow.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| wizard -> Checkmk REST | rule read/update/delete with the automation user |
| Checkmk REST -> wizard | `value_raw` strings from the server are parsed locally |
| wizard -> target host (SSH) | read-only `systemctl list-units` with operator-supplied credentials |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-ejn-01 | Tampering / Elevation | _parse_systemd_rule_names | mitigate | parse server `value_raw` with `ast.literal_eval` only, never eval; non-dict / non-list values rejected |
| T-ejn-02 | Tampering | update_rule | mitigate | always resend the rule's own conditions and properties so an edit can never widen a host rule to the whole site; only rules whose host_name.match_on is exactly [hostname] in the host's folder are ever modified |
| T-ejn-03 | Tampering | service names typed or scanned | mitigate | every name is `re.escape`d and anchored `~^...$` before writing, same as Phase 5 |
| T-ejn-04 | Denial of service (config) | apply loop | mitigate | single Apply confirm default No; per-host best-effort, failures warn only; Esc stays enabled so `_handle_abort` can revert pending edits |
| T-ejn-05 | Information disclosure | SSH credentials | accept | reuses `_establish_ssh_access`; credentials are held in memory only, as in Phase 5 |
</threat_model>

<verification>
- `uv run pytest -q` passes (whole suite).
- `uvx ruff check src tests` reports nothing new on touched files.
- `grep -n "manage_existing_host_services" src/checkmk_wizard/wizard.py` shows the definition and exactly one call in run().
- `grep -n "phase7_activation(client, connection, onboarded" src/checkmk_wizard/wizard.py` still matches (Phase 7 unchanged).
</verification>

<success_criteria>
- Declining the new prompt leaves the wizard flow and every pre-existing test unchanged.
- An existing Linux agent host's monitored systemd services can be added and removed from the wizard, with update / create / delete-when-empty / no-duplicate behaviour covered by tests.
- Rediscovery and activation reuse phase6_discovery and phase7_activation without changes to those functions.
- SUMMARY states the feature is not live-verified here, lists the unverified REST shapes (GET/PUT/DELETE /objects/rule/{id}, ETag presence on GET and If-Match "*" fallback, properties echo accepted by PUT), and gives this operator checklist: (1) run the wizard, answer Yes, add a service to an existing host, apply; after Phase 6/7 the "Systemd Service <name>" service appears; (2) rerun, untick that service, apply; it vanishes after discovery/activation and the rule no longer lists it; (3) rerun, untick everything; the host's "Systemd single services discovery" rule is gone; (4) check in Setup that each host has at most one such rule and its host_name condition is intact.
</success_criteria>

<output>
Create `.planning/quick/261008-ejn-wizard-step-manage-monitored-services-on/261008-ejn-SUMMARY.md` when done.
</output>
