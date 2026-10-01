---
phase: quick-261001-tpy
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - deploy/reset-site.sh
  - .planning/quick/261001-tpy-reset-site-sh-confirm-existing-site-ask-/test-reset-site.sh
  - docs/WIZARD-OPERATION.md
  - docs/Podman setup for checkmk, minio, mosquitto, worker.md
  - docs/DEPLOY-NEW-MACHINE.md
  - README.md
autonomous: true
requirements: [QUICK-261001-tpy]

must_haves:
  truths:
    - "reset-site.sh shows the site that actually exists in the checkmk_data volume, plus the CMK_SITE_ID from deploy/.env, and warns when they differ"
    - "Operator must type the EXISTING (volume) site name to confirm; a mismatch aborts with no changes"
    - "After confirmation the operator is asked 'New site name [<existing>]:', Enter keeps the old name, invalid names are re-asked"
    - "Esc or Ctrl+C at either prompt prints 'Aborted.' and exits 1 with no compose down, no volume removal, no .env write"
    - "The new name is written to deploy/.env CMK_SITE_ID BEFORE podman compose up -d, and every later message uses the new name"
    - "--yes keeps the current name non-interactively; --yes --site NAME renames non-interactively (NAME validated)"
    - "If podman compose config -q fails, the script tells the operator to run deploy/init-env.sh and exits before any prompt"
  artifacts:
    - path: "deploy/reset-site.sh"
      provides: "detect/confirm/rename/reset flow with Esc-abortable prompts"
      contains: "--site"
    - path: ".planning/quick/261001-tpy-reset-site-sh-confirm-existing-site-ask-/test-reset-site.sh"
      provides: "podman/curl-stubbed harness exercising abort, keep, rename, --yes, --site, invalid-name paths"
  key_links:
    - from: "deploy/reset-site.sh new-name step"
      to: "deploy/.env CMK_SITE_ID"
      via: "set_val (copied from init-env.sh) called after volume removal, before compose up"
      pattern: "set_val CMK_SITE_ID"
---

<objective>
Make `deploy/reset-site.sh` the single place to start over AND rename the Checkmk site in
container mode: detect the real site in the `checkmk_data` volume, confirm it by typed name,
ask for a new name (default = existing), write it to `deploy/.env`, then down / remove volumes /
up. Esc (and Ctrl+C) at any prompt aborts before anything changes.

Purpose: remove the chicken/egg confusion between `CMK_SITE_ID` in `.env` and the site that
actually lives in the volume.
Output: rewritten `deploy/reset-site.sh`, a stubbed test harness, updated docs.
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@./CLAUDE.md
@.planning/quick/261001-tpy-reset-site-sh-confirm-existing-site-ask-/261001-tpy-CONTEXT.md
@deploy/reset-site.sh
@deploy/init-env.sh

<interfaces>
Facts extracted from the codebase (use directly, no exploration needed):

- deploy/compose.yaml: checkmk service `image: checkmk/check-mk-raw:2.4.0-latest`,
  `container_name: checkmk`, volume `checkmk_data:/omd/sites`. compose.yaml is NOT edited
  (it only carries the `${CMK_SITE_ID:-dmc}` fallback).
- Volume names are `${project}_checkmk_data`, `${project}_mosquitto_data`,
  `${project}_clickhouse_data`; project = `${COMPOSE_PROJECT_NAME:-$(basename "$PWD")}` after
  `cd` into deploy/ (existing logic in reset-site.sh, keep it).
- init-env.sh helpers to copy verbatim (adapt `$env_file` to `.env`):
  `get_val KEY` = `sed -n "s/^KEY=//p" .env | tail -1`;
  `set_val KEY VALUE` = replace `^KEY=` line, else uncomment first `^# *KEY=` line
  (`sed -i "0,/^# *KEY=.*/s||KEY=VALUE|"`), else append. `.env.example` ships `# CMK_SITE_ID=dmc`.
- Site-name rule (init-env.sh and wizard `_SITE_NAME_RE`): `^[A-Za-z][A-Za-z0-9_]{0,15}$`;
  invalid message in init-env.sh: "Invalid: start with a letter; letters, digits, underscores; max 16 characters."
- Current reset-site.sh: header lines 2-16 printed by `--help` via `sed -n '2,16p' "$0"`
  (adjust the range to the new header length). Wait loop curls
  `http://localhost:8080/$site/check_mk/` (expect 302), then
  `podman compose exec checkmk omd config "$site" show LIVESTATUS_TCP_TLS`.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Rewrite reset-site.sh (detect, confirm, rename, Esc-abort) with a stubbed test harness</name>
  <files>deploy/reset-site.sh, .planning/quick/261001-tpy-reset-site-sh-confirm-existing-site-ask-/test-reset-site.sh</files>
  <behavior>
    Harness cases (each runs a COPY of reset-site.sh in a temp dir containing a copied
    `.env` with `CMK_SITE_ID=dmc` and a dummy compose.yaml, with PATH-shim `podman` and `curl`
    that log every invocation to a file):
    - Esc at confirm prompt (stdin `\e`): exit 1, stderr/stdout contains "Aborted.", log has no
      `compose down`, no `volume rm`, no `compose up`; .env byte-identical.
    - Correct confirm then Esc at new-name prompt (stdin `dmc\n\e`): same no-change guarantees.
    - Wrong confirm (stdin `xyz\n`): exit 1, "Aborted.", no changes.
    - EOF on stdin (empty input): treated as abort, exit 1, no changes.
    - Keep name (stdin `dmc\n\n`): exit 0; log order `compose down` < `volume rm` < `compose up`;
      .env still `CMK_SITE_ID=dmc`; curl called with `/dmc/check_mk/`.
    - Rename (stdin `dmc\nnewsite\n`): .env has exactly one active `CMK_SITE_ID=newsite`; curl URL
      and `omd config newsite show` use the new name; the .env write happens after `volume rm`
      and before `compose up` (harness: shim records `grep CMK_SITE_ID .env` at each call).
    - Invalid then valid (stdin `dmc\n1bad\ngood\n`): re-ask message printed, final .env `good`.
    - Backspace editing (stdin `dmc\nnewx\x7fsite\n` style, i.e. "newx", DEL, "site"): .env `newsite`.
    - `.env` with only `# CMK_SITE_ID=dmc` commented and rename to `abc`: line uncommented to `CMK_SITE_ID=abc`.
    - Volume site differs from .env (shim `ls /omd/sites` prints `other`): output warns about the
      mismatch; confirm must be `other` (typing `dmc` aborts); default new name is `other`.
    - `--yes`: no prompts read, name kept (= detected volume site), .env written with it.
    - `--yes --site foo`: .env `foo`, no prompts. `--site 9bad --yes`: exit 2 before any podman
      call other than config/detection.
    - Pre-flight: shim makes `podman compose config -q` fail → exit non-zero, message mentions
      `deploy/init-env.sh`, no prompt shown, no other podman calls.
    - Volume missing (shim `volume exists` returns 1): script says there is nothing to delete,
      still proceeds through confirm/new-name (confirm against .env value) — the operator may
      just want to (re)create under a chosen name.
  </behavior>
  <action>
    Restructure deploy/reset-site.sh per CONTEXT.md, keeping `set -euo pipefail`, why-comments,
    the `cd` into deploy/, the project/volumes logic, the full down/up rule and the "Next:" block.

    1. Args: add `--site NAME` (takes the next argument; switch the for-loop to a
       `while [ $# -gt 0 ]` / `shift` loop) alongside `--with-history`, `--yes`, `-h|--help`.
       Validate NAME against `^[A-Za-z][A-Za-z0-9_]{0,15}$` right after parsing; invalid → message
       to stderr, exit 2. `--site` without `--yes` is allowed: it becomes the default shown in the
       new-name prompt (discretion choice; document it in the header).
    2. Pre-flight (D: order step 1): `podman compose config -q >/dev/null 2>&1` fails → print
       "deploy/.env is missing or incomplete; run deploy/init-env.sh first." to stderr, exit 1.
    3. Detection (D: existing site detection): env_site = get_val CMK_SITE_ID (fallback dmc).
       If `podman volume exists "${project}_checkmk_data"` fails → echo that the volume does not
       exist (nothing to delete) and set existing site = env_site. Otherwise list sites: if
       `podman container inspect -f '{{.State.Running}}' checkmk` prints `true`, use
       `podman exec checkmk ls /omd/sites`; else run a throwaway
       `podman run --rm --pull=never --entrypoint ls -v "${project}_checkmk_data:/omd/sites:ro" <image> /omd/sites`
       where `<image>` is read from compose.yaml's checkmk `image:` line with sed (first line
       matching `image: *checkmk/`), so no new image is pulled. Filter the listing through the
       site-name regex (drops `lost+found` etc.). Detection failure (non-zero or empty) → warn and
       fall back to env_site. Multiple sites → print them all; existing site = env_site if listed,
       else the first. Print "Site in volume: X" and "CMK_SITE_ID in deploy/.env: Y", and a
       WARNING line when they differ (explain the volume's name is what exists now).
    4. Abort plumbing: before the first prompt, `trap 'echo; echo "Aborted." >&2; exit 1' INT`;
       remove it (`trap - INT`) right before `podman compose down` so Ctrl+C later behaves normally.
       Define a `read_line PROMPT VARNAME [DEFAULT]` helper: prints the prompt (to stderr or tty is
       fine; keep it to stdout/stderr, not /dev/tty, so piped tests work), then loops
       `IFS= read -rsn1 ch || abort` (EOF aborts); `ch` empty → Enter (newline) → finish;
       `$'\e'` → drain any escape-sequence tail with `read -rsn5 -t 0.05 _ || true`, then abort;
       `$'\x7f'` or `$'\b'` → drop last char and echo `\b \b` if buffer non-empty; anything else →
       append and echo it. Empty result + DEFAULT → DEFAULT. Assign via `printf -v "$2" '%s' ...`.
       `abort` prints "Aborted." to stderr and exits 1. Nothing is modified before this point.
    5. Confirm (D: confirmation): keep the existing warning text and volume list, but name the
       detected site. Unless `--yes`, `read_line "Type the site name to confirm: " answer`;
       mismatch with the detected existing site → abort.
    6. New name (D: new site name): new_site = `--site` value if given else existing site. Unless
       `--yes`, loop `read_line "New site name [$new_site]: " candidate "$new_site"` and re-ask with
       the init-env.sh invalid message until the regex matches. If new_site != existing, print a
       note that agents must re-register against the new site (already covered by Next: step 1).
    7. Changes (D: order step 3): `podman compose down` → volume removal loop (unchanged) →
       `set_val CMK_SITE_ID "$new_site"` (copied from init-env.sh, with `chmod 600 .env` kept as
       is — do not change perms) → `podman compose up -d` → wait loop. Use `$new_site` in the wait
       URL, the LIVESTATUS_TCP_TLS check and the Next: block (add a line "Site: <new_site>").
    8. Update the header comment: describe detect/confirm/rename, Esc/Ctrl+C abort, new Usage line
       `deploy/reset-site.sh [--with-history] [--yes] [--site NAME]`, and fix the `--help` sed range.

    Then write the harness test-reset-site.sh (bash, `set -euo pipefail`, uses `mktemp -d` under
    `${TMPDIR:-/tmp}`, never touches the real deploy/.env): per case, create temp dir with copy of
    reset-site.sh + compose.yaml + an .env, a `bin/` shim dir prepended to PATH with `podman`
    (logs `$*` plus current CMK_SITE_ID line to `$LOG`; behavior controlled by env vars such as
    STUB_CONFIG_FAIL, STUB_VOLUME_EXISTS, STUB_RUNNING, STUB_SITES; prints `true` for
    container inspect, the sites for `exec checkmk ls` / `run ... ls`, `off` for `omd config`),
    `curl` (logs URL, prints 302), and `sleep` (no-op). Feed input with `printf`. Print PASS/FAIL
    per case and exit non-zero on any failure. Run it until all cases pass.
  </action>
  <verify>
    <automated>bash -n deploy/reset-site.sh && (uvx --from shellcheck-py shellcheck deploy/reset-site.sh .planning/quick/261001-tpy-reset-site-sh-confirm-existing-site-ask-/test-reset-site.sh || echo "shellcheck unavailable/warnings — review") && bash .planning/quick/261001-tpy-reset-site-sh-confirm-existing-site-ask-/test-reset-site.sh && deploy/reset-site.sh --help | grep -q -- --site && git diff --quiet -- deploy/compose.yaml</automated>
  </verify>
  <done>All harness cases PASS; bash -n clean; shellcheck clean (or only justified, disabled-with-comment findings); --help shows --site; deploy/compose.yaml and the real deploy/.env untouched.</done>
</task>

<task type="auto">
  <name>Task 2: Update docs that describe reset-site.sh and site renaming</name>
  <files>docs/WIZARD-OPERATION.md, docs/Podman setup for checkmk, minio, mosquitto, worker.md, docs/DEPLOY-NEW-MACHINE.md, README.md</files>
  <action>
    Per the user's CLAUDE.md docs rule, make the docs match the new script (surgical edits only):
    - docs/WIZARD-OPERATION.md "Starting over with a blank site" (paragraph starting
      "`deploy/reset-site.sh` does all of this"): describe that it detects the site actually in
      the `checkmk_data` volume, shows it next to `CMK_SITE_ID` from `.env` (warns on mismatch),
      asks you to type the existing name, then asks for a new name (Enter keeps it) and writes it
      to `deploy/.env` before `up -d`; Esc or Ctrl+C at either prompt aborts with nothing changed;
      `--yes` keeps the name, `--yes --site NAME` renames non-interactively; it stops early and
      points to `deploy/init-env.sh` when `.env` is not usable.
    - docs/Podman setup ... §3 "Option 2 — rename an existing site" (around line 281-288): add that
      on a disposable stack `deploy/reset-site.sh` now does the wipe-and-rename in one step
      (replacing the "remove the checkmk_data volume (§8.5) and start again with Option 1"
      suggestion with a pointer to the script). §8.5 "Starting over with a blank site": add one
      sentence pointing to `deploy/reset-site.sh` (detect/confirm/rename) above the by-hand commands.
    - docs/DEPLOY-NEW-MACHINE.md line ~72 table row for CMK_SITE_ID ("Renaming it later needs
      `omd mv`") and line ~194: mention `deploy/reset-site.sh` as the way to start over under a new
      name (wipes the site).
    - README.md line ~56: where it says an existing site can be renamed with `omd mv`, add
      "or wiped and recreated under a new name with `deploy/reset-site.sh`".
    Do not rewrite unrelated text.
  </action>
  <verify>
    <automated>grep -q -- '--site' docs/WIZARD-OPERATION.md && grep -qi 'esc' docs/WIZARD-OPERATION.md && grep -q 'reset-site.sh' "docs/Podman setup for checkmk, minio, mosquitto, worker.md" && grep -c 'reset-site.sh' docs/DEPLOY-NEW-MACHINE.md | awk '$1>=2{ok=1} END{exit !ok}' && grep -q 'reset-site.sh' README.md</automated>
  </verify>
  <done>All four docs describe the confirm-existing / new-name / Esc-abort / --site behaviour accurately and consistently with the script.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| operator tty -> reset-site.sh | typed site names flow into sed (set_val), URLs and podman args |
| reset-site.sh -> podman volumes | destructive, irreversible volume removal |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-261001tpy-01 | Tampering | set_val CMK_SITE_ID (sed into .env) | mitigate | name validated against `^[A-Za-z][A-Za-z0-9_]{0,15}$` (prompt and --site) before any sed, so no sed/shell metacharacters reach it |
| T-261001tpy-02 | Denial of Service | accidental data wipe | mitigate | confirmation requires typing the real volume site name; Esc/Ctrl+C/EOF abort before `compose down`; harness asserts no destructive calls on abort paths |
| T-261001tpy-03 | Information Disclosure | .env secrets | accept | script only reads/writes the CMK_SITE_ID line and never prints other values |
</threat_model>

<verification>
- bash -n and shellcheck on deploy/reset-site.sh
- Harness passes all cases (abort paths make zero changes; rename writes .env between volume rm and up)
- Docs grep checks pass
</verification>

<success_criteria>
- Running reset-site.sh shows the real volume site and the .env value, requires typing the real name, asks for a new name defaulting to it, and Esc aborts with no changes
- The chosen name is in deploy/.env before `podman compose up -d`, and all later output uses it
- `--yes [--site NAME]` works non-interactively
- Docs updated in WIZARD-OPERATION.md, the Podman setup doc, DEPLOY-NEW-MACHINE.md, README.md
</success_criteria>

<output>
Create `.planning/quick/261001-tpy-reset-site-sh-confirm-existing-site-ask-/261001-tpy-SUMMARY.md` when done
</output>
