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
