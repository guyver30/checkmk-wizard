---
phase: quick-260906-iwo
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
autonomous: true
requirements: [QUICK-DOC-01]

must_haves:
  truths:
    - "A reader on a bare Linux machine with no podman on PATH can follow §1 top-to-bottom and end up with a working rootless Podman + compose provider before reaching §2"
    - "Both Debian/Ubuntu (apt) and RHEL/Fedora/CentOS (dnf) install paths are covered"
    - "The reader is told how to verify rootless is actually working (podman info) and how to check/repair subuid/subgid ranges"
    - "Every existing §N cross-reference in the doc still points at the section it pointed at before the edit"
    - "No file outside docs/Podman setup for checkmk, minio, mosquitto, worker.md is modified"
  artifacts:
    - path: "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
      provides: "§1.1 Install Podman (apt/dnf + compose provider + rootless verification), §1.2 holding the pre-existing socket/lingering content"
      contains: "### 1.1."
  key_links:
    - from: "docs/Podman setup for checkmk, minio, mosquitto, worker.md §1.1"
      to: "docs/Podman setup for checkmk, minio, mosquitto, worker.md §1.2"
      via: "§1.2 assumes podman is on PATH, which §1.1 now guarantees"
      pattern: "### 1\\.2\\."
    - from: "docs/Podman setup for checkmk, minio, mosquitto, worker.md §1.1"
      to: "§4 Deployment (`podman compose up -d`)"
      via: "compose provider install — `podman compose` is a thin shim that requires docker-compose or podman-compose to be present"
      pattern: "podman-compose"
---

<objective>
Add Podman installation instructions for a fresh Linux machine to `docs/Podman setup for checkmk, minio, mosquitto, worker.md`, in front of the existing prerequisites content that already assumes `podman` is on PATH.

Purpose: §1 currently opens with `systemctl --user enable --now podman.socket` — which fails outright on a machine that has never had Podman installed. The doc's happy path is unusable from a genuinely bare host.
Output: An expanded §1 with two subsections — §1.1 (install Podman + a compose provider, verify rootless) and §1.2 (the existing socket/lingering/DOCKER_HOST content, unchanged in substance).
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.5.5/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.5.5/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@CLAUDE.md

Target file (read in full before editing):
@docs/Podman setup for checkmk, minio, mosquitto, worker.md
</context>

<structural_decision>
**Expand §1 in place. Do NOT insert a new top-level section and do NOT renumber the doc.**

Rationale (already investigated — do not re-litigate):

1. The doc contains 11 internal `§N` cross-references at lines 33, 120, 160, 202, 240, 244, 254, 270, 272, 273, 278 pointing at §2, §3, §5, §8, §8.2 and §8.3. Inserting a new `## 1.` would invalidate all of them.
2. `.planning/phases/08-broker-infrastructure-hardening/08-03-PLAN.md` (unmerged, in-flight, in a separate worktree) pins this doc by section number *and* line range — it names "§2 (directory structure), §3 (config files, lines 47-160) and §6 (endpoints table + default credentials, lines 196-211)". Renumbering would silently break that plan's instructions and its grep-based verification.
3. The doc already establishes `### N.M.` subsections as its convention for exactly this shape of content (see `### 8.1. Get the code onto the host`, `### 8.2.`, `### 8.3.`, `### 8.4.` at lines 242–276).

Net effect: top-level numbering stays `## 1.` … `## 9.` exactly as it is today, and the only lines that change are inside the current §1 block (lines 7–22).
</structural_decision>

<tasks>

<task type="auto">
  <name>Task 1: Expand §1 into §1.1 (install Podman) and §1.2 (rootless socket setup)</name>
  <files>docs/Podman setup for checkmk, minio, mosquitto, worker.md</files>
  <action>
Edit only the block currently spanning lines 7–22 (from `## 1. Prerequisites (Rootless Podman Setup)` down to the closing fence of the existing bash block, exclusive of the trailing `---` on line 24). Leave the `## 1. Prerequisites (Rootless Podman Setup)` heading text itself byte-identical.

Under that heading, insert a one-sentence lead-in stating that §1.1 gets Podman onto a machine that has never had it, and §1.2 makes it usable rootless and persistent — then the two subsections:

**`### 1.1. Install Podman`**

Plain prose framing (matching the doc's existing register: conversational, explains *why*, no bullet-list-only sections), then bash fences. Cover, in this order:

- Debian / Ubuntu, via `apt`. Install `podman` plus `uidmap` (provides `newuidmap`/`newgidmap`, which rootless Podman cannot run without) and `podman-compose`. Note in prose that on Debian 12+/Ubuntu 22.04+ the distro package is recent enough; older releases ship a Podman too old for the `podman compose` subcommand.
- RHEL / Fedora / CentOS Stream, via `dnf`: `sudo dnf install -y podman podman-compose`. Mention in one line that on RHEL/CentOS the `container-tools` package group is the equivalent bundle if you want the full toolchain.
- A short prose note that `podman compose` is only a shim — it delegates to whichever external compose provider it finds (`docker-compose` or `podman-compose`), so one of them must be installed or every `podman compose` command later in this doc fails. This is the same delegation visible in the systemd failure log further down the doc (`/usr/libexec/docker/cli-plugins/docker-compose`), so cross-reference that behaviour in passing rather than re-explaining it.
- Verification fence:
  - `podman --version`
  - `podman info --format '{{.Host.Security.Rootless}}'` — expected output `true`; if it prints `false` you are running as root and the rest of this doc's rootless assumptions do not hold.
  - `podman run --rm docker.io/library/hello-world` as an end-to-end smoke test that image pull + rootless network + storage all work.
- A short **rootless UID/GID ranges** paragraph: the distro package normally allocates these for you, so this is a check, not a step. Show `grep "^$USER:" /etc/subuid /etc/subgid` with a note that you want a line in *both* files (e.g. `youruser:100000:65536`). If either is missing, show the repair: `sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER` followed by `podman system migrate` (state why the second command is needed: it re-maps any containers already created under the old, empty range).

**`### 1.2. Enable the rootless Podman socket`**

Move the existing content here verbatim. Keep the current lead-in sentence ("Enable the Podman systemd user socket and ensure rootless background persistence:") and the existing bash block byte-for-byte — including its `# Enable and start user-level Podman API socket`, `# Keep containers running after logout` and `# Configure Docker Compose provider to use Podman socket` comments and the hardcoded `/run/user/1000/` path in the `DOCKER_HOST` export.

Do **not** "fix" the hardcoded UID `1000` to `$(id -u)`, do not reword the existing comments, and do not touch the trailing blank line inside that fence. That snippet is referenced verbatim elsewhere and correcting it is out of scope for this change.

Style constraints for the new prose: plain declarative sentences and bash fences, the same voice as §5 and §8 (which explain the reasoning behind a step, not just the step). No emoji. No tables. No admonition syntax the doc doesn't already use. Distro commands go in `bash` fences; expected outputs go inline in prose or as `#` comments inside the fence, matching how §7 and the systemd sections already do it.

Touch no other section of this file, and no other file in the repo.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && D="docs/Podman setup for checkmk, minio, mosquitto, worker.md" && grep -qE '^### 1\.1\.' "$D" && grep -qE '^### 1\.2\.' "$D" && grep -q 'apt install' "$D" && grep -q 'dnf install' "$D" && grep -q 'uidmap' "$D" && grep -q 'podman-compose' "$D" && grep -q '/etc/subuid' "$D" && grep -q 'Host.Security.Rootless' "$D" && grep -q 'podman system migrate' "$D" && grep -q 'systemctl --user enable --now podman.socket' "$D" && grep -q 'unix:///run/user/1000/podman/podman.sock' "$D" && test "$(grep -cE '^## [0-9]+\. ' "$D")" = "9" && test "$(grep -oE '^## [0-9]+\. ' "$D" | grep -oE '[0-9]+' | sort -n | tail -1)" = "9" && test "$(grep -cE '^## 1\. Prerequisites \(Rootless Podman Setup\)$' "$D")" = "1" && test -z "$(git status --porcelain -- deploy/ src/ tests/)" && echo DOC_OK</automated>
  </verify>
  <done>
    - `## 1. Prerequisites (Rootless Podman Setup)` heading is unchanged and still the only `## 1.` heading.
    - `### 1.1.` covers apt and dnf install paths, the compose-provider caveat, `podman --version` / `podman info` / `hello-world` verification, and the subuid/subgid check plus repair.
    - `### 1.2.` contains the pre-existing socket/lingering/DOCKER_HOST block with its original commands intact.
    - Top-level headings still run `## 1.` through `## 9.` — exactly 9 of them, max is 9, nothing renumbered.
    - `git status --porcelain` shows no changes under `deploy/`, `src/` or `tests/`.
    - The verify command prints `DOC_OK`.
  </done>
</task>

<task type="auto">
  <name>Task 2: Confirm every pre-existing cross-reference still resolves</name>
  <files>docs/Podman setup for checkmk, minio, mosquitto, worker.md</files>
  <action>
Read-and-assert pass, not a rewrite. Confirm the Task 1 edit did not invalidate any pointer into or out of this doc:

1. Each of the 11 `§N` references still names the section it described before the edit: §8 (directory-structure comment and worker-service comment), §8.3 (the `CMK_PASSWORD` note), §5 (Livestatus row in the endpoints table, the container-mode paragraph, the Livestatus-reachability bullet), §2 (the "clone into app/" instruction), §3 (the `uv`-already-installed note, the `CMK_SITE_ID` bullet, the cmkadmin-password bullet), §8.3/§8.2/§5 (the re-running paragraph). Verify by reading each referenced heading, not by assuming.
2. The two relative markdown links out of this doc — `WIZARD-OPERATION.md` and `../README.md#prerequisites` in the opening paragraph — still resolve on disk.
3. No new `§` reference was introduced by Task 1 that points at a section number that does not exist.

If any reference is now wrong, fix that reference only — do not renumber sections to accommodate it.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && uv run python -c "
import os, re, sys
p = 'docs/Podman setup for checkmk, minio, mosquitto, worker.md'
t = open(p).read()
tops = set(re.findall(r'^## (\d+)\. ', t, re.M))
subs = set(re.findall(r'^### (\d+\.\d+)\. ', t, re.M))
refs = set(re.findall(r'§(\d+(?:\.\d+)?)', t))
bad = [r for r in refs if r not in tops and r not in subs]
links = [l for l in re.findall(r'\]\(([^)#]+)[^)]*\)', t) if not l.startswith('http')]
broken = [l for l in links if not os.path.exists(os.path.normpath(os.path.join('docs', l)))]
if bad or broken:
    sys.exit('dangling section refs: %s | broken links: %s' % (bad, broken))
print('REFS_OK', sorted(tops), sorted(subs))
"</automated>
  </verify>
  <done>
    - Every `§N` / `§N.M` reference in the doc resolves to a heading that exists in the doc.
    - `WIZARD-OPERATION.md` and `../README.md` both resolve on disk from `docs/`.
    - The verify command prints `REFS_OK` and lists top-level sections 1–9 plus subsections including `1.1` and `1.2`.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| doc reader → their own root shell | The doc instructs a human to run privileged commands; bad instructions execute as root on a fresh host |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-QUICK-01 | Tampering | §1.1 install commands | mitigate | Install strictly from first-party distro repositories (`apt install`, `dnf install`). No `curl \| sh`, no third-party PPA/COPR, no `add-apt-repository`, no unpinned upstream tarball. |
| T-QUICK-02 | Elevation of Privilege | §1.1 subuid/subgid repair | mitigate | The `usermod --add-subuids` repair is presented as conditional ("only if the grep shows nothing") with an explicit non-overlapping range, so a reader cannot be led into handing a user a range that collides with another account's. |
| T-QUICK-SC | Tampering | npm/pip/cargo installs | n/a | No package-manager installs of language ecosystem packages occur in this change — it is a documentation-only edit to a single markdown file. Package Legitimacy Gate not applicable. |
</threat_model>

<verification>
Run both task verify commands. Then eyeball the rendered diff:

```bash
cd /home/kone/checkmk-wizard && git diff -- "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
```

The diff should be confined to the region around the original lines 7–22. Any hunk touching §2 or later is a mistake — revert it.
</verification>

<success_criteria>
- A reader with a bare Linux box and no `podman` binary can execute §1.1 then §1.2 and arrive at the state §2 assumes.
- Both apt and dnf paths present; compose-provider requirement called out; rootless verified via `podman info`; subuid/subgid check plus repair documented.
- Doc top-level numbering unchanged (`## 1.` … `## 9.`); all 11 pre-existing `§N` references still valid.
- Exactly one file changed: `docs/Podman setup for checkmk, minio, mosquitto, worker.md`. Nothing under `deploy/`, `src/`, `tests/`, or any mosquitto config — phase 08 work is untouched.
</success_criteria>

<output>
Create `.planning/quick/260906-iwo-update-docs-podman-setup-for-checkmk-min/260906-iwo-SUMMARY.md` when done
</output>
