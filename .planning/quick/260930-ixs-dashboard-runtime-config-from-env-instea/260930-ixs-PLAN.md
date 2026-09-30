---
phase: quick-260930-ixs
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - dashboard-react/src/lib/config.ts
  - dashboard-react/src/lib/runtimeConfig.ts
  - dashboard-react/src/lib/runtimeConfig.test.ts
  - dashboard-react/src/lib/checkmkWrite.ts
  - dashboard-react/src/lib/checkmkWrite.test.ts
  - dashboard-react/src/store/mqttClient.ts
  - dashboard-react/src/store/mqttClient.test.ts
  - dashboard-react/src/main.tsx
  - deploy/dashboard-nginx.conf
  - deploy/compose.yaml
  - deploy/init-env.sh
  - deploy/.env.example
  - deploy/dashboard.Containerfile
  - docs/DEPLOY-NEW-MACHINE.md
  - docs/Podman setup for checkmk, minio, mosquitto, worker.md
  - docs/Incident demo with fake check results.md
  - docs/WIZARD-OPERATION.md
  - dashboard-react/README.md
  - README.md
autonomous: true
requirements: [QUICK-260930-ixs]

must_haves:
  truths:
    - "An operator never edits dashboard-react/src/lib/config.ts per machine: the Checkmk site name and the read-only broker credentials come from deploy/.env at dashboard container start"
    - "GET /config.json on the dashboard (port 8090) returns JSON {checkmkSite, wsUsername, wsPassword} rendered from CMK_SITE_ID / WS_USERNAME / WS_PASSWORD, with Cache-Control no-store, and is not swallowed by the SPA fallback"
    - "The SPA fetches /config.json once before first render; the topology-editor REST calls use /checkmk-api/<checkmkSite>/... and activation sends sites: [<checkmkSite>]; the MQTT connection uses wsUsername/wsPassword"
    - "If /config.json is missing, unreachable, not JSON, or a field is missing/invalid, the SPA falls back per field to dmc / wsreader / wsreader (vite dev and vitest keep working without nginx)"
    - "CHECKMK_BASE_URL, CHECKMK_BASE_URL_PLACEHOLDER and isCheckmkLinkConfigured() no longer exist, and no operator-facing doc tells anyone to edit config.ts or CHECKMK_BASE_URL"
    - "deploy/init-env.sh no longer ends with a 'Still manual, in config.ts' block"
  artifacts:
    - path: "dashboard-react/src/lib/runtimeConfig.ts"
      provides: "parseRuntimeConfig, loadRuntimeConfig, getRuntimeConfig, __setRuntimeConfigForTests"
      exports: ["RuntimeConfig", "parseRuntimeConfig", "loadRuntimeConfig", "getRuntimeConfig", "__setRuntimeConfigForTests"]
    - path: "dashboard-react/src/lib/runtimeConfig.test.ts"
      provides: "vitest coverage of the loader and fallbacks"
    - path: "deploy/dashboard-nginx.conf"
      provides: "location = /config.json"
      contains: "location = /config.json"
  key_links:
    - from: "dashboard-react/src/main.tsx"
      to: "loadRuntimeConfig"
      via: "awaited before createRoot().render()"
      pattern: "loadRuntimeConfig\\("
    - from: "dashboard-react/src/lib/checkmkWrite.ts"
      to: "getRuntimeConfig().checkmkSite"
      via: "API prefix built per request, not at module load"
      pattern: "getRuntimeConfig\\(\\)"
    - from: "dashboard-react/src/store/mqttClient.ts"
      to: "getRuntimeConfig().wsUsername / wsPassword"
      via: "read inside connect()"
      pattern: "getRuntimeConfig\\(\\)"
    - from: "deploy/compose.yaml dashboard service"
      to: "deploy/dashboard-nginx.conf ${CMK_SITE_ID}/${WS_USERNAME}/${WS_PASSWORD}"
      via: "container env -> nginx envsubst template"
      pattern: "WS_PASSWORD=\\$\\{WS_PASSWORD:-wsreader\\}"
---

<objective>
Move the per-deployment dashboard settings (Checkmk site name, read-only MQTT WebSocket
credentials) out of the build-time `dashboard-react/src/lib/config.ts` into runtime config
served by the dashboard's own nginx as `/config.json`, rendered from `deploy/.env`. Delete the
dead `CHECKMK_BASE_URL` machinery and every operator instruction to edit `config.ts`.

Purpose: one image works on every machine; `deploy/init-env.sh` + `deploy/.env` become the only
per-machine configuration. With a non-`dmc` site today, the topology-editor probe hits the wrong
site path and editing stays off unless the operator hand-edits and rebuilds.
Output: runtime-config module + tests, nginx `/config.json` location, compose env, trimmed
init-env.sh, updated docs.
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@./CLAUDE.md
@.planning/quick/260930-hpy-move-topology-editor-secret-out-of-brows/260930-hpy-SUMMARY.md
@dashboard-react/src/lib/config.ts
@dashboard-react/src/main.tsx
@deploy/dashboard-nginx.conf
@deploy/init-env.sh
@deploy/.env.example

<interfaces>
Current state, extracted from the codebase (use directly):

dashboard-react/src/lib/config.ts exports: WS_PORT=9002, WS_USERNAME="wsreader",
WS_PASSWORD="wsreader", POLL_INTERVAL_SECONDS=15, STALENESS_FACTOR=3, HISTORY_MAX_ENTRIES=20,
CHECKMK_BASE_URL="http://<HOST_IP>:8080", CHECKMK_SITE="dmc", CHECKMK_BASE_URL_PLACEHOLDER,
isCheckmkLinkConfigured(), CHECKMK_REST_ORIGIN="/checkmk-api". Long header comment
describing it as "the one file an operator edits per deployment".

Consumers of the per-machine values (grep-verified; no other consumers exist):
- dashboard-react/src/lib/checkmkWrite.ts:35 `import { CHECKMK_REST_ORIGIN, CHECKMK_SITE } from "./config";`
- checkmkWrite.ts:69 `const API_PREFIX = \`${CHECKMK_REST_ORIGIN}/${CHECKMK_SITE}/check_mk/api/1.0\`;`
  used at lines 85, 171, 424, 461.
- checkmkWrite.ts:434 `body: { redirect: false, sites: [CHECKMK_SITE], force_foreign_changes: false }`
- checkmkWrite.ts header comment line 1-2: "The one module in lib/ that makes network calls".
- dashboard-react/src/store/mqttClient.ts:23 `import { WS_PORT, WS_USERNAME, WS_PASSWORD } from "../lib/config";`
  used at lines 81-82 inside `connect(deps: ConnectDeps = {})`; ConnectDeps has
  `connectFn?: typeof mqtt.connect` (tests inject it). `__resetForTests()` exists.
- dashboard-react/src/App.tsx:60 calls `connect()` in a mount effect (no change needed there if
  config is loaded before render).
- Existing tests assert the default site: checkmkWrite.test.ts:59 expects
  "/checkmk-api/dmc/check_mk/api/1.0", :559 expects `sites: ["dmc"]`.
- StaleStability.test.tsx imports POLL_INTERVAL_SECONDS, STALENESS_FACTOR (keep them).

deploy/compose.yaml dashboard service (line ~373) `environment:` currently holds
CH_READER_PASSWORD, NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1, TOPOLOGY_EDITOR_SECRET; comment at
line ~376 says "Rebuild after every `git pull` or config.ts edit".

deploy/gen-mosquitto-passwd.sh reads WS_PASSWORD (default wsreader) and POLLER_PASSWORD; the
WS user name is fixed in that script (WS_USER) and in deploy/mosquitto.acl.

Site-name rule used by the wizard/docs: starts with a letter, 1-16 letters/digits/underscores.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Runtime config loader in the SPA; remove per-machine constants from config.ts</name>
  <files>dashboard-react/src/lib/runtimeConfig.ts, dashboard-react/src/lib/runtimeConfig.test.ts, dashboard-react/src/lib/config.ts, dashboard-react/src/lib/checkmkWrite.ts, dashboard-react/src/lib/checkmkWrite.test.ts, dashboard-react/src/store/mqttClient.ts, dashboard-react/src/store/mqttClient.test.ts, dashboard-react/src/main.tsx</files>
  <behavior>
    - parseRuntimeConfig({checkmkSite:"mysite", wsUsername:"u", wsPassword:"p"}) returns exactly those values
    - parseRuntimeConfig({}) / null / "string" / an array returns {checkmkSite:"dmc", wsUsername:"wsreader", wsPassword:"wsreader"}
    - Per-field fallback: {checkmkSite:"mysite"} keeps mysite and defaults both WS fields
    - Invalid site ids fall back to "dmc": "", "1abc", "my-site", "a/b", "../x", 17-char name, non-string (e.g. 42)
    - Empty-string or non-string wsUsername/wsPassword fall back to their defaults
    - loadRuntimeConfig(fakeFetch) with a 200 JSON body stores and returns the parsed config; getRuntimeConfig() afterwards returns it
    - loadRuntimeConfig resolves to defaults (never rejects) when fetch rejects, when the response is non-OK (404), and when the body is not JSON (vite dev's SPA fallback returns index.html)
    - getRuntimeConfig() before any load returns the defaults
    - checkmkWrite: after __setRuntimeConfigForTests({checkmkSite:"mysite", ...}) request URLs contain "/checkmk-api/mysite/check_mk/api/1.0" and activateChanges sends sites: ["mysite"]; existing "dmc" assertions still pass with defaults (reset in beforeEach/afterEach)
    - mqttClient: after __setRuntimeConfigForTests({... wsUsername:"u2", wsPassword:"p2"}) connect({connectFn}) passes username "u2" / password "p2" to connectFn
  </behavior>
  <action>
    RED first: write dashboard-react/src/lib/runtimeConfig.test.ts plus the new cases in checkmkWrite.test.ts and mqttClient.test.ts, run vitest, confirm they fail; commit as test(quick-260930-ixs). Then GREEN:

    (a) config.ts: delete WS_USERNAME, WS_PASSWORD, CHECKMK_SITE, CHECKMK_BASE_URL, CHECKMK_BASE_URL_PLACEHOLDER and isCheckmkLinkConfigured() (dead since the vanilla dashboard/ was deleted; no React consumer). Add DEFAULT_CHECKMK_SITE = "dmc", DEFAULT_WS_USERNAME = "wsreader", DEFAULT_WS_PASSWORD = "wsreader". Keep WS_PORT, POLL_INTERVAL_SECONDS, STALENESS_FACTOR, HISTORY_MAX_ENTRIES, CHECKMK_REST_ORIGIN unchanged. Rewrite the header comment: config.ts now holds only true constants and fallback defaults, no per-machine value, and must not be edited per deployment; per-deployment values come from /config.json (see runtimeConfig.ts, deploy/dashboard-nginx.conf, deploy/.env). Keep the existing paragraphs about broker host derivation, the committed read-only wsreader convention (reword: it is now the default), POLL_INTERVAL/HISTORY mirroring, CHECKMK_REST_ORIGIN/V-CORS (drop the "may be set to the literal CHECKMK_BASE_URL" sentence), and the 260930-hpy topology_editor note. Add a dated "Amended 2026-09-30 (quick 260930-ixs)" line in the house style.

    (b) New dashboard-react/src/lib/runtimeConfig.ts: exports interface RuntimeConfig { checkmkSite: string; wsUsername: string; wsPassword: string }; parseRuntimeConfig(raw: unknown): RuntimeConfig (pure, per-field validation/fallback as in behavior; site regex /^[A-Za-z][A-Za-z0-9_]{0,15}$/ matching the wizard's site-name rule, which is also a subset of the nginx allow-list's [A-Za-z0-9_]+ path segment); loadRuntimeConfig(fetchFn: typeof fetch = fetch): Promise<RuntimeConfig> which GETs "/config.json" with cache: "no-store" and signal AbortSignal.timeout(3000) so a hung request cannot block first render forever, returns defaults on any failure (catch everything, never rejects), stores the result in a module-level variable; getRuntimeConfig(): RuntimeConfig returning the stored value (defaults until loaded); __setRuntimeConfigForTests(cfg?: Partial<RuntimeConfig>) that sets defaults merged with cfg (no arg resets to defaults), matching mqttClient's existing __resetForTests naming style. Module header comment explains why (one image per any machine; values rendered by nginx from deploy/.env; falls back so vite dev/vitest work without nginx) and notes it is the third lib/store module allowed to do network I/O alongside checkmkWrite.ts and mqttClient.ts. Keep it short (target under ~70 lines incl. comments).

    (c) checkmkWrite.ts: replace the import of CHECKMK_SITE with getRuntimeConfig from "./runtimeConfig"; replace the module-level const API_PREFIX with a small function apiPrefix() that builds the same string from CHECKMK_REST_ORIGIN and getRuntimeConfig().checkmkSite, and use it at all four former API_PREFIX sites; activation body uses sites: [getRuntimeConfig().checkmkSite]. Reason it must be per call, not at module load: modules are evaluated before main.tsx's loadRuntimeConfig resolves. Amend the header's "The one module in lib/ that makes network calls" sentence minimally to acknowledge runtimeConfig.ts. No other behavior change.

    (d) mqttClient.ts: import WS_PORT from config and getRuntimeConfig from "../lib/runtimeConfig"; inside connect() read const { wsUsername, wsPassword } = getRuntimeConfig() and pass them as username/password. Nothing else changes.

    (e) main.tsx: call void loadRuntimeConfig().then(() => createRoot(...).render(...same StrictMode/App tree...)); add a two-line comment that the config must be loaded before App mounts because App's effect calls connect() and the editor probe runs on first render. loadRuntimeConfig never rejects, so no catch branch is needed.

    (f) Tests: in checkmkWrite.test.ts and mqttClient.test.ts add afterEach(() => __setRuntimeConfigForTests()) so the new non-default cases cannot leak into existing "dmc"/"wsreader" assertions. Use injected fake fetch functions in runtimeConfig.test.ts (no global fetch patching needed). Commit GREEN as feat(quick-260930-ixs).

    Worktree note: if node_modules is missing, run npm ci plus the design-system build per dashboard-react/README.md §2 first.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard/dashboard-react && npx vitest run && npm run build && ! grep -rn "CHECKMK_BASE_URL\|isCheckmkLinkConfigured\|CHECKMK_SITE\b\|WS_USERNAME\|WS_PASSWORD" src --include=*.ts --include=*.tsx | grep -v "^\S*:\s*//"</automated>
  </verify>
  <done>All vitest suites pass including the new runtimeConfig tests and the mysite/u2 cases; npm run build succeeds; no source (non-comment) reference to the removed constants remains; main.tsx renders only after loadRuntimeConfig resolves.</done>
</task>

<task type="auto">
  <name>Task 2: Serve /config.json from nginx, pass values via compose, trim init-env.sh</name>
  <files>deploy/dashboard-nginx.conf, deploy/compose.yaml, deploy/init-env.sh, deploy/.env.example, deploy/dashboard.Containerfile</files>
  <action>
    (a) deploy/dashboard-nginx.conf: add, right after the `location / { try_files ... }` SPA fallback block, an exact-match `location = /config.json` that sets `default_type application/json;`, `add_header Cache-Control "no-store" always;` and `return 200 '{"checkmkSite":"${CMK_SITE_ID}","wsUsername":"${WS_USERNAME}","wsPassword":"${WS_PASSWORD}"}';`. An exact-match `=` location always wins over the `/` prefix location, so the SPA fallback cannot swallow it (say so in the comment). Comment block (house style, dated "Added 2026-09-30, quick 260930-ixs"): these three values are substituted by envsubst at container start from the dashboard service's env (compose always defines them, with defaults, so envsubst always renders them); the SPA loads this once before first render (dashboard-react/src/lib/runtimeConfig.ts) and falls back to dmc/wsreader/wsreader on any failure; wsPassword is the read-only broker credential that previously shipped in the JS bundle anyway (grant: topic read lan/# in deploy/mosquitto.acl), so serving it here exposes nothing new; allowed characters: the site id follows the wizard rule (letter first, letters/digits/underscore, max 16), and WS_USERNAME/WS_PASSWORD must not contain single or double quotes, backslash, dollar sign, braces, semicolons or whitespace, because they are pasted verbatim into this nginx string literal and JSON (a quote breaks nginx startup, a $ becomes an nginx variable) — the URL-safe output of secrets.token_urlsafe satisfies this. Also update the file's top header list of substituted variables to include CMK_SITE_ID, WS_USERNAME, WS_PASSWORD.

    (b) deploy/compose.yaml dashboard service environment: append `CMK_SITE_ID=${CMK_SITE_ID:-dmc}`, `WS_USERNAME=${WS_USERNAME:-wsreader}`, `WS_PASSWORD=${WS_PASSWORD:-wsreader}` with a one-line comment pointing at the /config.json location. Change the service's header comment "Rebuild after every `git pull` or config.ts edit" to "Rebuild after every `git pull` (code changes only; per-machine settings come from deploy/.env at container start)". Touch nothing else in compose.yaml.

    (c) deploy/init-env.sh: replace the final heredoc ("Still manual, in dashboard-react/src/lib/config.ts ..." with CHECKMK_BASE_URL/CHECKMK_SITE and the build line) with a short "Next steps" block: `cd deploy && podman compose down && podman compose up -d` (use a full down/up, never a single-service restart — see the project memory about egress), plus a note that `podman compose build dashboard` is only needed after pulling code changes, and an optional line: to rotate the read-only dashboard broker password, set WS_PASSWORD in deploy/.env and regenerate deploy/mosquitto.passwd with `WS_PASSWORD=... deploy/gen-mosquitto-passwd.sh`. Do NOT make init-env.sh generate or set WS_PASSWORD (it would also have to regenerate mosquitto.passwd — out of scope; record as a follow-up in the SUMMARY). If `$site` / `$public_host` become unused only in the removed block, leave their other uses intact; update the script's header comment if it mentions config.ts.

    (d) deploy/.env.example: after the CMK_SITE_ID entry, add a commented optional block for WS_USERNAME / WS_PASSWORD: default wsreader/wsreader; read only by the dashboard container, which serves them to the browser via /config.json for the read-only MQTT WebSocket login; they must match a user in deploy/mosquitto.passwd (WS_PASSWORD: regenerate with `WS_PASSWORD=... deploy/gen-mosquitto-passwd.sh`, then `podman compose down && podman compose up -d`; WS_USERNAME: leave it unless you also change the user in deploy/gen-mosquitto-passwd.sh and deploy/mosquitto.acl); allowed characters as in (a). Also extend the CMK_SITE_ID comment: the dashboard reads it too (at container start, no rebuild). Keep lines commented out (`# WS_USERNAME=wsreader`, `# WS_PASSWORD=wsreader`).

    (e) deploy/dashboard.Containerfile header: replace the "locally edited dashboard-react/src/lib/config.ts (CHECKMK_BASE_URL) is baked into the image. Rebuild after editing it or after every git pull" sentences with: the image contains no per-machine settings (site name and broker credentials come from deploy/.env via /config.json at container start); rebuild after every git pull. Leave the 260930-hpy amendment paragraph, adjusting only its "config.ts no longer carries" wording if needed to stay accurate.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && bash -n deploy/init-env.sh && grep -q "location = /config.json" deploy/dashboard-nginx.conf && grep -q 'WS_PASSWORD=${WS_PASSWORD:-wsreader}' deploy/compose.yaml && grep -q 'CMK_SITE_ID=${CMK_SITE_ID:-dmc}' deploy/compose.yaml && ! grep -n "config\.ts\|CHECKMK_BASE_URL" deploy/init-env.sh deploy/compose.yaml deploy/.env.example && CMK_SITE_ID=mysite WS_USERNAME=wsreader WS_PASSWORD=pw envsubst '${CMK_SITE_ID} ${WS_USERNAME} ${WS_PASSWORD}' < deploy/dashboard-nginx.conf | grep -F '{"checkmkSite":"mysite","wsUsername":"wsreader","wsPassword":"pw"}' && uv run pytest -q</automated>
  </verify>
  <done>nginx template has the exact-match /config.json location rendering valid JSON after envsubst; compose passes the three vars with defaults; init-env.sh and .env.example no longer mention config.ts; pytest green.</done>
</task>

<task type="auto">
  <name>Task 3: Fix every operator-facing doc that says to edit config.ts / CHECKMK_BASE_URL</name>
  <files>docs/DEPLOY-NEW-MACHINE.md, docs/Podman setup for checkmk, minio, mosquitto, worker.md, dashboard-react/README.md, README.md, docs/Incident demo with fake check results.md, docs/WIZARD-OPERATION.md</files>
  <action>
    Edit surgically; keep each doc's tone and existing structure.

    docs/DEPLOY-NEW-MACHINE.md: §3 intro (~line 64) — drop "at the end it shows the two config.ts values to set", say it ends with the next steps. Remove the whole "### dashboard-react/src/lib/config.ts" subsection (~lines 74-84) including its amendment note. Add optional rows to the deploy/.env table for WS_USERNAME / WS_PASSWORD (default wsreader; served to the browser via /config.json; must match mosquitto.passwd) and extend the CMK_SITE_ID row: the dashboard picks it up at container start too. §4 MQTT credential row (~line 93): "update the poller's MQTT_PASSWORD in compose.yaml and set WS_PASSWORD in deploy/.env, then podman compose down && podman compose up -d" (no config.ts, no rebuild). "Updating later" (~line 284): "After every git pull" only.

    docs/Podman setup for checkmk, minio, mosquitto, worker.md: rewrite the §3 dashboard paragraph (~lines 172-192): the image carries no per-machine settings; the dashboard service's environment passes CMK_SITE_ID, WS_USERNAME, WS_PASSWORD (plus the existing CH_READER_PASSWORD / TOPOLOGY_EDITOR_SECRET), which nginx serves as /config.json; drop the CHECKMK_BASE_URL bullet entirely and the "no environment: block" claim; keep the WS credential rotation/read-only-grant explanation but point at deploy/.env WS_PASSWORD + gen-mosquitto-passwd.sh; rebuild only after git pull. ~line 278 and ~287 (site rename): the dashboard follows CMK_SITE_ID automatically — remove "update the dashboard's CHECKMK_SITE" and the "not driven by this variable" mention of it, and add `dashboard` to the recreate list or say a full down/up. ~line 302 build comment: "after every git pull". ~line 614 troubleshooting: check WS_USERNAME/WS_PASSWORD in deploy/.env (visible via curl http://HOST:8090/config.json) match mosquitto.passwd, instead of config.ts.

    dashboard-react/README.md §4: retitle to "Configuration — runtime /config.json and src/lib/config.ts". Explain: per-deployment values (checkmkSite, wsUsername, wsPassword) are loaded at startup from /config.json (src/lib/runtimeConfig.ts), which the production nginx renders from deploy/.env (CMK_SITE_ID, WS_USERNAME, WS_PASSWORD); under vite dev/preview there is no /config.json, so the defaults dmc/wsreader/wsreader apply; src/lib/config.ts holds only constants and those defaults and is never edited per deployment. Delete the CHECKMK_BASE_URL / "View in Checkmk" paragraph; update the constants list (drop WS_USERNAME/WS_PASSWORD/CHECKMK_SITE entries, add the three DEFAULT_* names; CHECKMK_REST_ORIGIN bullet drop "instead of CHECKMK_BASE_URL directly" wording but keep the CORS reason). ~line 110 "not a compile-time config.ts placeholder check" may stay (it's historical and accurate). §8 item 4 (~line 340): remove "src/lib/config.ts is baked in at build time, so rebuild after editing it too"; add a cutover-checklist item for /config.json.

    README.md ~line 194: replace "the one file an operator edits per deployment (src/lib/config.ts)" with a pointer that per-deployment dashboard settings come from deploy/.env at container start.

    docs/Incident demo with fake check results.md item 3 (~lines 18-25): stale since 260930-hpy — TOPOLOGY_EDITOR_SECRET lives in deploy/.env; fix is re-running scripts/provision_topology_editor.py (or the wizard) with the value from deploy/.env, then podman compose down && podman compose up -d; remove "paste the secret into config.ts".

    docs/WIZARD-OPERATION.md ~line 625: "not a compile-time config.ts check" is historical-accurate; leave unless it instructs editing (it does not).

    Final sweep: grep -rn "config\.ts\|CHECKMK_BASE_URL" across the repo excluding .planning/, .claude/, node_modules, dist and .git; every remaining hit must be either a non-instructional historical note or vite.config.ts/tsconfig/tsup references. List any intentionally kept hits in the SUMMARY.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && ! grep -rn "CHECKMK_BASE_URL" --exclude-dir=.planning --exclude-dir=.claude --exclude-dir=node_modules --exclude-dir=dist --exclude-dir=.git . && ! grep -n "lib/config\.ts" docs/DEPLOY-NEW-MACHINE.md "docs/Podman setup for checkmk, minio, mosquitto, worker.md" "docs/Incident demo with fake check results.md" README.md && grep -q "config.json" docs/DEPLOY-NEW-MACHINE.md && grep -q "config.json" dashboard-react/README.md</automated>
  </verify>
  <done>No doc tells an operator to edit config.ts or set CHECKMK_BASE_URL; DEPLOY-NEW-MACHINE, Podman setup and dashboard README describe CMK_SITE_ID / WS_USERNAME / WS_PASSWORD in deploy/.env and /config.json.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| deploy/.env -> nginx template | operator-supplied values pasted verbatim into an nginx string literal and JSON |
| nginx /config.json -> browser | unauthenticated LAN read of site name + read-only broker credential |
| /config.json -> SPA | untrusted JSON drives a REST path segment and broker login |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-ixs-01 | Information disclosure | /config.json wsPassword | accept | Same read-only wsreader credential previously shipped in the JS bundle; grant is `topic read lan/#` only (deploy/mosquitto.acl). No write-capable secret (TOPOLOGY_EDITOR_SECRET, CH_READER_PASSWORD) is added to the response — verify grep of the location block. |
| T-ixs-02 | Tampering | checkmkSite -> /checkmk-api/<site>/ path | mitigate | parseRuntimeConfig rejects anything not matching /^[A-Za-z][A-Za-z0-9_]{0,15}$/ (no "/", "..", "-"), falling back to dmc; nginx allow-list regex [A-Za-z0-9_]+ independently constrains the segment. |
| T-ixs-03 | Denial of service | nginx template rendering | mitigate | Document allowed characters for WS_USERNAME/WS_PASSWORD in dashboard-nginx.conf and .env.example (no quotes, backslash, $, braces, ;, whitespace); SPA tolerates malformed JSON by falling back to defaults. |
| T-ixs-04 | Denial of service | main.tsx startup fetch | mitigate | AbortSignal.timeout(3000) + never-rejecting loader so a hung/failed fetch cannot block rendering. |
| T-ixs-05 | Tampering | stale cached config | mitigate | Cache-Control: no-store on the response and cache: "no-store" on the fetch. |
</threat_model>

<verification>
Automated (executor):
- cd dashboard-react && npx vitest run && npm run build
- uv run pytest -q
- bash -n deploy/init-env.sh; envsubst render check of deploy/dashboard-nginx.conf (Task 2 verify)

Live checks — for the OPERATOR only (executor must not touch running containers):
1. cd deploy && podman compose build dashboard && podman compose down && podman compose up -d
2. curl -si http://HOST:8090/config.json -> 200, Content-Type application/json, Cache-Control: no-store, body {"checkmkSite":"<CMK_SITE_ID>","wsUsername":"wsreader","wsPassword":"..."}; pipe through `python3 -m json.tool` (or `uv run python -m json.tool`) to confirm valid JSON.
3. curl -si http://HOST:8090/details?id=x still returns index.html (SPA fallback intact).
4. On a stack whose CMK_SITE_ID is not dmc (with TOPOLOGY_EDITOR_SECRET set and provisioned): the "Edit topology" switch is enabled, and the browser network tab shows /checkmk-api/<site>/check_mk/api/1.0/version -> 200.
5. The dashboard's connection indicator reaches "Connected" (MQTT over ws://HOST:9002 with the served credentials).
</verification>

<success_criteria>
- config.ts contains no per-machine value and no dead CHECKMK_BASE_URL machinery.
- Site and WS credentials are taken from /config.json at runtime, with per-field fallback to dmc/wsreader/wsreader.
- nginx serves /config.json from deploy/.env values; compose passes them with defaults.
- init-env.sh ends with next steps, no config.ts instructions.
- vitest, npm run build and pytest all green; no operator doc mentions editing config.ts or CHECKMK_BASE_URL.
- SUMMARY records follow-up: init-env.sh could generate WS_PASSWORD together with regenerating mosquitto.passwd (deliberately out of scope).
</success_criteria>

<output>
Create `.planning/quick/260930-ixs-dashboard-runtime-config-from-env-instea/260930-ixs-SUMMARY.md` when done
</output>
