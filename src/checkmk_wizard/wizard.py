"""Interactive terminal wizard orchestrating Phases 1-7 of the Checkmk Setup
Configurator (see docs/CHECKMK_SETUP_CONFIGURATOR_PLAN.md).
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import secrets
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import questionary
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from checkmk_wizard import livestatus, remote, site
from checkmk_wizard.api import (
    CheckmkAPIError,
    CheckmkClient,
    CheckmkConnection,
    bootstrap_automation_user,
    change_cmkadmin_password,
)
from checkmk_wizard.scanner import DEFAULT_PORTS, scan_network

console = Console()

# Bundled smartmontools .deb packages (see remote.smartmontools_deb_filename)
# ship inside the repo, not the installed package, since this wizard is run
# via `uv run` from a checkout rather than installed as a distributed wheel.
_SMARTMONTOOLS_DIR = Path(__file__).resolve().parents[2] / "docs" / "smart"


def _smart_posix_plugin_path(site_name: str) -> Path:
    """The `smart_posix` agent plugin shipped with the *connected* site's own
    Checkmk install — read locally, not fetched over the API (Checkmk's REST
    API only exposes whole-agent-package downloads, not individual plugin
    files; see remote.py's AGENT_PLUGINS_DIR). Using the site's own copy
    (rather than a version bundled with the wizard) keeps it in sync with
    whatever Checkmk version that site actually runs — this wizard already
    assumes local shell access to the Checkmk host (site.py runs `omd`
    directly), so local filesystem access to the site's own files is no new
    assumption.
    """
    return Path(f"/omd/sites/{site_name}/share/check_mk/agents/plugins/smart_posix")

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


# cmkadmin password requirements. Checkmk's own default policy (Setup >
# Global settings > "Password policy for local accounts", verified from
# the installed site's cmk/gui/wato/_check_mk_configuration.py) requires a
# minimum length of 12 characters and no character-group complexity by
# default. `_PASSWORD_MIN_GROUPS` is a wizard-only, stricter-than-default
# complexity bar (Checkmk itself allows configuring 1-4 of the same 4
# groups) for a superuser account — being stricter here never causes a
# false rejection server-side. The REST API call itself re-validates
# against the site's actual configured policy regardless (which this
# wizard has no way to read back), so a server-side rejection is still
# caught and surfaced rather than assumed away.
_PASSWORD_MIN_LENGTH = 12
_PASSWORD_MIN_GROUPS = 3


def _password_group_count(pw: str) -> int:
    groups = (
        any(c.islower() for c in pw),
        any(c.isupper() for c in pw),
        any(c.isdigit() for c in pw),
        any(not c.isalnum() for c in pw),
    )
    return sum(groups)


def _password_problems(pw: str, username: str) -> list[str]:
    problems = []
    if len(pw) < _PASSWORD_MIN_LENGTH:
        problems.append(f"must be at least {_PASSWORD_MIN_LENGTH} characters long")
    if "\x00" in pw:
        problems.append("must not contain null bytes")
    if pw.lower() == username.lower():
        problems.append("must not be the same as the username")
    if _password_group_count(pw) < _PASSWORD_MIN_GROUPS:
        problems.append(
            f"must use at least {_PASSWORD_MIN_GROUPS} of these 4 character groups: "
            "lowercase letters, uppercase letters, digits, special characters"
        )
    return problems


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
    os_family: str  # "linux" | "windows" | "snmp" | "ping"
    snmp_version: str | None = None  # "v1" | "v2c" — only set when os_family == "snmp"
    snmp_community: str | None = None
    expected_open_ports: list[int] = field(default_factory=list)
    # Set during Phase 5 (needs SSH access, unlike expected_open_ports which
    # is a Phase 4 prompt) — systemd unit / Windows service names to
    # actively monitor. Read back by Phase 6 to verify they actually made
    # it into the "monitored" list, not just silently discovered nothing.
    expected_services: list[str] = field(default_factory=list)


@dataclass
class WizardState:
    connection: CheckmkConnection | None = None
    scan_results: list[ScannedHost] = field(default_factory=list)
    onboarded: list[OnboardedHost] = field(default_factory=list)


# ── Phase 1: Site bring-up ──────────────────────────────────────────────


async def _prompt_change_cmkadmin_password(checkmk_host: str, site_name: str, current_password: str) -> str:
    """Offer to replace the randomly-generated cmkadmin password with one
    the operator chooses. Returns whichever password is in effect
    afterwards (the new one on success, the original if declined or
    cancelled) — the caller needs this to keep bootstrapping with cmkadmin's
    *current* password.
    """
    change = await questionary.confirm(
        "Change the cmkadmin password now? (recommended — the one above was randomly generated)",
        default=True,
    ).ask_async()
    if not change:
        return current_password

    while True:
        new_password = await questionary.password(
            "New cmkadmin password (leave blank to cancel):"
        ).ask_async()
        if not new_password:
            console.print("[yellow]Keeping the generated password.[/yellow]")
            return current_password

        problems = _password_problems(new_password, "cmkadmin")
        if problems:
            console.print(f"[red]Password {'; '.join(problems)}.[/red]")
            continue

        confirm_password = await questionary.password("Confirm new password:").ask_async()
        if new_password != confirm_password:
            console.print("[red]Passwords don't match — try again.[/red]")
            continue

        try:
            await change_cmkadmin_password(checkmk_host, site_name, current_password, new_password)
        except CheckmkAPIError as exc:
            console.print(f"[red]Checkmk rejected the password: {exc}[/red]")
            continue

        console.print("[green]cmkadmin password changed.[/green]")
        return new_password


async def _create_fresh_site(site_name: str, checkmk_host: str) -> None:
    admin_password = secrets.token_urlsafe(16)
    console.print(site.create_site(site_name, admin_password), style="dim", end="")
    console.print(site.start_site(site_name), style="dim", end="")
    console.print(
        f"Site created. cmkadmin password (save this): [bold yellow]{admin_password}[/bold yellow]"
    )
    admin_password = await _prompt_change_cmkadmin_password(checkmk_host, site_name, admin_password)
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

        # Deleting the site destroys its certs, so any host already
        # registered with cmk-agent-ctl (tag_agent: cmk-agent, set for
        # both Linux and Windows onboarding) goes stale — this wizard has
        # no SSH credentials for hosts from a previous run at this point
        # in Phase 1, so it can't clean them up itself. Surface which
        # hosts are affected before the operator decides.
        agent_hosts = site.list_agent_registered_hosts(to_delete)
        if agent_hosts:
            console.print(
                f"[yellow]{len(agent_hosts)} host(s) in '{to_delete}' appear to have a Checkmk agent "
                "registered. Deleting this site destroys its certificates, so each agent's "
                "connection will go stale. Run 'cmk-agent-ctl delete-all' manually on each "
                "host below (before or after deleting):[/yellow]"
            )
            for hostname, ip in agent_hosts:
                console.print(f"    {hostname} ({ip})")

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
                questionary.Choice("simple ping (no agent, no SNMP — reachability only)", value="ping"),
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


def _expected_open_ports_by_hostname(
    scan_results: list[ScannedHost], onboarded: list[OnboardedHost]
) -> dict[str, list[int]]:
    """Every *scanned* host's expected-open ports, keyed by whichever
    hostname currently represents it in Checkmk — not just the hosts the
    user promoted/renamed in Phase 4. A host the user never promoted stays
    a bare Phase 3 placeholder object under `host_name=ip`, but the scan
    still found real open ports on it, so it still gets checks for them.

    For a promoted host, uses the (possibly user-edited-in-Phase-4)
    `expected_open_ports` under its new `hostname`. For everything else,
    falls back to the scan's own raw `open_ports` under the scanned `ip`
    directly, since Phase 4 never asked about these.
    """
    onboarded_by_ip = {h.ip: h for h in onboarded}
    result: dict[str, list[int]] = {}
    for scanned in scan_results:
        promoted = onboarded_by_ip.get(scanned.ip)
        host_name, ports = (promoted.hostname, promoted.expected_open_ports) if promoted else (scanned.ip, scanned.open_ports)
        if ports:
            result[host_name] = ports
    return result


async def _create_expected_open_port_rules(client: CheckmkClient, expected_ports_by_host: dict[str, list[int]]) -> None:
    """One `active_checks:tcp` ("Check TCP port connection") rule per
    distinct expected-open port across every scanned host — not one rule
    per (host, port) pair — the ruleset's `host_name` condition already
    accepts multiple hostnames in a single rule (`match_on` is a list), so
    e.g. two hosts both expecting port 22 open share one rule instead of
    each getting their own copy. Becomes a monitored "TCP Port <N>
    (expected open)" service on every matched host once Phase 6/7 discover
    and activate it, alerting if the port ever stops responding.

    Placed at the root folder ("/") rather than each host's own Phase 2
    folder: a rule's folder must be an ancestor of every host it's meant
    to cover, and hosts sharing a port can easily span different Phase 2
    folders — the `host_name` condition still restricts the rule to
    exactly the listed hosts, nothing broader. Live-verified against a
    real Checkmk 2.4.0p35 CE site end-to-end (rule created → activated →
    discovered as a real service). `value_raw` is a JSON string of the
    ruleset's parameter dict — Checkmk accepts plain JSON here, not just
    the Python-repr form its own GUI export produces. Best-effort per
    port: a failure on one port (e.g. a colliding rule) must not stop the
    rest.
    """
    port_hostnames: dict[int, list[str]] = {}
    for host_name, ports in expected_ports_by_host.items():
        for port in ports:
            port_hostnames.setdefault(port, []).append(host_name)

    for port, hostnames in port_hostnames.items():
        try:
            await client.create_rule(
                ruleset="active_checks:tcp",
                folder="/",
                value_raw=json.dumps({"port": port, "svc_description": f"TCP Port {port} (expected open)"}),
                conditions={"host_name": {"match_on": hostnames, "operator": "one_of"}},
            )
        except CheckmkAPIError as exc:
            console.print(
                f"  [yellow]could not create TCP-port-{port} check for {', '.join(hostnames)}: {exc}[/yellow]"
            )


def _ping_only_hostnames(scan_results: list[ScannedHost], onboarded: list[OnboardedHost]) -> list[str]:
    """Every hostname tagged `tag_agent: no-agent` / `tag_snmp_ds: no-snmp`
    — Phase 4's explicit "ping" choice, plus every scanned host the user
    never promoted at all (still a bare Phase 3 placeholder under
    `host_name=ip` with that same tag pair). These need an *explicit*
    PING active check, or they end up with no reachability service in the
    GUI at all: Checkmk only auto-adds its own implicit "PING" service
    when a host has NO other check configured (verified straight from the
    installed Checkmk's own core-config-generation source,
    `cmk/base/core_nagios/_create_config.py`: `if not have_at_least_one_
    service and not active_checks_rules_exist and not custchecks:`) — and
    every one of these hosts also gets an expected-open-port
    `active_checks:tcp` rule from `_create_expected_open_port_rules()`
    above, which makes `active_checks_rules_exist` true and silently
    suppresses the implicit PING. `_create_ping_check_rule()` below
    restores it explicitly.
    """
    onboarded_ips = {h.ip for h in onboarded}
    hostnames = [h.hostname for h in onboarded if h.os_family == "ping"]
    hostnames += [scanned.ip for scanned in scan_results if scanned.ip not in onboarded_ips]
    return hostnames


async def _create_ping_check_rule(client: CheckmkClient, hostnames: list[str]) -> None:
    """One shared `active_checks:icmp` ("Check hosts with PING (ICMP Echo
    Request)") rule covering every agent-less, SNMP-less host
    (`_ping_only_hostnames()` above) — restores an explicit "PING" service
    for hosts whose implicit one Checkmk skips because they also carry an
    expected-open-port `active_checks:tcp` rule. `value_raw={}` accepts
    every ruleset default (service description "PING", pings the host's
    own configured `ipaddress` attribute, default RTA/packet-loss/packet-
    count/timeout thresholds) — verified against the installed Checkmk's
    own ruleset source (`cmk/gui/plugins/wato/active_checks/icmp.py`):
    every field there is optional. Same grouped-into-one-rule shape as
    `_create_expected_open_port_rules()`, for the same reason (the
    ruleset's `host_name` condition already accepts a `match_on` list).
    """
    if not hostnames:
        return
    try:
        await client.create_rule(
            ruleset="active_checks:icmp",
            folder="/",
            value_raw=json.dumps({}),
            conditions={"host_name": {"match_on": hostnames, "operator": "one_of"}},
        )
    except CheckmkAPIError as exc:
        console.print(f"  [yellow]could not create PING check for {', '.join(hostnames)}: {exc}[/yellow]")


_DEFAULT_CPU_LOAD_LEVELS = (5.0, 10.0)  # per core
_DEFAULT_CPU_UTILIZATION_LEVELS = (80.0, 90.0)  # percent, averaged over one check interval (~1 minute)
_DEFAULT_MEMORY_LEVELS = (80.0, 90.0)  # percent RAM used
_DEFAULT_FILESYSTEM_LEVELS = (80.0, 90.0)  # percent used


async def _prompt_threshold_levels(label: str, unit: str, default: tuple[float, float]) -> tuple[float, float]:
    raw = (
        await questionary.text(
            f"{label} — warning,critical{f' ({unit})' if unit else ''} "
            f"(default {default[0]:g},{default[1]:g}):"
        ).ask_async()
    ).strip()
    if not raw:
        return default
    try:
        warn_s, crit_s = raw.split(",", 1)
        return float(warn_s), float(crit_s)
    except ValueError:
        console.print(f"  [yellow]could not parse '{raw}', using default {default[0]:g},{default[1]:g}[/yellow]")
        return default


async def _create_threshold_rules(client: CheckmkClient) -> None:
    """One global rule (root folder, no host_name condition) per check, so
    it applies wherever the matching service exists across every current
    and future host — a host without that service (e.g. a ping-only or
    SNMP-only host) is simply unaffected, so scoping isn't needed.

    `value_raw` here can't be plain JSON like the other rule-creation
    helpers in this file: live-verified against a real Checkmk 2.4.0p35 CE
    site that these four rulesets' warning/critical fields are Checkmk's
    `Levels()`/`CascadingDropdown` valuespecs, which distinguish their
    alternatives (fixed levels vs. no levels vs. predictive; percent-used
    vs. absolute) by the *Python type* of the value — a JSON array
    deserializes to a Python `list`, which matches none of them and is
    rejected ("data type of the value does not match any of the allowed
    alternatives"). Sending the dict via `repr()` instead produces genuine
    Python tuple syntax (`(5.0, 10.0)`), which Checkmk's own API parses
    (it accepts Python literal syntax, not just JSON) and which the
    `Levels()` alternative correctly matches as "Fixed Levels" — confirmed
    by round-tripping a real rule through the API and reading back the
    identical `value_raw` in the response.

    `memory_linux` only covers Linux hosts (Windows memory reporting uses
    a different ruleset this wizard doesn't set) — harmless no-op on
    Windows/SNMP hosts, same as the other three here.
    """
    cpu_load = await _prompt_threshold_levels("CPU load (per core)", "", _DEFAULT_CPU_LOAD_LEVELS)
    cpu_utilization = await _prompt_threshold_levels("CPU utilization", "%", _DEFAULT_CPU_UTILIZATION_LEVELS)
    memory = await _prompt_threshold_levels("Memory (RAM) used", "%", _DEFAULT_MEMORY_LEVELS)
    filesystem = await _prompt_threshold_levels("Filesystem used", "%", _DEFAULT_FILESYSTEM_LEVELS)

    rules = [
        (
            "checkgroup_parameters:cpu_load",
            repr({"levels1": cpu_load, "levels5": cpu_load, "levels15": cpu_load}),
        ),
        ("checkgroup_parameters:cpu_utilization_os", repr({"util": cpu_utilization})),
        ("checkgroup_parameters:memory_linux", repr({"levels_ram": ("perc_used", memory)})),
        ("checkgroup_parameters:filesystem", repr({"levels": filesystem})),
    ]
    for ruleset, value_raw in rules:
        try:
            await client.create_rule(ruleset=ruleset, folder="/", value_raw=value_raw)
        except CheckmkAPIError as exc:
            console.print(f"  [yellow]could not create {ruleset} rule: {exc}[/yellow]")
    console.print("[green]Default thresholds configured.[/green]")


async def _collect_expected_services(
    hostname: str, ip: str, os_family: str, ssh_creds: remote.SSHCredentials | None
) -> list[str]:
    """Which systemd units (Linux) / Windows services should be actively
    monitored on this host. Prefers a live SSH scan of currently-running
    systemd units when possible — the user picks from what's actually
    there instead of guessing spelling — falling back to manual entry
    otherwise. Windows is always manual: this wizard never establishes
    any remote connection to Windows hosts (same "manual path by design"
    as agent install above), so there is no scan to attempt there.
    """
    if os_family == "linux" and ssh_creds is not None:
        running = await remote.list_running_systemd_services(ip, ssh_creds)
        if running:
            choices = [questionary.Choice(name, value=name) for name in running]
            selected = await questionary.checkbox(
                f"Which running services on {hostname} should be actively monitored?",
                choices=choices,
            ).ask_async()
            return selected

    raw = (
        await questionary.text(
            f"Service names to actively monitor on {hostname} "
            "(comma-separated exact systemd unit / Windows service names, blank to skip):"
        ).ask_async()
    ).strip()
    return [s.strip() for s in raw.split(",") if s.strip()]


async def _create_service_discovery_rules(
    client: CheckmkClient, host: OnboardedHost, service_names: list[str]
) -> None:
    """One rule covering *all* requested service names at once (unlike
    the TCP-port rules above, this ruleset's name-list field natively
    holds multiple entries) that tells Checkmk's discovery to pick up
    these specific systemd units / Windows services as individually
    monitored checks, instead of only the always-on summary check.

    Regex construction here is the product of live debugging against a
    real Checkmk 2.4.0p35 CE site (installed the actual agent on a real
    systemd host to get ground truth) and reading the shipped check-plugin
    source, not assumption:
      - Systemd (`discovery_systemd_units_services`): a bare name entry
        requires an *exact* string match; only a `~`-prefixed entry is
        treated as a regex — live-verified a bare "apache2" entry alone
        does nothing useful for robustness, so every entry is always sent
        `~`-prefixed here. Separately, and easy to miss: Checkmk's own
        systemd parser strips the trailing `.service` suffix from the
        unit name *before* matching against the rule (confirmed by
        reading its discovery-parsing source) — a rule built from the raw
        "apache2.service" form silently discovers nothing, no error at
        all. The suffix is stripped here for exactly that reason.
      - Windows (`inventory_services_rules`): every entry is *always*
        treated as a regex already (no `~` needed) — confirmed via the
        check plugin's own discovery function.
    Both anchored with `^...$` and `re.escape()`d so a name matches
    exactly, never as an accidental prefix of a different service.
    """
    if not service_names or host.os_family not in ("linux", "windows"):
        return
    if host.os_family == "linux":
        names = [f"~^{re.escape(name.removesuffix('.service'))}$" for name in service_names]
        ruleset, value_raw = "discovery_systemd_units_services", json.dumps({"names": names})
    else:
        services = [f"^{re.escape(name)}$" for name in service_names]
        ruleset, value_raw = "inventory_services_rules", json.dumps({"services": services})

    try:
        await client.create_rule(
            ruleset=ruleset,
            folder=host.folder,
            value_raw=value_raw,
            conditions={"host_name": {"match_on": [host.hostname], "operator": "one_of"}},
        )
        console.print(f"  [green]service monitoring configured[/green] for: {', '.join(service_names)}")
    except CheckmkAPIError as exc:
        console.print(f"  [yellow]could not configure service monitoring for {host.hostname}: {exc}[/yellow]")


def _looks_loopback(host: str) -> bool:
    """Whether `host` can only ever mean "this machine itself" — the
    literal string `localhost`, or an IP address in the loopback range.
    `cmk-agent-ctl register --server` is resolved from the *target* host
    being registered, not from wherever the wizard process happens to
    run — so a loopback value here can never reach the real Checkmk
    server from any genuinely remote target (it would just try to contact
    itself).
    """
    if host.strip().lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _local_ipv4_addresses() -> list[str]:
    """Every non-loopback IPv4 address configured on this machine's own
    network interfaces — candidates for how a remote host could reach this
    Checkmk site back. Combines two standard-library-only techniques
    since neither alone is fully reliable across every environment
    (multiple NICs, containers, VPNs):
      - the "connect a UDP socket, then read its own bound address" trick,
        which reports whichever interface the OS would actually route
        through to reach the wider network (no packets are actually sent —
        UDP `connect()` just picks a route and binds locally);
      - `socket.gethostbyname_ex(hostname)`, which reports every address
        the local hostname itself resolves to (depends on `/etc/hosts`/
        DNS, so it can catch additional interfaces the first technique
        misses).
    Not guaranteed exhaustive (e.g. an interface with no default route and
    no `/etc/hosts` entry can still be missed) — callers still offer a
    manual-entry fallback for that case.
    """
    addresses: set[str] = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            addresses.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        _, _, ip_list = socket.gethostbyname_ex(socket.gethostname())
        addresses.update(ip_list)
    except OSError:
        pass
    return sorted(addr for addr in addresses if not ipaddress.ip_address(addr).is_loopback)


_MANUAL_REGISTRATION_ADDRESS = "manual_registration_address"


async def _resolve_agent_registration_server(hosts: list[OnboardedHost], checkmk_host: str) -> str:
    """The address Linux/Windows targets should use for `cmk-agent-ctl
    register --server`. Phase 1's "Hostname/IP to reach this Checkmk site
    on" answer defaults to `localhost` for the common case of testing
    against a site on the same machine the wizard runs on — but on a
    genuinely remote target, `localhost` always resolves to the target
    itself, so registration silently tries to contact itself and fails
    every time with a confusing "Failed to discover agent receiver port"
    error (live-reported symptom, 2026-08-27) rather than anything
    mentioning `localhost`. Detects this once, for the whole batch, and
    offers this machine's own non-loopback addresses (`_local_ipv4_
    addresses()`) as ready-to-pick options instead of asking the operator
    to go find and type one themselves.
    """
    if not _looks_loopback(checkmk_host):
        return checkmk_host
    if not any(not _looks_loopback(h.ip) for h in hosts):
        # Every target is loopback too (e.g. testing entirely on this same
        # machine) — `localhost` is actually correct here, nothing to fix.
        return checkmk_host

    console.print(
        f"[yellow]This Checkmk site is configured to be reached at '{checkmk_host}', but at least one "
        "host being onboarded is remote — a remote target can't use 'localhost' to reach this server "
        "back (cmk-agent-ctl register would try to contact itself and fail).[/yellow]"
    )

    candidates = _local_ipv4_addresses()
    if candidates:
        choices = [questionary.Choice(ip, value=ip) for ip in candidates]
        choices.append(questionary.Choice("Enter a different address", value=_MANUAL_REGISTRATION_ADDRESS))
        selected = await questionary.select(
            "Which address should Linux/Windows hosts use to reach this Checkmk server?",
            choices=choices,
        ).ask_async()
        if selected != _MANUAL_REGISTRATION_ADDRESS:
            return selected

    corrected = (
        await questionary.text(
            "Address Linux/Windows hosts should use to reach this Checkmk server for registration "
            f"(blank to keep using '{checkmk_host}' anyway):"
        ).ask_async()
    ).strip()
    return corrected or checkmk_host


async def _prompt_ssh_credentials() -> remote.SSHCredentials:
    """Collect a username + password/private-key path for the whole Linux
    batch — pure prompting, no connectivity check (that's
    `_establish_ssh_access()`, which calls this in a retry loop).
    """
    username = None
    while not username:
        username = (await questionary.text("SSH username:").ask_async()).strip()
        if not username:
            console.print("[red]SSH username can't be blank — try again.[/red]")

    auth_mode = await questionary.select("SSH auth method:", choices=["password", "private key"]).ask_async()
    if auth_mode == "password":
        password = await questionary.password("SSH password:").ask_async()
        return remote.SSHCredentials(username=username, password=password)

    key_path = None
    while key_path is None:
        raw_key_path = (await questionary.text("Private key path:").ask_async()).strip()
        # Local filesystem check, not a Checkmk-API validation — but a
        # nonexistent key would fail identically for every host in the
        # batch, so catching it once up front here (instead of once per
        # host inside asyncssh's connect error handling) is worth the
        # pre-flight check.
        if not Path(raw_key_path).expanduser().is_file():
            console.print(f"[red]'{raw_key_path}' isn't a file that exists — try again.[/red]")
        else:
            key_path = raw_key_path
    return remote.SSHCredentials(username=username, private_key_path=key_path)


_RETRY_SSH_CREDENTIALS = "retry_ssh_credentials"
_RETRY_SUDO_PASSWORD = "retry_sudo_password"
_SKIP_AUTOMATED_SSH = "skip_automated_ssh"


async def _establish_ssh_access(test_host_ip: str) -> remote.SSHCredentials | None:
    """Collect SSH credentials once for the whole Linux batch and verify
    them right away against `test_host_ip` (the first Linux host) —
    instead of a typo'd password only surfacing many steps later, deep
    inside the per-host loop, as a string of unexplained
    `FAILED_FALLBACK_MANUAL` results. Also confirms sudo elevation works,
    prompting for a sudo password if the account needs one. Returns None
    if the operator chooses to give up rather than keep retrying — callers
    then fall back to manual instructions for every Linux host.

    Since credentials (and, if needed, the sudo password) are shared
    across the whole batch by design (see `_onboard_hosts()`), testing
    once against one host is a deliberate simplification, not a full
    per-host credential check — a host with genuinely different
    credentials still falls back to manual instructions on its own via
    each remote.py function's own `check_ssh_reachable()` guard.
    """
    while True:
        creds = await _prompt_ssh_credentials()

        console.print(f"Testing SSH login on {test_host_ip}...")
        if not await remote.check_ssh_reachable(test_host_ip, creds):
            choice = await questionary.select(
                f"Could not log into {test_host_ip} with those credentials "
                "(wrong username/password/key, or the host is unreachable). What now?",
                choices=[
                    questionary.Choice("Re-enter SSH credentials", value=_RETRY_SSH_CREDENTIALS),
                    questionary.Choice(
                        "Skip automated SSH (manual instructions for all Linux hosts)",
                        value=_SKIP_AUTOMATED_SSH,
                    ),
                ],
            ).ask_async()
            if choice == _RETRY_SSH_CREDENTIALS:
                continue
            return None

        console.print("[green]SSH login confirmed.[/green]")

        if await remote.check_sudo(test_host_ip, creds):
            console.print("[green]Sudo elevation confirmed.[/green]")
            return creds

        console.print(f"[yellow]Logged in, but this account needs a password to use sudo on {test_host_ip}.[/yellow]")
        while True:
            creds.sudo_password = await questionary.password("Sudo password:").ask_async()
            if await remote.check_sudo(test_host_ip, creds):
                console.print("[green]Sudo elevation confirmed.[/green]")
                return creds

            choice = await questionary.select(
                "Sudo still failed with that password. What now?",
                choices=[
                    questionary.Choice("Try a different sudo password", value=_RETRY_SUDO_PASSWORD),
                    questionary.Choice("Re-enter SSH credentials", value=_RETRY_SSH_CREDENTIALS),
                    questionary.Choice(
                        "Skip automated SSH (manual instructions for all Linux hosts)",
                        value=_SKIP_AUTOMATED_SSH,
                    ),
                ],
            ).ask_async()
            if choice == _RETRY_SUDO_PASSWORD:
                continue
            if choice == _RETRY_SSH_CREDENTIALS:
                break
            return None


async def _onboard_hosts(
    client: CheckmkClient, connection: CheckmkConnection, hosts: list[OnboardedHost]
) -> None:
    """Per-host firewall/agent/SNMP/ping onboarding loop — everything
    Phase 5 does for hosts the user actually promoted in Phase 4. Split
    out from `phase5_onboarding()` (2026-08-26) so expected-open-port rule
    creation — which now also covers scanned-but-never-promoted hosts —
    still runs even when `hosts` (the promoted list) is empty.
    """
    register_server = await _resolve_agent_registration_server(hosts, connection.host)

    ssh_creds: remote.SSHCredentials | None = None
    install_smart = False
    # Only Linux hosts ever consume `ssh_creds` below (Windows is always a
    # manual path by design; snmp/ping hosts have no agent at all) — asking
    # for SSH credentials when no onboarded host is Linux is a dead-end
    # prompt with nothing to apply it to.
    linux_hosts = [h for h in hosts if h.os_family == "linux"]
    if linux_hosts:
        use_ssh = await questionary.confirm(
            "Attempt automated SSH firewall + agent install for Linux hosts?", default=True
        ).ask_async()
        if use_ssh:
            install_smart = await questionary.confirm(
                "Also install smartmontools + SMART disk monitoring (smart_posix plugin) on Linux hosts?",
                default=True,
            ).ask_async()
            ssh_creds = await _establish_ssh_access(linux_hosts[0].ip)
            if ssh_creds is None:
                # Nothing left to install smartmontools/plugin over — the
                # per-host loop below already handles ssh_creds=None by
                # falling back to manual instructions for firewall/agent.
                install_smart = False

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
            except CheckmkAPIError as exc:
                console.print(f"  [yellow]host create/update: {exc}[/yellow]")
            continue

        if h.os_family == "ping":
            # No agent, no SNMP — same "no-agent"/"no-snmp" tag pair Phase 3
            # already uses for its inert placeholder hosts, which leaves
            # Checkmk's default host check (ICMP ping) as the only
            # monitoring. No firewall/SSH/discovery steps apply.
            try:
                await _create_or_update_host(
                    client,
                    host_name=h.hostname,
                    folder=h.folder,
                    attributes={"ipaddress": h.ip, "tag_agent": "no-agent", "tag_snmp_ds": "no-snmp"},
                )
                console.print("  [green]Ping-only host created[/green] — reachability monitoring only, no agent/SNMP")
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
        except CheckmkAPIError as exc:
            console.print(f"  [yellow]host create/update: {exc}[/yellow]")

        # Ahead of the windows/linux branch below (not inside it) so it
        # runs the same way regardless of which path that branch takes —
        # Linux with working SSH gets a live scan; everything else
        # (Windows, or Linux with no/failed SSH) gets the manual prompt.
        h.expected_services = await _collect_expected_services(
            h.hostname, h.ip, h.os_family, ssh_creds if h.os_family == "linux" else None
        )
        await _create_service_discovery_rules(client, h, h.expected_services)

        if h.os_family == "windows":
            console.print("  [cyan]Windows target — manual path (by design):[/cyan]")
            console.print(f"    Firewall: {remote.windows_firewall_instructions(remote.AGENT_RECEIVER_PORT)}")
            console.print(
                f"    Register: {remote.windows_register_command(h.hostname, register_server, connection.site, connection.registration_user, connection.registration_secret)}"
            )
            continue

        # Linux
        probe = await remote.probe_port(h.ip, remote.AGENT_RECEIVER_PORT)
        console.print(f"  Port {remote.AGENT_RECEIVER_PORT} probe: {probe.classification}")

        if ssh_creds is None:
            console.print("  [yellow]No SSH credentials supplied — manual path.[/yellow]")
            _print_linux_manual(h, connection, register_server)
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
            h.hostname, register_server, connection.site, connection.registration_user, connection.registration_secret
        )

        # Skip a redundant upload + package install for a host that
        # already has the agent — e.g. a re-run of the wizard, or a host
        # provisioned with the agent baked into its base image.
        if await remote.check_agent_installed(h.ip, ssh_creds, pkg_family):
            console.print("  [cyan]check-mk-agent already installed — registering only.[/cyan]")
            install_result = await remote.register_agent_linux(h.ip, ssh_creds, register_cmd)
            step_label = "Agent registration"
        else:
            try:
                package_bytes = await client.download_agent(os_type)
            except CheckmkAPIError as exc:
                console.print(f"  [red]Agent download failed: {exc}[/red]")
                _print_linux_manual(h, connection, register_server)
                continue

            install_result = await remote.install_agent_linux(
                h.ip, ssh_creds, package_bytes, package_filename, register_cmd
            )
            step_label = "Agent install"

        color = "green" if install_result.outcome == remote.Outcome.AUTOMATED else "yellow"
        console.print(f"  {step_label}: [{color}]{install_result.outcome.value}[/] — {install_result.detail}")
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

        # SMART disk monitoring needs the plugin dir the agent package just
        # created, so this only runs once the agent install above actually
        # succeeded. No separate discovery rule is needed to "enable"
        # smart_posix's checks — unlike systemd unit monitoring, Checkmk's
        # smart_ata/smart_nvme/smart_scsi check plugins discover
        # unconditionally once the section data is present (verified
        # against the installed Checkmk's own check plugin source: no
        # discovery ruleset gates them), so Phase 6's normal `fix_all`
        # discovery picks them up on its own.
        if install_smart and install_result.outcome == remote.Outcome.AUTOMATED:
            deb_filename = remote.smartmontools_deb_filename(compat.target) if compat else None
            if deb_filename is None:
                console.print("  [yellow]SMART monitoring: no bundled smartmontools package for this OS — skipped.[/yellow]")
            else:
                try:
                    smart_bytes = (_SMARTMONTOOLS_DIR / deb_filename).read_bytes()
                except OSError as exc:
                    console.print(f"  [yellow]SMART monitoring: couldn't read bundled package {deb_filename}: {exc}[/yellow]")
                else:
                    smart_install = await remote.install_smartmontools(h.ip, ssh_creds, smart_bytes, "smartmontools.deb")
                    color = "green" if smart_install.outcome == remote.Outcome.AUTOMATED else "yellow"
                    console.print(f"  smartmontools install: [{color}]{smart_install.outcome.value}[/] — {smart_install.detail}")
                    if smart_install.manual_instructions and smart_install.outcome != remote.Outcome.AUTOMATED:
                        console.print(f"    {smart_install.manual_instructions}")

                    if smart_install.outcome == remote.Outcome.AUTOMATED:
                        # dpkg exiting 0 only means the package unpacked
                        # cleanly — confirm smartctl actually runs and SMART
                        # is turned on before bothering to copy the plugin
                        # that reads its output.
                        verify_result = await remote.verify_smartmontools(h.ip, ssh_creds)
                        color = "green" if verify_result.outcome == remote.Outcome.AUTOMATED else "yellow"
                        console.print(f"  smartmontools verify: [{color}]{verify_result.outcome.value}[/] — {verify_result.detail}")
                        if verify_result.manual_instructions and verify_result.outcome != remote.Outcome.AUTOMATED:
                            console.print(f"    {verify_result.manual_instructions}")

                        if verify_result.outcome == remote.Outcome.AUTOMATED:
                            plugin_path = _smart_posix_plugin_path(connection.site)
                            try:
                                plugin_bytes = plugin_path.read_bytes()
                            except OSError as exc:
                                console.print(f"  [yellow]SMART plugin: couldn't read {plugin_path}: {exc}[/yellow]")
                            else:
                                plugin_result = await remote.deploy_agent_plugin(h.ip, ssh_creds, plugin_bytes, "smart_posix")
                                color = "green" if plugin_result.outcome == remote.Outcome.AUTOMATED else "yellow"
                                console.print(f"  SMART plugin deploy: [{color}]{plugin_result.outcome.value}[/] — {plugin_result.detail}")
                                if plugin_result.manual_instructions and plugin_result.outcome != remote.Outcome.AUTOMATED:
                                    console.print(f"    {plugin_result.manual_instructions}")


async def phase5_onboarding(
    client: CheckmkClient,
    connection: CheckmkConnection,
    hosts: list[OnboardedHost],
    scan_results: list[ScannedHost],
) -> None:
    console.rule("[bold]Phase 5 — Host Onboarding")
    if hosts:
        await _onboard_hosts(client, connection, hosts)

    # Covers every scanned host, not just the ones promoted above — a scan
    # result the user never promoted stays a bare Phase 3 placeholder
    # object, but the ports the scan found open on it still get checks.
    await _create_expected_open_port_rules(client, _expected_open_ports_by_hostname(scan_results, hosts))
    # The TCP-port rule above suppresses Checkmk's own implicit PING
    # service for agent-less/SNMP-less hosts — restore it explicitly so
    # reachability stays visible in the GUI alongside the TCP port checks.
    await _create_ping_check_rule(client, _ping_only_hostnames(scan_results, hosts))

    if any(h.os_family in ("linux", "windows") for h in hosts):
        configure_thresholds = await questionary.confirm(
            "Configure default alert thresholds (CPU load, CPU utilization, memory, filesystem)?",
            default=False,
        ).ask_async()
        if configure_thresholds:
            await _create_threshold_rules(client)


def _print_linux_manual(host: OnboardedHost, connection: CheckmkConnection, register_server: str) -> None:
    register_cmd = remote.linux_register_command(
        host.hostname, register_server, connection.site, connection.registration_user, connection.registration_secret
    )
    console.print(f"    Firewall (ufw example): ufw allow {remote.AGENT_RECEIVER_PORT}/tcp")
    console.print(f"    Download agent from the Checkmk site, install it, then run: {register_cmd}")


# ── Phase 6: Discovery & baseline ───────────────────────────────────────


# A freshly registered agent's first successful data push to Checkmk can
# take a while to land — the push-agent daemon (cmk-agent-ctl) wakes up on
# its own periodic timer (commonly ~1 minute), independent of anything
# this wizard does. Running fix_all discovery immediately after
# registration can race ahead of that first push and simply find nothing
# new yet — live-reported: services the wizard reported as "NOT picked up"
# later showed up fine in Checkmk's own "undecided" list once its own
# background discovery check eventually ran. These delays retry fix_all a
# few times, growing, before giving up — total worst case ~60s, and only
# for a host that's actually still missing something.
_DISCOVERY_RETRY_DELAYS_SECONDS = (10, 20, 30)


async def _activate_pending_changes(client: CheckmkClient, connection: CheckmkConnection) -> bool:
    """Push every pending WATO change (host/folder/rule creation, and
    later, service-discovery acceptances) into the live monitoring core.
    Returns whether it succeeded, so a caller that depends on those
    changes actually being live — e.g. service discovery, which reads
    host/rule config from the *activated* core, not from WATO's on-disk
    but not-yet-activated pending state — knows whether to trust what it
    finds next.
    """
    try:
        etag = await client.get_pending_changes_etag()
        await client.activate_changes([connection.site], etag)
        console.print("[green]Changes activated.[/green]")
        return True
    except CheckmkAPIError as exc:
        console.print(f"[red]Activation failed: {exc}[/red]")
        return False


async def phase6_discovery(client: CheckmkClient, connection: CheckmkConnection, hosts: list[OnboardedHost]) -> None:
    console.rule("[bold]Phase 6 — Discovery & Baseline")
    # Service discovery reads host/rule config from the activated core,
    # not from WATO's pending-but-unactivated state — Phase 5's freshly
    # created hosts and discovery-selection rules (e.g. the systemd-unit
    # rule behind _create_service_discovery_rules) need to be live before
    # discovery can be trusted to reflect them. Live-reported 2026-08-27:
    # requested services missing from discovery even with the retries
    # below, since those retries alone can't fix discovery running
    # against config the core has never actually seen. Best-effort: still
    # attempt discovery even if activation itself fails, rather than
    # skipping the whole phase — some of it may still work.
    if not await _activate_pending_changes(client, connection):
        console.print("[yellow]Continuing to discovery despite the activation failure above — results may be incomplete.[/yellow]")

    # mode="fix_all" both discovers and accepts services in one call (adds
    # missing, removes vanished, accepts host labels) — Checkmk's REST
    # equivalent of the "Accept all" button. mode="refresh" alone only
    # refreshes the discovery state and leaves services "undecided," so
    # they'd never actually go live at Phase 7's activation.
    for h in hosts:
        try:
            result = await client.start_service_discovery(h.hostname, mode="fix_all")
            for delay in _DISCOVERY_RETRY_DELAYS_SECONDS:
                missing = _missing_expected_services(h, result)
                if not missing:
                    break
                console.print(
                    f"    [dim]{len(missing)} expected service(s) not yet reported on {h.hostname} "
                    f"({', '.join(missing)}) — retrying discovery in {delay}s...[/dim]"
                )
                await asyncio.sleep(delay)
                result = await client.start_service_discovery(h.hostname, mode="fix_all")
            console.print(f"  [green]services discovered and accepted[/green] {h.hostname}")
            _verify_expected_services(h, result)
        except CheckmkAPIError as exc:
            console.print(f"  [yellow]discovery failed[/yellow] {h.hostname}: {exc}")


def _monitored_service_names(discovery_result: dict) -> set[str]:
    check_table = discovery_result.get("extensions", {}).get("check_table", {})
    return {
        entry.get("extensions", {}).get("service_name")
        for entry in check_table.values()
        if entry.get("value") == "monitored"
    }


def _expected_service_candidates(name: str) -> set[str]:
    bare = name.removesuffix(".service")
    # Checkmk's own service-name templates: "Systemd Service %s" (Linux) /
    # "Service %s" (Windows) — check both since OnboardedHost doesn't
    # separately track which one applies.
    return {f"Systemd Service {bare}", f"Service {name}"}


def _missing_expected_services(host: OnboardedHost, discovery_result: dict) -> list[str]:
    """Which of Phase 5's requested systemd/Windows service names are NOT
    yet a monitored service per this discovery result. Empty `discovery_
    result` (204/303 background job, per api.py) is treated as "nothing
    confirmed missing" rather than "everything missing" — there's no
    check_table to verify against yet, so retrying wouldn't have anything
    new to check either.
    """
    if not host.expected_services or not discovery_result:
        return []
    monitored_names = _monitored_service_names(discovery_result)
    return [name for name in host.expected_services if not (_expected_service_candidates(name) & monitored_names)]


def _verify_expected_services(host: OnboardedHost, discovery_result: dict) -> None:
    """Confirm each of Phase 5's requested systemd/Windows service names
    actually became a monitored service after mode="fix_all" — not
    silently missing. Necessary specifically for this feature (unlike the
    TCP-port rules, which always produce their service once the rule
    exists): a discovery-selection rule whose name/regex doesn't match
    anything on the host raises no error at all anywhere in this
    pipeline — it just discovers zero matching services. This is exactly
    the failure mode live-verified while building this feature (an
    unstripped ".service" suffix silently matched nothing), so it needs
    surfacing here rather than assuming success.
    """
    if not host.expected_services:
        return
    if not discovery_result:
        # 204/303 (background job, per api.py) — no immediate check_table
        # to verify against; best-effort only, don't report false failures.
        console.print(f"    [dim]could not verify expected services for {host.hostname} — discovery ran as a background job[/dim]")
        return

    monitored_names = _monitored_service_names(discovery_result)
    for name in host.expected_services:
        if _expected_service_candidates(name) & monitored_names:
            console.print(f"    [green]✓[/green] '{name}' is now monitored on {host.hostname}")
        else:
            console.print(
                f"    [yellow]✗ '{name}' was NOT picked up on {host.hostname}[/yellow] — "
                "double check the exact service/unit name (case-sensitive) and that it's actually present on the host"
            )


# ── Phase 7: Activation & validation ────────────────────────────────────


async def phase7_activation(client: CheckmkClient, connection: CheckmkConnection, hosts: list[OnboardedHost]) -> None:
    console.rule("[bold]Phase 7 — Activation & Validation")
    # Phase 6 already activated once before running discovery (so
    # discovery reflects Phase 5's host/rule changes) — this activation
    # is for what Phase 6's own fix_all discovery produced: accepting a
    # newly discovered service (moving it from undecided to monitored) is
    # itself a pending WATO change, same as any host/rule edit.
    if not await _activate_pending_changes(client, connection):
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
        await phase5_onboarding(client, connection, onboarded, scan_results)
        await phase6_discovery(client, connection, onboarded)
        await phase7_activation(client, connection, onboarded)
    console.rule("[bold green]Done")


def main() -> None:
    asyncio.run(run())
