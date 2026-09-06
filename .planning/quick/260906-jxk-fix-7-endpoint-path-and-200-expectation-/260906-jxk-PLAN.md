---
phase: quick-260906-jxk
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
autonomous: true
requirements: [QUICK-260906-jxk]

must_haves:
  truths:
    - "The §7 Checkmk API check hits GET {CMK_REST_API}/version — the same endpoint this project's own REST client uses successfully at src/checkmk_wizard/api.py:120"
    - "A reader running the §7 command before §8 sees a 401 reported as a PASS (reachability proved), not as a failure to chase"
    - "A status code other than 200 or 401 is still visibly flagged as unexpected — the check does not rubber-stamp every response"
    - "The §7 command still sends no Authorization header and still requires no credentials to run"
    - "The §7 code block remains copy-pasteable: shell quoting inside bash -c \"...\" / python -c '...' is unbroken"
  artifacts:
    - path: "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
      provides: "Corrected §7 Verification & Pipeline Testing endpoint + expectation + one explanatory sentence"
      contains: "/version"
  key_links:
    - from: "docs §7 python one-liner"
      to: "src/checkmk_wizard/api.py:119-120 get_version()"
      via: "same REST path (/version relative to CMK_REST_API)"
      pattern: "CMK_REST_API.*\\+.*\"/version\""
    - from: "docs §7 explanatory prose"
      to: "docs §8 Installing & Running checkmk-wizard"
      via: "explains that §8 is what bootstraps the automation user, so 401 is correct beforehand"
      pattern: "401"
---

<objective>
Fix two confirmed defects in §7 "Verification & Pipeline Testing" of the Podman setup doc: a non-existent Checkmk REST endpoint path, and a success expectation that treats the correct pre-bootstrap 401 as a failure.

Purpose: A reader following the doc in order currently hits a live 404 (wrong path) or, once corrected, a live 401 that the doc gives them no way to interpret — sending them chasing a network problem that does not exist. §7 runs *before* §8, and §8 is what bootstraps the `automation` REST user and its secret; no Bearer-capable credential exists in the system yet. The check must therefore prove *reachability*, not *authorized success*.

Output: One edited markdown file. §7 only.
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.5.5/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.5.5/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@CLAUDE.md

Target file (edit §7 only, lines ~290-311):
@docs/Podman setup for checkmk, minio, mosquitto, worker.md

Ground-truth reference (read-only, do NOT modify):
@src/checkmk_wizard/api.py
</context>

<interfaces>
<!-- Verified facts the executor needs. Use directly — no exploration required. -->

**Correct endpoint (live-verified, already used by this project's own client):**
`src/checkmk_wizard/api.py:119-120`
```python
async def get_version(self) -> dict[str, Any]:
    resp = await self._request("GET", "/version")
```
i.e. `/version` relative to the REST API base URL.

**Auth format Checkmk requires (live-verified), `src/checkmk_wizard/api.py:63-64`:**
```python
"Authorization": f"Bearer {connection.username} {connection.secret}",
```
Only an *automation user's secret* works here. `cmkadmin`'s plain GUI password (`CMK_PASSWORD=cmkadmin` in compose.yaml) is NOT usable for Bearer auth. The automation user is created by checkmk-wizard's GUI-session login flow (`_gui_login`) — which the reader does not run until §8.

**Env var already defined in the doc, line 203 — no trailing slash:**
```
- CMK_REST_API=http://checkmk:5000/dmc/check_mk/api/1.0
```
So `os.environ["CMK_REST_API"] + "/version"` yields a clean URL with exactly one slash. Do not add a slash-stripping helper.

**Current §7 code block (lines 294-310), exact text as it appears in the file:**
The block is `podman compose exec worker bash -c "` ... `"` — a double-quoted shell string — containing `uv run --with paho-mqtt,minio,requests python3 -c '` ... `'` — a single-quoted shell string holding the Python source.

Consequences for any edit inside the Python source:
- Double quotes MUST stay escaped as `\"` (they are inside the outer `bash -c "..."`).
- Single quotes MUST NOT be introduced anywhere in the Python source — one would terminate the `python3 -c '...'` string and break the command.

Line 301-302 as they currently read in the file:
```
cmk = requests.get(os.environ[\"CMK_REST_API\"] + \"/domain-types/version/actions/show/invoke\")
print(f\"Checkmk API: {cmk.status_code}\")
```
</interfaces>

<tasks>

<task type="auto">
  <name>Task 1: Correct §7 endpoint path, accept 401 as a reachability PASS, and explain why</name>
  <files>docs/Podman setup for checkmk, minio, mosquitto, worker.md</files>
  <action>
Make exactly three edits, all confined to §7 "Verification &amp; Pipeline Testing" (lines ~290-311). Use the Edit tool.

**Edit 1 — fix the endpoint (line 301).**
Replace `\"/domain-types/version/actions/show/invoke\"` with `\"/version\"`, leaving the rest of the line byte-identical. The old path returns a live 404 with an `application/problem+json` body; it does not exist. Context7 confirms the general `/domain-types/{type}/actions/{action}/invoke` pattern is real for other domain types (e.g. `activation_run`, via `domain_type_action_href` in `cmk/gui/openapi/restful_objects/constructors.py`) but there is no `version` domain type anywhere in Checkmk's source or docs. `/version` is the correct, live-verified path — it is what `api.py:120` already uses successfully.

**Edit 2 — accept 200 OR 401 as a PASS (line 302).**
Replace the bare `print(f\"Checkmk API: {cmk.status_code}\")` with a conditional print so the command's own output states the verdict. Suggested form (executor has discretion on exact wording, subject to the hard constraints below):

```
print(f\"Checkmk API: {cmk.status_code}\" + (\" (reachable)\" if cmk.status_code in (200, 401) else \" (UNEXPECTED - check network/site status)\"))
```

Hard constraints on whatever wording is chosen:
- MUST NOT introduce a single-quote character anywhere in the Python source (see `<interfaces>` — it would terminate `python3 -c '...'`). This rules out `'reachable'`-style strings and apostrophes in prose like `doesn't`.
- All double quotes inside the Python source MUST remain backslash-escaped as `\"`.
- MUST keep ASCII only in the printed strings — use a plain hyphen `-`, not an em-dash. The block is meant to be copy-pasted into a terminal of unknown locale.
- MUST NOT treat codes other than 200/401 as fine: anything else still prints a visibly distinct "unexpected" marker.
- MUST NOT add an `Authorization` header, credentials, or any auth argument to `requests.get`. Per the locked decision, the check stays credential-free and stays positioned before §8.
- MUST NOT add `raise`/`sys.exit` — the block continues on to the MinIO check below it; keep it a print-only report.
- Leave the MinIO check (lines 304-306) untouched.

**Edit 3 — add ONE explanatory prose sentence.**
Add a single sentence adjacent to the code block (immediately after the existing lead-in "Verify end-to-end communication across the bridge network from inside the worker container:" as a second lead-in line, or immediately after the closing fence — executor's choice, whichever reads better in context). It must convey, in the section's existing plain-prose register that explains *why*:
- A **401** here is the expected, correct result and counts as a pass — §8 has not run yet, and §8 is what bootstraps the `automation` REST user whose secret is the only credential Checkmk's Bearer auth accepts. It is not a failure to chase.
- A **200** means an automation user already exists (e.g. on a re-run).
- Either one proves the worker container reached Checkmk's REST API — as opposed to a connection error, timeout, or proxy-level 404, which would indicate a genuine reachability problem.

Keep it to one sentence (a semicolon-joined sentence is acceptable). Match the surrounding style: no bold headers, no admonition blocks, no bullet list.

**Out of scope — do not touch:** §1.1, §1.2, §5 (all edited by prior quick tasks 260906-iwo / -jm0 / -jqk), and §2, §3, §4, §6, §8, §9. Do not "fix" the `dmc` vs `cmk` site-name inconsistency between line 203 and the §6 table — unrelated, not in scope, mention it in the SUMMARY instead. Do not touch any phase-08 files (deploy/, mosquitto config, compose.yaml) — those live in unmerged worktrees.
  </action>
  <verify>
    <automated>
cd /home/kone/checkmk-wizard &amp;&amp; F="docs/Podman setup for checkmk, minio, mosquitto, worker.md" &amp;&amp; \
test "$(grep -c 'domain-types/version/actions' "$F")" = "0" &amp;&amp; echo "PASS old-path-gone" &amp;&amp; \
grep -q 'CMK_REST_API.*+.*/version' "$F" &amp;&amp; echo "PASS new-path-present" &amp;&amp; \
grep -q '200, 401' "$F" &amp;&amp; echo "PASS 401-accepted" &amp;&amp; \
test "$(grep -c 'Authorization' "$F")" = "0" &amp;&amp; echo "PASS no-auth-header" &amp;&amp; \
test "$(awk '/^podman compose exec worker bash -c/,/^"$/' "$F" | grep -o "'" | wc -l)" = "2" &amp;&amp; echo "PASS shell-quoting-intact" &amp;&amp; \
test "$(git diff -U0 -- "$F" | grep -c '^@@')" -le "2" &amp;&amp; echo "PASS single-region-edit" &amp;&amp; \
test "$(git diff --name-only | wc -l)" = "1" &amp;&amp; echo "PASS only-doc-changed"
    </automated>
    <automated>
cd /home/kone/checkmk-wizard &amp;&amp; git diff -U0 -- "docs/Podman setup for checkmk, minio, mosquitto, worker.md" | grep '^@@' | \
awk '{split($2,a,","); n=-a[1]; if (n &lt; 285 || n &gt; 315) {print "FAIL: hunk at line " n " is outside §7"; exit 1}} END {print "PASS all-hunks-within-section-7"}'
    </automated>
  </verify>
  <done>
- §7 line 301 requests `os.environ["CMK_REST_API"] + "/version"`; the string `domain-types/version/actions` appears nowhere in the file.
- §7's print statement reports 200 and 401 as reachable, and any other status code with a distinct "unexpected" marker.
- Exactly one new prose sentence appears in §7 explaining that 401 is expected pre-§8 and that both 200 and 401 prove reachability.
- No `Authorization` header, credential, or auth argument was added anywhere.
- The `bash -c "..."` block still contains exactly two single-quote characters (the `python3 -c` delimiters), and every double quote inside the Python source is backslash-escaped.
- `git diff --name-only` lists only the doc file; all diff hunks fall between lines 285 and 315.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| worker container → checkmk container REST API | Documentation-only change; the boundary itself is unchanged by this edit |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-jxk-01 | Information Disclosure | §7 verification snippet | mitigate | Snippet stays credential-free by design — the locked decision forbids embedding an automation secret in a doc code block that readers copy-paste and shell-history |
| T-jxk-02 | Tampering | §7 shell/python quoting | mitigate | Automated gate asserts exactly two single-quote chars in the `bash -c` block, preventing a quoting break that would let the snippet execute unintended shell |
| T-jxk-SC | Tampering | npm/pip/cargo installs | accept | No package installs introduced; `--with paho-mqtt,minio,requests` is pre-existing and unchanged |
</threat_model>

<verification>
Run both `<automated>` gate commands from Task 1. Then visually read the rendered §7 (lines 290-315) once to confirm the added sentence reads naturally alongside the existing "Verify end-to-end communication..." lead-in and does not duplicate it.
</verification>

<success_criteria>
- All gate commands in Task 1 print their PASS lines with exit 0.
- §7's check now proves what it claims to prove: worker → Checkmk REST API network reachability, honestly verifiable before any credential exists.
- Reader following the doc top-to-bottom encounters no unexplained 404 or 401 in §7.
- Zero changes outside §7 of the single target file.
</success_criteria>

<output>
Create `.planning/quick/260906-jxk-fix-7-endpoint-path-and-200-expectation-/260906-jxk-SUMMARY.md` when done.
Note in the SUMMARY (do not fix): line 203 defines `CMK_REST_API` with site `dmc` while the §6 endpoints table shows site `cmk` — a pre-existing inconsistency outside this task's scope.
</output>
