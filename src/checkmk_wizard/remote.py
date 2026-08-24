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
                cmd = f"ufw allow {port}/tcp"
            elif (await conn.run("command -v firewall-cmd", check=False)).exit_status == 0:
                cmd = (
                    f"firewall-cmd --permanent --add-port={port}/tcp && firewall-cmd --reload"
                )
            elif (await conn.run("command -v nft", check=False)).exit_status == 0:
                cmd = f"nft add rule inet filter input tcp dport {port} accept"
            else:
                return ActionResult(
                    Outcome.FAILED_FALLBACK_MANUAL, "No recognized firewall backend found", manual
                )

            result = await conn.run(f"sudo {cmd}", check=False)
            if result.exit_status != 0:
                return ActionResult(
                    Outcome.FAILED_FALLBACK_MANUAL,
                    f"Command failed: {cmd} ({result.stderr})",
                    manual,
                )
            return ActionResult(Outcome.AUTOMATED, f"Applied: {cmd}")
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


def windows_register_command(
    hostname: str, server: str, site: str, user: str, password: str
) -> str:
    return (
        '& "C:\\Program Files (x86)\\checkmk\\service\\cmk-agent-ctl.exe" register '
        f"--hostname {hostname} --server {server} --site {site} "
        f'--user {user} --password "{password}"'
    )


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
    expected_sha256 = hashlib.sha256(package_bytes).hexdigest()
    try:
        async with await _connect(host, creds) as conn, conn.start_sftp_client() as sftp:
            async with sftp.open(remote_path, "wb") as f:
                await f.write(package_bytes)

            # A successful SFTP write only means no exception was raised —
            # it doesn't confirm the bytes that landed on disk match what
            # was sent (silent truncation/corruption on a bad connection
            # wouldn't raise). Verify with a checksum before installing.
            checksum_result = await conn.run(f"sha256sum {shlex.quote(remote_path)}", check=False)
            if checksum_result.exit_status != 0:
                return ActionResult(
                    Outcome.FAILED_FALLBACK_MANUAL,
                    f"Could not verify uploaded package (sha256sum failed: {checksum_result.stderr})",
                    manual,
                )
            checksum_output = checksum_result.stdout if isinstance(checksum_result.stdout, str) else ""
            remote_sha256 = checksum_output.split()[0] if checksum_output.split() else ""
            if remote_sha256 != expected_sha256:
                return ActionResult(
                    Outcome.FAILED_FALLBACK_MANUAL,
                    "Uploaded package checksum mismatch — transfer may be corrupted "
                    f"(expected {expected_sha256[:12]}…, got {remote_sha256[:12] or '(none)'}…)",
                    manual,
                )

            if package_filename.endswith(".deb"):
                install_cmd = f"sudo dpkg -i {shlex.quote(remote_path)}"
            elif package_filename.endswith(".rpm"):
                install_cmd = f"sudo rpm -i {shlex.quote(remote_path)}"
            else:
                return ActionResult(
                    Outcome.FAILED_FALLBACK_MANUAL,
                    f"Unrecognized package type: {package_filename}",
                    manual,
                )

            result = await conn.run(install_cmd, check=False)
            if result.exit_status != 0:
                return ActionResult(
                    Outcome.FAILED_FALLBACK_MANUAL,
                    f"Install failed: {result.stderr}",
                    manual,
                )

            reg_result = await conn.run(f"sudo {register_cmd}", check=False)
            if reg_result.exit_status != 0:
                return ActionResult(
                    Outcome.FAILED_FALLBACK_MANUAL,
                    f"Registration failed: {reg_result.stderr}",
                    manual,
                )
            return ActionResult(Outcome.AUTOMATED, "Package installed and agent registered")
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
            result = await conn.run("cmk-agent-ctl status", check=False)
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
