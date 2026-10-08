---
phase: quick-261008-cto
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/checkmk_wizard/api.py
  - src/checkmk_wizard/wizard.py
  - tests/test_api.py
  - tests/test_wizard.py
  - docs/WIZARD-OPERATION.md
autonomous: true
requirements: [QUICK-261008-CTO]

must_haves:
  truths:
    - "When Phase 5 onboards a Linux host with at least one expected systemd service, the wizard ensures exactly one global (folder '/', no host_name condition) 'Systemd single service' rule exists with inactive = CRIT"
    - "Re-running the wizard, or onboarding a second Linux host, does not create a duplicate rule"
    - "A REST failure while listing or creating the rule prints a yellow warning and onboarding continues"
    - "Windows hosts and Linux hosts with no expected services never trigger the rule"
    - "Docs tell operators of EXISTING sites how to get the rule (UI step or wizard re-run)"
  artifacts:
    - path: "src/checkmk_wizard/api.py"
      provides: "CheckmkClient.list_rules(ruleset_name) via _request"
      contains: "async def list_rules"
    - path: "src/checkmk_wizard/wizard.py"
      provides: "_ensure_systemd_inactive_crit_rule helper + call in phase5 onboarding"
      contains: "_ensure_systemd_inactive_crit_rule"
    - path: "tests/test_wizard.py"
      provides: "create / skip-existing / warn-on-failure / gating tests incl. regression comment"
    - path: "docs/WIZARD-OPERATION.md"
      provides: "Documentation of the new rule and existing-site note"
  key_links:
    - from: "src/checkmk_wizard/wizard.py (phase5 onboarding, next to `await _create_service_discovery_rules(client, h, h.expected_services)`)"
      to: "_ensure_systemd_inactive_crit_rule"
      via: "direct await"
      pattern: "await _ensure_systemd_inactive_crit_rule\\("
    - from: "_ensure_systemd_inactive_crit_rule"
      to: "GET /domain-types/rule/collections/all?ruleset_name=checkgroup_parameters:systemd_units_services"
      via: "client.list_rules then client.create_rule"
      pattern: "list_rules\\("
---

<objective>
Make a stopped (inactive) systemd service that the wizard set up for monitoring show CRIT instead of OK.

Purpose: Checkmk's "Systemd single service" ruleset defaults to active OK, inactive OK, failed CRIT, so stopping a monitored service shows "inactive" but stays OK, and the dashboard and analytics (failure needs) never see it. One global rule fixes that for every current and future host.
Output: `CheckmkClient.list_rules`, wizard helper `_ensure_systemd_inactive_crit_rule`, tests, docs.
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/templates/summary.md
</execution_context>

<context>
@./CLAUDE.md
@.planning/STATE.md

<interfaces>
From src/checkmk_wizard/api.py (CheckmkClient):
- `async def _request(self, method, path, *, json_body=None, params=None, extra_headers=None, expect=(200, 201)) -> httpx.Response` (line ~181). All new REST calls go through this.
- `async def list_folders(self) -> list[dict]` / `list_hosts` (lines ~241, ~286): pattern to copy, `return resp.json().get("value", [])` with a docstring citing how the collection shape was verified.
- `async def create_rule(self, ruleset: str, folder: str, value_raw: str, conditions: dict | None = None) -> dict` (line ~374): POST /domain-types/rule/collections/all; `conditions or {}`; comment says plain JSON value_raw is live-verified accepted.

From src/checkmk_wizard/wizard.py:
- `_create_threshold_rules(client)` (~2169): global-rule pattern (folder "/", no conditions), per-rule `except CheckmkAPIError` -> yellow warning. Its docstring explains why repr() is required ONLY for Levels()/CascadingDropdown valuespecs (Python tuple vs list).
- `_create_service_discovery_rules(client, host: OnboardedHost, service_names: list[str]) -> None` (~2246): gate `if not service_names or host.os_family not in ("linux", "windows"): return`.
- Call site in phase5 onboarding (~2684-2687):
  `h.expected_services = await _collect_expected_services(...)` then `await _create_service_discovery_rules(client, h, h.expected_services)`.
- `OnboardedHost(ip=..., hostname=..., folder=..., os_family=...)`; module-level `console`, `CheckmkAPIError`, `json`, `ast` availability: check imports at top of wizard.py (add `import ast` only if absent).

Tests: tests/test_wizard.py ~3642-3693 (respx.mock + `CheckmkClient(CONN)`, `BASE`, `json.loads(route.calls.last.request.content)`); tests/test_api.py ~162 `test_create_rule_sends_ruleset_folder_conditions`.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: list_rules REST helper and idempotent global systemd inactive=CRIT rule</name>
  <files>src/checkmk_wizard/api.py, src/checkmk_wizard/wizard.py, tests/test_api.py, tests/test_wizard.py</files>
  <behavior>
    - api: `list_rules("checkgroup_parameters:systemd_units_services")` sends GET /domain-types/rule/collections/all with query `ruleset_name=checkgroup_parameters:systemd_units_services` and returns the response's `value` list (empty list if `value` absent).
    - wizard: Linux host + non-empty services + list_rules returns [] -> exactly one POST with ruleset `checkgroup_parameters:systemd_units_services`, folder "/", conditions {}, and value_raw that decodes to {"states": {"active": 0, "inactive": 2, "failed": 2}, "states_default": 2}. This test carries the regression comment: bug = a stopped monitored systemd service showed "inactive" but stayed OK because Checkmk's default maps inactive to OK, so neither Checkmk, the dashboard nor analytics flagged it.
    - wizard: list_rules returns an existing rule with extensions.folder "/", no host_name in extensions.conditions, and value_raw whose states.inactive == 2 (test both a JSON-form and a Python-repr-form value_raw, e.g. "{'states': {'active': 0, 'inactive': 2, 'failed': 2}, 'states_default': 2}") -> no POST.
    - wizard: an existing rule in that ruleset that is host-scoped or in a subfolder or has inactive != 2 does NOT count -> POST happens.
    - wizard: GET returns 500 -> no exception, yellow warning printed, no POST attempted. POST returns 400 -> no exception, warning printed.
    - wizard: os_family "windows" or empty service list -> no HTTP calls at all.
  </behavior>
  <action>
In api.py, add `async def list_rules(self, ruleset_name: str) -> list[dict[str, Any]]` next to `create_rule`, implemented via `self._request("GET", "/domain-types/rule/collections/all", params={"ruleset_name": ruleset_name})` returning `resp.json().get("value", [])`. Before writing it, verify the endpoint: try Context7 (or `ctx7` CLI if present) for Checkmk REST API "Show rules" / list rules; if unavailable, WebFetch https://docs.checkmk.com/latest/en/rest_api.html or the Checkmk 2.4 source `cmk/gui/openapi/endpoints/rule/__init__.py` (`list_rules`, required `ruleset_name` query param) on GitHub. The docstring must cite which source confirmed it, following the existing "verified via context7: ..." comment style, and state it is not live-verified on 2.4.0p35. Each returned rule object carries `extensions.folder`, `extensions.conditions`, `extensions.value_raw`; note that in the docstring too.

In wizard.py, add module constants `_SYSTEMD_SERVICE_STATES_RULESET = "checkgroup_parameters:systemd_units_services"` and `_SYSTEMD_SERVICE_STATES_VALUE = {"states": {"active": 0, "inactive": 2, "failed": 2}, "states_default": 2}`, and a new `async def _ensure_systemd_inactive_crit_rule(client, host: OnboardedHost, service_names: list[str]) -> None` placed directly after `_create_service_discovery_rules`. Logic: return early unless `host.os_family == "linux"` and `service_names` is non-empty. Call `client.list_rules(...)`; if any existing rule has `extensions.folder == "/"`, no `host_name` key in `extensions.conditions` (missing/empty conditions OK), and its value_raw parsed with `ast.literal_eval` (catch ValueError/SyntaxError -> treat as non-matching) is a dict whose `states.inactive == 2`, print a dim "already present" line and return. Otherwise `create_rule(ruleset=..., folder="/", value_raw=json.dumps(_SYSTEMD_SERVICE_STATES_VALUE))` and print a green line. Wrap the list+create in `except CheckmkAPIError as exc:` printing a yellow warning that names the UI fallback (Setup > Services > Service monitoring rules > "Systemd single service", inactive = CRIT); never re-raise (best-effort convention). If the list call fails, warn and do not attempt create (avoids a duplicate when we cannot check).

value_raw encoding choice (document in the docstring): plain JSON via `json.dumps`, because every value is a plain int inside nested dicts; the repr() requirement described in `_create_threshold_rules` applies only to Levels()/CascadingDropdown valuespecs that distinguish tuple from list, and this value has no lists or tuples, so JSON and Python literal syntax are identical in meaning, matching `create_rule`'s live-verified JSON note. The idempotency parser uses `ast.literal_eval` because Checkmk echoes value_raw in Python-repr form, and literal_eval also accepts the JSON form for int-only dicts. The docstring must also state: ruleset id and the states/states_default keys come from Checkmk docs (https://checkmk.com/integrations/systemd_units_services) and `cmk/gui/plugins/wato/check_parameters/systemd_services.py`; the older `systemd_services` ruleset is deprecated and not used; defaults are active OK / inactive OK / failed CRIT; this is NOT yet live-verified on 2.4.0p35, with the same "create it in the GUI, GET the rule, compare extensions.value_raw" check instruction used by the host_check_commands helper. Global scope rationale: same as `_create_threshold_rules` (hosts without systemd unit services are unaffected); a more specific folder/host rule still wins per key.

Wire it in phase5 onboarding immediately after `await _create_service_discovery_rules(client, h, h.expected_services)`: `await _ensure_systemd_inactive_crit_rule(client, h, h.expected_services)`. Do not change `_create_service_discovery_rules` itself (its existing tests mock only the POST route).

Tests: add the api test in tests/test_api.py beside the create_rule test (assert `route.calls.last.request.url.params["ruleset_name"]`). Add the wizard tests from <behavior> beside the `_create_service_discovery_rules` tests, importing the new helper in the existing import block. To check printed warnings, follow how other tests in test_wizard.py capture `console` output (grep for an existing pattern; monkeypatch `wizard.console.print` if none). Then run the FULL suite: existing phase5_onboarding tests (around lines 1182-1290) that onboard a Linux host with expected services may now hit an unmocked GET under respx; fix by adding a `respx.get(f"{BASE}/domain-types/rule/collections/all").mock(return_value=Response(200, json={"value": []}))` route (or monkeypatching the new helper) in those tests only, without weakening their assertions.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && uv run pytest -q && uvx ruff check src/checkmk_wizard/api.py src/checkmk_wizard/wizard.py tests/test_api.py tests/test_wizard.py</automated>
  </verify>
  <done>All tests pass (including the new ones and every pre-existing one); ruff clean on touched files; `grep -c "await _ensure_systemd_inactive_crit_rule(" src/checkmk_wizard/wizard.py` == 1; the regression test comment names the inactive-stays-OK bug.</done>
</task>

<task type="auto">
  <name>Task 2: Document the rule and the existing-site step</name>
  <files>docs/WIZARD-OPERATION.md</files>
  <action>
In docs/WIZARD-OPERATION.md, right after the `_create_service_discovery_rules()` bullet in the Phase 5 section (~line 1314-1344), add a bullet for `_ensure_systemd_inactive_crit_rule()`: one global rule in folder "/" with no host condition on `checkgroup_parameters:systemd_units_services`, value states active 0 / inactive 2 / failed 2, states_default 2; why (Checkmk default keeps inactive OK, so a stopped service never alerted); created only when a Linux host has expected services; idempotent via `list_rules` (GET /domain-types/rule/collections/all?ruleset_name=...); best-effort warning on failure; JSON value_raw and why; not yet live-verified on 2.4.0p35. Add an "Existing sites" note: sites onboarded before this change lack the rule; either add it once by hand (Setup > Services > Service monitoring rules > "Systemd single service", create a rule in the main folder, set "inactive" to CRIT, keep failed CRIT and "other" CRIT, then Activate changes) or re-run the wizard's Phase 5 onboarding for any Linux host with expected services. Also add `checkgroup_parameters:systemd_units_services` to the list of JSON-safe rulesets in the paragraph ending "...specific to `Alternative`/`CascadingDropdown`-based ones." (~line 1590). Then `grep -rn "discovery_systemd_units_services\|_create_threshold_rules" README.md docs/*.md` and add a one-line mention wherever wizard-created rules are listed (skip docs/PLAN-CONFORMANCE-AUDIT.md, it is a historical audit). Plain prose, no line-number references to wizard.py that you have not verified.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && grep -c "systemd_units_services" docs/WIZARD-OPERATION.md && grep -c "Systemd single service" docs/WIZARD-OPERATION.md</automated>
  </verify>
  <done>WIZARD-OPERATION.md documents the rule, its value, idempotency, best-effort behavior, and the existing-site manual UI step / re-run option; both greps return >= 1.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| wizard -> Checkmk REST API | Authenticated automation user writes a site-wide rule |
| Checkmk REST response -> wizard | value_raw strings from existing rules are parsed locally |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-261008-cto-01 | Tampering | `_ensure_systemd_inactive_crit_rule` parsing value_raw | mitigate | Parse with `ast.literal_eval` only (never eval); catch ValueError/SyntaxError and treat as non-matching |
| T-261008-cto-02 | Denial of Service | Global rule makes every inactive unit service CRIT site-wide | accept | Only affects individually discovered systemd services, which the wizard only discovers for operator-selected units; intended behavior, documented |
| T-261008-cto-03 | Repudiation | Duplicate rules on re-run | mitigate | list-before-create; skip create when the list call fails |
</threat_model>

<verification>
- `uv run pytest -q` green; `uvx ruff check` clean on touched files.
- Cannot be live-verified from the dev machine (the podman stack runs on a separate deploy host). SUMMARY must say so and include this operator checklist:
  1. Run the wizard's Phase 5 for a Linux host with an expected service (or add the rule by hand on an existing site), then Activate changes.
  2. In Checkmk: Setup > Services > Service monitoring rules > "Systemd single service" shows exactly one rule in Main folder, inactive = CRIT; re-run does not add a second.
  3. Optional: `GET /objects/rule/{id}` and confirm `extensions.value_raw` matches the sent value.
  4. On the monitored host: `sudo systemctl stop <service>`; after the next check (~1 min) the "Systemd Service <name>" service is CRIT in Checkmk.
  5. The dashboard shows the host/service in CRIT, and a failure need appears (analytics, within ~15 s of the poll).
  6. `sudo systemctl start <service>`; the service returns to OK and the need clears.
</verification>

<success_criteria>
- One global inactive=CRIT systemd rule is created on first Linux-with-services onboarding, never duplicated, never fatal.
- Regression test documents the inactive-stays-OK bug.
- Docs cover the rule and the existing-site step.
</success_criteria>

<output>
Create `.planning/quick/261008-cto-wizard-global-rule-so-an-inactive-system/261008-cto-SUMMARY.md` when done, stating the value_raw encoding chosen (JSON) and why, how the list-rules endpoint was verified, that nothing was live-verified, and the operator checklist above.
</output>
