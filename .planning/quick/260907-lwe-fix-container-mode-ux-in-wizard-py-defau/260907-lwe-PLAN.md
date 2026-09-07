---
phase: quick
plan: 260907-lwe
type: execute
wave: 1
depends_on: []
files_modified:
  - src/checkmk_wizard/wizard.py
  - tests/test_wizard.py
  - deploy/compose.yaml
  - docs/Podman setup for checkmk, minio, mosquitto, worker.md
  - docs/WIZARD-OPERATION.md
autonomous: true
requirements: [QUICK-260907-lwe]

must_haves:
  truths:
    - "In container mode (site.omd_installed() false), the 'Hostname/IP to reach this Checkmk site on' prompt is pre-filled with 'checkmk' (the compose service hostname), not 'localhost'"
    - "In host-native mode (omd installed), that same prompt is still pre-filled with 'localhost' — behavior unchanged"
    - "In container mode, the cmkadmin password prompt is pre-filled with the value of the CMK_PASSWORD env var when it is set, so pressing Enter accepts it"
    - "When CMK_PASSWORD is unset, the cmkadmin password prompt has no default and pressing Enter still takes the existing 'blank = skip and provide an automation secret directly' path"
    - "The cmkadmin prompt remains a masked questionary.password prompt (the pre-filled value is never echoed in cleartext)"
    - "The full existing pytest suite still passes unchanged"
  artifacts:
    - path: "src/checkmk_wizard/wizard.py"
      provides: "Container-mode-aware Checkmk host default + CMK_PASSWORD-prefilled cmkadmin prompt"
      contains: "CMK_PASSWORD"
    - path: "tests/test_wizard.py"
      provides: "Regression tests for both prompt defaults (container mode and host-native mode)"
      contains: "CMK_PASSWORD"
    - path: "deploy/compose.yaml"
      provides: "CMK_PASSWORD on the worker service so the new default actually has a value in the documented stack"
      contains: "CMK_PASSWORD"
  key_links:
    - from: "src/checkmk_wizard/wizard.py phase1_site_bringup()"
      to: "questionary.text host prompt"
      via: "container-mode-dependent default value"
      pattern: "_default_checkmk_host"
    - from: "src/checkmk_wizard/wizard.py phase1_site_bringup()"
      to: "questionary.password cmkadmin prompt"
      via: "os.environ.get(\"CMK_PASSWORD\", \"\") as default"
      pattern: "os\\.environ\\.get\\(\"CMK_PASSWORD\""
    - from: "deploy/compose.yaml worker service"
      to: "wizard.py CMK_PASSWORD read"
      via: "environment variable"
      pattern: "CMK_PASSWORD"
---

<objective>
Fix two container-mode UX papercuts in Phase 1 of the wizard, both found during live verification of Phase 9 (poller-core) on a real deployment host:

1. The "Hostname/IP to reach this Checkmk site on" prompt suggests `localhost`, which cannot reach the Checkmk container from inside the sibling `worker` container on `cmk_net` — only the service hostname `checkmk` works there. Default to `checkmk` in the container-mode branch only.
2. The cmkadmin password prompt makes the operator retype a password the environment already knows. Pre-fill it from `CMK_PASSWORD` when set, mirroring how `CMK_SITE_ID` already pre-fills the site-name prompt at `wizard.py:290`.

Purpose: today every container-mode run requires the operator to know two undocumented-at-the-prompt facts (the service hostname, and the compose password) and to type both by hand. Both values are already available where the wizard runs; the defaults just were never wired up.

Output: a small, surgical change to `phase1_site_bringup()` plus regression tests, the `CMK_PASSWORD` env var added to the `worker` service in `deploy/compose.yaml` (without it, the new default has nothing to read), and the two operator-facing docs that describe these exact prompts brought back in sync.
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.5.5/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.5.5/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@CLAUDE.md

Source of the change:
@src/checkmk_wizard/wizard.py
@tests/test_wizard.py
@deploy/compose.yaml

<interfaces>
<!-- Extracted from the codebase. Use directly — no exploration needed. -->

`src/checkmk_wizard/wizard.py`, the container-mode branch of `phase1_site_bringup()`:

- Line 274: `container_mode = not site.omd_installed()`
- Lines 287-291: site-name prompt, already env-prefilled — this is the pattern to copy:
  `site_name = await _prompt_new_site_name(set(), prompt="Site name to connect to (already created by the Checkmk container):", default=os.environ.get("CMK_SITE_ID", ""))`
- Lines 357-366: the host prompt loop — `raw_host = await questionary.text("Hostname/IP to reach this Checkmk site on (as seen by agents/browser):", default="localhost").ask_async()`, validated with `_valid_checkmk_host(raw_host)` and re-prompted on failure.
- Lines 387-390: the cmkadmin prompt — `cmkadmin_password = await questionary.password("cmkadmin password (set when the Checkmk container was created — leave blank to skip and provide an automation secret directly instead):").ask_async()`, followed by `if cmkadmin_password:` gating the `bootstrap_automation_user()` call.
- `os` is already imported (line 10). Existing module-level constant style: `_UPPER_SNAKE` private names near the top of the file (`_DELETE_SITE`, `_SITE_NAME_RE`, `_PASSWORD_MIN_LENGTH`), each with a comment stating *why*.
- Existing small predicate/helper style to match: `_valid_checkmk_host(value: str) -> bool` (line 88), `_probe_livestatus_tcp(host, ...)` (line ~250).

`questionary.password(message, default="", validate=None, qmark=..., style=None, **kwargs)` — verified from the installed package (`.venv/.../questionary/prompts/password.py:10-17`): it accepts `default` and returns it when the user just hits Enter, while still masking input.

`tests/test_wizard.py` harness already available:
- `_mock_container_mode_omd_calls(monkeypatch)` (line 138) — stubs `site.omd_installed()` to False, makes the Livestatus probe fail harmlessly, and asserts `create_site`/`start_site`/`remove_site`/`list_sites` are never called.
- Existing container-mode tests drive prompts with `answers = iter([...])` + `monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)` (lines 173-178). Note this stub bypasses `default=` entirely, so **existing tests are unaffected by this change** — new tests must capture the `default` kwarg at the `questionary.text`/`questionary.password` call site instead, using the wrapper pattern from `test_prompt_new_site_name_uses_custom_prompt_text` (lines 96-113).

`deploy/compose.yaml`:
- `checkmk` service: `hostname: checkmk`, `environment: CMK_SITE_ID=dmc`, `CMK_PASSWORD=cmkadmin` (lines 7-10).
- `worker` service environment (lines 82-94) has `CMK_SITE_ID=dmc` with a comment explaining it mirrors the checkmk service's value for the wizard's site-name prefill — but has **no** `CMK_PASSWORD`.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Wire container-mode defaults into the Phase 1 host and cmkadmin prompts</name>
  <files>src/checkmk_wizard/wizard.py, tests/test_wizard.py</files>
  <behavior>
    - `_default_checkmk_host(container_mode=True)` returns `"checkmk"`.
    - `_default_checkmk_host(container_mode=False)` returns `"localhost"`.
    - Running `phase1_site_bringup()` in container mode with `CMK_PASSWORD=compose-pw` set passes `default="compose-pw"` to `questionary.password` for the cmkadmin prompt.
    - Running `phase1_site_bringup()` in container mode with `CMK_PASSWORD` unset passes `default=""` (or omits it), and answering blank still takes the existing "skip bootstrap, fall back to `site.get_site_credentials`" path.
    - Running `phase1_site_bringup()` in container mode passes `default="checkmk"` to the `questionary.text` call whose message starts with "Hostname/IP to reach this Checkmk site on".
  </behavior>
  <action>
Add a module-level constant near the other private constants at the top of `wizard.py`, following the file's convention of a comment that records *why* and cites the source of truth:

`_CONTAINER_MODE_CHECKMK_HOST` = `"checkmk"`, commented as: the `checkmk` service's compose-level `hostname:` in `deploy/compose.yaml`, which is the only name that resolves to the Checkmk container from a sibling container on the `cmk_net` bridge — `localhost` there is the wizard's own container, not Checkmk.

Add a tiny helper beside `_valid_checkmk_host`:

`def _default_checkmk_host(container_mode: bool) -> str:` returning `_CONTAINER_MODE_CHECKMK_HOST` when `container_mode` else `"localhost"`. It exists as a named function rather than an inline ternary so both branches are unit-testable without driving a full host-native Phase 1 run (there is no host-native `phase1_site_bringup` test today, and adding one would require stubbing `omd` site creation end to end).

In `phase1_site_bringup()`:
- Change the host prompt (currently `default="localhost"`) to `default=_default_checkmk_host(container_mode)`. Do not touch the surrounding validation loop or the `_valid_checkmk_host` re-prompt behavior. Host-native mode must keep suggesting `localhost` exactly as today.
- Change the cmkadmin prompt to pass `default=os.environ.get("CMK_PASSWORD", "")`, mirroring line 290's `CMK_SITE_ID` read exactly (inline `os.environ.get`, no new config layer, no new helper). Keep it `questionary.password` so the value stays masked. Keep the `if cmkadmin_password:` gate and the blank-means-skip fallback untouched — with `CMK_PASSWORD` unset the default is `""` and Enter still skips.
- Update that prompt's message so the operator understands the pre-fill: when `CMK_PASSWORD` is set, say the default came from the `CMK_PASSWORD` env var; keep the existing "leave blank to skip and provide an automation secret directly instead" wording for the unset case. A short conditional suffix on the message string is enough — do not restructure the prompt.
- Add a brief comment at the cmkadmin prompt recording why the env default is safe/useful here (same env var the `checkmk` container's entrypoint uses; the wizard already never persists this password).

Do not introduce a new env var for the host default, do not add CLI flags, and do not change anything outside the container-mode branch.

Then add regression tests to `tests/test_wizard.py`, next to the existing container-mode tests:
- Two direct unit tests for `_default_checkmk_host` (both branches) — import it alongside the other underscore-prefixed names already imported at the top of the test file.
- One container-mode `phase1_site_bringup()` test with `monkeypatch.setenv("CMK_PASSWORD", "compose-pw")` that wraps `questionary.password` (and `questionary.text`) to record `(message, kwargs.get("default"))` pairs, still stubs `questionary.Question.ask_async` with an `answers` iterator, reuses `_mock_container_mode_omd_calls`, and asserts the recorded default for the cmkadmin prompt is `"compose-pw"` and for the host prompt is `"checkmk"`. Answer the cmkadmin prompt with `""` and stub `site.get_site_credentials` the same way `test_phase1_container_mode_skips_omd_and_connects_over_rest` does so the run completes without hitting bootstrap.
- One container-mode test with `monkeypatch.delenv("CMK_PASSWORD", raising=False)` asserting the recorded cmkadmin default is `""` (hermetic against a developer machine that happens to export `CMK_PASSWORD`) and that the blank-password skip path still returns the locally-read `automation` secret.
- Give each new test a comment naming the real bug it guards against (per this repo's regression-test comment convention), i.e. "`localhost` doesn't reach the checkmk container from the worker container".
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && uv run pytest tests/test_wizard.py -q && uv run pytest -q</automated>
  </verify>
  <done>`_default_checkmk_host` returns "checkmk"/"localhost" per mode; container-mode Phase 1 pre-fills the host prompt with "checkmk" and the masked cmkadmin prompt with `$CMK_PASSWORD` when set; blank-means-skip still works when unset; new tests plus the entire pre-existing suite pass.</done>
</task>

<task type="auto">
  <name>Task 2: Give the worker service CMK_PASSWORD and resync the operator docs</name>
  <files>deploy/compose.yaml, docs/Podman setup for checkmk, minio, mosquitto, worker.md, docs/WIZARD-OPERATION.md</files>
  <action>
`deploy/compose.yaml` — the `worker` service (where `checkmk-wizard` actually runs) has `CMK_SITE_ID` but no `CMK_PASSWORD`, so Task 1's new default would read nothing in the documented stack. Add `CMK_PASSWORD=cmkadmin` to the `worker` service's `environment:` block, immediately after `CMK_SITE_ID`, with a comment in the same voice as the existing `CMK_SITE_ID` comment (lines 85-88): same name/value as the `checkmk` service's own `CMK_PASSWORD` above; checkmk-wizard reads it to pre-fill its cmkadmin-password prompt in container mode. Keep the value in sync with the `checkmk` service's value; change nothing else in the file.

`docs/Podman setup for checkmk, minio, mosquitto, worker.md` §8.3 — two bullets are now stale:
- The "Checkmk host/IP prompt" bullet currently says the default suggestion is `localhost` and won't resolve from the worker container. Rewrite it: the prompt now pre-fills `checkmk` in container mode, so just press Enter (type a different host only if the Checkmk service is reachable under another name).
- The "cmkadmin password prompt" bullet currently says to type whatever `CMK_PASSWORD` is. Rewrite it: the prompt is now pre-filled from the worker container's own `CMK_PASSWORD` (§3), so pressing Enter accepts it; keep the existing explanation that the wizard uses it once over REST and never stores it, and keep the "clear it and leave blank to paste an automation secret directly" alternative.
Also check §3/the worker-service listing in that doc for an environment-variable table or code block that enumerates the worker's env vars — if one exists, add `CMK_PASSWORD` there too so it matches the edited compose file.

`docs/WIZARD-OPERATION.md` — update the two places that state the old behavior:
- The container-mode bullet around lines 47-55 (which documents the `CMK_SITE_ID` pre-fill) — add the parallel `CMK_PASSWORD` pre-fill of the cmkadmin prompt, and the container-mode `checkmk` host default, in the same descriptive style with the `os.environ.get("CMK_PASSWORD", "")` reference.
- Step 3 around line 229 ("Prompts for **Checkmk host** ... defaults to `localhost`") — state that the default is `localhost` in host-native mode and `checkmk` in container mode, naming `_default_checkmk_host()`.
Leave the Phase 5 `_resolve_agent_registration_server()` discussion of `localhost` (around lines 670-700) alone — that is unrelated agent-registration logic and is unchanged by this work.

Do not update line numbers cited elsewhere in these docs beyond the passages you edit; do not restructure or reformat surrounding sections.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && grep -A6 'CMK_SITE_ID=dmc' deploy/compose.yaml | grep -q 'CMK_PASSWORD' && grep -v '^#' "docs/Podman setup for checkmk, minio, mosquitto, worker.md" | grep -c 'the default "localhost" suggestion' | grep -qx 0 && uv run pytest -q</automated>
  </verify>
  <done>The `worker` service in deploy/compose.yaml sets `CMK_PASSWORD` with an explanatory comment; the Podman setup §8.3 host and cmkadmin bullets and the two WIZARD-OPERATION.md passages describe the new pre-filled defaults; the test suite still passes.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| worker container env → wizard process | `CMK_PASSWORD` / `CMK_SITE_ID` are read from the process environment and used as prompt defaults |
| wizard → Checkmk REST API | the cmkadmin password is sent once to bootstrap the `automation` user |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-quick-01 | Information disclosure | cmkadmin prompt pre-fill | mitigate | Keep `questionary.password` (masked) — never switch to `questionary.text`; the pre-filled default is rendered as `*` and is never echoed, logged, or written to the config snapshot |
| T-quick-02 | Information disclosure | `CMK_PASSWORD` in `deploy/compose.yaml` | accept | The value (`cmkadmin`) is already a documented disposable default in this repo, sitting next to `CMK_PASSWORD` on the `checkmk` service and alongside other default credentials (`minioadmin`, `poller`); rotating it is already covered by the existing docs |
| T-quick-03 | Spoofing | container-mode default host `checkmk` | accept | Resolution is scoped to the private `cmk_net` bridge; the value remains operator-editable at the prompt and is still validated by `_valid_checkmk_host` |
| T-quick-SC | Tampering | npm/pip/cargo installs | mitigate | No new dependencies are added by this plan — no install step, so no package-legitimacy gate applies |
</threat_model>

<verification>
1. `uv run pytest -q` — full suite green, including the four new tests and all pre-existing container-mode Phase 1 tests.
2. `grep -n 'CMK_PASSWORD' src/checkmk_wizard/wizard.py deploy/compose.yaml` — the env read exists in the wizard and the var is set on the `worker` service.
3. `grep -n '_default_checkmk_host' src/checkmk_wizard/wizard.py tests/test_wizard.py` — helper defined, used at the host prompt, and covered by tests for both branches.
4. Diff review: no changes outside the container-mode branch of `phase1_site_bringup()`, the new constant/helper, the new tests, the worker env block, and the named doc passages.
</verification>

<success_criteria>
- Container-mode Phase 1 suggests `checkmk` for the Checkmk host and `$CMK_PASSWORD` (masked) for cmkadmin; both are accepted by pressing Enter.
- Host-native Phase 1 still suggests `localhost`; blank-cmkadmin still skips to the manual automation-secret path.
- No new dependencies, env vars beyond `CMK_PASSWORD`, or CLI flags introduced.
- Full pytest suite passes; docs and `deploy/compose.yaml` match the shipped behavior.
</success_criteria>

<output>
Create `.planning/quick/260907-lwe-fix-container-mode-ux-in-wizard-py-defau/260907-lwe-SUMMARY.md` when done
</output>
