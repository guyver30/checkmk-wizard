"""Interactive terminal wizard orchestrating Phases 1-7 of the Checkmk Setup
Configurator (see docs/CHECKMK_SETUP_CONFIGURATOR_PLAN.md).
"""

from __future__ import annotations

import asyncio
import ipaddress
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
    os_family: str  # "linux" | "windows" | "snmp"
    snmp_version: str | None = None  # "v1" | "v2c" — only set when os_family == "snmp"
    snmp_community: str | None = None


@dataclass
class WizardState:
    connection: CheckmkConnection | None = None
    scan_results: list[HostScanResult] = field(default_factory=list)
    onboarded: list[OnboardedHost] = field(default_factory=list)


# ── Phase 1: Site bring-up ──────────────────────────────────────────────


async def phase1_site_bringup() -> CheckmkConnection:
    console.rule("[bold]Phase 1 — Site Bring-up")

    if not site.omd_installed():
        console.print(f"[red]{site.CHECKMK_NOT_INSTALLED_INSTRUCTIONS}[/red]")
        raise SystemExit(1)

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

    # Checkmk ships a separate pre-configured 'agent_registration' user
    # scoped solely to host registration (verified via context7:
    # docs.checkmk.com/latest/en/agent_deployment.html — "the default
    # 'agent_registration' user is pre-configured with these rights").
    # Use it for cmk-agent-ctl register (Phase 5.2) instead of the broader
    # 'automation' REST credential, when it's available.
    registration_creds = site.get_site_credentials(site_name, automation_user="agent_registration")
    if registration_creds is not None:
        console.print(
            "[green]Using the dedicated 'agent_registration' user[/green] for agent "
            "registration (separate from the general automation account)."
        )
    else:
        console.print(
            "[yellow]No 'agent_registration' user found — agent registration will reuse "
            "the general 'automation' credential.[/yellow] For tighter scoping, create a "
            "user named 'agent_registration' with the 'Agent registration user' role "
            "(Setup > Users) and re-run the wizard."
        )

    connection = CheckmkConnection(
        host=checkmk_host,
        site=site_name,
        username=creds.automation_user,
        secret=creds.automation_secret,
        registration_user=registration_creds.automation_user if registration_creds else None,
        registration_secret=registration_creds.automation_secret if registration_creds else None,
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

    cidr = None
    while cidr is None:
        raw_cidr = await questionary.text("Subnet/CIDR to scan (e.g. 192.168.10.0/24):").ask_async()
        try:
            ipaddress.ip_network(raw_cidr, strict=False)
        except ValueError as exc:
            console.print(f"[red]Invalid CIDR ({exc}) — try again.[/red]")
        else:
            cidr = raw_cidr

    ports = None
    while ports is None:
        port_input = await questionary.text(
            f"Ports to check, comma-separated (default {','.join(map(str, DEFAULT_PORTS))}):",
            default="",
        ).ask_async()
        try:
            ports = tuple(int(p) for p in port_input.split(",") if p.strip()) or DEFAULT_PORTS
        except ValueError:
            console.print("[red]Ports must be comma-separated integers — try again.[/red]")

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
            f"Monitoring method for {hostname}:",
            choices=[
                questionary.Choice("linux (Checkmk agent)", value="linux"),
                questionary.Choice("windows (Checkmk agent)", value="windows"),
                questionary.Choice("snmp (no agent — switch/router/printer/etc.)", value="snmp"),
            ],
        ).ask_async()

        snmp_version = None
        snmp_community = None
        if os_family == "snmp":
            snmp_version = await questionary.select(
                "SNMP version:",
                choices=[questionary.Choice("v2c", value="v2c"), questionary.Choice("v1", value="v1")],
            ).ask_async()
            snmp_community = await questionary.text(
                "SNMP community string:", default="public"
            ).ask_async()

        onboarded.append(
            OnboardedHost(
                ip=ip,
                hostname=hostname,
                folder=folder,
                os_family=os_family,
                snmp_version=snmp_version,
                snmp_community=snmp_community,
            )
        )
    return onboarded


# ── Phase 5: Host onboarding, firewall (5.1), agent install (5.2) ─────────


async def _create_or_update_host(
    client: CheckmkClient, host_name: str, folder: str, attributes: dict
) -> None:
    """Create the host, falling back to updating it in place if it already
    exists — e.g. Phase 3 stages every scanned IP as a bare host object
    under that same name, so a Phase 4 promotion that keeps the default
    hostname (== IP) always collides here. Without this fallback, the
    create fails and this call's attributes (tag_agent/tag_snmp_ds/
    snmp_community/ipaddress) are silently never applied. Note: this only
    updates attributes, not folder placement — Checkmk's host-config PUT
    doesn't support moving folders, so a host promoted into a non-root
    folder that already exists at root (from Phase 3) stays at root.
    """
    try:
        await client.create_host(host_name=host_name, folder=folder, attributes=attributes)
    except CheckmkAPIError:
        resp = await client.get_host(host_name)
        etag = resp.headers.get("ETag")
        if not etag:
            raise
        await client.update_host_attributes(host_name, attributes, etag)


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

        if h.os_family == "snmp":
            # No agent, no firewall/SSH steps — Checkmk polls SNMP devices
            # directly. tag_agent/tag_snmp_ds values verified via context7
            # against docs.checkmk.com/latest/en/hosts_setup.html (CSV host
            # import attribute mapping: agent=no-agent, snmp_ds=snmp-v2).
            # NOTE: the exact snmp_community attribute schema below was not
            # confirmed against live Checkmk REST API docs — verify against
            # the target site's own API spec (e.g. its /ui/ swagger) before
            # relying on this in production.
            try:
                await _create_or_update_host(
                    client,
                    host_name=h.hostname,
                    folder=h.folder,
                    attributes={
                        "ipaddress": h.ip,
                        "tag_agent": "no-agent",
                        "tag_snmp_ds": "snmp-v2" if h.snmp_version == "v2c" else "snmp-v1",
                        "snmp_community": {"type": "v1_v2_community", "community": h.snmp_community},
                    },
                )
                console.print("  [green]SNMP host created[/green] — polled directly, no agent/firewall/SSH steps")
            except CheckmkAPIError as exc:
                console.print(f"  [yellow]host create/update: {exc}[/yellow]")
            continue

        try:
            await _create_or_update_host(
                client,
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
                f"    Register: {remote.windows_register_command(h.hostname, connection.host, connection.site, connection.registration_user, connection.registration_secret)}"
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
        pkg_family = "deb"
        proceed = True
        if compat is not None:
            style = "cyan" if compat.compatible else "yellow"
            console.print(f"  [{style}]{compat.message}[/{style}]")
            if compat.compatible:
                pkg_family = compat.package_family
            else:
                proceed = await questionary.confirm(
                    "Proceed anyway assuming a Debian/Ubuntu-compatible (.deb) package?", default=False
                ).ask_async()

        if not proceed:
            console.print("  Skipping agent install at user's request.")
            continue

        os_type = "linux_deb" if pkg_family == "deb" else "linux_rpm"
        package_filename = "check-mk-agent.deb" if pkg_family == "deb" else "check-mk-agent.rpm"

        register_cmd = remote.linux_register_command(
            h.hostname, connection.host, connection.site, connection.registration_user, connection.registration_secret
        )
        try:
            package_bytes = await client.download_agent(os_type)
        except CheckmkAPIError as exc:
            console.print(f"  [red]Agent download failed: {exc}[/red]")
            _print_linux_manual(h, connection)
            continue

        install_result = await remote.install_agent_linux(
            h.ip, ssh_creds, package_bytes, package_filename, register_cmd
        )
        color = "green" if install_result.outcome == remote.Outcome.AUTOMATED else "yellow"
        console.print(f"  Agent install: [{color}]{install_result.outcome.value}[/] — {install_result.detail}")
        if install_result.manual_instructions and install_result.outcome != remote.Outcome.AUTOMATED:
            console.print(f"    {install_result.manual_instructions}")

        # Trusting register_cmd's exit code alone only confirms the command
        # ran without error — it doesn't confirm the agent controller is
        # actually operational and connected. Verify directly.
        if install_result.outcome == remote.Outcome.AUTOMATED:
            status_check = await remote.check_agent_status(h.ip, ssh_creds, connection.site)
            status_color = "green" if status_check.verified else "yellow"
            status_label = "verified" if status_check.verified else "could not verify"
            console.print(f"  Agent status: [{status_color}]{status_label}[/] — {status_check.detail}")


def _print_linux_manual(host: OnboardedHost, connection: CheckmkConnection) -> None:
    register_cmd = remote.linux_register_command(
        host.hostname, connection.host, connection.site, connection.registration_user, connection.registration_secret
    )
    console.print(f"    Firewall (ufw example): ufw allow {remote.AGENT_RECEIVER_PORT}/tcp")
    console.print(f"    Download agent from the Checkmk site, install it, then run: {register_cmd}")


# ── Phase 6: Discovery & baseline ───────────────────────────────────────


async def phase6_discovery(client: CheckmkClient, hosts: list[OnboardedHost]) -> None:
    console.rule("[bold]Phase 6 — Discovery & Baseline")
    # mode="fix_all" both discovers and accepts services in one call (adds
    # missing, removes vanished, accepts host labels) — Checkmk's REST
    # equivalent of the "Accept all" button. mode="refresh" alone only
    # refreshes the discovery state and leaves services "undecided," so
    # they'd never actually go live at Phase 7's activation.
    for h in hosts:
        try:
            await client.start_service_discovery(h.hostname, mode="fix_all")
            console.print(f"  [green]services discovered and accepted[/green] {h.hostname}")
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

    # Pull the site's actual current host/folder configuration for the
    # snapshot, not just a log of what this run touched — this is what the
    # plan's "known good baseline... for diffing/disaster recovery" wording
    # calls for. Scope note: this covers hosts and folders only, not rules,
    # users, or other site-wide config — a partial config snapshot, not a
    # full site backup.
    try:
        all_hosts = await client.list_hosts()
        all_folders = await client.list_folders()
    except CheckmkAPIError as exc:
        console.print(f"[yellow]Could not export full host/folder snapshot: {exc}[/yellow]")
        all_hosts = None
        all_folders = None

    snapshot = {
        "generated_at": datetime.now(UTC).isoformat(),
        "site": connection.site,
        "onboarded_this_run": [h.__dict__ for h in hosts],
        "hosts": all_hosts,
        "folders": all_folders,
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
