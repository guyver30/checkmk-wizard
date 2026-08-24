"""Interactive terminal wizard orchestrating Phases 1-7 of the Checkmk Setup
Configurator (see docs/CHECKMK_SETUP_CONFIGURATOR_PLAN.md).
"""

from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import questionary
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from checkmk_wizard import livestatus, remote, site
from checkmk_wizard.api import CheckmkAPIError, CheckmkClient, CheckmkConnection
from checkmk_wizard.scanner import DEFAULT_PORTS, HostScanResult, scan_network

console = Console()


@dataclass
class OnboardedHost:
    ip: str
    hostname: str
    folder: str
    os_family: str  # "linux" | "windows"


@dataclass
class WizardState:
    connection: CheckmkConnection | None = None
    scan_results: list[HostScanResult] = field(default_factory=list)
    onboarded: list[OnboardedHost] = field(default_factory=list)


# ── Phase 1: Site bring-up ──────────────────────────────────────────────


async def phase1_site_bringup() -> CheckmkConnection:
    console.rule("[bold]Phase 1 — Site Bring-up")

    site_name = await questionary.text("Checkmk site name:").ask_async()
    checkmk_host = await questionary.text(
        "Hostname/IP to reach this Checkmk site on (as seen by agents/browser):",
        default="localhost",
    ).ask_async()

    if not site.site_exists(site_name):
        console.print(f"Site [bold]{site_name}[/bold] doesn't exist yet — creating it.")
        admin_password = secrets.token_urlsafe(16)
        site.create_site(site_name, admin_password)
        site.start_site(site_name)
        console.print(
            f"Site created. cmkadmin password (save this): [bold yellow]{admin_password}[/bold yellow]"
        )
    else:
        console.print(f"Site [bold]{site_name}[/bold] already exists — reusing it.")
        site.start_site(site_name)  # no-op if already running; omd handles that

    creds = site.get_site_credentials(site_name)
    if creds is None:
        console.print(
            "[yellow]No default 'automation' user secret found on disk.[/yellow]\n"
            "Create one manually: Setup > Users > Add user, authentication mode "
            "'Automation secret for machine accounts', then paste the secret below."
        )
        secret = await questionary.password("Automation secret:").ask_async()
        creds = site.SiteCredentials(site=site_name, automation_user="automation", automation_secret=secret)

    connection = CheckmkConnection(
        host=checkmk_host,
        site=site_name,
        username=creds.automation_user,
        secret=creds.automation_secret,
    )

    async with CheckmkClient(connection) as client:
        try:
            version = await client.get_version()
        except CheckmkAPIError as exc:
            console.print(f"[red]REST API check failed:[/red] {exc}")
            raise SystemExit(1) from exc
    console.print(f"[green]REST API reachable.[/green] Site version: {version.get('versions', version)}")
    return connection


# ── Phase 2: Folder structure (optional) ────────────────────────────────


async def phase2_folders(client: CheckmkClient) -> None:
    console.rule("[bold]Phase 2 — Folder Structure (optional)")
    use_folders = await questionary.confirm("Set up folders (one per VLAN/site)?", default=False).ask_async()
    if not use_folders:
        console.print("Skipping — all hosts will land in the root folder.")
        return

    raw = await questionary.text(
        "Comma-separated folder names (e.g. vlan10,vlan20):"
    ).ask_async()
    for name in [n.strip() for n in raw.split(",") if n.strip()]:
        try:
            await client.create_folder(name=name, title=name)
            console.print(f"  [green]created[/green] /{name}")
        except CheckmkAPIError as exc:
            console.print(f"  [red]failed[/red] /{name}: {exc}")


# ── Phase 3: Network discovery ──────────────────────────────────────────


async def phase3_discovery(client: CheckmkClient) -> list[HostScanResult]:
    console.rule("[bold]Phase 3 — Network Discovery (custom async scanner)")
    cidr = await questionary.text("Subnet/CIDR to scan (e.g. 192.168.10.0/24):").ask_async()
    port_input = await questionary.text(
        f"Ports to check, comma-separated (default {','.join(map(str, DEFAULT_PORTS))}):",
        default="",
    ).ask_async()
    ports = tuple(int(p) for p in port_input.split(",") if p.strip()) or DEFAULT_PORTS

    with Progress() as progress:
        task = progress.add_task("Scanning...", total=None)

        def on_progress(chunk, alive, total):
            progress.update(task, description=f"Scanned {chunk} — {alive}/{total} responsive")

        results = await scan_network(cidr, ports=ports, on_progress=on_progress)

    table = Table(title="Discovered hosts")
    table.add_column("IP")
    table.add_column("Open ports")
    for r in results:
        table.add_row(r.ip, ", ".join(map(str, r.open_ports)))
    console.print(table)

    for r in results:
        try:
            await client.create_host(host_name=r.ip, attributes={"ipaddress": r.ip})
        except CheckmkAPIError as exc:
            console.print(f"[yellow]Could not stage {r.ip}: {exc}[/yellow]")

    return results


# ── Phase 4: Host classification (manual, by design — no fingerprinting) ──


async def phase4_classification(scan_results: list[HostScanResult]) -> list[OnboardedHost]:
    console.rule("[bold]Phase 4 — Host Classification")
    console.print("No automatic fingerprinting — pick which IPs to promote to named hosts.")

    choices = [questionary.Choice(f"{r.ip} (ports: {r.open_ports})", value=r.ip) for r in scan_results]
    if not choices:
        console.print("No scanned hosts to promote.")
        return []

    selected_ips = await questionary.checkbox("Promote which hosts?", choices=choices).ask_async()

    onboarded: list[OnboardedHost] = []
    for ip in selected_ips:
        hostname = await questionary.text(f"Hostname for {ip}:", default=ip).ask_async()
        folder = await questionary.text(f"Folder for {hostname} (default /):", default="/").ask_async()
        os_family = await questionary.select(
            f"OS family for {hostname}:", choices=["linux", "windows"]
        ).ask_async()
        onboarded.append(OnboardedHost(ip=ip, hostname=hostname, folder=folder, os_family=os_family))
    return onboarded


# ── Phase 5: Host onboarding, firewall (5.1), agent install (5.2) ─────────


async def phase5_onboarding(
    client: CheckmkClient, connection: CheckmkConnection, hosts: list[OnboardedHost]
) -> None:
    console.rule("[bold]Phase 5 — Host Onboarding")
    if not hosts:
        return

    use_ssh = await questionary.confirm(
        "Attempt automated SSH firewall + agent install for Linux hosts?", default=True
    ).ask_async()
    ssh_creds: remote.SSHCredentials | None = None
    if use_ssh:
        username = await questionary.text("SSH username:").ask_async()
        auth_mode = await questionary.select("SSH auth method:", choices=["password", "private key"]).ask_async()
        if auth_mode == "password":
            password = await questionary.password("SSH password:").ask_async()
            ssh_creds = remote.SSHCredentials(username=username, password=password)
        else:
            key_path = await questionary.text("Private key path:").ask_async()
            ssh_creds = remote.SSHCredentials(username=username, private_key_path=key_path)

    for h in hosts:
        console.print(f"\n[bold]{h.hostname}[/bold] ({h.ip}, {h.os_family})")
        try:
            await client.create_host(
                host_name=h.hostname,
                folder=h.folder,
                attributes={"ipaddress": h.ip, "tag_agent": "cmk-agent"},
            )
        except CheckmkAPIError as exc:
            console.print(f"  [yellow]host create/update: {exc}[/yellow]")

        if h.os_family == "windows":
            console.print("  [cyan]Windows target — manual path (by design):[/cyan]")
            console.print(f"    Firewall: {remote.windows_firewall_instructions(remote.AGENT_RECEIVER_PORT)}")
            console.print(
                f"    Register: {remote.windows_register_command(h.hostname, connection.host, connection.site, connection.username, connection.secret)}"
            )
            continue

        # Linux
        probe = await remote.probe_port(h.ip, remote.AGENT_RECEIVER_PORT)
        console.print(f"  Port {remote.AGENT_RECEIVER_PORT} probe: {probe.classification}")

        if ssh_creds is None:
            console.print("  [yellow]No SSH credentials supplied — manual path.[/yellow]")
            _print_linux_manual(h, connection)
            continue

        fw_result = await remote.fix_firewall_linux(h.ip, ssh_creds, remote.AGENT_RECEIVER_PORT)
        console.print(f"  Firewall: [{'green' if fw_result.outcome.value == 'automated' else 'yellow'}]{fw_result.outcome.value}[/] — {fw_result.detail}")
        if fw_result.manual_instructions and fw_result.outcome != remote.Outcome.AUTOMATED:
            console.print(f"    {fw_result.manual_instructions}")

        compat = await remote.check_os_compatibility(h.ip, ssh_creds)
        proceed = True
        if compat is not None and not compat.compatible:
            console.print(f"  [yellow]{compat.message}[/yellow]")
            proceed = await questionary.confirm("Proceed anyway with the generic package?", default=False).ask_async()

        if not proceed:
            console.print("  Skipping agent install at user's request.")
            continue

        register_cmd = remote.linux_register_command(
            h.hostname, connection.host, connection.site, connection.username, connection.secret
        )
        try:
            package_bytes = await client.download_agent("linux_deb")
        except CheckmkAPIError as exc:
            console.print(f"  [red]Agent download failed: {exc}[/red]")
            _print_linux_manual(h, connection)
            continue

        install_result = await remote.install_agent_linux(
            h.ip, ssh_creds, package_bytes, "check-mk-agent.deb", register_cmd
        )
        color = "green" if install_result.outcome == remote.Outcome.AUTOMATED else "yellow"
        console.print(f"  Agent install: [{color}]{install_result.outcome.value}[/] — {install_result.detail}")
        if install_result.manual_instructions and install_result.outcome != remote.Outcome.AUTOMATED:
            console.print(f"    {install_result.manual_instructions}")


def _print_linux_manual(host: OnboardedHost, connection: CheckmkConnection) -> None:
    register_cmd = remote.linux_register_command(
        host.hostname, connection.host, connection.site, connection.username, connection.secret
    )
    console.print(f"    Firewall (ufw example): ufw allow {remote.AGENT_RECEIVER_PORT}/tcp")
    console.print(f"    Download agent from the Checkmk site, install it, then run: {register_cmd}")


# ── Phase 6: Discovery & baseline ───────────────────────────────────────


async def phase6_discovery(client: CheckmkClient, hosts: list[OnboardedHost]) -> None:
    console.rule("[bold]Phase 6 — Discovery & Baseline")
    for h in hosts:
        try:
            await client.start_service_discovery(h.hostname, mode="refresh")
            console.print(f"  [green]discovery started[/green] {h.hostname}")
        except CheckmkAPIError as exc:
            console.print(f"  [yellow]discovery failed[/yellow] {h.hostname}: {exc}")


# ── Phase 7: Activation & validation ────────────────────────────────────


async def phase7_activation(client: CheckmkClient, connection: CheckmkConnection, hosts: list[OnboardedHost]) -> None:
    console.rule("[bold]Phase 7 — Activation & Validation")
    try:
        etag = await client.get_pending_changes_etag()
        await client.activate_changes([connection.site], etag)
        console.print("[green]Changes activated.[/green]")
    except CheckmkAPIError as exc:
        console.print(f"[red]Activation failed: {exc}[/red]")
        return

    if hosts:
        states = livestatus.query_host_states(connection.site, [h.hostname for h in hosts])
        table = Table(title="Post-activation host state")
        table.add_column("Host")
        table.add_column("State")
        for h in hosts:
            state = states.get(h.hostname)
            label = {0: "UP", 1: "DOWN", 2: "UNREACHABLE"}.get(state, "unknown")
            table.add_row(h.hostname, label)
        console.print(table)

    snapshot = {
        "generated_at": datetime.now(UTC).isoformat(),
        "site": connection.site,
        "onboarded_hosts": [h.__dict__ for h in hosts],
    }
    out_path = Path(f"config_snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")  # noqa: DTZ005 -- local wall-clock filename, not a stored timestamp
    out_path.write_text(json.dumps(snapshot, indent=2))
    console.print(f"Snapshot written to [bold]{out_path}[/bold]")


# ── Entry point ──────────────────────────────────────────────────────────


async def run() -> None:
    connection = await phase1_site_bringup()
    async with CheckmkClient(connection) as client:
        await phase2_folders(client)
        scan_results = await phase3_discovery(client)
        onboarded = await phase4_classification(scan_results)
        await phase5_onboarding(client, connection, onboarded)
        await phase6_discovery(client, onboarded)
        await phase7_activation(client, connection, onboarded)
    console.rule("[bold green]Done")


def main() -> None:
    asyncio.run(run())
