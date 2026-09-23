---
phase: quick-260924-azn
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/checkmk_wizard/api.py
  - tests/test_api.py
  - src/checkmk_wizard/wizard.py
  - tests/test_wizard.py
  - deploy/compose.yaml
  - deploy/.env.example
  - docs/Podman setup for checkmk, minio, mosquitto, worker.md
  - docs/WIZARD-OPERATION.md
  - README.md
autonomous: true
requirements: [TODO-2026-09-21-pre-seed-rest-secret]

must_haves:
  truths:
    - "With CMK_REST_SECRET set in the worker env, a wizard run provisions the 'automation' user with exactly that secret — no generate/print/hand-copy step"
    - "Re-running the wizard against a site where 'automation' already exists updates that user's secret to the CMK_REST_SECRET value instead of failing"
    - "When CMK_REST_SECRET came from the environment, the secret value is never printed to the console"
    - "With CMK_REST_SECRET unset/empty, today's behavior is unchanged: random secret, POST-only create, secret printed once"
    - "worker and poller both read the one CMK_REST_SECRET value from deploy/.env, and the docs/.env.example describe setting it BEFORE the first wizard run"
  artifacts:
    - path: "src/checkmk_wizard/api.py"
      provides: "bootstrap_automation_user(..., secret=None) with create-vs-update idempotency"
      contains: "objects/user_config/"
    - path: "src/checkmk_wizard/wizard.py"
      provides: "Both bootstrap call sites pass os.environ CMK_REST_SECRET; env-sourced secret never printed"
      contains: "CMK_REST_SECRET"
    - path: "deploy/.env.example"
      provides: "Pre-chosen shared CMK_REST_SECRET documentation"
  key_links:
    - from: "src/checkmk_wizard/wizard.py"
      to: "bootstrap_automation_user"
      via: "secret= kwarg sourced from os.environ.get('CMK_REST_SECRET')"
      pattern: "secret=env_secret"
    - from: "deploy/compose.yaml worker + poller"
      to: "deploy/.env"
      via: "CMK_REST_SECRET=${CMK_REST_SECRET:-} interpolation (already present on both)"
      pattern: "CMK_REST_SECRET=\\$\\{CMK_REST_SECRET:-\\}"
---

<objective>
Implement todo `.planning/todos/pending/2026-09-21-pre-seed-fixed-automation-user-rest-secret-from-env.md`:
the operator pre-chooses `CMK_REST_SECRET` in `deploy/.env`; the wizard (running in the
`worker` container) pushes that exact value into Checkmk as the `automation` user's secret —
creating the user if missing, updating its secret if it already exists — so `worker`, `poller`
and every script share one value with no generate-then-copy step. Unset env keeps today's
generate+print fallback.

Purpose: remove the last manual credential hand-off in the container deployment, mirroring how
`CMK_PASSWORD` already works for `cmkadmin`.
Output: updated `api.py`, `wizard.py`, tests, compose comments, `.env.example`, docs.
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.0/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.0/templates/summary.md
</execution_context>

<context>
@./CLAUDE.md
@.planning/STATE.md
@.planning/todos/pending/2026-09-21-pre-seed-fixed-automation-user-rest-secret-from-env.md

<design_decisions>
Resolved by the planner (quick mode, no CONTEXT.md):

1. **Where env is read:** `wizard.py` reads `os.environ.get("CMK_REST_SECRET")` and passes it to
   `bootstrap_automation_user(..., secret=...)` as a new keyword-only-by-convention last
   parameter `secret: str | None = None`. Rationale: every other env read (`CMK_PASSWORD`,
   `CMK_SITE_ID`) lives in `wizard.py`; `api.py` has zero `os.environ` reads today and stays
   that way (adapter layer stays pure and trivially testable). Semantics are identical to
   "bootstrap_automation_user uses CMK_REST_SECRET when set". Empty string is treated as unset
   (`os.environ.get("CMK_REST_SECRET") or None`) because compose interpolates
   `${CMK_REST_SECRET:-}` to an empty string when `.env` lacks it.
2. **Idempotency (create vs update), only when `secret` is supplied:** after `_gui_login`, do
   `GET {base}/api/v1/objects/user_config/{username}`.
   - 404 → `POST .../domain-types/user_config/collections/all` exactly as today (same body).
   - 200 → take its `ETag` header (missing ETag → raise `CheckmkAPIError("GET", ..., "missing ETag header")`
     exactly like `change_cmkadmin_password`), then
     `PUT {base}/api/v1/objects/user_config/{username}` with
     `json={"auth_option": {"auth_type": "automation", "secret": secret, "store_automation_secret": True}}`,
     headers `Accept: application/json` + `If-Match: <etag>`; non-200 → `CheckmkAPIError("PUT", ...)`
     with the json-or-text body fallback. Do NOT send `roles`/`fullname` on update (surgical:
     only the secret is being reconciled).
   - any other GET status → `CheckmkAPIError("GET", ...)`.
   GET-then-branch was chosen over "POST and interpret the duplicate-user error" because the
   duplicate-user status code is not live-verified (existing tests mock both 400 and 409).
   The existing eager cmkadmin self-activation block runs unchanged after either branch (the PUT
   is also a pending cmkadmin `edit-users` change). Reuse the exact GET-ETag-PUT shape of
   `change_cmkadmin_password()` (api.py ~626-701) — no new helper.
3. **Fallback (`secret is None`):** byte-for-byte today's behavior — `secrets.token_urlsafe(24)`,
   POST-only (no GET probe), so an existing user still raises `CheckmkAPIError` and the wizard
   falls through to its manual prompt. Rationale: silently rotating an existing user's secret
   to a random value would break poller/scripts that already hold the old one.
4. **Never print an env-sourced secret:** `_print_automation_secret_created(secret, from_env: bool)`
   — `from_env=True` prints `"[green]Automation user 'automation' provisioned with CMK_REST_SECRET from the environment.[/green]"`
   (no secret value); `from_env=False` keeps today's message (secret shown once) but rewords the
   tail to: set `CMK_REST_SECRET` in `deploy/.env` BEFORE the next run to skip this step.
5. **Password policy / length:** NOT validated client-side (Checkmk stays the source of truth;
   its rejection surfaces through `CheckmkAPIError`, which both call sites already print).
   Flag as UNVERIFIED in the docstring: whether Checkmk 2.4.0p35 applies a minimum length /
   the site "Password policy for local accounts" to automation secrets. If the executor can reach
   a live site (`curl -s http://localhost:5000/dmc/check_mk/api/1.0/openapi-doc.yaml`), grep the
   `AuthSecret`/`AuthUpdateSecret`-style schema for `minLength` and whether
   `store_automation_secret` is accepted on update, and cite the result in the docstring instead
   of "unverified". Either way, `.env.example` recommends a long random value
   (`uv run python -c "import secrets; print(secrets.token_urlsafe(24))"` — 32 chars, same
   generator the fallback uses).
6. **Compose:** `worker` (line ~123) and `poller` (line ~192) ALREADY interpolate
   `CMK_REST_SECRET=${CMK_REST_SECRET:-}` from `deploy/.env` — no new env wiring needed, only
   comment updates. No other service consumes it (dashboard uses its own `topology_editor`
   credential; `scripts/provision_topology_editor.py`, `probe_*.py` run inside `worker`).
7. **`.env.example`:** change `CMK_REST_SECRET=REPLACE_ME` → `CMK_REST_SECRET=` (empty). A copied
   but unedited `REPLACE_ME` would otherwise be pushed into Checkmk as the real secret; empty
   triggers the safe generate+print fallback instead.
</design_decisions>

<interfaces>
From src/checkmk_wizard/api.py (current):
- `async def bootstrap_automation_user(host, site, cmkadmin_password, proto="http", username="automation", cmkadmin_user="cmkadmin", port=None) -> str` (~line 385). Body: `secret = secrets.token_urlsafe(24)` (~432), `base = _site_base(proto, host, port, site)`, `async with httpx.AsyncClient() as client:` → try: `_gui_login(...)`, POST create, non-2xx → CheckmkAPIError; `except httpx.HTTPError as exc: raise CheckmkAPIError("GET/POST", login_url, 0, str(exc)) from exc`; then best-effort activation block; `return secret`.
- `change_cmkadmin_password` (~626-701): canonical GET `objects/user_config/<user>` → ETag → PUT with If-Match pattern to copy.

From src/checkmk_wizard/wizard.py:
- `_print_automation_secret_created(secret: str) -> None` (~295-310)
- Call site A, `_create_fresh_site` (~326-331): `secret = await bootstrap_automation_user(checkmk_host, site_name, admin_password, port=checkmk_port)` then `_print_automation_secret_created(secret)`.
- Call site B, container-mode Phase 1 (~522-534): `secret = await bootstrap_automation_user(checkmk_host, site_name, cmkadmin_password, port=checkmk_port)`, builds `site.SiteCredentials(...)`, then `_print_automation_secret_created(secret)`; `except CheckmkAPIError` prints "likely already exists from a previous run..." warning.

Tests: tests/test_api.py `test_bootstrap_automation_user_success` (~374) is the respx template (LOGIN_URL, LOGIN_PAGE_HTML, BASE constants); tests/test_wizard.py ~220-265 is the container-mode Phase 1 template (`answers` iter, `_mock_container_mode_omd_calls`, `fake_bootstrap(host, site_name, cmkadmin_password, **kwargs)`, respx `/version`). `monkeypatch.setenv("CMK_PASSWORD", ...)` precedent at ~441.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: bootstrap_automation_user accepts a pre-chosen secret with create-vs-update idempotency</name>
  <files>src/checkmk_wizard/api.py, tests/test_api.py</files>
  <behavior>
    - test_bootstrap_automation_user_uses_supplied_secret_when_user_missing: GET objects/user_config/automation → 404; POST create body's auth_option.secret == "fixed-env-secret-0123456789"; return value is that same string; activation route called; no PUT made.
    - test_bootstrap_automation_user_updates_existing_user_secret: GET → 200 with ETag '"u-etag"'; PUT route called with If-Match '"u-etag"' and body auth_option == {"auth_type": "automation", "secret": <supplied>, "store_automation_secret": True}; create POST route NOT called; returns supplied secret; activation still called.
    - test_bootstrap_automation_user_update_rejected_raises: GET 200+ETag, PUT → 400 json {"title": "..."} → CheckmkAPIError.
    - test_bootstrap_automation_user_existing_user_missing_etag_raises: GET 200 without ETag → CheckmkAPIError.
    - Existing tests (no secret kwarg) keep passing unchanged — fallback path makes no GET to objects/user_config (assert in the existing success test is not required; respx.mock's default assert_all_mocked would fail on an unmocked GET, which already guards it).
  </behavior>
  <action>
    Per design_decisions 1-3 and 5: add `secret: str | None = None` as the LAST parameter of `bootstrap_automation_user` (after `port`; existing callers/test doubles are positional/`**kwargs`, so strictly additive). Replace the unconditional `secret = secrets.token_urlsafe(24)` with: remember `pre_seeded = secret is not None`; if not pre-seeded, generate as today. Inside the existing `try` (so httpx errors stay wrapped into `CheckmkAPIError("GET/POST", ...)`), after `_gui_login`: if pre-seeded, GET `f"{base}/api/v1/objects/user_config/{username}"` with Accept json and branch 404→existing POST create / 200→ETag+PUT / else raise, exactly as design_decisions 2 specifies, mirroring `change_cmkadmin_password`'s GET-ETag-PUT code and error-body fallback (json → ValueError → text). If not pre-seeded, run the existing POST unchanged. Leave the activation block and `return secret` untouched. Update the docstring (keep its prose style): add a paragraph explaining the pre-seeded path (why: `deploy/.env`'s `CMK_REST_SECRET` is shared with poller/worker so the value must be known ahead of time; why update-on-exists: a re-run/site restore must re-sync Checkmk to `.env`; why GET-probe instead of parsing the duplicate-user error: that status code is not live-verified) and a line on the policy question — cite the OpenAPI-spec finding if a live site was reachable, otherwise state explicitly "UNVERIFIED against a live site: PUT with auth_type automation + store_automation_secret on update, and any minimum-length/password-policy rule for automation secrets". Also update the "Raises" paragraph: with a pre-seeded secret an existing user is updated rather than raising. Write the four tests first (RED), modeled on `test_bootstrap_automation_user_success` (same LOGIN_URL/BASE constants, same pending_changes + activate mocks), then implement (GREEN).
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && uv run pytest tests/test_api.py -q -k bootstrap_automation_user && uvx ruff check src/checkmk_wizard/api.py tests/test_api.py</automated>
  </verify>
  <done>All bootstrap_automation_user tests (old + 4 new) pass; ruff clean; fallback path unchanged; pre-seeded path creates when missing and PUT-updates when present.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Wizard passes CMK_REST_SECRET from env and never prints it</name>
  <files>src/checkmk_wizard/wizard.py, tests/test_wizard.py</files>
  <behavior>
    - test_phase1_container_mode_pushes_cmk_rest_secret_from_env: monkeypatch.setenv("CMK_REST_SECRET", "env-secret-abcdefghij"); fake_bootstrap asserts kwargs["secret"] == "env-secret-abcdefghij" and returns it; resulting connection.secret == that value; captured stdout (capsys) does NOT contain "env-secret-abcdefghij" and DOES contain "CMK_REST_SECRET from the environment".
    - test_phase1_container_mode_without_cmk_rest_secret_keeps_generated_fallback: monkeypatch.delenv("CMK_REST_SECRET", raising=False) (and a second case/param with setenv to "" ) → fake_bootstrap sees kwargs.get("secret") is None; the generated secret IS printed once (today's behavior).
    - Existing container-mode tests: add monkeypatch.delenv("CMK_REST_SECRET", raising=False) where they'd otherwise be sensitive to the developer's shell env (the worker container sets it).
  </behavior>
  <action>
    Per design_decisions 1 and 4: change `_print_automation_secret_created(secret: str)` to `_print_automation_secret_created(secret: str, from_env: bool) -> None`. When `from_env` is True print only the non-secret confirmation from design_decisions 4; otherwise keep today's secret-once message but replace "save this to deploy/.env as CMK_REST_SECRET so the worker and poller containers can authenticate." with wording that tells the operator to put this value (or any pre-chosen one) into `deploy/.env` as `CMK_REST_SECRET` so worker/poller authenticate and future runs skip this step. Update its docstring: the env-sourced secret is deliberately never echoed (the operator already has it in `deploy/.env`; echoing would only add scrollback exposure). At BOTH call sites (`_create_fresh_site` ~326 and container-mode Phase 1 ~522), read `env_secret = os.environ.get("CMK_REST_SECRET") or None` immediately before the call, pass `secret=env_secret` to `bootstrap_automation_user`, and call `_print_automation_secret_created(secret, from_env=env_secret is not None)`. Add a short comment at the container-mode site noting that with `env_secret` set an existing 'automation' user is updated, not rejected, so the "likely already exists" except-branch now only fires in the fallback path; adjust that warning text minimally to say "(set CMK_REST_SECRET in deploy/.env to have the wizard reconcile an existing user automatically)". No new helpers. Write tests first using the existing container-mode Phase 1 test (~220-265) as the template, with `capsys` for output assertions (rich Console writes to stdout).
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && uv run pytest tests/test_wizard.py -q && uv run pytest -q && uvx ruff check src tests</automated>
  </verify>
  <done>Full test suite green; env-sourced secret reaches bootstrap_automation_user via secret= at both call sites and is absent from console output; unset/empty env keeps the generated-secret print.</done>
</task>

<task type="auto">
  <name>Task 3: Document one pre-chosen shared CMK_REST_SECRET in compose, .env.example and docs</name>
  <files>deploy/compose.yaml, deploy/.env.example, docs/Podman setup for checkmk, minio, mosquitto, worker.md, docs/WIZARD-OPERATION.md, README.md</files>
  <action>
    Per design_decisions 6-7. Comments/docs only — do not change any env line in compose (worker ~123 and poller ~192 already interpolate `CMK_REST_SECRET=${CMK_REST_SECRET:-}`; keep the empty-default rationale comment intact).
    (a) `deploy/compose.yaml`: in the worker comment block (~112-118) state the wizard now PUSHES this value into Checkmk as the `automation` user's secret (create or update), so worker and poller share one value from `deploy/.env`. In the poller comment (~170-188) replace "fill it in after running the wizard's Phase 1 bootstrap" with: choose it BEFORE the first wizard run; the wizard provisions Checkmk to match; recreate the poller (`podman compose up -d poller`) after changing it.
    (b) `deploy/.env.example`: rewrite the header comment — pick a long random value up front (`uv run python -c "import secrets; print(secrets.token_urlsafe(24))"`), it is shared by worker (wizard, provisioning/probe scripts) and poller, the wizard pushes it into Checkmk (creating or updating the `automation` user), changing it later = edit `.env`, re-run the wizard's Phase 1, recreate poller/worker; leave empty to fall back to the wizard generating and printing one. Keep the "cmkadmin password does NOT work here" note but drop the stale `api.py:360` line reference. Set the value line to `CMK_REST_SECRET=` (empty — see design_decisions 7).
    (c) Podman doc "Note on `CMK_REST_SECRET` (poller)" paragraph (~line 214): replace the "real secret comes from the Checkmk UI / automation.secret file ... after a first wizard run ... This copy is manual" sentences with the pre-seed flow (set it in `deploy/.env` before `podman compose up`, the wizard's Phase 1 pushes it into Checkmk; re-running reconciles an existing user). Keep the empty-default/degradation and rotate-before-exposing sentences. Also update line ~195-196 wording if it implies the secret is obtained after the fact, and the §8 cmkadmin-prompt bullet (~528) to mention the pre-seeded secret is used automatically.
    (d) `docs/WIZARD-OPERATION.md`: in the "How `bootstrap_automation_user()` works" section (~417) add a step/paragraph for the pre-seeded path (GET user → POST create or ETag PUT update); fix the security bullets (~1501 and ~1531) so they say the automation secret is printed only in the fallback (env unset) path and an env-sourced secret is never printed.
    (e) `README.md` container-mode cmkadmin bullet (~60-68): one sentence that with `CMK_REST_SECRET` set in the worker env the wizard provisions/updates the `automation` user with that exact value.
    Keep edits surgical; match each file's existing voice.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && test "$(grep -cF 'CMK_REST_SECRET=${CMK_REST_SECRET:-}' deploy/compose.yaml)" = 2 && grep -qx 'CMK_REST_SECRET=' deploy/.env.example && ! grep -q REPLACE_ME deploy/.env.example && ! grep -q 'This copy is manual' "docs/Podman setup for checkmk, minio, mosquitto, worker.md" && grep -qi 'before the first wizard run' deploy/compose.yaml && echo OK</automated>
  </verify>
  <done>Both compose services still interpolate the single `${CMK_REST_SECRET:-}`; compose comments, `.env.example`, Podman doc, WIZARD-OPERATION.md and README describe choosing the secret up front and the wizard pushing/reconciling it; no remaining instruction to hand-copy the wizard-printed secret except as the documented env-unset fallback.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| deploy/.env → worker/poller env | Operator-chosen secret enters containers via compose interpolation |
| wizard → Checkmk REST (cmkadmin GUI session) | Secret sent in PUT/POST body, plain HTTP on cmk_net by default |
| wizard → terminal | Console scrollback |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-azn-01 | Information Disclosure | `_print_automation_secret_created` | mitigate | `from_env=True` path prints no secret; Task 2 test asserts the env value is absent from captured stdout |
| T-azn-02 | Tampering | `.env.example` placeholder pushed as real secret | mitigate | Placeholder removed (`CMK_REST_SECRET=` empty → safe fallback) |
| T-azn-03 | Tampering | Existing user's secret overwritten | accept | Only when the operator explicitly set `CMK_REST_SECRET`; that is the intended reconcile. Fallback path never overwrites (POST-only) |
| T-azn-04 | Information Disclosure | Secret in REST body over HTTP | accept | Same exposure as existing bootstrap/`CMK_PASSWORD` flows on the private `cmk_net`; documented rotate-before-exposing guidance retained (CONCERNS.md cleartext-HTTP item) |
| T-azn-05 | Information Disclosure | deploy/.env committed | mitigate | Already gitignored (`.gitignore:6`); `.env.example` holds no value |
</threat_model>

<verification>
- `uv run pytest -q` green; `uvx ruff check src tests` clean.
- `grep -n "CMK_REST_SECRET" src/checkmk_wizard/wizard.py` shows the env read at both bootstrap call sites.
- `grep -n "os.environ" src/checkmk_wizard/api.py` returns nothing (adapter stays env-free).
</verification>

<success_criteria>
- Pre-seeded secret: missing user → created with it; existing user → secret PUT-updated to it; never printed.
- Unset/empty env: identical to pre-change behavior.
- worker + poller share one `deploy/.env` value; docs/.env.example/compose comments describe the up-front flow; no stale "copy the printed secret" instruction outside the fallback.
</success_criteria>

<output>
Create `.planning/quick/260924-azn-pre-seed-fixed-automation-user-rest-secr/260924-azn-SUMMARY.md` when done
</output>
