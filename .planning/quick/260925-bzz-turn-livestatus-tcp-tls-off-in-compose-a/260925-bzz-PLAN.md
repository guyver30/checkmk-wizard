---
phase: quick-260925-bzz
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - deploy/checkmk-hooks/pre-start/10-livestatus-tcp-plaintext.sh
  - deploy/compose.yaml
  - src/checkmk_wizard/site.py
  - src/checkmk_wizard/wizard.py
  - src/checkmk_wizard/livestatus.py
  - tests/test_site.py
  - tests/test_wizard.py
  - README.md
  - docs/Podman setup for checkmk, minio, mosquitto, worker.md
autonomous: true
requirements: [QUICK-260925-bzz]

must_haves:
  truths:
    - "A checkmk container started from deploy/compose.yaml (blank or existing volume) comes up with LIVESTATUS_TCP_TLS=off, so tmp/run/live-tcp points at live (plain LQL) and the poller/wizard work without manual omd commands"
    - "Host-mode wizard (omd present) leaves the site with LIVESTATUS_TCP=on AND LIVESTATUS_TCP_TLS=off, stopping the site for `omd config set` and starting it again afterward if it had been running"
    - "Container-mode wizard warns with the exact `podman exec checkmk su - <site> -c 'omd stop; omd config set LIVESTATUS_TCP_TLS off; omd start'` command when port 6557 accepts connections but gives no plain-text Livestatus reply, and never aborts the run over it"
    - "README and the Podman doc (sections 5 and 8.5) no longer imply CMK_LIVESTATUS_TCP=on alone makes TCP Livestatus usable; they document the TLS symptom and fix"
  artifacts:
    - path: "deploy/checkmk-hooks/pre-start/10-livestatus-tcp-plaintext.sh"
      provides: "Entrypoint pre-start hook that turns LIVESTATUS_TCP_TLS off"
      contains: "LIVESTATUS_TCP_TLS"
    - path: "deploy/compose.yaml"
      provides: "Bind mount of the hook into /docker-entrypoint.d/pre-start/"
      contains: "/docker-entrypoint.d/pre-start/"
    - path: "src/checkmk_wizard/site.py"
      provides: "livestatus_tcp_tls_enabled() and TLS-off handling in enable_livestatus_tcp()"
      contains: "def livestatus_tcp_tls_enabled"
    - path: "src/checkmk_wizard/wizard.py"
      provides: "_livestatus_answers_plaintext() probe + container-mode warning"
      contains: "def _livestatus_answers_plaintext"
  key_links:
    - from: "deploy/compose.yaml"
      to: "deploy/checkmk-hooks/pre-start/10-livestatus-tcp-plaintext.sh"
      via: "checkmk service volumes: bind mount, read-only"
      pattern: "checkmk-hooks/pre-start/10-livestatus-tcp-plaintext.sh:/docker-entrypoint.d/pre-start/"
    - from: "src/checkmk_wizard/wizard.py phase1_site_bringup (container branch)"
      to: "_livestatus_answers_plaintext"
      via: "called only when _probe_livestatus_tcp() is True"
      pattern: "_livestatus_answers_plaintext\\("
---

<objective>
Make a freshly created (or existing) Checkmk site serve plain-text Livestatus over TCP by turning LIVESTATUS_TCP_TLS off: automatically in deploy/compose.yaml through the container's entrypoint hook mechanism, in the wizard's host mode through `omd config`, and in container mode by detecting the symptom and printing the exact fix. Then correct the docs.

Purpose: diagnosed live on 2026-09-25. A fresh `checkmk/check-mk-raw:2.4.0-latest` site (`dmc`) had `LIVESTATUS_TCP_TLS=on`. xinetd forwarded port 6557 to `tmp/run/live-tcp -> live-tls`, so plain LQL clients got "Connection reset by peer". The poller exited with "Malformed columns response" and the dashboard showed "connected" but empty. `CMK_LIVESTATUS_TCP=on` only runs `omd config set LIVESTATUS_TCP on`; it does not touch TLS.
Output: entrypoint hook script, compose mount, site.py and wizard.py changes with tests, corrected docs.
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/templates/summary.md
</execution_context>

<context>
@./CLAUDE.md
@.planning/STATE.md
@deploy/compose.yaml
@src/checkmk_wizard/site.py
@src/checkmk_wizard/livestatus.py

Verification already done by the planner (2026-09-25). Cite this in the compose/hook comments:
- docs.checkmk.com/latest/en/introduction_docker.html ("Additional environment variables") documents only CMK_PASSWORD, TZ, CMK_SITE_ID, CMK_LIVESTATUS_TCP (runs `omd config set LIVESTATUS_TCP on`) and MAIL_RELAY_HOST. **No env var exists for LIVESTATUS_TCP_TLS**, and the user docs do NOT describe the /docker-entrypoint.d hook mechanism. Do NOT invent an env var.
- The hook mechanism is verified from source rather than user docs: github.com/Checkmk/checkmk, branch 2.4.0, `docker_image/docker-entrypoint.sh`. It has `HOOKROOT=/docker-entrypoint.d`. `exec_hook <name>` runs every executable non-directory file in `$HOOKROOT/<name>` as `./"$hook"`. The hooks are pre-entrypoint, pre-create, post-create, pre-update, post-update, pre-start and post-start. The sequence is `exec_hook pre-start; omd start "$CMK_SITE_ID"; exec_hook post-start`, so pre-start runs as root with the site still stopped, on every container start. post-create runs only right after `omd create`, which also runs `set LIVESTATUS_TCP on`.
- **Choice: use a pre-start hook, not post-create.** Pre-start runs on every container start while the site is stopped, so `omd config set` is allowed. It covers a blank site on first boot. It also repairs an already-created site such as the current `dmc` on its next container restart, which post-create would never touch.
- **Not verified (flag in SUMMARY and in the compose comment):** (a) whether the image ships its own files in /docker-entrypoint.d/pre-start/. This is why we bind-mount a single file instead of the whole directory, so we cannot hide anything. (b) whether the entrypoint runs under `set -e`. This is why the hook always exits 0. (c) that the `2.4.0-latest` tag's entrypoint matches branch 2.4.0. If `podman` is available on this machine, the executor MAY confirm with `podman run --rm --entrypoint sh checkmk/check-mk-raw:2.4.0-latest -c 'ls -la /docker-entrypoint.d; grep -n exec_hook /docker-entrypoint.sh'`. This is optional and must not block anything. Record the result either way.

<interfaces>
From src/checkmk_wizard/site.py (existing):
- `livestatus_tcp_enabled(site) -> bool`: runs `["omd","config",site,"show","LIVESTATUS_TCP"]` via `subprocess.run(..., capture_output=True, text=True, check=False)` and returns stdout.strip() == "on"
- `site_running(site) -> bool`: `omd status` returncode != 2
- `enable_livestatus_tcp(site) -> None`: returns early if already enabled, otherwise sets LIVESTATUS_TCP on and runs `omd restart` if the site was running. Raises SiteBootstrapError on a nonzero `set`. Called from wizard.py `_create_fresh_site` (line ~329, before start_site) and from the reuse_existing branch (line ~557, before start_site).
- `start_site(site) -> str`: raises only if rc != 0 and "failed" in stdout (rc 2 = already running is fine)

From src/checkmk_wizard/wizard.py (existing):
- `_probe_livestatus_tcp(host, port=livestatus.DEFAULT_PORT, timeout=2.0) -> bool`: TCP connect only, via `socket.create_connection`
- phase1_site_bringup container branch (line ~501-509): `if not _probe_livestatus_tcp(checkmk_host): console.print("[yellow]Could not reach Livestatus ...")`

Tests: tests/test_site.py patches `subprocess.run` with `side_effect=[CompletedProcess...]` lists (see test_enable_livestatus_tcp_* at lines 135-177). tests/test_wizard.py `_mock_container_mode_omd_calls` (line 155) already patches `checkmk_wizard.wizard.socket.create_connection` to raise OSError, so a new socket-based helper fails harmlessly in the existing container-mode tests.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Compose pre-start hook that turns LIVESTATUS_TCP_TLS off</name>
  <files>deploy/checkmk-hooks/pre-start/10-livestatus-tcp-plaintext.sh, deploy/compose.yaml</files>
  <action>
Create `deploy/checkmk-hooks/pre-start/10-livestatus-tcp-plaintext.sh` with the `#!/bin/bash` shebang. Write a header comment covering four points:
- The bug, with the 2026-09-25 date. A fresh 2.4.0 site defaults LIVESTATUS_TCP_TLS=on, `live-tcp` symlinks to `live-tls`, and plain LQL clients get "Connection reset by peer".
- Why a hook: no documented env var exists for this option.
- How the hook mechanism was verified: entrypoint source, branch 2.4.0, docker_image/docker-entrypoint.sh, pre-start runs as root before `omd start` with the site stopped.
- Why it always exits 0: the entrypoint's `set -e` behaviour is unverified, and a failed hook must never stop Checkmk from starting.

Logic:
- `site="${CMK_SITE_ID:-cmk}"`. `cmk` is the image default site name, per the docs.
- Read the value with `omd config "$site" show LIVESTATUS_TCP_TLS`, suppressing stderr.
- If the value equals `on`, echo a one-line message and run `omd config "$site" set LIVESTATUS_TCP_TLS off`. If that command fails, echo a warning.
- Otherwise do nothing. This also covers an empty value from an older Checkmk that lacks the option.
- End with `exit 0`.
- Do not use `set -e`.

Make the file executable (`chmod +x`). Ensure git records mode 100755: run `git add` then `git update-index --chmod=+x` on it. A 100644 file would be silently skipped by `exec_hook`'s `-x` test.

In deploy/compose.yaml, add a volume to the `checkmk` service: `./checkmk-hooks/pre-start/10-livestatus-tcp-plaintext.sh:/docker-entrypoint.d/pre-start/10-livestatus-tcp-plaintext.sh:ro,z`. Mount a single file rather than the directory, so any image-provided hooks in that directory stay visible.

Extend the existing CMK_LIVESTATUS_TCP comment block to say that the variable does NOT cover TLS, and point to the hook. Put a short comment above the new mount with these citations: the docker docs env var list (no TLS variable), the entrypoint source (branch 2.4.0, pre-start before omd start, root, site stopped), and the unverified items (a)-(c) from the context section. Match the file's existing comment style (dated "Bug fixed" prose). Do not change any other service.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && bash -n deploy/checkmk-hooks/pre-start/10-livestatus-tcp-plaintext.sh && test -x deploy/checkmk-hooks/pre-start/10-livestatus-tcp-plaintext.sh && git ls-files -s deploy/checkmk-hooks/pre-start/10-livestatus-tcp-plaintext.sh | grep -q '^100755' && grep -v '^\s*#' deploy/compose.yaml | grep -q 'checkmk-hooks/pre-start/10-livestatus-tcp-plaintext.sh:/docker-entrypoint.d/pre-start/10-livestatus-tcp-plaintext.sh:ro,z' && grep -v '^\s*#' deploy/checkmk-hooks/pre-start/10-livestatus-tcp-plaintext.sh | grep -q 'set LIVESTATUS_TCP_TLS off'</automated>
  </verify>
  <done>The hook script passes a bash syntax check, is executable and tracked as 100755, and exits 0 on every path. The checkmk service mounts it read-only into /docker-entrypoint.d/pre-start/. The comments cite what was verified (docs plus entrypoint source) and flag what was not.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Wizard host-mode TLS-off and container-mode TLS symptom detection</name>
  <files>src/checkmk_wizard/site.py, src/checkmk_wizard/wizard.py, src/checkmk_wizard/livestatus.py, tests/test_site.py, tests/test_wizard.py</files>
  <behavior>
    - site.livestatus_tcp_tls_enabled("mysite") runs ["omd","config","mysite","show","LIVESTATUS_TCP_TLS"] and returns True only for stdout "on" (returns False for "off" and for empty stdout, i.e. an older Checkmk without the option)
    - enable_livestatus_tcp: TCP on + TLS off → only the two show calls, no set/stop/start
    - enable_livestatus_tcp: TCP on + TLS on, site stopped → sets LIVESTATUS_TCP_TLS off, does NOT set LIVESTATUS_TCP, and makes no stop/start calls
    - enable_livestatus_tcp: TCP off + TLS on, site running → `omd stop mysite`, set LIVESTATUS_TCP on, set LIVESTATUS_TCP_TLS off, `omd start mysite`, in that order
    - enable_livestatus_tcp: set fails while the site was running → the site is started again anyway (try/finally), then SiteBootstrapError is raised with the omd output
    - wizard._livestatus_answers_plaintext: a fake socket whose recv returns b"2.4.0p35\n" then b"" → True; recv raises ConnectionResetError → False; first recv returns b"" → False; create_connection raises OSError → False
    - phase1 container mode: when _probe_livestatus_tcp is True and _livestatus_answers_plaintext is False, the output contains "LIVESTATUS_TCP_TLS off" and the `podman exec checkmk su - dmc -c 'omd stop; omd config set LIVESTATUS_TCP_TLS off; omd start'` command, and phase1 still returns a CheckmkConnection (no exception)
  </behavior>
  <action>
**site.py**

Add `livestatus_tcp_tls_enabled(site) -> bool` next to `livestatus_tcp_enabled`, using the same subprocess pattern, with `LIVESTATUS_TCP_TLS` as the variable.

Rework `enable_livestatus_tcp(site)` so it ensures both LIVESTATUS_TCP=on and LIVESTATUS_TCP_TLS=off:
- Compute `need_tcp = not livestatus_tcp_enabled(site)` and `need_tls_off = livestatus_tcp_tls_enabled(site)`. Return early if neither is needed.
- Otherwise record `was_running = site_running(site)`. If it was running, run `omd stop <site>` first. `omd config set` refuses to run on a running site with "Cannot change config variables while site is running." This is already documented in the Podman doc section 5. The old set-then-`omd restart` path contradicted it; replace that path with stop, set, start.
- Inside try/finally, run each needed `omd config <site> set ...` call, raising SiteBootstrapError with stdout+stderr on a nonzero exit, as today. In `finally`, if the site was running, call the existing `start_site(site)` so a failed set never leaves the site down.
- Update the docstring. Explain why TLS must be off: the wizard's livestatus.py and scripts/mqtt_poller.py speak plain LQL. Add a dated "Bug fixed 2026-09-25" note: the default TLS=on made `live-tcp` a symlink to `live-tls` and gave "Connection reset by peer". Also cite the "site must be stopped" behaviour.
- Keep `check=False` on every call, per convention.

Update livestatus.py's module docstring sentence about `site.enable_livestatus_tcp()` to also mention plain text (TLS off). Change only that one line.

**wizard.py**

Add `_livestatus_answers_plaintext(host, port=livestatus.DEFAULT_PORT, timeout=2.0) -> bool` next to `_probe_livestatus_tcp`:
- Use `socket.create_connection` with the timeout.
- Send `GET status\nColumns: program_version\n\n`, then `shutdown(SHUT_WR)`, then read until EOF.
- Return True if any non-whitespace bytes came back. Return False on an empty reply or any OSError. ConnectionResetError and TimeoutError are both OSError subclasses, so catch only OSError.
- Docstring: a TLS listener resets or ignores a plain LQL request. This distinguishes "port open but TLS" from "port closed", which `_probe_livestatus_tcp` cannot.

In `phase1_site_bringup`'s container branch, turn the existing `if not _probe_livestatus_tcp(...)` block into if/elif. The elif is `not _livestatus_answers_plaintext(checkmk_host)` and prints a yellow warning with four parts:
- Livestatus on host:6557 accepts connections but gives no plain-text reply.
- The likely cause: LIVESTATUS_TCP_TLS is on (the default for a new Checkmk 2.4 site); the poller and Phase 7 need it off.
- The exact command with the real site name interpolated: `podman exec checkmk su - {site_name} -c 'omd stop; omd config set LIVESTATUS_TCP_TLS off; omd start'`, then restart the poller: `podman restart mqtt-poller`.
- The deploy/compose.yaml pre-start hook does this automatically on the next checkmk container start.

The warning never raises and never returns early; follow the best-effort convention.

**tests**

Update test_site.py for the new call sequence:
- The existing enable_livestatus_tcp tests now see two show calls first. Adjust their `side_effect` lists.
- Replace `test_enable_livestatus_tcp_restarts_when_already_running` with a stop→set→set→start ordering test. Its comment must name the real bug (config set refused on a running site; the old code set and then restarted).
- Add the TLS-specific tests from `<behavior>`, each with a regression comment naming the 2026-09-25 live bug: a fresh 2.4 site defaulted to TLS on, `live-tcp` pointed at `live-tls`, the poller got "Connection reset by peer" and "Malformed columns response", and the dashboard sat empty.

Add the `_livestatus_answers_plaintext` tests and the phase1 container-mode warning test to test_wizard.py. Reuse `_mock_container_mode_omd_calls` plus monkeypatches of `_probe_livestatus_tcp` (True) and `_livestatus_answers_plaintext` (False). Model the test on the existing container-mode phase1 test around line 420-470, including its questionary and bootstrap fakes. Capture output via monkeypatching `checkmk_wizard.wizard.console.print` or with capsys, whichever that file already uses. Import the new helper in the test module's existing import block.

After the tests pass, run `uvx ruff check`. The finding count must not rise above the pre-existing baseline of 7. If ruff errors on the .ruff_cache temp dir, retry with `uvx ruff check --no-cache`.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && uv run pytest tests/test_site.py tests/test_wizard.py -q && uv run pytest -q && (uvx ruff check --no-cache src tests || true)</automated>
  </verify>
  <done>All tests pass, including the new TLS tests. Host mode ends with TCP on and TLS off: it stops the site before `omd config set` and restarts it only if it had been running, even when the set fails. Container mode prints the exact podman exec fix when 6557 is open but gives no plain reply, and it never raises. The ruff finding count is unchanged at 7.</done>
</task>

<task type="auto">
  <name>Task 3: Correct the "automatic" Livestatus TCP claims in README and the Podman doc</name>
  <files>README.md, docs/Podman setup for checkmk, minio, mosquitto, worker.md</files>
  <action>
**README.md**, lines ~79-95 (the "Livestatus-over-TCP already enabled" prerequisite and the network-access bullet):
- State that TCP Livestatus must be enabled AND plain text (LIVESTATUS_TCP_TLS off).
- Say that deploy/compose.yaml handles both: `CMK_LIVESTATUS_TCP=on` plus the `deploy/checkmk-hooks/pre-start/` hook.
- Say that host-native mode turns TCP on and TLS off itself.
- Give the manual command for other setups: `omd stop <site>; omd config <site> set LIVESTATUS_TCP on; omd config <site> set LIVESTATUS_TCP_TLS off; omd start <site>`.
- Describe the symptom in one sentence: "Connection reset by peer", the poller's "Malformed columns response", and an empty dashboard.

**Podman doc section 5:**
- Rewrite the "nothing to do here" paragraph. CMK_LIVESTATUS_TCP=on only turns TCP on. A fresh 2.4 site defaults LIVESTATUS_TCP_TLS=on, and xinetd then sends 6557 to `live-tls`, which plain-LQL clients (poller, wizard) cannot speak.
- Explain that the shipped compose.yaml mounts a pre-start entrypoint hook, which sets TLS off before every site start. It is not a documented env var; it was verified from the image's entrypoint source.
- Add a check command next to the existing LIVESTATUS_TCP one: `podman compose exec checkmk omd config dmc show LIVESTATUS_TCP_TLS` (expect `off`). Also mention `ls -l /omd/sites/dmc/tmp/run/live-tcp`, which should point at `live`, not `live-tls`.
- Add the manual fix to the existing manual block: set LIVESTATUS_TCP_TLS off alongside LIVESTATUS_TCP on in the same stopped window, then `podman restart mqtt-poller`.
- Mention the hook's executable-bit requirement in one sentence, for people who copy the file elsewhere.
- Update the "If you skip this step" paragraph to mention the new Phase 1 TLS warning.

**Podman doc section 8.5, step 2 (line ~559):** say that Livestatus-over-TCP comes up on its own and in plain text (CMK_LIVESTATUS_TCP=on plus the pre-start hook). Add the TLS show check.

**Podman doc section 8.3 bullet (line ~527):** note that the Livestatus reachability check also warns when the port answers only TLS.

Keep edits surgical. Don't rewrite unrelated prose.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && grep -q 'LIVESTATUS_TCP_TLS' README.md && test "$(grep -c 'LIVESTATUS_TCP_TLS' 'docs/Podman setup for checkmk, minio, mosquitto, worker.md')" -ge 3 && grep -q 'checkmk-hooks' 'docs/Podman setup for checkmk, minio, mosquitto, worker.md' && ! grep -q 'With the shipped `compose.yaml` there is nothing to do here' 'docs/Podman setup for checkmk, minio, mosquitto, worker.md'</automated>
  </verify>
  <done>The README and Podman doc sections 5, 8.3 and 8.5 describe TCP plus TLS-off accurately. They name the hook, give the show checks and the manual fix command, and describe the TLS symptom. No doc still claims CMK_LIVESTATUS_TCP alone is sufficient.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| cmk_net → checkmk:6557 | Unauthenticated Livestatus; exposure is limited by network isolation (not published to host/LAN) |
| repo file → checkmk container root | Hook script executes as root inside the checkmk container at every start |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-bzz-01 | Information Disclosure | Livestatus TLS off on 6557 | accept | Port 6557 stays unpublished (no `ports:` entry). Only cmk_net containers reach it, and the plain LQL clients (poller, wizard) need plaintext. The docs keep the "do not publish 6557" guidance. |
| T-bzz-02 | Tampering | pre-start hook runs as root | mitigate | Mounted `:ro`, so the container cannot modify it. The script runs only fixed `omd config` commands on `$CMK_SITE_ID`, and nothing is evaluated from input. |
| T-bzz-03 | Denial of Service | hook failure blocking Checkmk start | mitigate | No `set -e`, and it always exits 0, so a failed hook never prevents `omd start`. |
| T-bzz-04 | Denial of Service | host-mode stop for config set | mitigate | try/finally restarts the site if it had been running, even when `omd config set` fails. |
</threat_model>

<verification>
- `uv run pytest -q` passes (full suite)
- `uvx ruff check` (or `--no-cache`) shows no findings beyond the pre-existing 7
- `git ls-files -s deploy/checkmk-hooks/pre-start/10-livestatus-tcp-plaintext.sh` shows mode 100755
- Live check (operator, optional, after deploy): `podman compose up -d --force-recreate checkmk`, then `podman compose exec checkmk omd config dmc show LIVESTATUS_TCP_TLS` prints `off` and `podman logs checkmk` shows "### Running /docker-entrypoint.d/pre-start/10-livestatus-tcp-plaintext.sh"
</verification>

<success_criteria>
- A compose-deployed checkmk site (blank or existing) serves plain-text Livestatus on 6557 without any manual omd command
- Host-mode wizard ensures TCP on and TLS off; container mode detects the TLS symptom and prints the exact fix without failing
- Docs are accurate about what is automatic and document the symptom and fix
- The SUMMARY lists the unverified items (a)-(c) and any podman confirmation result
</success_criteria>

<output>
Create `.planning/quick/260925-bzz-turn-livestatus-tcp-tls-off-in-compose-a/260925-bzz-SUMMARY.md` when done
</output>
