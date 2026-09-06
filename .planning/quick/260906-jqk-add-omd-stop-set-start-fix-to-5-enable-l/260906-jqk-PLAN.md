---
phase: quick-260906-jqk
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
autonomous: true
requirements: [QUICK-260906-JQK]

must_haves:
  truths:
    - "A reader following §5 verbatim on a freshly-started site no longer hits 'Cannot change config variables while site is running.'"
    - "§5 explains *why* the site is stopped first (omd refuses config changes on a running site) rather than just restarted afterward."
    - "§5 reassures the reader that stopping the site to flip this toggle loses no data."
    - "No section other than §5 is modified."
  artifacts:
    - path: "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
      provides: "§5 corrected stop/set/start command sequence plus rationale prose"
      contains: "omd stop dmc"
  key_links:
    - from: "§5 bash fence"
      to: "§5 rationale prose"
      via: "prose explains the stop step that the fence performs"
      pattern: "omd stop dmc"
---

<objective>
Fix §5 "Enable Livestatus-over-TCP (required for checkmk-wizard)" in
`docs/Podman setup for checkmk, minio, mosquitto, worker.md` so its commands actually
work on a freshly-started site.

Purpose: Confirmed on a real deployment host — §5's current two-command sequence
(`omd config dmc set LIVESTATUS_TCP on` then `omd restart dmc`) fails on the first
command with `Cannot change config variables while site is running.`, because `omd config
... set` refuses to change config variables on a running site, and §4's `podman compose up
-d` leaves the site running by the time the reader reaches §5. Every reader following the
doc in order hits this.

Output: §5's bash fence replaced with the confirmed-working stop/set/start sequence, plus
brief rationale prose in the section's existing register.
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.5.5/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.5.5/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@docs/Podman setup for checkmk, minio, mosquitto, worker.md

<current_state>
§5 spans lines 250-266 of the doc. The parts that change:

Line 254 (lead-in prose, unchanged):
  "Run this once, right after the site first comes up (a fresh `podman compose up`, or any
   time you delete/recreate the site inside the `checkmk` container):"

Lines 256-259 (the bash fence to REPLACE):
  podman compose exec checkmk omd config dmc set LIVESTATUS_TCP on
  podman compose exec checkmk omd restart dmc

Line 263 (parenthetical aside) currently ends with the phrase
"...so the `omd config`/`omd restart` steps above are the confirmed way." — the
`omd restart` half of that reference becomes stale once the fence changes, so this
one phrase must be updated too. It is inside §5, so it is in scope.

Sections that must NOT be touched: §1.1 and §1.2 (already edited by prior quick tasks
260906-iwo and 260906-jm0), and §2, §3, §4, §6, §7, §8, §9.
</current_state>

<doc_register>
§5 already explains *why* things are the way they are, not just *what* to type — e.g. line
261's clause about Livestatus's wire protocol having no authentication of its own and
relying entirely on network-level isolation. Match that register: explanatory prose in
complete sentences, inline backticks for identifiers, em dashes for asides. Do not add a
warning callout, a bolded "NOTE:", or a bulleted list — §5 has none of those.
</doc_register>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Replace §5's command sequence with stop/set/start and add rationale prose</name>
  <files>docs/Podman setup for checkmk, minio, mosquitto, worker.md</files>
  <action>
Edit §5 only, in three surgical Edit-tool operations against
`docs/Podman setup for checkmk, minio, mosquitto, worker.md`.

1. Replace the two-line bash fence body (currently `podman compose exec checkmk omd config
dmc set LIVESTATUS_TCP on` followed by `podman compose exec checkmk omd restart dmc`) with
the three-command sequence confirmed working on the real host, in this exact order:
`podman compose exec checkmk omd stop dmc`, then `podman compose exec checkmk omd config
dmc set LIVESTATUS_TCP on`, then `podman compose exec checkmk omd start dmc`. Keep the
bash fence markers and the surrounding blank lines exactly as they are.

2. Add ONE short prose paragraph immediately after the fence (before the existing "This
binds Livestatus on port **6557**..." paragraph on line 261) covering two points in the
section's existing explanatory register:
   - `omd config ... set` refuses to change config variables while the site is running
     (it errors with `Cannot change config variables while site is running.`), which is why
     the site is stopped first and then *started* — not left running and restarted
     afterward. A site freshly brought up by §4's `podman compose up -d` is already running
     when the reader arrives here, so the stop is always needed, not situational.
   - Stopping the site for this loses nothing: flipping `LIVESTATUS_TCP` is a config
     change, not a code change or a data wipe — the site's monitoring data, hosts, and
     history all live in the `checkmk_data` volume and survive the stop/start untouched.
   Keep it to roughly 2-4 sentences total. Prose only — no bullets, no bold callout header.

3. In the existing parenthetical aside (line 263), update the stale phrase "so the `omd
config`/`omd restart` steps above are the confirmed way" so it names the new sequence
instead — e.g. "so the `omd stop`/`omd config`/`omd start` steps above are the confirmed
way". Change nothing else in that sentence.

Do NOT touch §1.1, §1.2, §2, §3, §4, §6, §7, §8, or §9. Do NOT touch any phase-08 files
(deploy/, mosquitto config, compose.yaml) — those live in unmerged worktrees and are
unrelated. §6's table row referencing §5 and §8.4's "Livestatus TCP (§5) only need doing
once" sentence stay as-is; neither names the specific commands, so neither goes stale.
  </action>
  <verify>
    <automated>
F="docs/Podman setup for checkmk, minio, mosquitto, worker.md"
test "$(grep -c 'omd stop dmc' "$F")" -eq 1 &&
test "$(grep -c 'omd config dmc set LIVESTATUS_TCP on' "$F")" -eq 1 &&
test "$(grep -c 'omd start dmc' "$F")" -eq 1 &&
test "$(grep -c 'omd restart dmc' "$F")" -eq 0 &&
test "$(grep -c 'Cannot change config variables while site is running' "$F")" -eq 1 &&
git diff --name-only -- "$F" | grep -q 'Podman setup' &&
echo PASS
    </automated>
    <automated>
# Confine the diff to §5: every hunk's old-side start line must fall in the §5 band.
# Portable awk (no gawk-only 3-arg match): hunk header field 2 looks like "-256,4".
git diff -U0 -- "docs/Podman setup for checkmk, minio, mosquitto, worker.md" \
  | grep '^@@' \
  | awk '{ split($2, a, ","); n = substr(a[1], 2) + 0;
           if (n < 240 || n > 275) { print "OUT OF SCOPE HUNK: " $0; bad = 1 } }
         END { exit bad ? 1 : 0 }' \
  && echo "PASS: diff confined to section 5"
    </automated>
  </verify>
  <done>
§5's fence reads `omd stop dmc` / `omd config dmc set LIVESTATUS_TCP on` / `omd start dmc`
in that order; `omd restart dmc` appears nowhere in the file; a 2-4 sentence paragraph
after the fence explains the running-site config refusal and the no-data-loss
reassurance; the line-263 aside names the new command trio; `git diff` shows changes
only within §5 of that one file.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| none | Documentation-only edit. No code, no package installs, no runtime surface. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-jqk-01 | Information Disclosure | §5 doc prose | accept | The doc already documents why Livestatus stays unpublished and relies on `cmk_net` isolation; this edit changes only the enable sequence and does not add a `ports:` publication or weaken that guidance. |
| T-jqk-SC | Tampering | package installs | n/a | No npm/pip/cargo installs in this plan. |
</threat_model>

<verification>
Re-read §5 after editing and confirm the section reads coherently top to bottom: lead-in
sentence -> stop/set/start fence -> new rationale paragraph -> existing port-6557
paragraph -> updated parenthetical aside -> existing "if you skip this step" paragraph.
</verification>

<success_criteria>
- §5's bash fence contains exactly the three commands, in stop/set/start order.
- `omd restart dmc` no longer appears anywhere in the file.
- Rationale prose states both the running-site config refusal and the no-data-loss point.
- The line-263 aside no longer references `omd restart`.
- `git diff` touches only that one file, and only within §5.
</success_criteria>

<output>
Create `.planning/quick/260906-jqk-add-omd-stop-set-start-fix-to-5-enable-l/260906-jqk-SUMMARY.md` when done
</output>
