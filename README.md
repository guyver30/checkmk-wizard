# checkmk-wizard

Interactive terminal wizard that configures a fresh Checkmk Community Edition
site from scratch — network discovery, host onboarding, agent installation,
and activation. See [docs/CHECKMK_SETUP_CONFIGURATOR_PLAN.md](docs/CHECKMK_SETUP_CONFIGURATOR_PLAN.md)
for the full design and phase breakdown.

For exactly how the implementation behaves today, see
[docs/WIZARD-OPERATION.md](docs/WIZARD-OPERATION.md). For how that
implementation compares to the plan above (verified against live Checkmk
docs), see [docs/PLAN-CONFORMANCE-AUDIT.md](docs/PLAN-CONFORMANCE-AUDIT.md).

## Prerequisites

### On the machine running this wizard

This wizard supports two modes, auto-detected at startup by whether `omd`
is on `PATH` — no flag to set:

**Host-native mode** — the wizard runs directly on the Checkmk site's
host, driving `omd` and reading the site's automation secret off the
local filesystem. This is the original, fully-featured mode: it can
create, reuse, or delete OMD sites.

- **Linux.** Required throughout (`omd`, `/etc/os-release`, etc.) —
  there's no Windows/macOS support for the host running the wizard.
- **Checkmk Community Edition already installed on this host**, with
  `omd` on `PATH`. The wizard does **not** install the Checkmk package
  itself — it only creates/starts the OMD *site* on top of an existing
  install; see [Checkmk's install
  docs](https://docs.checkmk.com/latest/en/install_packages.html) for your
  distro (Debian, Ubuntu, RHEL/AlmaLinux/Rocky, and SLES are officially
  supported).
- **Plain root at the OS level — not `omd su <site>`.** Phase 1 runs
  `omd create`/`omd start`/`omd config` as root, naming the site
  explicitly each time (the pattern Checkmk's docs specify for root-level
  `omd` invocation); site *creation* specifically requires root and can't
  be done as a site user. Nothing in this codebase drops into a site's own
  shell/environment — it reads the automation secret via a plain absolute
  filesystem path, which root can access unconditionally. Run it from a
  root shell or via `sudo` (see [Run](#run) below) — not via `omd su
  <site>`.

**Container mode** — the wizard runs somewhere `omd` isn't available (e.g.
a separate "worker" container alongside a containerized Checkmk). Site
creation/deletion aren't possible from here — the wizard connects to a
site that already exists instead (e.g. one a Checkmk container's own
entrypoint auto-created via `CMK_SITE_ID`/`CMK_PASSWORD`). If `omd` simply
isn't installed anywhere and this isn't actually a container deployment,
the wizard prints the same install instructions it always has, as a
fallback hint, since it can't tell the two situations apart on its own.

- **`CMK_SITE_ID` set on the wizard's own container too** (matching
  whatever it's set to on the Checkmk container) — purely a convenience:
  it pre-fills the site-name prompt so you don't have to retype it, and
  can still be overridden by typing a different name. There's no
  network-based way for the wizard to discover site names on its own —
  every Checkmk REST endpoint is scoped under `/<site>/...`, so the name
  has to be known before anything can be queried.
- **The `cmkadmin` password** (whatever the Checkmk container's own
  `CMK_PASSWORD` was set to) — prompted for at startup. The wizard uses it
  to create the site's `automation` REST user itself over the API (the
  same `bootstrap_automation_user()` mechanism host-native mode uses right
  after `omd create`), so there's no local secret file to read. Leave it
  blank to skip this and provide an automation secret directly instead
  (e.g. fetched manually via `podman exec <checkmk-container> cat
  /omd/sites/<site>/var/check_mk/web/automation/automation.secret`, or one
  from a dedicated user created via Setup > Users in the web UI) — the
  wizard also falls back to this automatically if bootstrapping fails
  (e.g. re-running against a site that already has an `automation` user
  from a previous run). The same cmkadmin password is also used to reset
  the secret of Checkmk's built-in `agent_registration` user (the
  least-privilege account recommended for `cmk-agent-ctl register`) if no
  local secret is found for it either — falling back to reusing the
  general `automation` credential for registration if that also fails.
- **Livestatus-over-TCP already enabled** on the target site (`omd config
  <site> set LIVESTATUS_TCP on && omd restart <site>`, run on the Checkmk
  host/container) — the wizard can't turn this on remotely, and warns at
  startup if it can't reach it.

**Both modes need:**

- **Python 3.11 or newer** and **[uv](https://docs.astral.sh/uv/)** as the
  package manager. Install uv if you don't already have it:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Network access** to the Checkmk REST API and to the site's Livestatus
  TCP port (6557 by default — host-native mode turns this on automatically
  for any site it creates or reuses, for the Phase 7 host-state check),
  usually `localhost` for both in host-native mode, or the Checkmk
  container's hostname/IP in container mode, plus outbound access to
  whatever subnet(s) you intend to scan (Phase 3) and whatever hosts you
  onboard (Phase 5).

### On target hosts you onboard (Phase 5 — only if you use SSH automation)

Only relevant if you opt into automated SSH firewall/agent-install for
Linux targets; skipping SSH credentials in Phase 5 falls back to
copy-paste manual instructions instead, with none of these requirements.

- **SSH reachable** from the Checkmk host, with a valid password or
  private key for the account you provide.
- **`sudo` access** for that SSH account — used to modify firewall rules,
  install the agent package, and run `cmk-agent-ctl register`.
- **`dpkg` (Debian/Ubuntu-family) or `rpm` (RHEL/SLES/Fedora-family)**,
  whichever matches the target's distro — detected automatically from
  `/etc/os-release`.
- **`sha256sum`** (part of GNU coreutils, present by default on all
  mainstream distros) — used to verify the uploaded agent package before
  installing it.
- **Windows targets** need none of the above: the wizard never
  automates against Windows, it only generates PowerShell commands for
  you to run manually.
- **SNMP-only devices** (switches, routers, etc.) need none of the above
  either — no SSH, just SNMP read access and a community string, which
  the wizard prompts for directly.

## Setup

```bash
uv sync
```

## Run

As root (see [Prerequisites](#prerequisites) for why):

```bash
uv run checkmk-wizard
```

If you're using `sudo` instead of a root shell, use `sudo -E` (or an
explicit `PATH=`) so `sudo` doesn't lose `uv` off your regular user's
`PATH`:

```bash
sudo -E uv run checkmk-wizard
```

## Test

```bash
uv run pytest
```

Tests cover the REST API client (mocked via `respx`), the async port
scanner, and the remote (SSH/firewall/OS-compatibility) helpers in
isolation. They don't exercise a live Checkmk site, real network targets,
or actual SSH connections — that requires a real lab environment.

## Project layout

- `src/checkmk_wizard/api.py` — Checkmk REST API client (Phase 1, 2, 5-7)
- `src/checkmk_wizard/site.py` — OMD site bootstrap and automation credentials (Phase 1)
- `src/checkmk_wizard/scanner.py` — async TCP port scanner (Phase 3)
- `src/checkmk_wizard/remote.py` — SSH firewall check/fix and agent install (Phase 5.1/5.2)
- `src/checkmk_wizard/livestatus.py` — post-activation host state check (Phase 7)
- `src/checkmk_wizard/wizard.py` — interactive orchestration of all phases
