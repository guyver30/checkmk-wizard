"""Phase 5.1 (firewall) and 5.2 (agent install) — SSH automation for Linux,
manual-instructions generation for Windows, with a full-manual fallback on
any failure.

Verified facts used here (via context7 against live Checkmk docs):
- Agent Receiver port is 8000 (`omd config show | grep AGENT_RECEIVER`).
- `cmk-agent-ctl register --hostname --server --site --user --password`
  must run locally on the target host — it cannot be invoked remotely via
  the REST API.
- Windows equivalent is `cmk-agent-ctl.exe register` with the same flags
  (or short flags -H -s -i -U).
- Linux agent packages are published by distro family: RPM for RHEL-based
  systems, SLES, Fedora, and openSUSE; DEB for Debian, Ubuntu, and other
  DEB-based distributions (docs.checkmk.com/latest/en/agent_linux.html,
  "Downloading RPM/DEB packages") — not per exact distro/version match.
- `cmk-agent-ctl status` reports a `Connection: <server>/<site>` line per
  registered connection (docs.checkmk.com/latest/en/hosts_autoregister.html,
  "Check Agent Controller status").
"""

from __future__ import annotations

import asyncio
import hashlib
import shlex
from dataclasses import dataclass
from enum import Enum

import asyncssh

AGENT_RECEIVER_PORT = 8000


class Outcome(str, Enum):
    AUTOMATED = "automated"
    MANUAL_REQUIRED = "manual_required"  # by design (e.g. Windows)
    FAILED_FALLBACK_MANUAL = "failed_fallback_manual"


@dataclass
class SSHCredentials:
    username: str
    password: str | None = None
    private_key_path: str | None = None
    # Only set when `check_sudo()` (during initial SSH setup) finds the
    # account needs a password to elevate — None means either passwordless
    # sudo (NOPASSWD) or that it hasn't been checked yet. Kept separate
    # from `password` since a login password and a sudo password aren't
    # guaranteed to be the same.
    sudo_password: str | None = None


@dataclass
class PortProbeResult:
    reachable: bool
    classification: str  # "open" | "closed_rst" | "filtered_or_down"


@dataclass
class ActionResult:
    outcome: Outcome
    detail: str
    manual_instructions: str | None = None


@dataclass
class OSRelease:
    id: str
    version_id: str
    id_like: str = ""

    @classmethod
    def parse(cls, text: str) -> OSRelease:
        values: dict[str, str] = {}
        for line in text.splitlines():
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"')
        return cls(
            id=values.get("ID", "unknown"),
            version_id=values.get("VERSION_ID", "unknown"),
            id_like=values.get("ID_LIKE", ""),
        )


# Checkmk publishes Linux agent packages by distro family, not per exact
# distro/version (verified via context7: docs.checkmk.com/latest/en/
# agent_linux.html, "Downloading RPM/DEB packages" — "RPM packages are
# intended for RHEL-based systems, SLES, Fedora, and openSUSE, while DEB
# packages are used for Debian, Ubuntu, and other DEB-based distributions").
# Classification uses ID + ID_LIKE (the standard freedesktop.org os-release
# fallback convention) so derivatives (Rocky/Alma/Mint/etc.) are recognized
# without an exhaustive distro list.
_DEB_FAMILY = {"debian", "ubuntu"}
_RPM_FAMILY = {"rhel", "fedora", "centos", "suse", "opensuse"}


def package_family(os_release: OSRelease) -> str | None:
    """Classify a target's agent-package family as "deb" or "rpm" from its
    /etc/os-release ID/ID_LIKE. Returns None if neither family matches.
    """
    tokens = {os_release.id, *os_release.id_like.split()}
    if tokens & _DEB_FAMILY:
        return "deb"
    if tokens & _RPM_FAMILY:
        return "rpm"
    return None


# smartmontools .deb packages bundled with the wizard (docs/smart/) — the
# target host has no internet access, so `apt install smartmontools` isn't
# an option. Only the exact Ubuntu releases the wizard ships a package for
# are supported; unlike `package_family` above (a same-family package works
# across any Debian/Ubuntu derivative), a smartmontools .deb is built
# against a specific release's libc/libssl, so this matches on the precise
# VERSION_ID rather than the broader ID_LIKE family.
_SMARTMONTOOLS_DEB_BY_UBUNTU_VERSION = {
    "20.04": "smartmontools_7.1-1build1_amd64(Focal).deb",
    "22.04": "smartmontools_7.2-1build2_amd64(Jammy).deb",
    "24.04": "smartmontools_7.4-2build1_amd64(Noble).deb",
}


def smartmontools_deb_filename(target: OSRelease) -> str | None:
    """The bundled smartmontools .deb filename (under docs/smart/) matching
    this target's exact Ubuntu release, or None if the target isn't Ubuntu
    or isn't one of the releases bundled with the wizard.
    """
    if target.id != "ubuntu":
        return None
    return _SMARTMONTOOLS_DEB_BY_UBUNTU_VERSION.get(target.version_id)


@dataclass
class CompatibilityCheck:
    compatible: bool
    target: OSRelease
    package_family: str | None
    message: str


@dataclass
class AgentStatusCheck:
    verified: bool
    detail: str


async def probe_port(host: str, port: int, timeout: float = 3.0) -> PortProbeResult:
    """Distinguish an open port from a closed (RST) vs. filtered/unreachable one.

    A plain TCP connect can make this distinction without raw sockets:
    ConnectionRefusedError means the remote stack sent RST (port closed);
    a timeout means no response came back at all (filtered or host down).
    """
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        return PortProbeResult(reachable=True, classification="open")
    except ConnectionRefusedError:
        return PortProbeResult(reachable=False, classification="closed_rst")
    except (TimeoutError, OSError):
        return PortProbeResult(reachable=False, classification="filtered_or_down")


async def _connect(host: str, creds: SSHCredentials) -> asyncssh.SSHClientConnection:
    kwargs: dict[str, object] = {"username": creds.username, "known_hosts": None}
    if creds.private_key_path:
        kwargs["client_keys"] = [creds.private_key_path]
    if creds.password:
        kwargs["password"] = creds.password
    return await asyncssh.connect(host, **kwargs)


async def check_ssh_reachable(host: str, creds: SSHCredentials, timeout: float = 5.0) -> bool:
    try:
        conn = await asyncio.wait_for(_connect(host, creds), timeout=timeout)
        conn.close()
        return True
    except (TimeoutError, OSError, asyncssh.Error):
        return False


async def _run_sudo(
    conn: asyncssh.SSHClientConnection, creds: SSHCredentials, cmd: str, check: bool = False
) -> asyncssh.SSHCompletedProcess:
    """Run `cmd` with sudo, feeding `creds.sudo_password` over stdin via
    `-S` unconditionally. Harmless when sudo doesn't actually need a
    password (NOPASSWD, or a live cached credential) — `-S` only changes
    *where* sudo reads a password from if it needs one, so this is safe to
    use as the one code path for every sudo invocation rather than
    branching on whether the account was found to need a password.
    `-p ''` suppresses the "[sudo] password for user:" prompt text so it
    doesn't get mixed into stdout/stderr. Every sudo call gets its own
    fresh `-S` authentication rather than `&&`-chaining multiple sudo
    commands in one shell line — sudo's cached-credential lifetime/scoping
    across non-interactive, non-tty SSH exec channels isn't reliable
    enough to depend on.
    """
    return await conn.run(f"sudo -S -p '' {cmd}", input=(creds.sudo_password or "") + "\n", check=check)


async def check_sudo(host: str, creds: SSHCredentials) -> bool:
    """Whether `creds` (including `creds.sudo_password`, if set) can
    actually elevate on `host`. Checked once up front during SSH setup —
    see `wizard._establish_ssh_access()` — so a missing/wrong sudo
    password surfaces immediately as one clear prompt, instead of as a
    string of unexplained `FAILED_FALLBACK_MANUAL` results deep in the
    per-host onboarding loop (every firewall/install/plugin step below
    needs sudo). Returns False (not an exception) if SSH itself fails,
    same convention as `check_ssh_reachable`.
    """
    try:
        async with await _connect(host, creds) as conn:
            result = await _run_sudo(conn, creds, "true")
            return result.exit_status == 0
    except (OSError, asyncssh.Error):
        return False


async def list_running_systemd_services(host: str, creds: SSHCredentials) -> list[str] | None:
    """SSH in and list currently-running systemd service units, by name
    with the `.service` suffix stripped — live-verified against a real
    Checkmk 2.4.0p35 CE site (installed the real agent on a live systemd
    host, read its own discovery-parsing source): Checkmk's systemd
    plugin strips that suffix from the unit name before matching a
    discovery rule against it, so a rule built from the raw
    "apache2.service" form would silently match nothing. Returns None if
    SSH is unreachable or the command fails — caller falls back to
    manual entry, same as the other remote.py automation here.
    """
    if not await check_ssh_reachable(host, creds):
        return None
    try:
        async with await _connect(host, creds) as conn:
            result = await conn.run(
                "systemctl list-units --type=service --state=running --no-legend --plain", check=False
            )
            if result.exit_status != 0:
                return None
            output = result.stdout if isinstance(result.stdout, str) else ""
            names = []
            for line in output.splitlines():
                fields = line.split()
                if not fields:
                    continue
                unit = fields[0].removesuffix(".service")
                if unit:
                    names.append(unit)
            return names
    except (OSError, asyncssh.Error):
        return None


def windows_firewall_instructions(port: int) -> str:
    return (
        f"New-NetFirewallRule -DisplayName \"Checkmk Agent Receiver {port}\" "
        f"-Direction Inbound -Protocol TCP -LocalPort {port} -Action Allow"
    )


async def fix_firewall_linux(host: str, creds: SSHCredentials, port: int) -> ActionResult:
    """Detect the Linux firewall backend over SSH and add an allow rule."""
    manual = (
        f"On the target host, allow inbound TCP {port}, e.g.:\n"
        f"  ufw allow {port}/tcp\n"
        f"  # or: firewall-cmd --permanent --add-port={port}/tcp && firewall-cmd --reload\n"
        f"  # or: nft add rule inet filter input tcp dport {port} accept"
    )
    if not await check_ssh_reachable(host, creds):
        return ActionResult(Outcome.FAILED_FALLBACK_MANUAL, "SSH unreachable", manual)

    try:
        async with await _connect(host, creds) as conn:
            if (await conn.run("command -v ufw", check=False)).exit_status == 0:
                commands = [f"ufw allow {port}/tcp"]
            elif (await conn.run("command -v firewall-cmd", check=False)).exit_status == 0:
                # Two separate sudo invocations, not one `&&`-chained
                # command — `sudo cmd1 && cmd2` only elevates cmd1, so
                # `firewall-cmd --reload` would silently run unprivileged
                # and fail (this was a live bug before `_run_sudo()` made
                # each sudo call explicit).
                commands = [f"firewall-cmd --permanent --add-port={port}/tcp", "firewall-cmd --reload"]
            elif (await conn.run("command -v nft", check=False)).exit_status == 0:
                commands = [f"nft add rule inet filter input tcp dport {port} accept"]
            else:
                return ActionResult(
                    Outcome.FAILED_FALLBACK_MANUAL, "No recognized firewall backend found", manual
                )

            for cmd in commands:
                result = await _run_sudo(conn, creds, cmd)
                if result.exit_status != 0:
                    return ActionResult(
                        Outcome.FAILED_FALLBACK_MANUAL,
                        f"Command failed: {cmd} ({result.stderr})",
                        manual,
                    )
            return ActionResult(Outcome.AUTOMATED, f"Applied: {' && '.join(commands)}")
    except (OSError, asyncssh.Error) as exc:
        return ActionResult(Outcome.FAILED_FALLBACK_MANUAL, str(exc), manual)


async def check_os_compatibility(host: str, creds: SSHCredentials) -> CompatibilityCheck | None:
    """Classify the target's agent-package family (deb/rpm) from its own
    /etc/os-release. This does NOT compare against the Checkmk host's own
    OS — Checkmk publishes agent packages per distro *family*, so a target
    running a different distro in the same family (e.g. Debian target vs.
    Ubuntu Checkmk host, both deb-based) installs fine. Returns None if the
    check itself couldn't run (e.g. SSH unreachable) — caller should fall
    back to manual.
    """
    if not await check_ssh_reachable(host, creds):
        return None
    try:
        async with await _connect(host, creds) as conn:
            result = await conn.run("cat /etc/os-release", check=False)
            if result.exit_status != 0:
                return None
            target = OSRelease.parse(result.stdout if isinstance(result.stdout, str) else "")
    except (OSError, asyncssh.Error, FileNotFoundError):
        return None

    family = package_family(target)
    if family is not None:
        message = f"Target OS is {target.id} {target.version_id} — using {family} packages."
    else:
        message = (
            f"Target OS is {target.id} {target.version_id}, which isn't a recognized "
            "Debian/Ubuntu-family (deb) or RHEL/SLES/Fedora/openSUSE-family (rpm) distro. "
            "Can't determine which agent package to install."
        )
    return CompatibilityCheck(compatible=family is not None, target=target, package_family=family, message=message)


def linux_register_command(
    hostname: str, server: str, site: str, user: str, password: str
) -> str:
    return (
        "cmk-agent-ctl register "
        f"--hostname {shlex.quote(hostname)} "
        f"--server {shlex.quote(server)} "
        f"--site {shlex.quote(site)} "
        f"--user {shlex.quote(user)} "
        f"--password {shlex.quote(password)}"
    )


def _ps_quote(value: str) -> str:
    """Quote a value for PowerShell as a single-quoted (non-interpolating)
    string literal — doubling embedded single quotes is PowerShell's escape
    for them, and single-quoting avoids `$`-variable interpolation that a
    double-quoted string would trigger on a hostname/password containing `$`.
    """
    return "'" + value.replace("'", "''") + "'"


def windows_register_command(
    hostname: str, server: str, site: str, user: str, password: str
) -> str:
    return (
        '& "C:\\Program Files (x86)\\checkmk\\service\\cmk-agent-ctl.exe" register '
        f"--hostname {_ps_quote(hostname)} --server {_ps_quote(server)} --site {_ps_quote(site)} "
        f"--user {_ps_quote(user)} --password {_ps_quote(password)}"
    )


async def _upload_verified(
    conn: asyncssh.SSHClientConnection, sftp: asyncssh.SFTPClient, package_bytes: bytes, remote_path: str
) -> str | None:
    """Write bytes to `remote_path` over SFTP and confirm they landed intact
    with a checksum. A successful SFTP write only means no exception was
    raised — it doesn't confirm the bytes that landed on disk match what
    was sent (silent truncation/corruption on a bad connection wouldn't
    raise). Returns an error message on mismatch/failure, None on success.
    """
    async with sftp.open(remote_path, "wb") as f:
        await f.write(package_bytes)

    expected_sha256 = hashlib.sha256(package_bytes).hexdigest()
    checksum_result = await conn.run(f"sha256sum {shlex.quote(remote_path)}", check=False)
    if checksum_result.exit_status != 0:
        return f"Could not verify uploaded file (sha256sum failed: {checksum_result.stderr})"
    checksum_output = checksum_result.stdout if isinstance(checksum_result.stdout, str) else ""
    remote_sha256 = checksum_output.split()[0] if checksum_output.split() else ""
    if remote_sha256 != expected_sha256:
        return (
            "Uploaded file checksum mismatch — transfer may be corrupted "
            f"(expected {expected_sha256[:12]}…, got {remote_sha256[:12] or '(none)'}…)"
        )
    return None


async def check_agent_installed(host: str, creds: SSHCredentials, pkg_family: str) -> bool:
    """Whether the `check-mk-agent` package is already present on the
    target, checked before attempting a fresh install so a host that
    already has it doesn't get a redundant upload + package-manager
    invocation — `dpkg -i`/`rpm -i` on top of an existing install isn't
    dangerous (dpkg reinstalls in place; rpm just errors "already
    installed"), but it wastes an SFTP upload and a full package op for
    no benefit. Returns False (not an exception) on any SSH failure, same
    convention as `check_ssh_reachable`/`check_sudo` — callers then take
    the normal fresh-install path, which itself already handles
    unreachable SSH.
    """
    query_cmd = "dpkg -s check-mk-agent" if pkg_family == "deb" else "rpm -q check-mk-agent"
    try:
        async with await _connect(host, creds) as conn:
            result = await conn.run(f"{query_cmd} >/dev/null 2>&1", check=False)
            return result.exit_status == 0
    except (OSError, asyncssh.Error):
        return False


async def register_agent_linux(host: str, creds: SSHCredentials, register_cmd: str) -> ActionResult:
    """Run `cmk-agent-ctl register` on a target where the agent package is
    already installed (see `check_agent_installed()`) — split out from
    `install_agent_linux()` so that case can skip straight to registration
    instead of re-uploading and reinstalling a package that's already
    there.
    """
    manual = f"Run on the target host: {register_cmd}"
    if not await check_ssh_reachable(host, creds):
        return ActionResult(Outcome.FAILED_FALLBACK_MANUAL, "SSH unreachable", manual)
    try:
        async with await _connect(host, creds) as conn:
            reg_result = await _run_sudo(conn, creds, register_cmd)
            if reg_result.exit_status != 0:
                return ActionResult(Outcome.FAILED_FALLBACK_MANUAL, f"Registration failed: {reg_result.stderr}", manual)
            return ActionResult(Outcome.AUTOMATED, "Agent already installed; registered")
    except (OSError, asyncssh.Error) as exc:
        return ActionResult(Outcome.FAILED_FALLBACK_MANUAL, str(exc), manual)


async def install_agent_linux(
    host: str,
    creds: SSHCredentials,
    package_bytes: bytes,
    package_filename: str,
    register_cmd: str,
) -> ActionResult:
    """Push the agent package over SFTP, install it, and register it locally
    on the target host (registration cannot be done remotely via the API).
    """
    manual = (
        f"1. Download the agent package from the Checkmk host and copy it to the target.\n"
        f"2. Install it: sudo dpkg -i {package_filename}  (or: sudo rpm -i {package_filename})\n"
        f"3. Run on the target host: {register_cmd}"
    )
    if not await check_ssh_reachable(host, creds):
        return ActionResult(Outcome.FAILED_FALLBACK_MANUAL, "SSH unreachable", manual)

    remote_path = f"/tmp/{package_filename}"
    try:
        async with await _connect(host, creds) as conn, conn.start_sftp_client() as sftp:
            error = await _upload_verified(conn, sftp, package_bytes, remote_path)
            if error:
                return ActionResult(Outcome.FAILED_FALLBACK_MANUAL, error, manual)

            if package_filename.endswith(".deb"):
                install_cmd = f"dpkg -i {shlex.quote(remote_path)}"
            elif package_filename.endswith(".rpm"):
                install_cmd = f"rpm -i {shlex.quote(remote_path)}"
            else:
                return ActionResult(
                    Outcome.FAILED_FALLBACK_MANUAL,
                    f"Unrecognized package type: {package_filename}",
                    manual,
                )

            result = await _run_sudo(conn, creds, install_cmd)
            if result.exit_status != 0:
                return ActionResult(
                    Outcome.FAILED_FALLBACK_MANUAL,
                    f"Install failed: {result.stderr}",
                    manual,
                )

            reg_result = await _run_sudo(conn, creds, register_cmd)
            if reg_result.exit_status != 0:
                return ActionResult(
                    Outcome.FAILED_FALLBACK_MANUAL,
                    f"Registration failed: {reg_result.stderr}",
                    manual,
                )
            return ActionResult(Outcome.AUTOMATED, "Package installed and agent registered")
    except (OSError, asyncssh.Error) as exc:
        return ActionResult(Outcome.FAILED_FALLBACK_MANUAL, str(exc), manual)


async def install_smartmontools(
    host: str, creds: SSHCredentials, package_bytes: bytes, package_filename: str
) -> ActionResult:
    """Install smartmontools from a bundled .deb (docs/smart/) — the target
    has no internet access, so `apt install smartmontools` isn't an option.
    Caller picks the right bundled package via `smartmontools_deb_filename()`.
    """
    manual = (
        f"1. Copy the matching smartmontools .deb (see docs/smart/) to the target host.\n"
        f"2. Install it: sudo dpkg -i {package_filename}"
    )
    if not await check_ssh_reachable(host, creds):
        return ActionResult(Outcome.FAILED_FALLBACK_MANUAL, "SSH unreachable", manual)

    remote_path = f"/tmp/{package_filename}"
    try:
        async with await _connect(host, creds) as conn, conn.start_sftp_client() as sftp:
            error = await _upload_verified(conn, sftp, package_bytes, remote_path)
            if error:
                return ActionResult(Outcome.FAILED_FALLBACK_MANUAL, error, manual)

            result = await _run_sudo(conn, creds, f"dpkg -i {shlex.quote(remote_path)}")
            if result.exit_status != 0:
                return ActionResult(Outcome.FAILED_FALLBACK_MANUAL, f"Install failed: {result.stderr}", manual)
            return ActionResult(Outcome.AUTOMATED, "smartmontools installed")
    except (OSError, asyncssh.Error) as exc:
        return ActionResult(Outcome.FAILED_FALLBACK_MANUAL, str(exc), manual)


async def verify_smartmontools(host: str, creds: SSHCredentials) -> ActionResult:
    """Confirm smartctl actually works and turn SMART monitoring on for
    every drive it can see, right after installing the package —
    `dpkg -i` exiting 0 only means the package unpacked cleanly, it doesn't
    confirm the binary runs or that any drive has SMART enabled (a drive
    with SMART support disabled reports no attributes at all, so the
    `smart_posix` plugin installed next would silently have nothing to
    report). The version-7 check mirrors the same floor `smart_posix`
    itself enforces (see docs/smart/smart_posix — "smartctl version 7 or
    newer is required").
    """
    manual = "On the target host, run: smartctl -V (expect version 7+); smartctl --scan; smartctl -s on <device> for each drive listed."
    if not await check_ssh_reachable(host, creds):
        return ActionResult(Outcome.FAILED_FALLBACK_MANUAL, "SSH unreachable", manual)

    try:
        async with await _connect(host, creds) as conn:
            # `smartctl` needs root for anything beyond printing its own
            # version — even `--scan` can miss or misidentify devices when
            # run unprivileged (it can't send the ATA/SCSI passthrough
            # probes needed to fully identify a device without raw access
            # to /dev/sdX), which was live-reported as a downstream
            # "could not enable" failure on a device --scan itself found.
            # `-V` alone doesn't strictly need it, but running it via sudo
            # too keeps this whole function consistent and avoids relying
            # on that distinction holding on every distro/smartctl build.
            version_result = await _run_sudo(conn, creds, "smartctl -V")
            version_output = version_result.stdout if isinstance(version_result.stdout, str) else ""
            first_line = version_output.splitlines()[0] if version_output.splitlines() else ""
            if version_result.exit_status != 0 or not first_line.startswith("smartctl 7"):
                return ActionResult(
                    Outcome.FAILED_FALLBACK_MANUAL,
                    f"smartctl did not report version 7+ after install (got: {first_line or version_result.stderr})",
                    manual,
                )

            scan_result = await _run_sudo(conn, creds, "smartctl --scan | awk '{print $1}'")
            scan_output = scan_result.stdout if isinstance(scan_result.stdout, str) else ""
            devices = [line.strip() for line in scan_output.splitlines() if line.strip()]
            if not devices:
                return ActionResult(Outcome.AUTOMATED, "smartctl works (version 7+) but found no drives to enable SMART on")

            enabled, failed = [], []
            for device in devices:
                enable_result = await _run_sudo(conn, creds, f"smartctl -s on {shlex.quote(device)}")
                (enabled if enable_result.exit_status == 0 else failed).append(device)

            detail = f"smartctl 7+ confirmed; SMART enabled on {len(enabled)}/{len(devices)} device(s)"
            if failed:
                detail += f" (could not enable on: {', '.join(failed)})"
            return ActionResult(Outcome.AUTOMATED, detail)
    except (OSError, asyncssh.Error) as exc:
        return ActionResult(Outcome.FAILED_FALLBACK_MANUAL, str(exc), manual)


AGENT_PLUGINS_DIR = "/usr/lib/check_mk_agent/plugins"


async def deploy_agent_plugin(
    host: str, creds: SSHCredentials, plugin_bytes: bytes, plugin_name: str
) -> ActionResult:
    """Copy an agent plugin script (e.g. `smart_posix`) into the Checkmk
    agent's plugin directory and make it executable, so the next service
    discovery on this host picks up whatever sections/checks it reports.

    `AGENT_PLUGINS_DIR` is root-owned (0755, live-verified against the
    check-mk-agent .deb's own file list), so a non-root SSH user can't SFTP
    directly into it — stage the file under /tmp (same pattern as
    `install_agent_linux`/`install_smartmontools`) and move it into place
    with sudo.
    """
    final_path = f"{AGENT_PLUGINS_DIR}/{plugin_name}"
    manual = (
        f"Copy the plugin to the target host and run:\n"
        f"  sudo mv <plugin> {final_path}\n"
        f"  sudo chmod +x {final_path}"
    )
    if not await check_ssh_reachable(host, creds):
        return ActionResult(Outcome.FAILED_FALLBACK_MANUAL, "SSH unreachable", manual)

    staged_path = f"/tmp/{plugin_name}"
    try:
        async with await _connect(host, creds) as conn, conn.start_sftp_client() as sftp:
            error = await _upload_verified(conn, sftp, plugin_bytes, staged_path)
            if error:
                return ActionResult(Outcome.FAILED_FALLBACK_MANUAL, error, manual)

            mv_result = await _run_sudo(conn, creds, f"mv {shlex.quote(staged_path)} {shlex.quote(final_path)}")
            if mv_result.exit_status != 0:
                return ActionResult(Outcome.FAILED_FALLBACK_MANUAL, f"Deploy failed (mv): {mv_result.stderr}", manual)

            chmod_result = await _run_sudo(conn, creds, f"chmod +x {shlex.quote(final_path)}")
            if chmod_result.exit_status != 0:
                return ActionResult(
                    Outcome.FAILED_FALLBACK_MANUAL, f"Deploy failed (chmod): {chmod_result.stderr}", manual
                )
            return ActionResult(Outcome.AUTOMATED, f"Plugin deployed to {final_path}")
    except (OSError, asyncssh.Error) as exc:
        return ActionResult(Outcome.FAILED_FALLBACK_MANUAL, str(exc), manual)


def agent_status_shows_connection(output: str, site: str) -> bool:
    """Whether `cmk-agent-ctl status` output includes a `Connection:` line
    for the given site (format confirmed via context7:
    docs.checkmk.com/latest/en/hosts_autoregister.html — "Connection:
    myserver/mysite").
    """
    suffix = f"/{site}"
    return any(
        line.strip().startswith("Connection:") and line.strip().endswith(suffix)
        for line in output.splitlines()
    )


async def check_agent_status(host: str, creds: SSHCredentials, site: str) -> AgentStatusCheck:
    """Run `cmk-agent-ctl status` on the target after install+registration to
    confirm the agent controller is actually operational and recorded a
    connection for this site — rather than trusting the register command's
    exit code alone. This is a local check on the target (reads the agent
    controller's own state); it doesn't independently confirm the Checkmk
    server has accepted the host as UP — that's confirmed later, for the
    whole batch, by Phase 7's Livestatus query.
    """
    try:
        async with await _connect(host, creds) as conn:
            # cmk-agent-ctl drops from root to its own `cmk-agent` service
            # user internally, which needs real root privileges to set up
            # (setgroups) — running this unprivileged fails with exactly
            # the permission error `cmk-agent-ctl` itself reports ("Please
            # execute with sufficient permissions (maybe try 'sudo')"),
            # live-reported 2026-08-27. Every other cmk-agent-ctl
            # invocation here (register, in install_agent_linux/
            # register_agent_linux) already runs via `_run_sudo` — this
            # verification step was the one left behind.
            result = await _run_sudo(conn, creds, "cmk-agent-ctl status")
    except (OSError, asyncssh.Error) as exc:
        return AgentStatusCheck(verified=False, detail=f"Could not run cmk-agent-ctl status: {exc}")

    output = result.stdout if isinstance(result.stdout, str) else ""
    if result.exit_status != 0:
        detail = result.stderr if isinstance(result.stderr, str) and result.stderr else output
        return AgentStatusCheck(verified=False, detail=f"cmk-agent-ctl status exited {result.exit_status}: {detail}")

    if not agent_status_shows_connection(output, site):
        return AgentStatusCheck(
            verified=False,
            detail=f"cmk-agent-ctl status ran but reported no connection for site '{site}'",
        )
    return AgentStatusCheck(verified=True, detail="cmk-agent-ctl reports an active connection for this site")
