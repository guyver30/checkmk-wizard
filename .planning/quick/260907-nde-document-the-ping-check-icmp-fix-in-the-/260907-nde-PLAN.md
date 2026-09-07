---
phase: quick-260907-nde
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
autonomous: true
requirements: [DOC-PING-01]

must_haves:
  truths:
    - "An operator reading the Podman setup doc learns that Checkmk's PING/check_icmp service needs two independent fixes under rootless Podman, and that only one of them is already shipped in the repo."
    - "The operator can copy/paste the host-level `sysctl` commands (immediate + persistent) that are the only part they must act on themselves."
    - "The operator can copy/paste a container-recreate sequence that actually works with podman-compose 1.0.6 and a dependent container, framed as the general procedure for picking up any deploy/compose.yaml change."
    - "The operator can recognise both failure signatures (RC 126 exec error; silent 100% packet loss) and map each to the fix that resolves it."
    - "No existing section number or cross-reference in the doc changes."
  artifacts:
    - path: "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
      provides: "New section 5.1 documenting the PING/check_icmp CAP_NET_RAW + net.ipv4.ping_group_range fix"
      contains: "ping_group_range"
  key_links:
    - from: "docs/Podman setup for checkmk, minio, mosquitto, worker.md §5.1"
      to: "deploy/compose.yaml checkmk service cap_add"
      via: "prose reference stating cap_add: [NET_RAW] is already committed"
      pattern: "NET_RAW"
---

<objective>
Document the two-part PING/`check_icmp` fix (container `CAP_NET_RAW` + host `net.ipv4.ping_group_range` sysctl) in the operator-facing Podman setup doc.

Purpose: `deploy/compose.yaml` already carries the `cap_add: [NET_RAW]` half of the fix, but the host sysctl half cannot live in any repo file — it is a property of the Podman host. Without it, every Checkmk PING service silently reports 100% packet loss with no error anywhere. The doc currently has zero mention of PING or ICMP, so a fresh deployment reproduces the bug with no path to a fix.

Output: One new section in `docs/Podman setup for checkmk, minio, mosquitto, worker.md`. Docs-only — no source code, no `deploy/compose.yaml` change, no tests.
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.5.5/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.5.5/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@docs/Podman setup for checkmk, minio, mosquitto, worker.md
@deploy/compose.yaml

**Placement decision (already made — do not re-derive):**

The doc's current top-level structure is: §1 Prerequisites (with `### 1.1`, `### 1.2`), §2 Directory Structure, §3 Configuration Files, §4 Deployment, §5 Enable Livestatus-over-TCP, §6 Endpoints & Network Access, §7 Verification & Pipeline Testing, §8 Installing & Running checkmk-wizard (with `### 8.1`–`### 8.4`), §9 Packaging the Worker as an Image, followed by unnumbered `### Step 1..4` systemd-boot blocks.

The new content belongs immediately after §5 — §5 is the doc's only other "one-time required post-§4 config step for a specific feature to work", and is the explicit style template.

**Insert it as a new `## 5.1.` section between the end of §5 (the "If you skip this step..." paragraph, currently line 190) and the `---` + `## 6. Endpoints & Network Access` that follows.** Do NOT renumber §6–§9. Renumbering would break seven inline `§6`/`§8.1`/`§8.2`/`§8.3` cross-references inside the doc plus `§2`/`§3`/`§4`/`§8.1` references in `deploy/compose.yaml`'s own comments — all of which are unrelated sections this task must not touch. `##`-level dotted numbering is a deliberate signal that this is a peer of §5 inserted without renumbering; the doc already uses dotted numbers (1.1, 8.1) so the reference form `§5.1` reads naturally.

**Style template — §5, lines 172–190.** Match it: a one-line "what this is and why it isn't on by default" opener, a "run this once, right after ..." framing, fenced `bash` blocks with the exact commands, prose paragraphs explaining *why* each command is shaped the way it is, and a closing "If you skip this step, here is exactly what you'll see" paragraph naming the literal error string. Prose voice is operator-facing and explanatory — never a debugging narrative, never a chronology of how it was discovered.

**Already-shipped half (do not ask the operator to add it):** `deploy/compose.yaml` lines 8–20 — the `checkmk` service has `cap_add: [NET_RAW]` with a dated post-mortem comment. §5.1 references it as already committed.
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add §5.1 "Enable ICMP/PING checks" to the Podman setup doc</name>
  <files>docs/Podman setup for checkmk, minio, mosquitto, worker.md</files>
  <action>
Insert one new `## 5.1. Enable ICMP/PING checks (required for Checkmk's PING service)` section between the last paragraph of §5 ("If you skip this step, checkmk-wizard still runs fine through Phase 6 ...") and the `---` separator preceding `## 6. Endpoints & Network Access`. Preserve the doc's existing `---`-between-sections rhythm: end the new section with its own `---` so both §5 and §5.1 remain separated from §6. Change nothing else in the file — no renumbering, no edits to §5's text, no new cross-references added to other sections.

Write the section in §5's voice, covering these five things in this order:

1. **Why PING needs anything at all.** Checkmk's PING service runs the `check_icmp` plugin, which needs a raw ICMP socket. Under rootless Podman that requires two unrelated things to be true at once — a container capability and a host kernel setting — and each one fails with a different, misleading symptom. State plainly that both are required together and that fixing only one leaves PING broken.

2. **The container capability half (already done — informational only).** `check_icmp` ships with the file capability `cap_net_raw=ep`, but rootless Podman's default container capability set excludes `CAP_NET_RAW`, so the kernel refuses to grant it at exec time. `deploy/compose.yaml` already adds `cap_add: [NET_RAW]` to the `checkmk` service — the operator does not need to add it. Name the symptom this fixes: Checkmk reports `Return code of 126 is out of bounds - plugin may not be executable` on the PING service of every host. Add the disambiguation an operator needs: this is an exec-level error, not a reachability failure — a genuine network problem surfaces as a normal `check_icmp` CRIT such as "100% packet loss", so RC 126 is never a NAT/VMware-networking symptom even though it superficially looks like one.

3. **Picking the new capability up on an already-running stack.** Frame this as the general procedure for any `deploy/compose.yaml` change that a container must be recreated (not merely restarted) to pick up — capabilities, mounts, ports — not as a PING-specific one-off. State the trap: `podman-compose` 1.0.6 has no `rm` subcommand, and its recreate-on-`up` logic can silently fall back to restarting the *old* container in place when another container is registered as a dependent (here, `mqtt-poller` depends on `checkmk`), so `podman compose up -d` alone appears to succeed while changing nothing. The working order is: stop and remove the dependent container(s) first, then the target container, then bring each back up in turn. Give the verified sequence in a `bash` block:

    podman stop mqtt-poller && podman rm mqtt-poller
    podman stop checkmk && podman rm checkmk
    podman compose up -d checkmk
    podman compose up -d poller

    Reassure that removing these containers loses no data — Checkmk's site lives in the `checkmk_data` volume and the poller is stateless. Note this step is only needed on an already-running stack; a first-ever `podman compose up -d` from §4 creates the container with the capability already applied.

4. **The host sysctl half (the operator's actual work).** Rootless Podman's netavark/pasta networking relays container ICMP through the host's unprivileged "ping socket" mechanism rather than a true host-level raw socket, and that mechanism is gated by the `net.ipv4.ping_group_range` sysctl. Its default value `1 0` is an empty range — it permits no group at all to open a ping socket — so all relayed ICMP is dropped silently, with no error logged on either the container or the host side. Mention `podman info --format '{{.Host.NetworkBackend}}'` and `sysctl net.ipv4.ping_group_range` as the two commands that confirm you are in this situation (`netavark` and `1  0` respectively). Then give the fix as two `bash` blocks or one block with both — immediate, and persistent across reboots:

    sudo sysctl -w net.ipv4.ping_group_range="0 2147483647"
    echo 'net.ipv4.ping_group_range = 0 2147483647' | sudo tee /etc/sysctl.d/99-podman-ping.conf

    Say explicitly that this is a host-level setting with no representation in `deploy/compose.yaml` or any other repo file — it is a property of the Podman host, which is why it is the one part of this fix a fresh deployment must perform by hand. Note the `sysctl -w` takes effect immediately with no container restart needed, while the `/etc/sysctl.d/` file is what survives a reboot; both are wanted.

5. **Confirming it works, and what a skip looks like.** Give the verification command and its expected output, e.g. `podman compose exec checkmk /omd/sites/dmc/lib/nagios/plugins/check_icmp -H 192.168.0.1` returning `OK - 192.168.0.1 rta 1.072ms lost 0%` (substituting the reader's own LAN gateway). Close with §5's skip pattern, and make it two-branched because the symptoms differ: without the capability, every PING service reports `Return code of 126 is out of bounds - plugin may not be executable`; with the capability but without the sysctl, `check_icmp` runs cleanly but reports 100% packet loss to every target — including the LAN gateway that the host itself can ping successfully — which is indistinguishable from a genuine network fault unless you check this sysctl specifically.

Do not include the discovery chronology, the `getcap`/`/proc/self/status`/`CapBnd` forensics, or any "we found this by" framing — those belong in the compose.yaml post-mortem comment that already exists, not in an operator setup guide.
  </action>
  <verify>
    <automated>D="docs/Podman setup for checkmk, minio, mosquitto, worker.md"; grep -q '^## 5\.1\. Enable ICMP/PING checks' "$D" && grep -q 'net\.ipv4\.ping_group_range="0 2147483647"' "$D" && grep -q '/etc/sysctl\.d/99-podman-ping\.conf' "$D" && grep -q 'cap_add' "$D" && grep -q 'NET_RAW' "$D" && grep -q 'Return code of 126' "$D" && grep -q 'podman rm mqtt-poller' "$D" && grep -q 'podman rm checkmk' "$D" && grep -q '^## 6\. Endpoints & Network Access' "$D" && grep -q '^## 9\. Packaging the Worker as an Image' "$D" && ! grep -q '^## 10\.' "$D" && echo PASS</automated>
  </verify>
  <done>
`## 5.1.` exists between §5 and §6 in the doc; it names both root causes, states the `cap_add` half is already in `deploy/compose.yaml`, gives the four-command recreate sequence framed as the general compose-change procedure, gives both the immediate and persistent sysctl commands, and closes with a two-branched "if you skip this" paragraph. §6–§9 headings and all existing `§N` cross-references are byte-identical to before. `deploy/compose.yaml` and all files under `src/` are unmodified (`git status --porcelain` shows only the doc).
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| none introduced | Documentation-only change; no code path, no input handling, no new dependency |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-nde-01 | Elevation of Privilege | Documented `sudo sysctl -w net.ipv4.ping_group_range="0 2147483647"` | accept | Widening `ping_group_range` grants all GIDs the ability to open unprivileged ICMP *ping* sockets (`SOCK_DGRAM`/`IPPROTO_ICMP`) only — not raw sockets, not spoofed source addresses. This is the value shipped by default on Fedora/RHEL and recommended upstream for rootless Podman; no additional attack surface beyond outbound ICMP echo from unprivileged local users. |
| T-nde-02 | Elevation of Privilege | Documented `cap_add: [NET_RAW]` on the `checkmk` container | accept | Already shipped and in effect in `deploy/compose.yaml`; this plan only describes it. `NET_RAW` is scoped to a rootless user namespace, so it confers no host-level raw-socket privilege. Documenting it makes the grant auditable rather than hidden. |
| T-nde-SC | Tampering | package installs | n/a | No `npm`/`pip`/`uv add`/`cargo` install is introduced by this plan. |
</threat_model>

<verification>
- `git status --porcelain` lists exactly one modified tracked file: `docs/Podman setup for checkmk, minio, mosquitto, worker.md` (plus pre-existing untracked/modified entries unrelated to this task).
- `git diff --stat -- deploy/compose.yaml src/` is empty.
- The automated grep gate in Task 1 returns `PASS`.
- Rendered section reads as a peer of §5 in tone and length — not a bug report.
</verification>

<success_criteria>
- An operator following the doc from §4 → §5 → §5.1 on a fresh host ends up with a working Checkmk PING service without needing any information outside the doc.
- Both failure signatures (RC 126; silent 100% packet loss) appear verbatim enough to be found by someone pasting the error into a search.
- Existing section numbering and every `§N` cross-reference in the doc and in `deploy/compose.yaml` remain valid.
</success_criteria>

<output>
Create `.planning/quick/260907-nde-document-the-ping-check-icmp-fix-in-the-/260907-nde-SUMMARY.md` when done
</output>
