"""Phase 1: OMD site bring-up and automation-credential bootstrap.

Facts used here are verified against live Checkmk docs via context7:
- `omd create --admin-password <pwd> <site>` sets a known cmkadmin password at
  creation time instead of leaving it randomly generated.
- A fresh site auto-provisions a default `automation` user, with its secret
  readable at `var/check_mk/web/automation/automation.secret` relative to the
  site home directory — no separate user-creation step is required in the
  common case.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class SiteBootstrapError(RuntimeError):
    pass


@dataclass
class SiteCredentials:
    site: str
    automation_user: str
    automation_secret: str


CHECKMK_NOT_INSTALLED_INSTRUCTIONS = """\
Checkmk doesn't appear to be installed on this host (the 'omd' command
wasn't found on PATH).

1. Download the Community Edition package for your distro from
   https://checkmk.com/download
2. Install it, e.g. on Debian/Ubuntu:
     apt install /path/to/check-mk-community-<version>_<codename>_<arch>.deb
   (see https://docs.checkmk.com/latest/en/install_packages_debian.html for
   RPM-based distros and other install methods)
3. Re-run this wizard."""


def omd_installed() -> bool:
    """Whether the `omd` command is available — i.e. Checkmk is installed."""
    return shutil.which("omd") is not None


def site_home(site: str) -> Path:
    return Path(f"/omd/sites/{site}")


def site_exists(site: str) -> bool:
    return site_home(site).is_dir()


def list_sites() -> list[str]:
    """List every OMD site on this host. Each site is a directory under
    `/omd/sites/` (same convention `site_home()`/`site_exists()` already
    rely on) — reading the directory listing directly avoids parsing
    `omd sites`' table-formatted CLI output.
    """
    sites_root = Path("/omd/sites")
    if not sites_root.is_dir():
        return []
    return sorted(p.name for p in sites_root.iterdir() if p.is_dir())


def create_site(site: str, admin_password: str) -> str:
    """Create a new OMD site with a known cmkadmin password.

    Returns the command's stdout — `omd create` prints per-step progress
    (post-create scripts, core config generation, etc.) there, not just on
    failure. Verified live: a failure (e.g. one post-create script erroring
    out) can leave the actionable detail on stdout with stderr empty, so
    both streams are captured in the raised error rather than stderr alone.
    """
    result = subprocess.run(
        ["omd", "create", "--admin-password", admin_password, site],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SiteBootstrapError(f"omd create failed:\n{result.stdout}{result.stderr}".strip())
    return result.stdout


def start_site(site: str) -> str:
    """Start every daemon of an OMD site.

    Returns the command's stdout — `omd start` prints one line per daemon
    (`Starting apache...OK`, etc.), not just on failure. Verified live: a
    single-daemon failure (e.g. a port already in use) does propagate to
    the process's exit code, but the "which daemon, and why" detail is on
    stdout (`Starting apache.............failed`) with the underlying
    reason on stderr — both are needed, and both were previously discarded
    on success and stdout was dropped entirely even on failure.

    Also live-verified: `omd start` on a site that's **already fully
    running** returns a nonzero exit code (2) too, even though every
    daemon just reports "already running"/"already started" — not a real
    failure. The wizard's "reuse an existing site" path calls this
    unconditionally (the ordinary case of re-running against a site it
    already started), so treating every nonzero exit as fatal broke the
    single most common re-run. `omd`'s stdout is the only signal available
    to tell the two apart: every genuine failure observed includes the
    literal word "failed"; the already-running case never does.
    """
    result = subprocess.run(["omd", "start", site], capture_output=True, text=True, check=False)
    if result.returncode != 0 and "failed" in result.stdout.lower():
        raise SiteBootstrapError(f"omd start failed:\n{result.stdout}{result.stderr}".strip())
    return result.stdout


def livestatus_tcp_enabled(site: str) -> bool:
    """Whether Livestatus-over-TCP is already turned on for this site."""
    result = subprocess.run(
        ["omd", "config", site, "show", "LIVESTATUS_TCP"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() == "on"


def site_running(site: str) -> bool:
    """Whether at least one daemon of this site is currently running.

    `omd status <site>` exits 0 (all running) or 1 (partially running) in
    either case some daemon is up; 2 means fully stopped.
    """
    result = subprocess.run(["omd", "status", site], capture_output=True, text=True, check=False)
    return result.returncode != 2


def enable_livestatus_tcp(site: str) -> None:
    """Turn on Livestatus-over-TCP for this site.

    Required unconditionally: the wizard's Phase 7 health check
    (`livestatus.query_host_states()`) connects over TCP, not the site's
    local UNIX socket, so it can run from a different container/host than
    Checkmk itself. Restarts the site if it was already running, since
    this setting only takes effect on daemon (re)start — a plain `omd
    start` on an already-running site is a no-op and won't pick it up.
    """
    if livestatus_tcp_enabled(site):
        return
    was_running = site_running(site)
    result = subprocess.run(
        ["omd", "config", site, "set", "LIVESTATUS_TCP", "on"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SiteBootstrapError(f"omd config set LIVESTATUS_TCP failed:\n{result.stdout}{result.stderr}".strip())
    if was_running:
        restart = subprocess.run(["omd", "restart", site], capture_output=True, text=True, check=False)
        if restart.returncode != 0 and "failed" in restart.stdout.lower():
            raise SiteBootstrapError(f"omd restart failed:\n{restart.stdout}{restart.stderr}".strip())


def remove_site(site: str) -> str:
    """Delete an OMD site entirely — stops it and removes its config, data,
    and system user/group. Only this site is affected; the Checkmk install
    itself (and any other sites) is untouched, so `create_site()` can be
    called again right after. `-f` before `rm` skips the interactive
    yes/NO confirmation `omd rm` normally requires (verified via context7:
    docs.checkmk.com/latest/en/omd_basics.html, "Deleting sites"). Returns
    the command's stdout (per-step teardown progress), same rationale as
    `create_site()`/`start_site()`.
    """
    result = subprocess.run(["omd", "-f", "rm", site], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SiteBootstrapError(f"omd rm failed:\n{result.stdout}{result.stderr}".strip())
    return result.stdout


def _parse_host_attributes(hosts_mk: Path) -> dict[str, dict]:
    """Extract the `host_attributes` dict from one WATO `hosts.mk` config
    file. These files are executable Python (Checkmk itself `exec`s them
    at startup — "Created by HostStorage"), but every value inside
    `host_attributes` is a plain literal (strings/dicts/numbers/lists).

    Parses the whole file as a real AST (`ast.parse` — this does not
    execute anything, just builds a syntax tree) and walks it for the
    exact `host_attributes.update({...})` call, then runs
    `ast.literal_eval()` directly on that argument's own AST node.
    Bug fixed 2026-08-27 (live-reported: delete-a-site never flagged any
    host at all) — an earlier regex-based version
    (`re.search(r"host_attributes\\.update\\((\\{.*\\})\\)", text,
    re.DOTALL)`) used a greedy `.*` that doesn't stop at the end of the
    `host_attributes.update(...)` call: every real `hosts.mk` has a later
    `folder_attributes.update({})` call too, so the greedy match ran all
    the way to *that* call's closing `})` instead, capturing extra
    trailing text and producing an unparseable string — `ast.literal_eval`
    then raised on every real file, silently returning `{}` every time.
    Parsing the real AST and taking one specific call's own argument node
    sidesteps this whole class of "where does the literal actually end"
    problem entirely, rather than trying to patch the regex.

    Returns {} if the expected call isn't found or the file doesn't parse
    (e.g. an unexpected format) rather than raising — this is a
    best-effort warning aid, not a config source of truth.
    """
    try:
        tree = ast.parse(hosts_mk.read_text())
    except (OSError, SyntaxError):
        return {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "update"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "host_attributes"
            and node.args
        ):
            try:
                return ast.literal_eval(node.args[0])
            except ValueError:
                return {}
    return {}


def list_agent_registered_hosts(site: str) -> list[tuple[str, str]]:
    """Every host in `site`'s config expected to have a real Checkmk agent
    installed (`tag_agent: cmk-agent` — set for both Linux and Windows
    hosts by `wizard._onboard_hosts()`), as `(hostname, ip)` pairs, sorted
    by hostname.

    WATO stores host configuration per-folder, each folder under its own
    `etc/check_mk/conf.d/wato/<folder-path>/hosts.mk` (live-verified
    against a real Checkmk 2.4.0p35 CE site), so every such file under the
    site is scanned — not just the root one.

    Used before deleting a site: each of these hosts likely has a live
    `cmk-agent-ctl` registration on the actual target machine that this
    wizard has no way to reach and clean up itself at delete-site time
    (Phase 1 doesn't have SSH credentials for hosts from a *previous* run)
    — the registration goes stale (pinned to a cert this site's deletion
    just destroyed) the moment the site is gone, so the caller should warn
    the operator to run `cmk-agent-ctl delete-all` on each one manually.
    """
    wato_root = site_home(site) / "etc" / "check_mk" / "conf.d" / "wato"
    hosts: dict[str, dict] = {}
    for hosts_mk in wato_root.rglob("hosts.mk"):
        hosts.update(_parse_host_attributes(hosts_mk))

    return sorted(
        (name, attrs.get("ipaddress", "?")) for name, attrs in hosts.items() if attrs.get("tag_agent") == "cmk-agent"
    )


def read_automation_secret(site: str, automation_user: str = "automation") -> str | None:
    """Read the automation secret from the site filesystem, if it exists.

    Returns None if the site doesn't have this automation user provisioned —
    the caller should fall back to prompting the user to create one manually
    via Setup > Users in the web UI.
    """
    secret_path = site_home(site) / "var" / "check_mk" / "web" / automation_user / "automation.secret"
    if not secret_path.is_file():
        return None
    return secret_path.read_text().strip()


def get_site_credentials(site: str, automation_user: str = "automation") -> SiteCredentials | None:
    secret = read_automation_secret(site, automation_user)
    if secret is None:
        return None
    return SiteCredentials(site=site, automation_user=automation_user, automation_secret=secret)
