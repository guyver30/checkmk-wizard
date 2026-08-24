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
"""

from __future__ import annotations

import asyncio
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

    @classmethod
    def parse(cls, text: str) -> OSRelease:
        values: dict[str, str] = {}
        for line in text.splitlines():
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"')
        return cls(id=values.get("ID", "unknown"), version_id=values.get("VERSION_ID", "unknown"))


@dataclass
class CompatibilityCheck:
    compatible: bool
    target: OSRelease
    expected: OSRelease
    message: str


def local_os_release(path: str = "/etc/os-release") -> OSRelease:
    with open(path) as f:
        return OSRelease.parse(f.read())


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
    """Compare the target's OS to the Checkmk host's own OS as a proxy for
    agent-package compatibility. Returns None if the check itself couldn't
    run (e.g. SSH unreachable) — caller should fall back to manual.
    """
    if not await check_ssh_reachable(host, creds):
        return None
    try:
        expected = local_os_release()
        async with await _connect(host, creds) as conn:
            result = await conn.run("cat /etc/os-release", check=False)
            if result.exit_status != 0:
                return None
            target = OSRelease.parse(result.stdout if isinstance(result.stdout, str) else "")
    except (OSError, asyncssh.Error, FileNotFoundError):
        return None

    compatible = target.id == expected.id and target.version_id == expected.version_id
    if compatible:
        message = f"Target OS ({target.id} {target.version_id}) matches the Checkmk host."
    else:
        message = (
            f"Target OS is {target.id} {target.version_id}, but the Checkmk host "
            f"(and its agent packages) is {expected.id} {expected.version_id}. "
            "The generic agent package may still install and run correctly, but this "
            "hasn't been verified for this combination."
        )
    return CompatibilityCheck(compatible=compatible, target=target, expected=expected, message=message)


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
    try:
        async with await _connect(host, creds) as conn, conn.start_sftp_client() as sftp:
            async with sftp.open(remote_path, "wb") as f:
                await f.write(package_bytes)

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
