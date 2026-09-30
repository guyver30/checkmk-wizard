---
phase: quick-260930-hpy
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/checkmk_wizard/api.py
  - src/checkmk_wizard/wizard.py
  - scripts/provision_topology_editor.py
  - tests/test_api.py
  - tests/test_wizard.py
  - tests/test_provision_topology_editor.py
  - deploy/compose.yaml
  - deploy/.env.example
  - deploy/dashboard-nginx.conf
  - deploy/dashboard.Containerfile
  - dashboard-react/vite.config.ts
  - dashboard-react/src/lib/checkmkWrite.ts
  - dashboard-react/src/lib/checkmkWrite.test.ts
  - dashboard-react/src/lib/config.ts
  - dashboard-react/src/lib/config.test.ts
  - dashboard-react/src/components/TopologyToolbar.tsx
  - dashboard-react/src/components/TopologyToolbar.test.tsx
  - dashboard-react/src/routes/IndexRoute.tsx
  - dashboard-react/src/routes/IndexRoute.test.tsx
  - dashboard-react/README.md
  - docs/DEPLOY-NEW-MACHINE.md
  - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
  - docs/WIZARD-OPERATION.md
  - .planning/PROJECT.md
  - CLAUDE.md
  - .planning/phases/13-wizard-parents-support-and-topology-map/13-CONTEXT.md
autonomous: true
requirements: [QUICK-260930-hpy]

must_haves:
  truths:
    - "The built dashboard bundle contains no topology_editor secret and the browser never sends an Authorization header to /checkmk-api/"
    - "nginx injects 'Authorization: Bearer topology_editor <TOPOLOGY_EDITOR_SECRET>' on the allowed /checkmk-api/ paths, overriding anything the client sent"
    - "Only the method+path pairs the dashboard uses are proxied to Checkmk; every other /checkmk-api/ request returns 403"
    - "With TOPOLOGY_EDITOR_SECRET set in deploy/.env, a wizard run creates the topology_editor role and user (or rotates an existing user's secret to the env value) right after Phase 1, without ever aborting the run on failure"
    - "With TOPOLOGY_EDITOR_SECRET empty, the wizard skips provisioning with one dim note, and the dashboard's Edit topology switch is disabled with the hint 'Editing is off: set TOPOLOGY_EDITOR_SECRET in deploy/.env and run the wizard.'"
    - "The dashboard decides at runtime whether editing is available: GET /checkmk-api/<site>/check_mk/api/1.0/version returning 200 enables it; 401, any other status, or a network error keeps it off"
    - "scripts/provision_topology_editor.py still works as a manual fallback and uses TOPOLOGY_EDITOR_SECRET from env (create or rotate) when set"
  artifacts:
    - path: "src/checkmk_wizard/api.py"
      provides: "topology_editor constants + CheckmkClient.ensure_topology_editor_role / user_exists / upsert_automation_user / provision_topology_editor, all via _request()"
      contains: "async def provision_topology_editor"
    - path: "src/checkmk_wizard/wizard.py"
      provides: "_provision_topology_editor(client, connection) called first inside run()'s CheckmkClient block"
      contains: "async def _provision_topology_editor"
    - path: "deploy/dashboard-nginx.conf"
      provides: "allow-listed /checkmk-api/ locations with server-side Authorization injection, 403 catch-all"
      contains: "Bearer topology_editor ${TOPOLOGY_EDITOR_SECRET}"
    - path: "dashboard-react/src/lib/checkmkWrite.ts"
      provides: "probeEditingAvailable(); request() without Authorization"
      contains: "export async function probeEditingAvailable"
  key_links:
    - from: "deploy/compose.yaml (dashboard, worker)"
      to: "deploy/.env TOPOLOGY_EDITOR_SECRET"
      via: "environment entry TOPOLOGY_EDITOR_SECRET=${TOPOLOGY_EDITOR_SECRET:-}"
      pattern: "TOPOLOGY_EDITOR_SECRET=\\$\\{TOPOLOGY_EDITOR_SECRET:-\\}"
    - from: "src/checkmk_wizard/wizard.py run()"
      to: "CheckmkClient.provision_topology_editor"
      via: "_provision_topology_editor reads os.environ TOPOLOGY_EDITOR_SECRET"
      pattern: "provision_topology_editor\\("
    - from: "dashboard-react/src/routes/IndexRoute.tsx"
      to: "probeEditingAvailable"
      via: "useEffect on mount -> editingAvailable state -> TopologyToolbar editingConfigured + CriticalityEditor gate"
      pattern: "probeEditingAvailable\\(\\)"
    - from: "probe path /version"
      to: "nginx GET allow-list regex"
      via: "same path must be allowed by nginx or the probe always reports off"
      pattern: "version"
---

<objective>
Move the dashboard's `topology_editor` Checkmk credential out of the browser bundle. The
secret lives in `deploy/.env` as `TOPOLOGY_EDITOR_SECRET`; the wizard provisions the
role/user to that value right after Phase 1; the dashboard's nginx injects the Authorization
header server-side on an allow-list of the exact REST calls the dashboard makes; the SPA
stops sending credentials and detects "editing available" with a runtime probe.

Purpose: a secret in a static JS bundle is readable by anyone who can load the dashboard.
This design (approved by the user 2026-09-30) supersedes Phase 13 D-04's client-embedded
credential. Record it as an amendment; do not re-litigate it.

Output: api.py/wizard.py provisioning plus the refactored fallback script and pytest; nginx,
compose and .env wiring; dashboard-react probe/gating plus vitest; updated docs and
constraint amendments.
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/templates/summary.md
</execution_context>

<context>
@./CLAUDE.md
@.planning/STATE.md

<interfaces>
<!-- Extracted from the codebase. Use these directly; no exploration needed. -->

src/checkmk_wizard/api.py:
- `CheckmkConnection(host, site, username, secret, proto="http", registration_user=None, registration_secret=None, port=None)`; `.base_url` = `<proto>://<host>[:port]/<site>/check_mk/api/v1`
- `CheckmkClient(connection, timeout=30.0)`: async context manager; httpx client already carries `Authorization: Bearer <username> <secret>` and `Accept: application/json`.
- `async def _request(self, method, path, *, json_body=None, params=None, extra_headers=None, expect=(200, 201)) -> httpx.Response`: raises `CheckmkAPIError(method, url, status_code, body)` for any status not in `expect` (204 always allowed) and wraps `httpx.HTTPError` as status_code 0. Every new method MUST go through it (project rule). To inspect a 404 without raising, pass `expect=(200, 404)`.
- Existing: `get_pending_changes() -> (etag, list)`, `activate_changes(sites, etag, force_foreign_changes=False) -> dict`, `get_activation_run(activation_id) -> dict`.
- `bootstrap_automation_user(...)` lines ~470-535: the pre-seeded create-or-update pattern to mirror. If the user exists, it PUTs `{"auth_option": {"auth_type": "automation", "secret": secret, "store_automation_secret": True}}` with `If-Match: <ETag from the GET>` (a missing ETag raises CheckmkAPIError). Otherwise it POSTs the full user body to `/domain-types/user_config/collections/all`.

scripts/provision_topology_editor.py (current, urllib-based, 399 lines):
- Constants: `ROLE_ID = "topology_editor"`, `ROLE_ALIAS = "Topology editor (dashboard)"`, `BASE_ROLE_ID = "user"`, `USER_ID = "topology_editor"`, `REQUIRED_PERMISSIONS` = ("wato.use","wato.edit","wato.all_folders","wato.see_all_folders","wato.edit_hosts","wato.manage_hosts","wato.activate") with a long comment explaining why (keep that comment with the constant when you move it).
- `build_role_permissions(perm_ids) -> {id: "yes"}`, `build_user_body(username, secret)` -> `{username, fullname: ROLE_ALIAS, auth_option{automation, secret, store_automation_secret: True}, roles: [ROLE_ID]}`.
- `ensure_role`: GET `/objects/user_role/topology_editor`. On a non-200 it POSTs `/domain-types/user_role/collections/all` with `{"role_id": "user", "new_role_id": "topology_editor", "new_alias": ROLE_ALIAS}` (expects 200/201). It then ALWAYS PUTs `/objects/user_role/topology_editor` with `{"new_permissions": build_role_permissions(...)}` (expects 200/204, no If-Match).
- `activate_own_changes`: non-forced activation; a 401 means foreign changes are pending, so it warns and does not force.
- `main()`: reads CMK_REST_HOST/PORT (defaults checkmk/5000), CMK_SITE_ID (dmc), CMK_REST_USERNAME (automation), CMK_REST_SECRET (required, returns 1 if empty); `redact_auth_header`, `generate_secret` (token_urlsafe(32)).
- tests/test_provision_topology_editor.py imports it via importlib and uses: REQUIRED_PERMISSIONS, build_role_permissions, build_user_body, redact_auth_header, generate_secret, main (fails fast with 1 when CMK_REST_SECRET missing). Keep all these names importable from the script.

src/checkmk_wizard/wizard.py:
- `async def run()`: `connection = await phase1_site_bringup()`, then `async with CheckmkClient(connection) as client:` phase2..phase7. This path is shared by container mode and host-native mode.
- `async def _activate_pending_changes(client, connection) -> bool` (line ~2664): the wizard's standard awaited, multi-round activation helper.
- The module-level `console` (rich) is used for all output. `from_env` secrets are never echoed (see `_print_automation_secret_created`).

dashboard-react/src/lib/checkmkWrite.ts:
- `API_PREFIX = \`${CHECKMK_REST_ORIGIN}/${CHECKMK_SITE}/check_mk/api/1.0\`` (for example `/checkmk-api/dmc/check_mk/api/1.0`)
- `request(method, path, opts?)` is the choke point. It currently sets `Authorization: Bearer ${TOPOLOGY_EDITOR_USER} ${TOPOLOGY_EDITOR_SECRET}` (line ~86) and throws `CheckmkWriteError` on unexpected status.
- REST calls the dashboard makes, all relative to API_PREFIX. This is the nginx allow-list:
  - GET  /objects/host_config/{host}            (updateHostAttributes read-merge)
  - PUT  /objects/host_config/{host}            (If-Match full-attribute PUT)
  - POST /domain-types/host_config/collections/all?bake_agent=false  (createUnmanagedSwitch)
  - GET  /domain-types/activation_run/collections/pending_changes    (countPendingChanges, activateChanges)
  - POST /domain-types/activation_run/actions/activate-changes/invoke (activateChanges)
  - GET  /objects/activation_run/{id}           (activation poll)
  - GET  /version                               (new runtime probe, this plan)

dashboard-react/src/lib/config.ts (lines ~33-82): TOPOLOGY_EDITOR_USER, TOPOLOGY_EDITOR_SECRET_PLACEHOLDER, TOPOLOGY_EDITOR_SECRET, isSecretConfigured(), isTopologyEditingConfigured(), plus a comment block explaining them. CHECKMK_SITE = "dmc", CHECKMK_REST_ORIGIN = "/checkmk-api".

dashboard-react/src/routes/IndexRoute.tsx (lines ~285-298): `editingConfigured={isTopologyEditingConfigured()}` on TopologyToolbar, and `{editMode && isTopologyEditingConfigured() && (<CriticalityEditor .../>)}`. It imports isTopologyEditingConfigured from ../lib/config (line 19) and activateChanges/countPendingChanges from ../lib/checkmkWrite (line 18).
IndexRoute.test.tsx mocks ../lib/checkmkWrite as `{countPendingChanges, activateChanges, setCriticality}` and mocks ../lib/config to force `isTopologyEditingConfigured: () => true`.

dashboard-react/src/components/TopologyToolbar.tsx: `const CONFIGURATION_HINT = "Editing is off until TOPOLOGY_EDITOR_SECRET is set in src/lib/config.ts."`; the prop `editingConfigured: boolean` disables the Switch and shows the hint. TopologyToolbar.test.tsx line ~76 asserts the old hint text.

deploy/dashboard-nginx.conf: an envsubst template installed at /etc/nginx/templates/default.conf.template. The official nginx entrypoint substitutes ONLY variable names present in the container env, so nginx's own `$uri`/`$1`/`$args` are safe as long as no env var shares their name. The current block is `location /checkmk-api/ { proxy_pass http://checkmk:5000/; }`, a static upstream resolved at startup (the dashboard depends_on checkmk). `/ch-api/` shows the house pattern: `limit_except GET { deny all; }` plus `proxy_set_header ... "${CH_READER_PASSWORD}"`.

deploy/compose.yaml: the worker env block (lines ~235-267) ends with `CMK_REST_SECRET=${CMK_REST_SECRET:-}`. The dashboard env block (lines ~384-386) holds `CH_READER_PASSWORD=${CH_READER_PASSWORD:-}` and `NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1`. The comment above the dashboard service (lines ~362-364) says per-deployment settings live in config.ts.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Move topology_editor provisioning into api.py, run it from the wizard after Phase 1, refactor the fallback script, and wire TOPOLOGY_EDITOR_SECRET into compose/.env</name>
  <files>src/checkmk_wizard/api.py, src/checkmk_wizard/wizard.py, scripts/provision_topology_editor.py, tests/test_api.py, tests/test_wizard.py, tests/test_provision_topology_editor.py, deploy/compose.yaml, deploy/.env.example</files>
  <behavior>
    - api: ensure_topology_editor_role() with GET role 404 POSTs the clone body {"role_id": "user", "new_role_id": "topology_editor", "new_alias": "Topology editor (dashboard)"}, then PUTs {"new_permissions": {id: "yes" for the 7 ids}}
    - api: ensure_topology_editor_role() with GET role 200 skips the POST but still PUTs the permissions
    - api: the permission set never contains wato.activateforeign or any wato.users/wato.global/wato.rulesets id
    - api: upsert_automation_user() on GET 404 POSTs the user body with roles ["topology_editor"] and returns True (created)
    - api: upsert_automation_user() on GET 200 with an ETag PUTs only auth_option (secret, store_automation_secret True) with an If-Match header equal to that ETag, and returns False (updated)
    - api: upsert_automation_user() on GET 200 without an ETag raises CheckmkAPIError; a rejected POST/PUT raises CheckmkAPIError
    - wizard: an empty or unset TOPOLOGY_EDITOR_SECRET makes zero client calls and prints one dim skip note
    - wizard: a set secret calls client.provision_topology_editor(secret) once and prints "created" or "updated" depending on the return value; the secret value never appears in console output
    - wizard: provision_topology_editor raising CheckmkAPIError prints a yellow warning and returns normally; run() continues into phase2
    - script: main() still returns 1 when CMK_REST_SECRET is missing; with TOPOLOGY_EDITOR_SECRET set it provisions with exactly that value (create or rotate) and never prints it
  </behavior>
  <action>
Write the failing tests first. Add respx tests to tests/test_api.py using the existing module constants CONN/BASE. Add wizard tests to tests/test_wizard.py following that file's monkeypatch/AsyncMock conventions and capture console output the way that file already does. Extend tests/test_provision_topology_editor.py. Then implement.

api.py: move ROLE_ID/ROLE_ALIAS/BASE_ROLE_ID/USER_ID/REQUIRED_PERMISSIONS out of the script and give them `TOPOLOGY_EDITOR_` prefixes: TOPOLOGY_EDITOR_ROLE_ID, TOPOLOGY_EDITOR_ROLE_ALIAS, TOPOLOGY_EDITOR_BASE_ROLE_ID, TOPOLOGY_EDITOR_USER_ID, TOPOLOGY_EDITOR_PERMISSIONS. Move their explanatory comments with them, including the see_all_folders UAT finding and the activateforeign exclusion, and the role-body source-verification note from the script docstring (Checkmk 2.4.0p35 endpoints/user_role source). Also move the module-level helpers `build_role_permissions(perm_ids)` and `build_topology_editor_user_body(username, secret)`. Add CheckmkClient methods, all through `self._request()`:
- `ensure_topology_editor_role() -> None`. GET `/objects/user_role/{id}` with expect=(200, 404); on 404 POST `/domain-types/user_role/collections/all`; then always PUT `/objects/user_role/{id}` with expect=(200, 204). Keep the script's semantics exactly: no If-Match on the role PUT, because that is how it was live-UAT'd.
- `user_exists(username) -> bool`. GET `/objects/user_config/{username}` with expect=(200, 404).
- `upsert_automation_user(username, secret, *, roles, fullname) -> bool`. Mirror bootstrap_automation_user's pre-seeded create-or-update: on 200, take the ETag (missing raises CheckmkAPIError) and PUT only auth_option with If-Match, expect=(200,); on 404, POST the full body to `/domain-types/user_config/collections/all`, expect=(200, 201). Return True when created.
- `provision_topology_editor(secret) -> bool`. Calls ensure_topology_editor_role() and then upsert_automation_user(TOPOLOGY_EDITOR_USER_ID, secret, roles=[TOPOLOGY_EDITOR_ROLE_ID], fullname=TOPOLOGY_EDITOR_ROLE_ALIAS), and returns the created flag.

Give provision_topology_editor a docstring that says why it exists: this supersedes D-04's client-embedded secret as of 2026-09-30. The secret now lives only in deploy/.env and the dashboard's nginx, and the role stays narrowly scoped as defence in depth.

wizard.py: add `async def _provision_topology_editor(client, connection) -> None`. Read `os.environ.get("TOPOLOGY_EDITOR_SECRET", "").strip()`. If it is empty, print a dim note ("TOPOLOGY_EDITOR_SECRET not set — skipping topology_editor provisioning; dashboard map editing stays off.") and return. Otherwise call client.provision_topology_editor(secret), print a green "created" or "updated with TOPOLOGY_EDITOR_SECRET from the environment" line (never echo the value, same rule as _print_automation_secret_created), then call `await _activate_pending_changes(client, connection)` so the new user is live even if the operator quits early. Wrap everything in `except CheckmkAPIError` and print a yellow warning naming the manual fallback (`scripts/provision_topology_editor.py`). This step is best-effort and never fatal; add a comment explaining why swallowing is safe here. Call it as the first statement inside run()'s `async with CheckmkClient(connection) as client:` block. That block is shared by container mode and host-native mode, and by then Phase 1 has produced working REST credentials.

scripts/provision_topology_editor.py: rewrite it on top of CheckmkClient/CheckmkConnection (asyncio.run), dropping the urllib `_rest`/ProvisionError layer so every REST call goes through `_request()`. Keep importable names for the tests: `REQUIRED_PERMISSIONS = TOPOLOGY_EDITOR_PERMISSIONS`, `build_role_permissions`, `build_user_body` (alias of build_topology_editor_user_body), `redact_auth_header`, `generate_secret`, `main`. main() keeps the CMK_REST_* env handling and its fail-fast behaviour; build `CheckmkConnection(host=rest_host, site=site_id, username, secret, port=int(rest_port))`. If TOPOLOGY_EDITOR_SECRET is set, call provision_topology_editor(env value), which creates or rotates to that value, and never print the value. If it is unset, ensure the role; if the user exists, print "already exists — secret not rotated (set TOPOLOGY_EDITOR_SECRET to rotate)"; otherwise generate a secret, create the user, and print it once with "put this into deploy/.env as TOPOLOGY_EDITOR_SECRET, then recreate the dashboard (podman compose down && podman compose up -d)". Keep the non-forced own-change activation using client.get_pending_changes/activate_changes(force_foreign_changes=False)/get_activation_run with the same 30 x 0.3s poll; a CheckmkAPIError with status_code 401 keeps the existing "other operators' changes were NOT forced" warning. CheckmkAPIError anywhere else prints [FAIL] and returns 1. Update the module docstring: the credential is no longer in the browser bundle; nginx injects it (dated 2026-09-30).

deploy/compose.yaml: add `- TOPOLOGY_EDITOR_SECRET=${TOPOLOGY_EDITOR_SECRET:-}` to the worker env block, with a short comment that the wizard pushes it into Checkmk as the topology_editor user's secret. Add the same line to the dashboard env block, with a comment that nginx injects it into /checkmk-api/ and it never reaches the browser. Also fix the comment above the dashboard service so it no longer says the credential lives in config.ts.

deploy/.env.example: add a `TOPOLOGY_EDITOR_SECRET=` entry after CMK_REST_SECRET, in the same comment style. Cover: generate it with `uv run python -c "import secrets; print(secrets.token_urlsafe(24))"`; it is read by the worker (the wizard creates or rotates the scoped topology_editor user to it right after Phase 1) and by the dashboard's nginx (injected server-side, never sent to the browser); leave it empty to keep map editing off; to change it, edit it here, re-run the wizard, then recreate the stack.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && uv run pytest tests/test_api.py tests/test_wizard.py tests/test_provision_topology_editor.py -q && uv run pytest -q && uvx ruff check src/checkmk_wizard/api.py src/checkmk_wizard/wizard.py scripts/provision_topology_editor.py && test "$(grep -c 'TOPOLOGY_EDITOR_SECRET=${TOPOLOGY_EDITOR_SECRET:-}' deploy/compose.yaml)" -eq 2 && grep -q '^TOPOLOGY_EDITOR_SECRET=$' deploy/.env.example && ! grep -n 'urllib' scripts/provision_topology_editor.py</automated>
  </verify>
  <done>All new and existing pytest pass; ruff is clean. api.py exposes the four CheckmkClient methods, all using _request(). run() calls _provision_topology_editor first, and it is never fatal and silent-with-dim-note when the env var is empty. The script uses CheckmkClient and honours TOPOLOGY_EDITOR_SECRET. compose passes the env var to worker and dashboard, and .env.example documents it.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: nginx injects the credential on an allow-list; dashboard-react stops sending Authorization and gates editing on a runtime probe</name>
  <files>deploy/dashboard-nginx.conf, deploy/dashboard.Containerfile, dashboard-react/vite.config.ts, dashboard-react/src/lib/checkmkWrite.ts, dashboard-react/src/lib/checkmkWrite.test.ts, dashboard-react/src/lib/config.ts, dashboard-react/src/lib/config.test.ts, dashboard-react/src/components/TopologyToolbar.tsx, dashboard-react/src/components/TopologyToolbar.test.tsx, dashboard-react/src/routes/IndexRoute.tsx, dashboard-react/src/routes/IndexRoute.test.tsx</files>
  <behavior>
    - checkmkWrite: no request() call sends an Authorization header (assert on the mocked fetch init headers for a GET and a PUT path)
    - probeEditingAvailable(): GETs `/checkmk-api/dmc/check_mk/api/1.0/version`; resolves true on 200 and false on 401 or 500; resolves false (does not reject) when fetch rejects
    - IndexRoute: when the probe resolves true, the Edit topology switch is enabled; when it resolves false, the switch is disabled and the new hint is shown, and CriticalityEditor is never rendered
    - TopologyToolbar: editingConfigured false shows exactly "Editing is off: set TOPOLOGY_EDITOR_SECRET in deploy/.env and run the wizard."
  </behavior>
  <action>
deploy/dashboard-nginx.conf: replace the single `location /checkmk-api/` block with three regex locations and a catch-all. Anchor each regex to `^/checkmk-api/[A-Za-z0-9_]+/check_mk/api/1\.0/`, then add the alternatives below, and quote each regex:
- GET-only (`limit_except GET { deny all; }`): `version`, `domain-types/activation_run/collections/pending_changes`, `objects/activation_run/[^/]+`.
- GET+PUT (`limit_except GET PUT { deny all; }`): `objects/host_config/[^/]+`.
- POST-only (`limit_except POST { deny all; }`): `domain-types/host_config/collections/all`, `domain-types/activation_run/actions/activate-changes/invoke`.

In each location:
- Add `proxy_set_header Authorization "Bearer topology_editor ${TOPOLOGY_EDITOR_SECRET}";`. This replaces any client-sent header.
- Strip the prefix with `rewrite ^/checkmk-api/(.*)$ /$1 break;` followed by `proxy_pass http://checkmk:5000;`. A proxy_pass with a URI part is not allowed inside a regex location. This keeps the old `proxy_pass http://checkmk:5000/;` semantics: prefix stripped, query string such as `?bake_agent=false` preserved by rewrite, and a static upstream resolved at startup (not the variable/resolver form).

Then add `location /checkmk-api/ { return 403; }` as the fallback. Regex locations win over non-`^~` prefix locations, so this catches everything not allow-listed.

Update the file header comment:
- ${TOPOLOGY_EDITOR_SECRET} is now substituted too.
- compose always defines it (empty default), so envsubst renders it. When it is empty, Checkmk answers 401, which the dashboard's probe reads as "editing off".
- nginx's own $1/$uri/$args are untouched because they are not env vars.

Rewrite the /checkmk-api/ comment:
- It supersedes D-04 (2026-09-30): the browser holds no secret.
- The allow-list was derived from dashboard-react/src/lib/checkmkWrite.ts, and any new REST call there must be added here too.

deploy/dashboard.Containerfile: fix the header comment. config.ts no longer carries TOPOLOGY_EDITOR_SECRET; the secret comes from deploy/.env at container start via the template.

dashboard-react/vite.config.ts: have the dev/preview proxy mirror nginx by adding `headers: { Authorization: \`Bearer topology_editor ${process.env.TOPOLOGY_EDITOR_SECRET ?? ""}\` }` to checkmkApiProxy. Update the comment: the browser no longer sends a credential, and the proxy injects it from the dev shell's env.

dashboard-react/src/lib/checkmkWrite.ts: remove the Authorization header and the TOPOLOGY_EDITOR_* imports from request(). Keep Accept and the existing error normalisation. Add `export async function probeEditingAvailable(): Promise<boolean>`: request("GET", "/version") inside try/catch, returning true on success and false on any CheckmkWriteError or other thrown error. Do not wrap it in serialize(). Update the header comment: the credential is injected by the dashboard's nginx (or the Vite proxy in dev) from TOPOLOGY_EDITOR_SECRET in deploy/.env, per the 2026-09-30 amendment to D-04; the probe path must stay on nginx's GET allow-list.

dashboard-react/src/lib/config.ts: delete TOPOLOGY_EDITOR_USER, TOPOLOGY_EDITOR_SECRET_PLACEHOLDER, TOPOLOGY_EDITOR_SECRET, isSecretConfigured and isTopologyEditingConfigured, and replace their comment block with a two-line note saying where the credential now lives. Remove their tests from config.test.ts and keep the others. Grep the src tree afterwards; nothing may still import them.

TopologyToolbar.tsx: set CONFIGURATION_HINT to exactly "Editing is off: set TOPOLOGY_EDITOR_SECRET in deploy/.env and run the wizard." and update TopologyToolbar.test.tsx to match. The prop name editingConfigured stays.

IndexRoute.tsx: drop the config import. Add `const [editingAvailable, setEditingAvailable] = useState(false)` and a mount-only useEffect that calls probeEditingAvailable() and sets the state unless the component has unmounted (cancelled flag). Pass `editingConfigured={editingAvailable}` and gate CriticalityEditor on `editMode && editingAvailable`.

IndexRoute.test.tsx: add `probeEditingAvailable: vi.fn()` to the checkmkWrite mock, make it resolve true in beforeEach, and remove the ../lib/config mock. Existing tests that toggle the switch must await the probe, for example with findBy* or waitFor. Add one test where it resolves false: the switch is disabled and the hint is visible.

checkmkWrite.test.ts: remove the TOPOLOGY_EDITOR_SECRET import and assertion. Replace them with "no Authorization header is sent" plus the probe cases from <behavior>.

Build precondition: follow dashboard-react/README.md §2. If design-system/dist or the packed tgz is missing, run `npm --prefix design-system ci && npm --prefix design-system run build && (cd design-system && npm pack)` before building.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && npm --prefix dashboard-react test && npm --prefix dashboard-react run build && test "$(grep -c 'proxy_set_header Authorization "Bearer topology_editor ${TOPOLOGY_EDITOR_SECRET}";' deploy/dashboard-nginx.conf)" -eq 3 && grep -q 'location /checkmk-api/ { return 403; }' deploy/dashboard-nginx.conf && grep -v '^\s*#' deploy/dashboard-nginx.conf | grep -q 'api/1\\.0/(version' && ! grep -rn 'TOPOLOGY_EDITOR_SECRET\|isTopologyEditingConfigured\|Authorization' dashboard-react/src --include=*.ts --include=*.tsx | grep -v '\.test\.' | grep -v '^\S*:\s*//' && ! grep -rl 'topology_editor ' dashboard-react/dist</automated>
  </verify>
  <done>All vitest suites pass and the production build succeeds. The built dist contains no topology_editor credential string. nginx has exactly three allow-listed /checkmk-api/ locations that inject Authorization, plus a 403 catch-all. The SPA enables editing only when the /version probe returns 200.</done>
</task>

<task type="auto">
  <name>Task 3: Update operator docs and record the D-04 amendment</name>
  <files>docs/DEPLOY-NEW-MACHINE.md, docs/Podman setup for checkmk, minio, mosquitto, worker.md, docs/WIZARD-OPERATION.md, dashboard-react/README.md, .planning/PROJECT.md, CLAUDE.md, .planning/phases/13-wizard-parents-support-and-topology-map/13-CONTEXT.md</files>
  <action>
Follow the user's global rule: docs must match the implementation from Tasks 1-2.

- docs/DEPLOY-NEW-MACHINE.md §3: replace the config.ts TOPOLOGY_EDITOR_SECRET bullet (lines ~76-77) with a deploy/.env entry. It should cover generating it with token_urlsafe(24), setting it before the wizard run, and that it is read by the worker and dashboard containers. §8 step 3 (lines ~191-195, the manual provision script run and the config.ts paste): replace it with "nothing to do. The wizard provisions topology_editor right after Phase 1 when TOPOLOGY_EDITOR_SECRET is set. `scripts/provision_topology_editor.py` remains a manual fallback (it reads the same env var)". Renumber any later steps and fix any cross-references.
- docs/Podman setup for checkmk, minio, mosquitto, worker.md: lines ~188 and ~202-223 now cover four points. The credential lives in deploy/.env and is injected by the dashboard's nginx on an allow-list of REST calls, with everything else under /checkmk-api/ returning 403. The wizard provisions it. Rotation means editing .env, re-running the wizard (or the script), then a full `podman compose down && podman compose up -d`; do not restart the container on its own, because that breaks Checkmk egress. Keep the blast-radius note. Update ~616 and ~734: the start-over step no longer needs the script, because a fresh wizard run re-provisions it.
- docs/WIZARD-OPERATION.md: in the Phase 1 section, add a short subsection "Topology editor provisioning (after Phase 1)". It covers the env var, create vs rotate, the dim skip note when unset, the never-fatal warning, the immediate activation, and the fallback script. Update the start-over section (~line 107) the same way as the Podman doc.
- dashboard-react/README.md: remove the TOPOLOGY_EDITOR_SECRET/TOPOLOGY_EDITOR_USER config.ts entries (lines ~93-105). Add a short section covering: no credential in the bundle; nginx injects it from deploy/.env; editing is gated by a runtime GET /version probe through /checkmk-api/; for local dev, export TOPOLOGY_EDITOR_SECRET (and CHECKMK_PROXY_TARGET) before `npm run dev`, because the Vite proxy injects the header. Fix the reference at ~160 if it points at config.ts.
- .planning/PROJECT.md line 51 and CLAUDE.md line 13: append this after the existing 2026-09-28 note in the "No new backend for the dashboard" constraint: *(Amended 2026-09-30, quick 260930-hpy: supersedes the 2026-09-23 D-04 note's client-embedded credential — the `topology_editor` secret now lives only in `deploy/.env` (`TOPOLOGY_EDITOR_SECRET`), is provisioned by the wizard after Phase 1, and is injected by the dashboard's nginx on an allow-list of the REST calls the dashboard makes; the browser holds no secret. Still no custom server-side application.)*. The CLAUDE.md edit is explicitly requested by the user for this task.
- 13-CONTEXT.md: directly under the D-04 bullet, add an indented "**Amended 2026-09-30 (quick 260930-hpy, user-approved):**" note in one or two sentences, stating the same thing and that it is not to be re-litigated.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && ! grep -n 'src/lib/config.ts' docs/DEPLOY-NEW-MACHINE.md "docs/Podman setup for checkmk, minio, mosquitto, worker.md" dashboard-react/README.md | grep -i 'TOPOLOGY_EDITOR' && grep -q 'Amended 2026-09-30' .planning/PROJECT.md && grep -q 'Amended 2026-09-30' CLAUDE.md && grep -q 'Amended 2026-09-30' .planning/phases/13-wizard-parents-support-and-topology-map/13-CONTEXT.md && grep -q 'TOPOLOGY_EDITOR_SECRET' docs/WIZARD-OPERATION.md</automated>
  </verify>
  <done>No doc tells the operator to put TOPOLOGY_EDITOR_SECRET in config.ts or to run the script as a mandatory step. The wizard doc describes the post-Phase-1 provisioning. PROJECT.md, CLAUDE.md and 13-CONTEXT.md carry the dated 2026-09-30 amendment.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| browser -> dashboard nginx (/checkmk-api/) | Untrusted LAN client; can send any method, path and headers |
| dashboard nginx -> checkmk:5000 | Carries the injected topology_editor credential |
| deploy/.env -> worker/dashboard containers | The secret enters via the compose env |
| wizard (admin automation user) -> Checkmk user/role REST | Creates or rotates the scoped user |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-hpy-01 | Information disclosure | dashboard bundle | mitigate | Secret removed from config.ts/checkmkWrite.ts; the Task 2 verify greps dist/ for `topology_editor ` |
| T-hpy-02 | Elevation of privilege | nginx /checkmk-api/ | mitigate | Method+path allow-list of 3 regex locations with limit_except; catch-all `return 403`; user_config/user_role/rulesets/DELETE are unreachable |
| T-hpy-03 | Spoofing | client-sent Authorization | mitigate | proxy_set_header Authorization in every allowed location overrides the client header |
| T-hpy-04 | Elevation of privilege | topology_editor role | mitigate | Role stays scoped to TOPOLOGY_EDITOR_PERMISSIONS (no activateforeign/users/global/rulesets); a test asserts the exclusions |
| T-hpy-05 | Information disclosure | wizard/script output | mitigate | An env-provided secret is never echoed; a test asserts the secret is absent from console output |
| T-hpy-06 | Tampering | anyone on the LAN can use the allowed writes | accept | Same trusted-LAN, no-user-accounts posture as D-04; the exposure is now narrower than before (no secret to exfiltrate, fixed call set) |
| T-hpy-07 | Denial of service | wizard provisioning failure | mitigate | CheckmkAPIError is caught; never fatal; run() continues |
</threat_model>

<verification>
Automated (executor): full `uv run pytest -q`, `uvx ruff check` on the touched Python, `npm --prefix dashboard-react test`, `npm --prefix dashboard-react run build`, and the grep gates in each task.

Live verification is left to the operator. There is no podman on this host, and the executor must NOT touch running containers. The operator should:
1. Set TOPOLOGY_EDITOR_SECRET in deploy/.env.
2. Run `podman compose build dashboard && podman compose down && podman compose up -d`. Use a full down/up, not a single-container restart, which breaks Checkmk egress.
3. Run the wizard. After Phase 1 it should report topology_editor created/updated.
4. `curl -s -o /dev/null -w '%{http_code}' http://<host>:8090/checkmk-api/<site>/check_mk/api/1.0/version` should return 200.
5. The same prefix with `/domain-types/user_config/collections/all` should return 403.
6. `curl -X DELETE .../objects/host_config/x` should return 403.
7. In the dashboard, the Edit topology switch should be enabled, and a map edit plus Apply should work.
8. With the variable empty (after a rebuild), the switch should be disabled and show the new hint.
</verification>

<success_criteria>
- The browser bundle and the browser's requests carry no topology_editor credential
- nginx injects the credential only on the dashboard's exact REST call set; everything else under /checkmk-api/ returns 403
- The wizard provisions or rotates topology_editor from TOPOLOGY_EDITOR_SECRET after Phase 1, best-effort, silent-with-note when unset
- The fallback script honours TOPOLOGY_EDITOR_SECRET and goes through CheckmkClient._request()
- Editing availability is a runtime probe, not a compile-time placeholder check
- All pytest and vitest pass; the dashboard builds; docs and constraint amendments are updated
</success_criteria>

<output>
Create `.planning/quick/260930-hpy-move-topology-editor-secret-out-of-brows/260930-hpy-SUMMARY.md` when done
</output>
