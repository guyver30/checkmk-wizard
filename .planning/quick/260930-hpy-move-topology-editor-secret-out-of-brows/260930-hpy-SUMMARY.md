# Quick 260930-hpy: Move topology_editor secret out of the browser bundle Summary

The dashboard's `topology_editor` Checkmk credential no longer ships in the browser bundle: it lives in `deploy/.env` as `TOPOLOGY_EDITOR_SECRET`, the wizard provisions/rotates it right after Phase 1, the dashboard's nginx injects it server-side on a method+path allow-list of the exact REST calls the SPA makes (403 catch-all for everything else), and the SPA gates its "Edit topology" switch on a runtime `GET /version` probe instead of a compile-time config.ts placeholder check. Supersedes Phase 13 D-04's client-embedded credential (user-approved 2026-09-30).

## Performance

- **Duration:** ~29 min (2026-09-30T04:51:58Z -> 2026-09-30T05:21:12Z)
- **Tasks:** 3/3 completed
- **Files modified:** 25 (incl. 1 deletion, 2 new `.planning` artifacts)

## Commits

1. `4451f15` feat(260930-hpy): move topology_editor provisioning into api.py and run it from the wizard
2. `306f9e2` feat(260930-hpy): nginx injects topology_editor credential; dashboard drops client-side secret
3. `d08edb2` docs(260930-hpy): update operator docs and record the D-04 amendment

## What changed

### Task 1 — api.py / wizard.py / provisioning script
- `src/checkmk_wizard/api.py`: moved `TOPOLOGY_EDITOR_ROLE_ID`/`ROLE_ALIAS`/`BASE_ROLE_ID`/`USER_ID`/`PERMISSIONS` constants and `build_role_permissions`/`build_topology_editor_user_body` helpers in from the standalone script. Added four `CheckmkClient` methods, all through `_request()`: `ensure_topology_editor_role()`, `user_exists()`, `upsert_automation_user()` (generic create-or-rotate, mirroring `bootstrap_automation_user()`'s GET-ETag-PUT/POST shape), `provision_topology_editor()`.
- `src/checkmk_wizard/wizard.py`: new `_provision_topology_editor(client, connection)`, called as the first statement inside `run()`'s `CheckmkClient` block (before Phase 2). Reads `TOPOLOGY_EDITOR_SECRET`; empty/unset prints one dim skip note and makes zero REST calls; a set value calls `provision_topology_editor()`, prints "created" or "updated ... from the environment" (never the value), then calls `_activate_pending_changes()`. Any `CheckmkAPIError` is caught, prints a yellow warning naming the manual fallback script, and `run()` continues into Phase 2 regardless.
- `scripts/provision_topology_editor.py`: rewritten on top of `CheckmkClient`/`CheckmkConnection` (`asyncio.run`), dropping the `urllib`/`_rest`/`ProvisionError` layer. Kept importable: `REQUIRED_PERMISSIONS`, `build_role_permissions`, `build_user_body`, `redact_auth_header`, `generate_secret`, `main` (via an explicit `__all__`, since the constants/builders are no longer called from this module — they're re-exported for the test file). Remains a manual fallback honouring `TOPOLOGY_EDITOR_SECRET` the same way.
- `deploy/compose.yaml` / `deploy/.env.example`: `TOPOLOGY_EDITOR_SECRET=${TOPOLOGY_EDITOR_SECRET:-}` added to the `worker` and `dashboard` env blocks; `.env.example` documents generation, ownership (worker provisions, dashboard's nginx injects) and rotation.

### Task 2 — nginx allow-list + dashboard-react
- `deploy/dashboard-nginx.conf`: the single `location /checkmk-api/ { proxy_pass ...; }` is replaced with three regex locations anchored to `^/checkmk-api/[A-Za-z0-9_]+/check_mk/api/1\.0/` (GET-only: version/pending-changes/activation-run poll; GET+PUT: the one host object; POST-only: unmanaged-switch create, activate-changes), each injecting `proxy_set_header Authorization "Bearer topology_editor ${TOPOLOGY_EDITOR_SECRET}"` and `rewrite ... break` + a bare `proxy_pass http://checkmk:5000;` (regex locations can't carry a URI in proxy_pass). A `location /checkmk-api/ { return 403; }` catch-all closes everything else (DELETE, user_config, user_role, rulesets, ...).
- `deploy/dashboard.Containerfile`: header comments updated — config.ts no longer carries the secret; nginx's template now also substitutes `${TOPOLOGY_EDITOR_SECRET}`.
- `dashboard-react/src/lib/checkmkWrite.ts`: `request()` no longer sets an `Authorization` header at all. New `probeEditingAvailable()`: `GET /version`, resolves `true` on success, `false` on any thrown `CheckmkWriteError` or other error (never rejects).
- `dashboard-react/src/lib/config.ts`: `TOPOLOGY_EDITOR_USER`, `TOPOLOGY_EDITOR_SECRET_PLACEHOLDER`, `TOPOLOGY_EDITOR_SECRET`, `isSecretConfigured`, `isTopologyEditingConfigured` all removed; `dashboard-react/src/lib/config.test.ts` deleted (every test in it covered only the removed functions).
- `dashboard-react/src/routes/IndexRoute.tsx`: drops the `config.ts` import; adds `editingAvailable` state set by a mount-only `useEffect` calling `probeEditingAvailable()` (cancelled-flag guarded); `TopologyToolbar`'s `editingConfigured` and `CriticalityEditor`'s gate both now read `editingAvailable`.
- `dashboard-react/src/components/TopologyToolbar.tsx`: `CONFIGURATION_HINT` now reads "Editing is off: set TOPOLOGY_EDITOR_SECRET in deploy/.env and run the wizard." (was "...in src/lib/config.ts").
- `dashboard-react/vite.config.ts`: the dev/preview `/checkmk-api` proxy now injects `Authorization: Bearer topology_editor ${TOPOLOGY_EDITOR_SECRET}` from the dev shell's env, mirroring nginx's production behaviour.
- Tests updated/added across `checkmkWrite.test.ts` (no-Authorization-header assertions on GET+PUT, `probeEditingAvailable` 200/401/500/network-error cases), `IndexRoute.test.tsx` (mocked `probeEditingAvailable` resolved `true` by default in a global `beforeEach`; every test that toggles the switch now awaits the mount-time probe first — `flush()` under fake timers, `waitFor(...).toBeEnabled()` under real timers; one new test covers a `false`-resolving probe: switch disabled, hint shown, `CriticalityEditor` absent), `TopologyToolbar.test.tsx` (hint string match).

### Task 3 — docs and constraint amendment
- `docs/DEPLOY-NEW-MACHINE.md`: `TOPOLOGY_EDITOR_SECRET` moves from the config.ts table to the `deploy/.env` table (with the `token_urlsafe(24)` generation command); §8 step 3 becomes "nothing to do".
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md`: the topology-editor credential note rewritten around four points (where it lives / what enforces the scope / how it's provisioned / how to rotate — full down/up, never a single-container restart); start-over checklist step 4 no longer requires a manual script re-run.
- `docs/WIZARD-OPERATION.md`: new "Topology editor provisioning (after Phase 1)" subsection (env var, create/rotate, skip note, never-fatal contract, immediate activation, fallback script); start-over section updated the same way.
- `dashboard-react/README.md`: removes the config.ts `TOPOLOGY_EDITOR_SECRET`/`TOPOLOGY_EDITOR_USER` bullets, adds a short section on nginx-injected credential + `probeEditingAvailable()`, fixes the §8 cutover reference to the old single `proxy_pass`.
- `.planning/PROJECT.md`, `CLAUDE.md`, `13-CONTEXT.md`: append the dated 2026-09-30 amendment to the "No new backend for the dashboard" constraint / D-04 decision, explicitly marked not to be re-litigated.

## Verification (actually run)

- `uv run pytest tests/test_api.py tests/test_wizard.py tests/test_provision_topology_editor.py -q`: 307 passed.
- `uv run pytest -q` (full suite): 670 passed.
- `uvx ruff check src/checkmk_wizard/api.py src/checkmk_wizard/wizard.py scripts/provision_topology_editor.py`: clean except one pre-existing, unrelated `B023` warning at `wizard.py:1595` (confirmed present at the base commit `a548b45`, outside every file this plan touches — logged in `deferred-items.md`, not fixed, per the scope-boundary rule).
- `npm --prefix dashboard-react test`: 505 passed (39 files) — required building `design-system` (`npm ci && npm run build && npm pack`) and `npm ci` in `dashboard-react` first, since this worktree had no `node_modules`.
- `npm --prefix dashboard-react run build`: succeeds; `grep -rl 'topology_editor ' dashboard-react/dist` finds nothing.
- `grep -c 'proxy_set_header Authorization "Bearer topology_editor ${TOPOLOGY_EDITOR_SECRET}";' deploy/dashboard-nginx.conf` = 3; `grep -q 'location /checkmk-api/ { return 403; }'` and the `api/1\.0/(version` allow-list-regex grep both match.
- `grep -q 'TOPOLOGY_EDITOR_SECRET=$' deploy/.env.example`, the compose double-entry count check, `! grep urllib scripts/provision_topology_editor.py`, and all three Task 3 doc greps (`PROJECT.md`/`CLAUDE.md`/`13-CONTEXT.md` amendment markers, `WIZARD-OPERATION.md` env var mention, no config.ts+TOPOLOGY_EDITOR co-occurrence) — all pass.
- Not verified (explicitly out of scope for this executor, per the plan): no podman available in this environment; the operator must run the 8-step live-verification checklist in the plan's `<verification>` block (set the secret, rebuild+full-down/up the dashboard, run the wizard, curl the allow-listed/blocked paths, exercise the Edit switch with the secret set and unset).

## Environment note

`grep` in this sandbox's Bash tool resolves to `ugrep` 7.8.4 (not GNU grep, despite `/usr/bin/grep` on disk actually being GNU grep 3.11) and mis-parses some BRE patterns containing `${...}` as literal text (e.g. the compose double-entry count check reported 0 instead of 2 under the shadowed `grep`). All grep-based verification in this summary was re-run against `/usr/bin/grep` explicitly to get correct results; this is a harness/environment quirk, not a content issue.

## Deviations

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Built `design-system` and installed dependencies before running dashboard-react tests/build**
- **Found during:** Task 2
- **Issue:** This worktree had no `dashboard-react/node_modules` or `design-system/dist`/tarball (main checkout's are not shared into a fresh worktree).
- **Fix:** Ran `npm --prefix design-system ci && npm --prefix design-system run build && (cd design-system && npm pack)`, then `npm --prefix dashboard-react ci`, exactly as the constraints and `dashboard-react/README.md` §2 direct.
- **Files modified:** none (build artifacts are gitignored: `dashboard-react/node_modules/`, `dashboard-react/dist/`, `design-system/node_modules/`, `design-system/dist/`, `design-system/kone-design-system-0.1.0.tgz`).
- **Verification:** `npm --prefix dashboard-react test` (505 passed) and `npm --prefix dashboard-react run build` (succeeds) both ran afterward.

**2. [Rule 3 - Blocking] Removed the literal word "urllib" from a code comment**
- **Found during:** Task 1, running the exact `<verify>` command
- **Issue:** `! grep -n 'urllib' scripts/provision_topology_editor.py` failed because the module docstring described the old implementation as "instead of a bare `urllib` client" — a true statement, but the literal substring tripped the gate meant to confirm the dependency was actually dropped.
- **Fix:** Reworded to "instead of a bare standard-library HTTP client" (same meaning, no `urllib` substring). No behavior change.
- **Files modified:** `scripts/provision_topology_editor.py`
- **Verification:** `grep -n 'urllib' scripts/provision_topology_editor.py` now finds nothing.

---

**Total deviations:** 2 auto-fixed (both Rule 3 — blocking, mechanical). No scope creep; no product-behavior changes beyond what the plan specified.

### Assumption Drift (advisory)

- **Found during:** Task 2, writing `IndexRoute.test.tsx`
- **Planned assumption:** the plan's action text described the probe/gating change as a drop-in swap (`isTopologyEditingConfigured()` mock -> `probeEditingAvailable()` mock), implying existing switch-toggle tests would need only the mock swap.
- **Actual:** because `editingConfigured` now starts `false` until an async probe resolves, every existing test that clicks the "Edit topology" switch immediately after `render()` needed an explicit flush point inserted first (`await flush()` under the fake-timers describe block, `await waitFor(() => expect(switch).toBeEnabled())` under the two real-timer DASH-16 tests) — otherwise the switch was still `disabled` at click time and the test silently no-opped instead of failing loudly.
- **Why:** asynchronous state (even one that resolves "immediately" via a mocked resolved Promise) still requires a microtask tick before React applies it; a synchronous mock-swap alone doesn't reproduce that timing.
- **Impact:** more test-file lines changed in Task 2 than the plan's action text implied, but the behavior implemented is exactly what the plan's `<behavior>` list specifies.

### Verify-gate false positive (not a deviation, no code change)

**Task 2's own `<verify>` grep** (`grep -rn 'TOPOLOGY_EDITOR_SECRET|isTopologyEditingConfigured|Authorization' dashboard-react/src ... | grep -v '\.test\.' | grep -v '^\S*:\s*//'`) flags `TopologyToolbar.tsx`'s `CONFIGURATION_HINT` string, which the same plan's action text explicitly requires to read `"...set TOPOLOGY_EDITOR_SECRET in deploy/.env and run the wizard."`. This is the operator-facing hint naming the env var (not a leaked secret value, not an `Authorization` header, not the removed `isTopologyEditingConfigured` function) — the plan's action text and its own verify grep are in tension here. The underlying threat (T-hpy-01, secret in the bundle) is independently confirmed closed by `grep -rl 'topology_editor ' dashboard-react/dist` (no match) and by `checkmkWrite.test.ts`'s explicit "no Authorization header sent" assertions.

## Threat Flags

None. All surface introduced (the three nginx allow-list locations, the four new `CheckmkClient` methods, `probeEditingAvailable()`) is exactly what this plan's own `<threat_model>` register (T-hpy-01..07) anticipated and mitigates; no new endpoint, auth path, or trust boundary outside that register was added.

## Known Stubs

None.

## User Setup Required

None for this quick task's own scope — no new external service. Live verification (setting `TOPOLOGY_EDITOR_SECRET`, rebuilding/restarting the dashboard, curling the allow-listed and blocked paths, exercising the Edit switch) is explicitly left to the operator per the plan's `<verification>` section, since this executor has no podman access.

## Self-Check: PASSED

- `src/checkmk_wizard/api.py` — FOUND, contains `provision_topology_editor`.
- `src/checkmk_wizard/wizard.py` — FOUND, contains `_provision_topology_editor` called first in `run()`'s `CheckmkClient` block.
- `scripts/provision_topology_editor.py` — FOUND, no `urllib` string remains.
- `deploy/dashboard-nginx.conf` — FOUND, three allow-listed locations + 403 catch-all.
- `dashboard-react/src/lib/checkmkWrite.ts` — FOUND, `probeEditingAvailable` exported.
- `dashboard-react/src/lib/config.test.ts` — confirmed absent (intentionally deleted).
- Commits `4451f15`, `306f9e2`, `d08edb2` — all present in `git log --oneline`.

---
*Quick task: 260930-hpy*
*Completed: 2026-09-30*
