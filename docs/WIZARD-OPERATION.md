# How the Wizard Works

Exact technical walkthrough of `checkmk-wizard` as implemented today. Every
claim below is traced to a file and line. For how this compares to the
original design, see [PLAN-CONFORMANCE-AUDIT.md](PLAN-CONFORMANCE-AUDIT.md).

## Prerequisites the wizard assumes are already true

- **Checkmk Community Edition is already installed** on the host (the `.deb`
  package). The wizard never installs it — see Phase 1 below.
- The wizard runs **locally on the Checkmk host**, as a user able to run
  `omd` and read `/omd/sites/<site>/...` (`site.py:30-31`).
- Python 3.11+, `uv`-managed environment (`pyproject.toml`).

## Entry point and control flow

`uv run checkmk-wizard` → `checkmk_wizard.__main__` → `wizard.main()`
(`wizard.py:491-492`) → `asyncio.run(run())` → `run()` (`wizard.py:479-489`),
which executes all 7 phases **sequentially, in a single process, with no
resume/checkpoint support**:

```
phase1_site_bringup()
  → CheckmkClient context manager opens
  → phase2_folders()
  → phase3_discovery()
  → phase4_classification()
  → phase5_onboarding()
  → phase6_discovery()
  → phase7_activation()
  → CheckmkClient context manager closes
```

State is passed by return value / parameter only — there is no persisted
state file. If the process is killed mid-run, the next run starts at Phase 1
with no memory of what happened before (site/hosts already created in
Checkmk are simply re-detected or re-created).

## Phase 1 — Site Bring-up (`wizard.py:47-118`)

1. **Pre-flight check:** `site.omd_installed()` (`site.py:44-46`) checks
   `shutil.which("omd")`. If Checkmk isn't installed at all, prints install
   instructions (`site.CHECKMK_NOT_INSTALLED_INSTRUCTIONS`, `site.py:31-41`
   — download link + `apt install` example) and `raise SystemExit(1)`
   immediately, before prompting for anything, rather than letting
   `omd create` fail later with a raw `FileNotFoundError`/subprocess error.
2. Prompts for **site name** and **Checkmk host** (hostname/IP other systems
   use to reach this site; defaults to `localhost`).
3. `site.site_exists(site_name)` (`site.py:53-54`) checks whether
   `/omd/sites/<site>` is a directory.
   - **If it doesn't exist:** generates a random admin password via
     `secrets.token_urlsafe(16)`, runs `omd create --admin-password <pwd>
     <site>` as a subprocess (`site.py:57-66`), then `omd start <site>`
     (`site.py:69-72`), then **prints the generated cmkadmin password to the
     console**.
   - **If it already exists:** just runs `omd start <site>` again (no-op if
     already running).
4. `site.get_site_credentials(site_name)` (`site.py:88-92`) reads
   `/omd/sites/<site>/var/check_mk/web/automation/automation.secret`
   directly off disk.
   - **If found:** used as-is — no user prompt.
   - **If not found:** prints instructions to create an `automation` user
     manually via the web UI and prompts for the secret interactively.
5. Separately, looks up a **dedicated `agent_registration` credential**
   the same way (`site.get_site_credentials(site_name,
   automation_user="agent_registration")`, `wizard.py:88`) — Checkmk ships
   this as a separate pre-configured, least-privilege user scoped solely to
   host registration (doc-verified: `docs.checkmk.com/latest/en/
   agent_deployment.html`). If found, it's kept separate from the REST
   credential and used only for `cmk-agent-ctl register` in Phase 5.2; if
   not found, prints a note and Phase 5.2 falls back to reusing the general
   `automation` credential (no prompt — silent, doc-explained fallback).
6. Builds a `CheckmkConnection(host, site, username, secret,
   registration_user, registration_secret)` (`api.py:27-50`) — `base_url`
   becomes `http://<host>/<site>/check_mk/api/v1`.
   `registration_user`/`registration_secret` default to `username`/`secret`
   via `__post_init__` (`api.py:42-46`) when no dedicated credential was
   found (or when constructed without them, e.g. in tests).
7. Opens a `CheckmkClient` and calls `GET /version` (`api.py:102-104`). On any
   `CheckmkAPIError`, prints the error and `raise SystemExit(1)` — **this is
   the only phase whose failure is fatal to the whole run.**

**Nothing in this phase installs the Checkmk package itself** — step 1
only *checks* that it's already installed and fails fast with guidance if
not; the rest of the phase creates/starts the OMD *site* inside an
already-installed Checkmk.

## Phase 2 — Folder Structure (`wizard.py:124-140`)

1. `questionary.confirm` — "Set up folders?" Defaults to **No**.
2. If yes: comma-separated folder names, each created via
   `POST /domain-types/folder_config/collections/all` with
   `{name, title, parent: "/", attributes: {}}` (`api.py:108-120`). Failures
   are printed per-folder and do not stop the loop.
3. If no: nothing happens — later hosts land in the root folder `/`.

## Phase 3 — Network Discovery (`wizard.py:145-195`)

1. Prompts for a CIDR (e.g. `192.168.10.0/24`) and an optional
   comma-separated port list (default `22,80,443` — `scanner.py:17`). Each
   is validated on entry (`ipaddress.ip_network(..., strict=False)` for the
   CIDR, `int()` per port) and re-prompted on a parse failure instead of
   raising uncaught out of the phase — a bad CIDR/port no longer kills the
   whole run.
2. `scan_network()` (`scanner.py:63-85`):
   - Parses the CIDR with `ipaddress.ip_network(cidr, strict=False)`.
   - Splits anything larger than `/24` into `/24` chunks
     (`chunk_network`, `scanner.py:56-60`).
   - Per chunk, for every host address, opens a TCP connection to each
     configured port with a 1.5s timeout, bounded by a semaphore of 256
     concurrent probes (`_probe_port`, `scanner.py:32-45`).
   - A host is "alive" if **any** of the checked ports connected
     successfully. Only alive hosts are returned — closed/filtered hosts
     are silently dropped, not reported.
   - Calls `on_progress(chunk, alive_count, total_count)` once per `/24`
     chunk (not per host).
3. Renders a `rich` table of IP → open ports.
4. Stages **every** alive IP into Checkmk immediately:
   `POST /domain-types/host_config/collections/all` with
   `{host_name: ip, folder: "/", attributes: {ipaddress: ip}}` — always at
   root, regardless of any folders created in Phase 2
   (`wizard.py:184-186`, `api.py:133-147`). Failures are printed and
   skipped, not retried.

## Phase 4 — Host Classification (`wizard.py:196-241`)

Purely interactive — **no API calls, no fingerprinting**:

1. Presents a checkbox list of scanned IPs (with their open ports) via
   `questionary.checkbox`.
2. For each selected IP: prompts for hostname (default = the IP), folder
   (default `/`), and a monitoring-method choice — `linux` (agent),
   `windows` (agent), or `snmp` (no agent — switches/routers/printers/etc.)
   (`questionary.select`, `wizard.py:211-218`).
3. **If `snmp`:** additionally prompts for SNMP version (`v2c` or `v1` —
   **v3 is not supported**, community-string auth only) and the community
   string (default `public`) (`wizard.py:220-229`).
4. Returns a list of `OnboardedHost(ip, hostname, folder, os_family,
   snmp_version, snmp_community)`.

## Phase 5 — Host Onboarding (`wizard.py:270-408`)

Runs once for the whole batch, then loops **sequentially, one host at a
time** — no concurrency.

**Setup (once):**
1. Asks "Attempt automated SSH firewall + agent install for Linux hosts?"
   (default Yes).
2. If yes: prompts for SSH username, then auth mode (password or private
   key path) → builds one `SSHCredentials` object reused for **every**
   Linux host in the batch (same username/credential for all hosts).

**Host create/update (`_create_or_update_host()`, `wizard.py:247-266`):**
Both branches below go through this helper instead of calling
`client.create_host()` directly. Phase 3 already staged every scanned IP
as a bare host object under `host_name=ip` (see Phase 3 above); a Phase 4
promotion that keeps the default hostname (== IP) therefore always
collides with that stub host on `create_host`. The helper catches the
resulting `CheckmkAPIError`, fetches the existing host's ETag
(`client.get_host()`), and `PUT`s the attributes via
`update_host_attributes()` instead — so `tag_agent`/`tag_snmp_ds`/
`snmp_community`/`ipaddress` still land on the host rather than being
silently dropped by the failed create. **Known limitation:** this only
updates attributes, not folder placement — Checkmk's host-config `PUT`
doesn't support moving folders, so a host promoted into a non-root folder
that already exists at root (from Phase 3) stays at root. A create/update
failure for any other reason (e.g. an invalid hostname) still just prints
a warning and the wizard **continues anyway** to the firewall/SSH steps
regardless (known bug — see audit) — this fix narrows that bug's trigger
to genuine failures, since the common IP-collision case no longer fails
at all.

**Per host:**
1. **If `os_family == "snmp"`:** `_create_or_update_host(host_name=hostname,
   folder=..., attributes={ipaddress, tag_agent: "no-agent", tag_snmp_ds:
   "snmp-v2"|"snmp-v1", snmp_community: {type: "v1_v2_community",
   community}})` (`wizard.py:299-312`) — no firewall/SSH/agent steps at
   all, `continue` to next host. `tag_agent`/`tag_snmp_ds` values are
   doc-verified (Checkmk's CSV host-import attribute mapping,
   `docs.checkmk.com/latest/en/hosts_setup.html`); the `snmp_community`
   payload shape is best-effort and **not** independently doc-confirmed —
   verify against the target site's own REST API spec before relying on it.
2. **Otherwise:** `_create_or_update_host(host_name=hostname, folder=...,
   attributes={ipaddress, tag_agent: "cmk-agent"})` (`wizard.py:319-325`).
3. **If `os_family == "windows"`:** prints
   `windows_firewall_instructions()` and `windows_register_command()`
   (`remote.py:160-164, 259-267`) as copy-paste text, using
   `connection.registration_user`/`registration_secret` (not
   `username`/`secret` — see credential-scope note below). No automation
   attempted at all for Windows — `continue` to next host.
   `windows_register_command()` PowerShell-quotes each argument
   (`_ps_quote()`, `remote.py:250-256` — single-quoted literal, doubled
   embedded `'`) so a hostname/site/password containing a space, `$`, or
   `'` still produces a valid command to copy-paste; `linux_register_command`
   already did the POSIX-shell equivalent via `shlex.quote()`.
4. **If `os_family == "linux"`:**
   a. `remote.probe_port(ip, 8000)` (`remote.py:119-139`) — TCP connect
      attempt to the Agent Receiver port; classifies as `open`,
      `closed_rst` (got `ConnectionRefusedError`), or `filtered_or_down`
      (timeout/other OSError). Result is printed, **not acted on** —
      informational only.
   b. If no SSH credentials were supplied: prints manual firewall/install
      instructions (`_print_linux_manual`, `wizard.py:400-405`) and moves
      to the next host.
   c. Otherwise, `remote.fix_firewall_linux(ip, creds, 8000)`
      (`remote.py:167-202`):
      - `check_ssh_reachable()` first; if it fails →
        `FAILED_FALLBACK_MANUAL`.
      - Over one SSH connection, runs `command -v ufw`, then
        `command -v firewall-cmd`, then `command -v nft` (first match
        wins, in that fixed order) to pick a backend.
      - Runs `sudo <backend-specific allow rule>` unconditionally
        (`sudo ufw allow 8000/tcp`, etc.) — **no confirmation prompt, no
        dry-run, no rollback.**
      - Any failure → `FAILED_FALLBACK_MANUAL` with the manual rule text.
   d. `remote.check_os_compatibility(ip, creds)` (`remote.py:205-234`):
      reads `/etc/os-release` over SSH on the target and classifies it as
      `deb`-family or `rpm`-family via `remote.package_family()`
      (`remote.py:93-102`), using the target's own `ID`/`ID_LIKE` — **not**
      a comparison against the Checkmk host's own OS. Doc-verified against
      `docs.checkmk.com/latest/en/agent_linux.html` ("RPM packages are
      intended for RHEL-based systems, SLES, Fedora, and openSUSE, while
      DEB packages are used for Debian, Ubuntu, and other DEB-based
      distributions"). If the distro isn't recognized as either family,
      shows a warning and asks "Proceed anyway assuming .deb?" (default
      **No**).
   e. If the user chose not to proceed, skips agent install for that host
      and continues to the next.
   f. `register_cmd = remote.linux_register_command(hostname, host, site,
      connection.registration_user, connection.registration_secret)`
      (`wizard.py:372-374`) — uses the dedicated `agent_registration`
      credential from Phase 1 when one was found, **not** the general
      `automation` REST credential (see credential-scope note below).
   g. `client.download_agent(os_type)` (`api.py:170-177`) — requests
      `linux_deb` or `linux_rpm` based on the package family determined in
      step d (defaults to `linux_deb` if the compatibility check itself
      couldn't run, e.g. SSH became unreachable between steps).
   h. `remote.install_agent_linux(ip, creds, package_bytes,
      package_filename, register_cmd)` (`remote.py:269-343`), where
      `package_filename` is `check-mk-agent.deb` or `check-mk-agent.rpm`
      to match the package family from step g:
      - SFTP-uploads the package to `/tmp/<package_filename>` on the
        target.
      - **Verifies the upload with a checksum** (`remote.py:294-313`):
        runs `sha256sum <path>` on the target and compares it to a
        `hashlib.sha256` of the bytes sent — a successful SFTP write only
        means no exception was raised, not that what landed on disk
        matches what was sent, so this catches silent truncation/
        corruption before attempting install. Mismatch or a failed
        `sha256sum` call → `FAILED_FALLBACK_MANUAL`, install is not
        attempted.
      - Installs with `sudo dpkg -i <path>` or `sudo rpm -i <path>`
        (chosen by filename suffix — both branches are now reachable).
      - Runs `sudo cmk-agent-ctl register --hostname ... --server ...
        --site ... --user <registration_user> --password ...` (the
        `register_cmd` built in step f) **on the target host over the same
        SSH connection** (registration must run locally on the monitored
        machine, not via REST API).
      - Any step failing → `FAILED_FALLBACK_MANUAL` with manual
        instructions; success → `AUTOMATED`.
   i. **If install returned `AUTOMATED`:** `remote.check_agent_status(ip,
      creds, site)` (`remote.py:359-374`, `wizard.py:390-397`) runs
      `cmk-agent-ctl status` on the target and checks (via
      `agent_status_shows_connection()`, `remote.py:346-356`) that its
      output contains a `Connection: <server>/<site>` line for this site —
      confirming the agent controller is actually operational and recorded
      a connection, rather than trusting the register command's exit code
      alone. Doc-verified output format:
      `docs.checkmk.com/latest/en/hosts_autoregister.html`, "Check Agent
      Controller status". This is a **local** check on the target only —
      it doesn't independently confirm the Checkmk server accepted the
      host as UP; that's confirmed later, for the whole batch, by Phase 7's
      Livestatus query. Printed as its own `Agent status: verified /
      could not verify` line, separate from the install line.

## Phase 6 — Discovery & Baseline (`wizard.py:411-423`)

For every onboarded host: `POST
/domain-types/service_discovery_run/actions/start/invoke` with
`{host_name, mode: "fix_all"}` (`api.py:181-193`) — discovers services and
accepts them (adds missing, removes vanished, accepts host labels) in one
call, so services are actually in the monitored state by the time Phase 7
activates changes. A `303` response (Checkmk ran discovery as an async
background job) is treated as success, not an error.

**Deliberately not implemented (decision 2026-08-24):** applying baseline
discovery rulesets (systemd services, disabled-services). The plan's own
language hedges these as situational ("where useful", "if the host runs
relevant services", "known-noisy checks") and both require operator
judgment about a specific environment that the wizard has no way to infer
from a scan — building either would mean guessing at a REST payload shape
this session couldn't confirm via context7, for behavior the plan doesn't
actually specify concretely enough to build against. The plan's third
example, an "SNMP community ruleset," is effectively already covered:
Phase 5 sets the SNMP community as a **host attribute** directly
(`snmp_community`) rather than via a separate folder-level ruleset object —
a different mechanism than the plan's wording, but the same outcome
(SNMP-only hosts get their community string configured).

## Phase 7 — Activation & Validation (`wizard.py:429-473`)

1. `GET /domain-types/activation_run/collections/pending_changes` to read
   the `ETag` header (`api.py:197-202`).
2. `POST /domain-types/activation_run/actions/activate-changes/invoke` with
   `{redirect: false, sites: [site], force_foreign_changes: false}` and
   `If-Match: <etag>` (`api.py:204-220`). On failure, prints the error and
   **returns early — the snapshot step below does not run.**
3. If there are onboarded hosts, queries Livestatus directly:
   - Connects to the UNIX socket `/omd/sites/<site>/tmp/run/live`
     (`livestatus.py:14-15`).
   - Sends the raw LQL query `GET hosts\nColumns: name state\nOutputFormat:
     csv\nColumnHeaders: off\n\n` and reads the socket until EOF.
   - Parses each line by splitting on the **first** `;` only
     (`line.partition(";")`, `livestatus.py:51`).
   - Maps state `0→UP`, `1→DOWN`, `2→UNREACHABLE`, anything else →
     `"unknown"`, and prints a table.
4. Pulls the site's **actual current** host/folder configuration —
   `client.list_hosts()` → `GET /domain-types/host_config/collections/all`
   and `client.list_folders()` → `GET
   /domain-types/folder_config/collections/all` (`api.py:122-129,
   149-152`; `wizard.py:456-462`) — rather than only logging what this run
   touched. Both return the collection's `value` array (doc-confirmed
   response shape: `docs.checkmk.com/latest/en/rest_api.html`,
   pending-changes collection example). If this fetch fails, prints a
   warning and writes the snapshot anyway with `hosts`/`folders` set to
   `null`, rather than aborting.
5. Writes a JSON file `config_snapshot_<YYYYMMDD_HHMMSS>.json` to the
   **current working directory** (wherever the wizard was launched from)
   containing `generated_at`, `site`, `onboarded_this_run` (this run's
   onboarding list — hostname/ip/folder/os_family, plus
   snmp_version/snmp_community **in plaintext** for SNMP hosts), and now
   also `hosts`/`folders` (the site's full current configuration from step
   4). **Scope note:** this covers hosts and folders only — rules, users,
   and other site-wide config are not included, so it's a partial
   configuration snapshot, not a full site backup.

## Key data structures

| Type | File | Purpose |
|---|---|---|
| `CheckmkConnection` | `api.py:27-50` | host/site/username/secret + computed `base_url`; `registration_user`/`registration_secret` default to `username`/`secret` via `__post_init__` |
| `CheckmkClient` | `api.py:53-220` | async context-managed `httpx` wrapper; one method per endpoint used |
| `WizardState` | `wizard.py:38-41` | declared but **unused** — phases pass state via direct return values/params instead |
| `HostScanResult` | `scanner.py:22-29` | IP + open ports from Phase 3 |
| `OnboardedHost` | `wizard.py:28-34` | ip/hostname/folder/os_family (+ snmp_version/snmp_community if SNMP) from Phase 4 |
| `ActionResult` | `remote.py:54-57` | outcome (`automated`/`manual_required`/`failed_fallback_manual`) + detail + manual text |
| `SSHCredentials` | `remote.py:41-44` | username + password or private key path, held in memory only |
| `OSRelease` | `remote.py:61-79` | parsed `/etc/os-release` (id, version_id, id_like) |
| `CompatibilityCheck` | `remote.py:106-110` | target OS + classified package family (`deb`/`rpm`/`None`) — not a same-OS-as-host comparison |
| `AgentStatusCheck` | `remote.py:114-116` | `verified: bool` + `detail: str` from post-install `cmk-agent-ctl status` check |

## Error-handling model

- Phase 1 pre-flight check (Checkmk not installed): **fatal**
  (`SystemExit(1)`, before any prompts).
- Phase 1 REST check failure: **fatal** (`SystemExit(1)`).
- Site bootstrap (`omd create`/`omd start`) failure: **fatal**
  (unhandled `SiteBootstrapError`).
- Everything else (folder create, host create, firewall, agent install,
  discovery start): **caught and printed, execution continues** — the
  wizard never aborts the whole run over a single host/folder failure.
- Livestatus socket errors in Phase 7: **unhandled** (bare exception
  propagates if the socket is missing/unreadable).

## Credential handling

- SSH password/private-key path lives only in the in-memory
  `SSHCredentials` dataclass for the duration of the run — never written to
  disk.
- The Checkmk automation secret and generated cmkadmin password are printed
  to the console (`rich` output) — visible in scrollback/terminal capture.
- SSH host key verification is disabled (`known_hosts=None`,
  `remote.py:143`) for every connection.
- The registration credential (`connection.registration_secret` — the
  dedicated `agent_registration` secret when found, otherwise the same
  `automation` secret used for REST calls) is passed as a `--password`
  command-line argument to `cmk-agent-ctl register` over the SSH session
  (`remote.py:237-247`), visible to anything reading that process's argv
  on the target host. Using the narrower `agent_registration` credential
  when available (Phase 1, `wizard.py:88-109`) limits what this exposure
  can be used for, compared to leaking the full `automation` credential.
- The SNMP community string (Phase 4, `snmp` hosts) is prompted in plain
  text via `questionary.text` (not password-masked) and later written
  unmasked into the Phase 7 `config_snapshot_*.json` file on disk — no
  worse than the existing automation-secret/cmkadmin-password console
  exposure noted above, but adds a second plaintext-on-disk credential
  path not present before this bundle of fixes.

---
*Traced against commit implementing Phases 1–7 of the wizard, 2026-08-24.*
