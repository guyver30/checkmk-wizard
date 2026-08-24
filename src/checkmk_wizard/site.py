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


def create_site(site: str, admin_password: str) -> None:
    """Create a new OMD site with a known cmkadmin password."""
    result = subprocess.run(
        ["omd", "create", "--admin-password", admin_password, site],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SiteBootstrapError(f"omd create failed: {result.stderr.strip()}")


def start_site(site: str) -> None:
    result = subprocess.run(["omd", "start", site], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SiteBootstrapError(f"omd start failed: {result.stderr.strip()}")


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
