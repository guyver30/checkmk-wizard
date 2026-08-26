"""Interactive terminal wizard orchestrating Phases 1-7 of the Checkmk Setup
Configurator (see docs/CHECKMK_SETUP_CONFIGURATOR_PLAN.md).
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import questionary
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from checkmk_wizard import livestatus, remote, site
from checkmk_wizard.api import CheckmkAPIError, CheckmkClient, CheckmkConnection, bootstrap_automation_user
from checkmk_wizard.scanner import DEFAULT_PORTS, scan_network

console = Console()

# Sentinel for the "delete a site" menu choice in phase1_site_bringup() —
# see the comment at its use site for why this can't just be `value=None`.
_DELETE_SITE = object()

# OMD site name rules (docs.checkmk.com/latest/en/omd_basics.html,
# "Creating sites"): must start with a letter, contain only letters,
# digits, and underscores, max 16 characters.
_SITE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,15}$")

# Checkmk REST API validation patterns — live-verified against a running
# 2.4.0p35 CE site by provoking 400 responses and reading the exact regex
# Checkmk's own field validation reports back, rather than guessing:
#   folder name  (POST .../folder_config/collections/all, "name"):
#     rejected "my folder" and "my.folder" with pattern '^[-\w]*\Z' —
#     letters/digits/underscore/hyphen only, no spaces or dots (unlike
#     hostnames below, which do allow dots).
_FOLDER_NAME_RE = re.compile(r"^[-\w]+$")
#   host name    (POST .../host_config/collections/all, "host_name"):
#     rejected "my host" and "host@name" with pattern '^[-0-9a-zA-Z_.]+\Z'
#     — letters/digits/underscore/hyphen/dot (dots needed for FQDNs and
#     dotted IPv4 addresses).
_HOST_NAME_RE = re.compile(r"^[-0-9a-zA-Z_.]+$")

# Not a Checkmk-enforced pattern (this value is never validated server-side
# — it's only used to build the wizard's own base_url and printed into
# commands) but bad input here still needs catching before it reaches
# httpx: RFC-1123-style hostname, checked alongside a plain IP address.
_HOSTNAME_RE = re.compile(
    r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)


def _valid_checkmk_host(value: str) -> bool:
    if len(value) > 253:
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return bool(_HOSTNAME_RE.match(value))


@dataclass
class ScannedHost:
    ip: str
    open_ports: list[int]
    folder: str  # which Phase 2 folder's subnet this host was discovered in ("/" if none)


@dataclass
class OnboardedHost:
    ip: str
    hostname: str
    folder: str
    os_family: str  # "linux" | "windows" | "snmp"
    snmp_version: str | None = None  # "v1" | "v2c" — only set when os_family == "snmp"
    snmp_community: str | None = None
    expected_open_ports: list[int] = field(default_factory=list)


@dataclass
class WizardState:
    connection: CheckmkConnection | None = None
    scan_results: list[ScannedHost] = field(default_factory=list)
    onboarded: list[OnboardedHost] = field(default_factory=list)


# ── Phase 1: Site bring-up ──────────────────────────────────────────────


async def _create_fresh_site(site_name: str, checkmk_host: str) -> None:
    admin_password = secrets.token_urlsafe(16)
    console.print(site.create_site(site_name, admin_password), style="dim", end="")
    console.print(site.start_site(site_name), style="dim", end="")
    console.print(
        f"Site created. cmkadmin password (save this): [bold yellow]{admin_password}[/bold yellow]"
    )
    try:
        await bootstrap_automation_user(checkmk_host, site_name, admin_password)
        console.print("[green]Automation user 'automation' created automatically.[/green]")
    except CheckmkAPIError as exc:
        console.print(
            f"[yellow]Could not auto-create the 'automation' user ({exc}) — "
            "you'll be prompted to create one manually below.[/yellow]"
        )


async def _prompt_new_site_name(taken: set[str]) -> str:
    while True:
        raw_name = await questionary.text("New Checkmk site name:").ask_async()
        if not _SITE_NAME_RE.match(raw_name):
            console.print(
                "[red]Invalid site name — must start with a letter, contain only "
                "letters/digits/underscores, and be 1-16 characters long. Try again.[/red]"
            )
        elif raw_name in taken:
            console.print(f"[red]Site '{raw_name}' already exists — choose a different name.[/red]")
        else:
            return raw_name


async def phase1_site_bringup() -> CheckmkConnection:
    console.rule("[bold]Phase 1 — Site Bring-up")

    if not site.omd_installed():
        console.print(f"[red]{site.CHECKMK_NOT_INSTALLED_INSTRUCTIONS}[/red]")
        raise SystemExit(1)

    site_name: str | None = None
    reuse_existing = False
    existing_sites = site.list_sites()
    while site_name is None:
        if not existing_sites:
            site_name = await _prompt_new_site_name(set(existing_sites))
            break

        choices = [
            questionary.Choice(f"Continue with existing site '{s}'", value=s) for s in existing_sites
        ]
        # NOT value=None: questionary.Choice's own __init__ default for
        # `value` is also None, so passing it explicitly is indistinguishable
        # from omitting it — Choice then falls back to using the *title
        # string* as the value. Live-verified this bug: selecting "Delete a
        # site..." returned that literal title string as `selection`
        # (not None), which `is not None` treated as a real site name,
        # skipping the delete flow and the new-name prompt entirely,
        # straight to the host prompt. A dedicated sentinel avoids the trap.
        choices.append(questionary.Choice("Delete a site, then create a new one", value=_DELETE_SITE))
        selection = await questionary.select(
            "Existing Checkmk site(s) found on this host:", choices=choices
        ).ask_async()

        if selection is not _DELETE_SITE:
            site_name = selection
            reuse_existing = True
            break

        to_delete = (
            existing_sites[0]
            if len(existing_sites) == 1
            else await questionary.select(
                "Which site do you want to delete?", choices=existing_sites
            ).ask_async()
        )
        confirmed = await questionary.confirm(
            f"Delete site '{to_delete}'? This removes ALL its config/data permanently "
            "(does not touch the Checkmk install itself).",
            default=False,
        ).ask_async()
        if confirmed:
            console.print(f"[yellow]Deleting site {to_delete}...[/yellow]")
            console.print(site.remove_site(to_delete), style="dim", end="")
            existing_sites = site.list_sites()
        # else: loop back to the same menu (nothing changed).

    checkmk_host = None
    while checkmk_host is None:
        raw_host = await questionary.text(
            "Hostname/IP to reach this Checkmk site on (as seen by agents/browser):",
            default="localhost",
        ).ask_async()
        if not _valid_checkmk_host(raw_host):
            console.print(f"[red]'{raw_host}' isn't a valid hostname or IP address — try again.[/red]")
        else:
            checkmk_host = raw_host

    if reuse_existing:
        console.print(f"Reusing existing site [bold]{site_name}[/bold].")
        # no-op if already running; omd handles that
        console.print(site.start_site(site_name), style="dim", end="")
    else:
        console.print(f"Creating new site [bold]{site_name}[/bold].")
        await _create_fresh_site(site_name, checkmk_host)

    creds = site.get_site_credentials(site_name)
    if creds is None:
        console.print(
            "[yellow]No default 'automation' user secret found on disk.[/yellow]\n"
            "Create one manually: Setup > Users > Add user, authentication mode "
            "'Automation secret for machine accounts', then paste the secret below."
        )
        secret = ""
        while not secret:
            secret = await questionary.password("Automation secret:").ask_async()
            if not secret:
                console.print("[red]Automation secret can't be blank — try again.[/red]")
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


def _network_scan_attributes(cidr: str) -> dict[str, Any] | None:
    """Folder attribute payload that turns on Checkmk's own built-in
    per-folder Network Scan — a background cronjob Checkmk itself runs
    (not this wizard), covering the same subnet Phase 3 scans once, so new
    hosts added to the network later keep getting picked up without
    re-running the wizard. Live-verified against a real Checkmk 2.4.0p35
    CE site: only creates hosts for IPs not already configured anywhere on
    the site, so it doesn't duplicate or touch hosts already onboarded.
    `tag_criticality="offline"` ("Do not monitor this host") so newly
    found hosts land in host administration unmonitored, for manual
    review/classification — mirrors Phase 3/4's own stage-then-promote
    flow instead of auto-monitoring unclassified hosts.
    Returns None for a non-IPv4 network — Checkmk's network_scan
    `addresses` field is IPv4-only.
    """
    network = ipaddress.ip_network(cidr, strict=False)
    if network.version != 4:
        return None
    return {
        "network_scan": {
            "addresses": [{"type": "network_range", "network": str(network)}],
            "time_allowed": [{"start": "00:00", "end": "23:59"}],
            "scan_interval": 86400,
            "tag_criticality": "offline",
        }
    }


async def phase2_folders(client: CheckmkClient) -> dict[str, str | None]:
    """Optionally create folders, each with its own subnet to scan in
    Phase 3. Returns {folder_name: cidr_or_None} — an empty dict (no
    folders, or every folder's subnet left blank) tells Phase 3 to fall
    back to a single flat scan into the root folder.
    """
    console.rule("[bold]Phase 2 — Folder Structure (optional)")
    use_folders = await questionary.confirm("Set up folders (one per VLAN/site)?", default=False).ask_async()
    if not use_folders:
        console.print("Skipping — Phase 3 will scan a single subnet into the root folder.")
        return {}

    console.print(
        "Add folders one at a time. Each folder can have its own subnet for Phase 3 "
        "to scan directly into it — leave the subnet blank to create the folder "
        "without scanning it now."
    )
    folder_subnets: dict[str, str | None] = {}
    while True:
        name = (await questionary.text("Folder name (blank to finish adding folders):").ask_async()).strip()
        name = name.lstrip("/")
        if not name:
            break
        if not _FOLDER_NAME_RE.match(name):
            console.print(
                f"[red]Invalid folder name '{name}' — Checkmk only allows letters, digits, "
                "underscores, and hyphens (no spaces or dots). Try again.[/red]"
            )
            continue

        cidr: str | None = None
        while True:
            raw_cidr = (
                await questionary.text(
                    f"Subnet/CIDR to scan for folder '{name}' (blank to skip scanning it):",
                    default="",
                ).ask_async()
            ).strip()
            if not raw_cidr:
                break
            try:
                ipaddress.ip_network(raw_cidr, strict=False)
            except ValueError as exc:
                console.print(f"[red]Invalid CIDR ({exc}) — try again.[/red]")
            else:
                cidr = raw_cidr
                break

        folder_created = False
        try:
            # Default every host that lands in this folder — including ones
            # this wizard never touches, like a host the Network Scan below
            # creates on its own — to fully inert monitoring ("no-agent",
            # "no-snmp"), rather than Checkmk's implicit default of
            # "API integrations if configured, else Checkmk agent" (which
            # falsely implies agent-based monitoring is already active).
            # Live-verified: a host created bare in a folder with these set
            # inherits them via effective_attributes. Phase 3/5 override
            # these explicitly, per host, once a host's actual monitoring
            # method (SNMP or agent) is known.
            await client.create_folder(
                name=name, title=name, attributes={"tag_agent": "no-agent", "tag_snmp_ds": "no-snmp"}
            )
            console.print(f"  [green]created[/green] /{name}")
            folder_created = True
        except CheckmkAPIError as exc:
            console.print(f"  [red]failed[/red] /{name}: {exc}")

        # Configured as a separate PUT (not baked into the create_folder
        # call above) so a network_scan validation failure (e.g. a site
        # customized to drop the standard "criticality" tag group) can
        # never take the folder itself down with it — folder creation
        # must never depend on this succeeding.
        if folder_created and cidr:
            scan_attrs = _network_scan_attributes(cidr)
            if scan_attrs is None:
                console.print(f"  [yellow]skipping network scan setup for /{name} — {cidr} isn't IPv4[/yellow]")
            else:
                try:
                    resp = await client.get_folder(name)
                    etag = resp.headers.get("ETag")
                    if etag:
                        await client.update_folder_attributes(name, scan_attrs, etag)
                        console.print(
                            f"  [green]network scan configured[/green] on /{name} — Checkmk will keep "
                            f"re-scanning {cidr} (~daily) for new hosts, added unmonitored for review"
                        )
                except CheckmkAPIError as exc:
                    console.print(f"  [yellow]could not configure network scan on /{name}: {exc}[/yellow]")

        # Checkmk's REST API `folder` field for hosts must be a full path
        # ("/vlan10"), not the bare name `create_folder()` takes — live-
        # verified a bare name is rejected with a 400 pattern-mismatch
        # error. Store the full path here so it flows unchanged through
        # Phase 3's ScannedHost.folder and Phase 4/5's OnboardedHost.folder
        # without every later call needing to know about the distinction.
        folder_subnets[f"/{name}"] = cidr

    if not folder_subnets:
        console.print("No folders added — Phase 3 will scan a single subnet into the root folder.")
    return folder_subnets


# ── Phase 3: Network discovery ──────────────────────────────────────────


async def phase3_discovery(client: CheckmkClient, folder_subnets: dict[str, str | None]) -> list[ScannedHost]:
    """Scan each Phase 2 folder's subnet directly into that folder. Falls
    back to a single flat scan into the root folder when Phase 2 defined
    no folders (skipped, or every folder's subnet was left blank) —
    matches the wizard's original single-CIDR-prompt behavior.
    """
    console.rule("[bold]Phase 3 — Network Discovery (custom async scanner)")

    scans: list[tuple[str, str]] = [(folder, cidr) for folder, cidr in folder_subnets.items() if cidr]
    skipped_folders = [folder for folder, cidr in folder_subnets.items() if not cidr]
    if skipped_folders:
        console.print(f"Skipping scan for folder(s) with no subnet given: {', '.join(skipped_folders)}")

    if not scans:
        cidr = None
        while cidr is None:
            raw_cidr = await questionary.text("Subnet/CIDR to scan (e.g. 192.168.10.0/24):").ask_async()
            try:
                ipaddress.ip_network(raw_cidr, strict=False)
            except ValueError as exc:
                console.print(f"[red]Invalid CIDR ({exc}) — try again.[/red]")
            else:
                cidr = raw_cidr
        scans = [("/", cidr)]

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

    all_results: list[ScannedHost] = []
    for folder, cidr in scans:
        console.print(f"[bold]Scanning {cidr} → folder '{folder}'[/bold]")
        with Progress() as progress:
            task = progress.add_task("Scanning...", total=None)

            def on_progress(chunk, alive, total):
                progress.update(task, description=f"Scanned {chunk} — {alive}/{total} responsive")

            results = await scan_network(cidr, ports=ports, on_progress=on_progress)

        for r in results:
            all_results.append(ScannedHost(ip=r.ip, open_ports=r.open_ports, folder=folder))
            try:
                # Explicit here (not just relying on the folder default set
                # in Phase 2) because the root-folder fallback path (no
                # Phase 2 folders defined) has no folder object of ours to
                # carry that default — every staged host must still come up
                # inert until Phase 4/5 knows its real monitoring method.
                await client.create_host(
                    host_name=r.ip,
                    folder=folder,
                    attributes={"ipaddress": r.ip, "tag_agent": "no-agent", "tag_snmp_ds": "no-snmp"},
                )
            except CheckmkAPIError as exc:
                console.print(f"[yellow]Could not stage {r.ip}: {exc}[/yellow]")

    table = Table(title="Discovered hosts")
    table.add_column("IP")
    table.add_column("Folder")
    table.add_column("Open ports")
    for sh in all_results:
        table.add_row(sh.ip, sh.folder, ", ".join(map(str, sh.open_ports)))
    console.print(table)

    return all_results


# ── Phase 4: Host classification (manual, by design — no fingerprinting) ──


async def phase4_classification(scan_results: list[ScannedHost]) -> list[OnboardedHost]:
    """Purely interactive — no fingerprinting, no folder prompt: each host's
    folder is already known from which Phase 2 folder-subnet scan found it.
    """
    console.rule("[bold]Phase 4 — Host Classification")
    console.print("No automatic fingerprinting — pick which IPs to promote to named hosts.")

    choices = [
        questionary.Choice(f"{r.ip} [{r.folder}] (ports: {r.open_ports})", value=r) for r in scan_results
    ]
    if not choices:
        console.print("No scanned hosts to promote.")
        return []

    selected = await questionary.checkbox("Promote which hosts?", choices=choices).ask_async()

    onboarded: list[OnboardedHost] = []
    for scanned in selected:
        hostname = None
        while hostname is None:
            raw_hostname = await questionary.text(
                f"Hostname for {scanned.ip}:", default=scanned.ip
            ).ask_async()
            if not _HOST_NAME_RE.match(raw_hostname):
                console.print(
                    f"[red]Invalid hostname '{raw_hostname}' — Checkmk only allows letters, "
                    "digits, underscores, hyphens, and dots. Try again.[/red]"
                )
            else:
                hostname = raw_hostname
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

        # Defaults to what Phase 3's scan actually found open on this IP —
        # a reasonable starting guess for "should be open" — but the user
        # can clear/edit it. Phase 5 turns each port into a monitored
        # "Check TCP port connection" service; blank means no such
        # services are created for this host.
        expected_open_ports: list[int] = []
        default_ports = ",".join(str(p) for p in scanned.open_ports)
        while True:
            raw_ports = (
                await questionary.text(
                    f"Expected-open ports for {hostname} to monitor (comma-separated, blank to skip):",
                    default=default_ports,
                ).ask_async()
            ).strip()
            if not raw_ports:
                break
            try:
                candidate_ports = [int(p) for p in raw_ports.split(",") if p.strip()]
                if not all(1 <= p <= 65535 for p in candidate_ports):
                    raise ValueError("ports must be 1-65535")
            except ValueError as exc:
                console.print(f"[red]Invalid port list ({exc}) — try again.[/red]")
            else:
                expected_open_ports = candidate_ports
                break

        onboarded.append(
            OnboardedHost(
                ip=scanned.ip,
                hostname=hostname,
                folder=scanned.folder,
                os_family=os_family,
                snmp_version=snmp_version,
                snmp_community=snmp_community,
                expected_open_ports=expected_open_ports,
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
    doesn't support moving folders. In practice this no longer bites for
    the folder itself: Phase 3 now stages each host directly into the
    folder its scan belongs to (`folder=` on the same `create_host` call
    used here), so by the time this fallback runs, `folder` already
    matches where Phase 3 put it.
    """
    try:
        await client.create_host(host_name=host_name, folder=folder, attributes=attributes)
    except CheckmkAPIError:
        resp = await client.get_host(host_name)
        etag = resp.headers.get("ETag")
        if not etag:
            raise
        await client.update_host_attributes(host_name, attributes, etag)


async def _create_expected_open_port_rules(client: CheckmkClient, host: OnboardedHost) -> None:
    """One `active_checks:tcp` ("Check TCP port connection") rule per
    expected-open port from Phase 4, scoped to this host only via a
    `host_name` condition — becomes a monitored "TCP Port <N> (expected
    open)" service once Phase 6/7 discover and activate it, alerting if
    the port ever stops responding. Live-verified against a real Checkmk
    2.4.0p35 CE site end-to-end (rule created → activated → discovered as
    a real service). `value_raw` is a JSON string of the ruleset's
    parameter dict — Checkmk accepts plain JSON here, not just the
    Python-repr form its own GUI export produces. Best-effort per port: a
    failure on one port (e.g. a colliding rule) must not stop onboarding
    or block the rest of this host's ports.
    """
    for port in host.expected_open_ports:
        try:
            await client.create_rule(
                ruleset="active_checks:tcp",
                folder=host.folder,
                value_raw=json.dumps({"port": port, "svc_description": f"TCP Port {port} (expected open)"}),
                conditions={"host_name": {"match_on": [host.hostname], "operator": "one_of"}},
            )
        except CheckmkAPIError as exc:
            console.print(f"  [yellow]could not create TCP-port-{port} check for {host.hostname}: {exc}[/yellow]")


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
        username = None
        while not username:
            username = (await questionary.text("SSH username:").ask_async()).strip()
            if not username:
                console.print("[red]SSH username can't be blank — try again.[/red]")

        auth_mode = await questionary.select("SSH auth method:", choices=["password", "private key"]).ask_async()
        if auth_mode == "password":
            password = await questionary.password("SSH password:").ask_async()
            ssh_creds = remote.SSHCredentials(username=username, password=password)
        else:
            key_path = None
            while key_path is None:
                raw_key_path = (await questionary.text("Private key path:").ask_async()).strip()
                # Local filesystem check, not a Checkmk-API validation —
                # but a nonexistent key would fail identically for every
                # host in the batch, so catching it once up front here
                # (instead of once per host inside asyncssh's connect
                # error handling) is worth the pre-flight check.
                if not Path(raw_key_path).expanduser().is_file():
                    console.print(f"[red]'{raw_key_path}' isn't a file that exists — try again.[/red]")
                else:
                    key_path = raw_key_path
            ssh_creds = remote.SSHCredentials(username=username, private_key_path=key_path)

    for h in hosts:
        console.print(f"\n[bold]{h.hostname}[/bold] ({h.ip}, {h.os_family})")

        if h.hostname != h.ip:
            # Phase 3 stages every scanned IP as an inert placeholder host
            # under its own name (tag_agent="no-agent", tag_snmp_ds=
            # "no-snmp") so it lands in the right folder. When Phase 4
            # renames it, the block below creates a *new* host object
            # under h.hostname, leaving the IP-named placeholder behind as
            # a duplicate. Delete it; best-effort since its absence isn't
            # fatal (e.g. Phase 3 failed to stage it in the first place).
            try:
                await client.delete_host(h.ip)
            except CheckmkAPIError:
                pass

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
                await _create_expected_open_port_rules(client, h)
            except CheckmkAPIError as exc:
                console.print(f"  [yellow]host create/update: {exc}[/yellow]")
            continue

        try:
            await _create_or_update_host(
                client,
                host_name=h.hostname,
                folder=h.folder,
                attributes={"ipaddress": h.ip, "tag_agent": "cmk-agent", "tag_snmp_ds": "no-snmp"},
            )
            await _create_expected_open_port_rules(client, h)
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
        folder_subnets = await phase2_folders(client)
        scan_results = await phase3_discovery(client, folder_subnets)
        onboarded = await phase4_classification(scan_results)
        await phase5_onboarding(client, connection, onboarded)
        await phase6_discovery(client, onboarded)
        await phase7_activation(client, connection, onboarded)
    console.rule("[bold green]Done")


def main() -> None:
    asyncio.run(run())
