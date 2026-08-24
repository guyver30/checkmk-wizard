# CheckMK Setup Configurator — High-Level Plan

**Implementation status:** Phases 1-7 implemented as a Python wizard under
`src/checkmk_wizard/` — see [README.md](../README.md) for setup/run/test
instructions. Unit tests cover the REST client, scanner, and remote helpers
in isolation (mocked); the wizard has not been run end-to-end against a live
Checkmk site or real network/SSH targets, since none are available in the
environment it was built in.

**Goal:** A reusable tool/script that automates the base setup of CheckMK Community Edition
(2.4.0p34) from scratch — installation through activated, monitored hosts. Scope is CheckMK setup
only. MQTT publisher, notification scripts, and the dashboard are a separate downstream layer and
are explicitly **out of scope** for this plan.

**Primary interface:** CheckMK REST API (`/check_mk/api/v1/...`), driven from an interactive Python
terminal wizard. Native CheckMK features (discovery rulesets, activation) are used wherever
available; network discovery uses a custom async port scanner instead of CheckMK's native
"Networks to scan" (see Phase 3 rationale). All REST API facts in this plan are verified against
live Checkmk docs via context7 — see inline source notes.

**Key decisions (locked):**
- **Discovery:** custom async (`asyncio`) TCP port scanner, not native CheckMK network scan.
- **Firewall management:** automatically checked and modified/added via SSH on Linux targets;
  manual instructions only on Windows targets; full manual fallback on any failure (SSH
  unreachable, permission denied, unsupported firewall backend).
- **Agent installation:** automated as much as possible via SSH on Linux targets; Windows targets
  get generated manual instructions only (no WinRM automation); full manual fallback on any
  failure.
- **Host classification:** still no automatic fingerprinting/OS-guessing (unchanged from original
  decision) — the async scanner produces port-response data, but promoting an IP to a named,
  fully-configured host remains a manual, user-driven step (Phase 4).

---

## Phase 1 — Installation & Site Bring-up

1. Install the CheckMK Community package (`.deb`) on the target OS.
2. Create the OMD site with a known password set at creation time, avoiding the
   generated-password ambiguity entirely:
   `omd create --admin-password <known-password> <sitename>`, then `omd start <sitename>`.
   (Verified: `omd create` accepts `--admin-password`; without it, `cmkadmin`'s password is
   randomly generated and only shown once in the create-command output.)
3. If the site already exists (installed by someone else before the wizard runs), fall back to
   prompting the user for the existing `cmkadmin` credentials instead of step 2.
4. Create a dedicated **automation user** (e.g. `automation`), authentication mode = "Automation
   secret for machine accounts." This is the credential the rest of the tool authenticates with —
   never use `cmkadmin` for scripted calls. Best practice per Checkmk docs: assign a scoped custom
   role rather than full Administrator, though Administrator is acceptable for a single-operator
   setup tool.
5. The automation secret is also readable directly from the site filesystem once created —
   `~/var/check_mk/web/<username>/automation.secret` — useful since the wizard runs locally on the
   Checkmk host and can bootstrap without re-prompting for it on later runs.
6. Verification: `GET /check_mk/api/v1/version` returns valid JSON — confirms site is up, REST API
   reachable, and credentials work before proceeding.

**Output of this phase:** a reachable CheckMK site + working automation credentials. Everything
after this point is scriptable via the REST API.

---

## Phase 2 — Folder Structure (Optional)

1. Optionally create one folder per site/VLAN via `POST /domain-types/folder_config/collections/all`
   (e.g. `/vlan10`, `/vlan20`, or `/site_a`, `/site_b`).
2. If skipped, all hosts land in the root folder — acceptable for small/single-site setups.
3. This phase has no dependents downstream — folder assignment can be decided per-host in Phase 4
   regardless of whether this phase runs.

**Decision point (user input):** does this setup use folders? If yes, what's the folder list?

---

## Phase 3 — Network Discovery (Custom Async Scanner)

**Why not native CheckMK scan:** verified via context7 against live Checkmk docs — the native
"Networks to scan" folder attribute is a **background cronjob** (checked once per minute against
each folder's configured interval/time-window), not a synchronous, on-demand operation, capped at
a recommended ~2048 IPs (/21), and performs **ping + DNS resolution only — no TCP port checks**.
It cannot serve the wizard's need for immediate, port-level classification data during an
interactive session. A custom scanner is therefore necessary, not a stylistic preference.

1. **User input required:** subnet/CIDR range(s) to scan (e.g. `192.168.10.0/24`).
2. Run a Python `asyncio` TCP-connect sweep against the target range(s), bounded by a semaphore
   (e.g. capped concurrency to stay well under the process's open-file-descriptor limit) to avoid
   descriptor exhaustion on large ranges. Recommend chunking anything larger than a `/24` into
   `/24`-sized batches.
3. **User input required:** which ports to check for classification purposes. Keep this list small
   and purposeful per the user's stated need — starting set:
   - SSH (22)
   - HTTP (80)
   - HTTPS (443)
   - (extendable later — SMB, RDP, WinRM 5985/5986, Checkmk Agent Receiver 8000, legacy agent
     6556, SNMP UDP 161 — but not required for the base tool)
4. UDP ports (e.g. SNMP 161) cannot be reliably classified with a plain connect-scan; treat as a
   documented limitation for the base tool rather than building active SNMP probing into v1.
5. Run the scan. Output: a raw list of live IPs, each with which of the defined ports responded.
6. Stage scan results into CheckMK as provisional host objects via
   `POST /domain-types/host_config/collections/all` (folder, host_name/IP, minimal attributes) —
   the wizard does this directly instead of relying on native scan's auto-import behavior.

**Output of this phase:** every live IP on the given subnet(s) exists as a CheckMK host object,
each tagged implicitly by which ports responded (SSH/HTTP/HTTPS open or not).

---

## Phase 4 — Host Classification (Named vs. IP-only)

1. No automatic classification logic needed — per user decision, hosts without a resolvable
   hostname simply remain as bare IP addresses in CheckMK. No fingerprinting, no port-based OS
   guessing.
2. **Manual step (by design):** the user reviews the scanned host list and decides which IPs get
   promoted to fully-configured, named hosts (Phase 5) — e.g. renaming a host object, assigning it
   a proper hostname, moving it to the right folder.
3. Hosts left as IP-only continue to exist with just the Phase 3 scan checks (ping + the 2-3 TCP
   port checks) — no agent, no further config, unless later promoted.

**Output of this phase:** a curated list of hosts the user has explicitly chosen to fully onboard.
Everything else stays as lightweight IP-only entries.

---

## Phase 5 — Host Onboarding (REST API)

For each host the user has chosen to fully configure:

1. `POST /domain-types/host_config/collections/all` — set/update hostname, IP address, folder
   placement, and the "Checkmk agent / API integrations" attribute:
   - `"API integrations, Checkmk agent"` for agent-based hosts (Linux/Windows)
   - `"No API integrations, no Checkmk agent"` + SNMP credentials for SNMP-only devices (network
     gear, switches, routers)
2. For SNMP hosts: set the SNMP community/version via the host's attributes in the same API call
   or a follow-up `PUT`.

### 5.1 Firewall Check & Remediation

For each agent-based host, before attempting agent install:

1. Probe the required port from the Checkmk server (Agent Receiver **8000**, confirmed via
   `omd config show | grep AGENT_RECEIVER` — legacy plaintext agent mode used 6556, not the
   default in current Agent Controller setups) to distinguish "closed" (RST) vs. "filtered"
   (silent drop / no response) vs. "host unreachable."
2. **Linux targets, if SSH is reachable:** connect via SSH and automatically inspect/modify the
   local firewall (detect `ufw`, `firewalld`, or raw `nftables`/`iptables`; add the specific rule
   needed to allow the Checkmk server to reach the agent, or allow outbound to the receiver,
   depending on the connection direction required). Report exactly what rule was added.
3. **Windows targets:** never auto-modify — generate the exact `New-NetFirewallRule` PowerShell
   command for the user to run manually, as part of the same instructions bundle as agent install.
4. **Fallback (any target, on any failure):** if SSH is unavailable, auth fails, or the firewall
   backend isn't recognized, drop to full manual instructions (present the same rule the automated
   path would have applied, worded for manual execution) rather than silently giving up.

### 5.2 Agent Installation & Registration

1. **Linux targets, if SSH is reachable:**
   - Detect the target's OS distro/version over SSH (e.g. `cat /etc/os-release`) and compare
     against the package family Checkmk offers for that distro (deb vs. rpm, and any
     version-specific package if the site publishes one). If the target's distro/version doesn't
     match what's available (e.g. target is Ubuntu 20.04 but the closest package is built for
     22.04), **warn the user with the specific mismatch** and require explicit confirmation before
     proceeding — the wizard does not silently install a mismatched package, but also does not
     hard-block; the user may accept the risk and continue.
   - Download the correct agent package via the REST API's dedicated endpoint (verified):
     `GET /domain-types/agent/actions/download/invoke?os_type=linux_deb` (or `linux_rpm`, etc.),
     with `Authorization: Bearer automation <secret>` and `Accept: application/octet-stream`.
   - Push the package to the target over SSH/SCP, install it (`dpkg -i` / `rpm -i` as appropriate),
     then run registration **on the target host itself** — this step cannot be done remotely via
     the REST API, `cmk-agent-ctl` must execute locally on the monitored machine (verified):
     ```
     cmk-agent-ctl register --hostname <name> --server <cmk-host> --site <site> \
       --user automation --password '<secret>'
     ```
   - Verify: agent controller reports registration complete; confirm host later shows `OK` state
     via Livestatus/API (Phase 7).
2. **Windows targets:** never auto-install — generate copy-paste PowerShell instructions
   containing the equivalent `cmk-agent-ctl.exe register` command (verified syntax: `--hostname
   --server --site --user --password`, or short flags `-H -s -i -U`), plus the MSI download link
   and firewall rule from 5.1.3. This is a first-class path, not a degraded fallback — Windows
   hosts commonly don't expose SSH/WinRM by default.
3. **Fallback (any target, on any failure):** if SSH is unavailable, connection/auth fails, or the
   remote install step errors out, drop to full manual instructions — same package URL, same
   `cmk-agent-ctl register` command, worded for the user to run by hand. Never leave the operator
   with a half-completed automated attempt and no next step.

**Output of this phase:** host objects exist in CheckMK with correct monitoring method configured;
agent-based hosts have the agent installed and registered (trust established) on the target
machine itself, and required firewall ports are open (automatically on Linux, per generated
instructions on Windows).

---

## Phase 6 — Discovery & Baseline Rules

1. Run service discovery per onboarded host via
   `POST /domain-types/service_discovery_run/actions/start/invoke` with `{"host_name": "<name>",
   "mode": "refresh"}` (verified endpoint — corrects an earlier draft that referenced a
   non-existent `discovery_run`/`mode: "fix_all"` combination), or `cmk -II <hostname>` if
   scripting at the CLI level is simpler.
2. Apply baseline discovery rulesets programmatically where useful, e.g.:
   - Systemd single services discovery (if the host runs relevant services)
   - SNMP community ruleset (for SNMP-only hosts)
   - Disabled services ruleset (to suppress known-noisy checks, e.g. unused mail/file-sharing port
     checks on hosts that don't run those services)
3. Accept discovered services (bulk accept via API, or flag for manual review per host if the user
   wants a check-before-activate step).

**Output of this phase:** each onboarded host has its full service checklist discovered and staged
for activation.

---

## Phase 7 — Activation & Validation

1. `POST /domain-types/activation_run/actions/activate-changes/invoke` — push all pending
   configuration live.
2. Post-activation health check:
   - Confirm all onboarded hosts show state UP via LiveStatus/API.
   - Spot-check that expected services exist per host (e.g. compare discovered count against an
     expected minimum).
3. Export a configuration snapshot immediately after activation using the existing
   `Checkmk configuration exporter.py` script — this becomes the "known good baseline" artifact for
   this setup run, useful for diffing against future changes or disaster recovery.

**Output of this phase:** a fully activated, validated CheckMK monitoring setup, plus a JSON backup
of the resulting configuration.

---

## Open items / TBD

- **Folder strategy specifics** (Phase 2) — left optional/flexible; only the "one folder per VLAN"
  convention is recommended, not mandated.
- **Port list for discovery** (Phase 3) — currently SSH/HTTP/HTTPS only, per stated need. Extend
  later if broader classification is required.
- **SSH credential handling for automated push** (Phase 5) — how the wizard obtains/stores SSH
  credentials for Linux target hosts during a single run is not yet specified (e.g. prompt once
  per batch, per-host key selection, agent forwarding). Must exclude persisting raw credentials to
  disk in any checkpoint/state file.
- **Legacy vs. Agent Controller push mode** (Phase 5.1) — the plan targets the modern TLS Agent
  Controller (port 8000, `cmk-agent-ctl register`). Confirm whether any legacy plaintext-agent
  (port 6556) support is actually needed before implementation, since it changes firewall
  direction/rules.

Resolved (previously TBD):
- **Agent deployment mechanism** — automated via SSH for Linux, manual-instructions-only for
  Windows, full manual fallback on failure (see Phase 5.2).
- **Firewall management** — automated via SSH for Linux, manual-instructions-only for Windows,
  full manual fallback on failure (see Phase 5.1).

## Explicitly out of scope

- MQTT publisher setup (`mqtt_publisher_changes.py`, `mqtt_notify.py`)
- Dashboard setup (`mqtt_dashboard.py`, templates)
- Any dashboard-side host classification/rendering logic — this plan covers CheckMK-side setup only
