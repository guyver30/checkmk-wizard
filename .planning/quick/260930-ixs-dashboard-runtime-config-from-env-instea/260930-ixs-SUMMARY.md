---
phase: quick-260930-ixs
plan: 01
subsystem: dashboard
tags: [react, vite, nginx, envsubst, mqtt, checkmk-rest, runtime-config]

# Dependency graph
requires:
  - phase: quick-260930-hpy
    provides: dashboard nginx allow-list injecting TOPOLOGY_EDITOR_SECRET server-side, the pattern this plan extends to CMK_SITE_ID/WS_USERNAME/WS_PASSWORD
provides:
  - "dashboard-react/src/lib/runtimeConfig.ts: parseRuntimeConfig/loadRuntimeConfig/getRuntimeConfig/__setRuntimeConfigForTests, loaded once in main.tsx before first render"
  - "deploy/dashboard-nginx.conf location = /config.json rendering {checkmkSite, wsUsername, wsPassword} from CMK_SITE_ID/WS_USERNAME/WS_PASSWORD via envsubst"
  - "deploy/compose.yaml dashboard service passes CMK_SITE_ID/WS_USERNAME/WS_PASSWORD with dmc/wsreader/wsreader defaults"
  - "deploy/init-env.sh next-steps block (down/up, optional WS_PASSWORD rotation note) replacing the old config.ts instructions"
  - "operator docs (DEPLOY-NEW-MACHINE.md, Podman setup doc, dashboard-react/README.md, top-level README, incident-demo runbook) updated to point at deploy/.env + /config.json instead of config.ts"
affects: [dashboard-react, deploy]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Runtime config loaded once before first render (main.tsx awaits loadRuntimeConfig()), read per-call via getRuntimeConfig() in checkmkWrite.ts/mqttClient.ts rather than a module-load-time constant, because those modules evaluate before the fetch resolves"
    - "nginx envsubst template location = /config.json (exact-match, wins over the SPA fallback prefix location) rendering a runtime config blob from container env, same pattern as the existing TOPOLOGY_EDITOR_SECRET injection from quick 260930-hpy"

key-files:
  created:
    - dashboard-react/src/lib/runtimeConfig.ts
    - dashboard-react/src/lib/runtimeConfig.test.ts
  modified:
    - dashboard-react/src/lib/config.ts
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
    - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
    - "docs/Incident demo with fake check results.md"
    - dashboard-react/README.md
    - README.md

key-decisions:
  - "checkmkWrite.ts's API prefix is built per call via a new apiPrefix() function reading getRuntimeConfig().checkmkSite, not a module-level const, because ES module top-level code runs before main.tsx's awaited loadRuntimeConfig() resolves"
  - "config.ts keeps DEFAULT_CHECKMK_SITE/DEFAULT_WS_USERNAME/DEFAULT_WS_PASSWORD as the fallback source of truth for runtimeConfig.ts, so vite dev/preview and vitest need no /config.json at all"

patterns-established:
  - "Third lib/store module allowed to do network I/O (runtimeConfig.ts), alongside checkmkWrite.ts and mqttClient.ts, each documented in its module header"

requirements-completed: [QUICK-260930-ixs]

# Metrics
duration: 40min
completed: 2026-09-30
---

# Quick Task 260930-ixs: Dashboard Runtime Config From deploy/.env Summary

**Dashboard's Checkmk site name and read-only MQTT WebSocket credentials now come from nginx's `/config.json` (rendered from `deploy/.env`) at container start, not from a build-time `dashboard-react/src/lib/config.ts` edit — the dead `CHECKMK_BASE_URL`/`isCheckmkLinkConfigured()` machinery is removed and every operator doc updated to match.**

## Performance

- **Duration:** ~40 min
- **Tasks:** 3 completed
- **Files modified:** 16 (2 created, 14 modified)

## Accomplishments

- One dashboard image now runs on every machine: `checkmkSite`/`wsUsername`/`wsPassword` are runtime values loaded from `/config.json` before first render, with per-field fallback to `dmc`/`wsreader`/`wsreader` when the endpoint is missing, unreachable, non-JSON, or a field is invalid.
- `deploy/dashboard-nginx.conf` serves `/config.json` from an exact-match location (wins over the SPA `try_files` fallback) rendered by envsubst from `CMK_SITE_ID`/`WS_USERNAME`/`WS_PASSWORD`, all three always defined by compose with defaults.
- `checkmkWrite.ts` and `mqttClient.ts` read the runtime site/credentials per call instead of importing build-time constants; the dead `CHECKMK_BASE_URL`, `CHECKMK_BASE_URL_PLACEHOLDER`, `isCheckmkLinkConfigured()` are deleted from `config.ts`.
- `deploy/init-env.sh` no longer ends with a "paste these into config.ts" block — it prints a down/up next-steps block plus an optional WS_PASSWORD rotation note.
- Every operator-facing doc that told someone to edit `config.ts` or set `CHECKMK_BASE_URL` (DEPLOY-NEW-MACHINE.md, the Podman setup doc, dashboard-react/README.md, the top-level README, the incident-demo runbook) now points at `deploy/.env` and `/config.json`.

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: failing tests for runtime config loader** - `0cdd867` (test)
2. **Task 1 GREEN: runtime config loader + config.ts/checkmkWrite.ts/mqttClient.ts/main.tsx wiring** - `3981cb2` (feat)
3. **Task 2: nginx /config.json, compose env, init-env.sh, .env.example, Containerfile** - `299482d` (feat)
4. **Task 3: operator-doc updates** - `733ef25` (docs)

**Plan metadata:** (this commit, made after this SUMMARY) - `docs(260930-ixs): complete plan`

_Task 1 is TDD (`tdd="true"`): test → feat, no refactor commit was needed._

## Files Created/Modified

- `dashboard-react/src/lib/runtimeConfig.ts` - RuntimeConfig loader/parser/getter with per-field fallback and test-only setter
- `dashboard-react/src/lib/runtimeConfig.test.ts` - vitest coverage of parsing and the never-reject load contract
- `dashboard-react/src/lib/config.ts` - now holds only `WS_PORT`/`DEFAULT_CHECKMK_SITE`/`DEFAULT_WS_USERNAME`/`DEFAULT_WS_PASSWORD`/`POLL_INTERVAL_SECONDS`/`STALENESS_FACTOR`/`HISTORY_MAX_ENTRIES`/`CHECKMK_REST_ORIGIN`; dead `CHECKMK_BASE_URL`/`CHECKMK_SITE`/`WS_USERNAME`/`WS_PASSWORD`/`isCheckmkLinkConfigured()` removed
- `dashboard-react/src/lib/checkmkWrite.ts` - `apiPrefix()` and activation `sites` list now read `getRuntimeConfig().checkmkSite` per call
- `dashboard-react/src/lib/checkmkWrite.test.ts` - added `mysite` runtime-config cases; `afterEach` resets the runtime config
- `dashboard-react/src/store/mqttClient.ts` - `connect()` reads `wsUsername`/`wsPassword` from `getRuntimeConfig()`
- `dashboard-react/src/store/mqttClient.test.ts` - added a `u2`/`p2` runtime-config case; `afterEach` resets the runtime config
- `dashboard-react/src/main.tsx` - awaits `loadRuntimeConfig()` before `createRoot(...).render(...)`
- `deploy/dashboard-nginx.conf` - new exact-match `location = /config.json`, header comment updated with the new substituted variables
- `deploy/compose.yaml` - dashboard service environment gains `CMK_SITE_ID`/`WS_USERNAME`/`WS_PASSWORD` with defaults; comments updated
- `deploy/init-env.sh` - final heredoc replaced with a down/up next-steps block
- `deploy/.env.example` - new optional `WS_USERNAME`/`WS_PASSWORD` block; `CMK_SITE_ID` comment extended
- `deploy/dashboard.Containerfile` - header no longer claims `config.ts` is baked in
- `docs/DEPLOY-NEW-MACHINE.md` - dropped the `config.ts` subsection, added `WS_USERNAME`/`WS_PASSWORD` row, updated the MQTT-rotation and "Updating later" text
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` - rewrote the §3 dashboard paragraph, site-rename note, build comment, troubleshooting line
- `docs/Incident demo with fake check results.md` - item 3's `topology_editor` troubleshooting step now points at `deploy/.env`
- `dashboard-react/README.md` - §4 retitled and rewritten around runtime `/config.json`; §8 cutover item 4 updated
- `README.md` - dashboard blurb no longer calls out `config.ts` as the one file to edit

## Decisions Made

- Built `apiPrefix()` as a function rather than a module-level constant in `checkmkWrite.ts`, since ES module top-level code executes before `main.tsx`'s awaited `loadRuntimeConfig()` resolves — a constant would always freeze on the default site.
- Kept `config.ts`'s `DEFAULT_*` constants as the single source of fallback truth that `runtimeConfig.ts` imports, rather than duplicating `"dmc"`/`"wsreader"` literals in the new module.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Task 1's literal automated verify grep false-positives on the plan's own required `DEFAULT_WS_USERNAME`/`DEFAULT_WS_PASSWORD` names**
- **Found during:** Task 1 verification
- **Issue:** The plan's `<verify>` line for Task 1 is `grep -rn "CHECKMK_BASE_URL\|isCheckmkLinkConfigured\|CHECKMK_SITE\b\|WS_USERNAME\|WS_PASSWORD" ...` — `CHECKMK_SITE` has a `\b` word-boundary but `WS_USERNAME`/`WS_PASSWORD` do not, so the grep matches them as substrings of the plan's own required `DEFAULT_WS_USERNAME`/`DEFAULT_WS_PASSWORD` constant names (plan step 1a explicitly instructs adding those two names). Running the exact command as written fails even though no removed identifier (bare `WS_USERNAME`, `WS_PASSWORD`, `CHECKMK_SITE`, `CHECKMK_BASE_URL`, `isCheckmkLinkConfigured`) actually remains in source.
- **Fix:** No code change — added `\b` boundaries around `WS_USERNAME`/`WS_PASSWORD` when re-running the check by hand to confirm the intended behavior: `grep -rnE "CHECKMK_BASE_URL|isCheckmkLinkConfigured|\bCHECKMK_SITE\b|\bWS_USERNAME\b|\bWS_PASSWORD\b" src --include=*.ts --include=*.tsx | grep -v "^\S*:[0-9]*:\s*//"` returns nothing (the only two hits, both in `config.ts`'s own removal-note comment, are filtered out as comment lines).
- **Files modified:** none (verification-only)
- **Verification:** Corrected regex confirms zero non-comment references; `npx vitest run` (527 passed) and `npm run build` both green regardless.
- **Committed in:** n/a (documented here, not a code change)

**2. [Rule 3 - Blocking] Task 3's repo-wide `CHECKMK_BASE_URL` grep has no comment exception, unlike Task 1's**
- **Found during:** Task 3 verification
- **Issue:** `config.ts`'s own dated removal-note comment ("Amended 2026-09-30 (quick 260930-ixs): CHECKMK_BASE_URL, ...") named the deleted identifier literally, which the plan's Task 3 verify grep (no comment-filtering pipe, unlike Task 1's) flagged even though it is a historical note, not an instruction to an operator.
- **Fix:** Reworded the comment to describe the removed identifiers ("the human-facing Checkmk base URL constant, its unedited-placeholder sentinel, the link-configured predicate...") instead of naming them literally, preserving the same explanation without tripping the literal-string check.
- **Files modified:** `dashboard-react/src/lib/config.ts`
- **Verification:** `grep -rn "CHECKMK_BASE_URL" --exclude-dir=.planning --exclude-dir=.claude --exclude-dir=node_modules --exclude-dir=dist --exclude-dir=.git .` returns nothing; full Task 3 verify chain passes.
- **Committed in:** `733ef25` (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3, both verify-script imprecisions, no functional code changes beyond a comment reword)
**Impact on plan:** No scope creep. The plan's own `done` criteria ("no source (non-comment) reference to the removed constants remains", "no doc tells an operator to edit config.ts or set CHECKMK_BASE_URL") are satisfied; only the literal `<verify>` shell one-liners had regex gaps against the plan's own required new names.

## Follow-up (deliberately out of scope, per plan)

`deploy/init-env.sh` could generate `WS_PASSWORD` itself, but doing so would also require it to regenerate `deploy/mosquitto.passwd` in lockstep — left as a manual step (`WS_PASSWORD=... deploy/gen-mosquitto-passwd.sh`) per the plan's explicit instruction not to add this.

## Issues Encountered

- `dashboard-react/node_modules` and `design-system/dist` were absent in this worktree (gitignored, not checked out). Built per `dashboard-react/README.md` §2: `npm --prefix design-system ci && npm --prefix design-system run build && (cd design-system && npm pack)`, then `npm --prefix dashboard-react ci`. `esbuild`'s postinstall scripts were skipped by npm's `allowScripts` gate but the build succeeded anyway (esbuild ships prebuilt platform binaries as optional deps that still installed).
- A new `mqttClient.test.ts` case needed an explicit `IClientOptions` type import from `mqtt` to destructure `connectFn.mock.calls[0]` under `tsc -b`'s strict overload-resolution; resolved with an `as unknown as [string, IClientOptions]` cast on the mock-call tuple rather than trying to make the mock itself satisfy `mqtt.connect`'s three-way overload.

## User Setup Required

None - no external service configuration required. (The plan's `<verification>` §"Live checks" section lists operator-only steps — starting/restarting containers and curling `/config.json` on a live stack — which this executor deliberately did not run, per the constraint against touching running containers.)

## Next Phase Readiness

- All automated verification is green: `npx vitest run` (527 passed, including the 22 new runtime-config/checkmkWrite/mqttClient cases), `npm run build` (typecheck + production build), `uv run pytest -q` (670 passed), `bash -n deploy/init-env.sh`, and an `envsubst` render check of the new `/config.json` nginx location.
- Not run by this executor (requires a live container stack, per the plan's constraints and this executor's instructions): the five "Live checks — for the OPERATOR only" steps in the plan's `<verification>` section (`podman compose build dashboard && ... up -d`, curling `/config.json`, confirming the SPA fallback still works, exercising a non-`dmc` site's topology editor, and confirming the MQTT connection indicator reaches "Connected"). An operator should run these before considering the change live-verified.

## Self-Check: PASSED

- FOUND: `dashboard-react/src/lib/runtimeConfig.ts`
- FOUND: `dashboard-react/src/lib/runtimeConfig.test.ts`
- FOUND: `deploy/dashboard-nginx.conf`
- FOUND: `deploy/compose.yaml`
- FOUND: `deploy/init-env.sh`
- FOUND: `deploy/.env.example`
- FOUND: `.planning/quick/260930-ixs-dashboard-runtime-config-from-env-instea/260930-ixs-SUMMARY.md`
- FOUND commits: `0cdd867`, `3981cb2`, `299482d`, `733ef25` (all present in `git log --oneline -5`)

---
*Phase: quick-260930-ixs*
*Completed: 2026-09-30*
