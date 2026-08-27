import json

import pytest
import questionary
import respx
from httpx import Response

from checkmk_wizard.api import CheckmkAPIError, CheckmkClient, CheckmkConnection
from checkmk_wizard.remote import (
    ActionResult,
    AgentStatusCheck,
    CompatibilityCheck,
    OSRelease,
    Outcome,
    PortProbeResult,
    SSHCredentials,
)
from checkmk_wizard.scanner import HostScanResult
from checkmk_wizard.wizard import (
    _DELETE_SITE,
    _FOLDER_NAME_RE,
    _HOST_NAME_RE,
    _MANUAL_REGISTRATION_ADDRESS,
    _RETRY_SSH_CREDENTIALS,
    _RETRY_SUDO_PASSWORD,
    _SITE_NAME_RE,
    _SKIP_AUTOMATED_SSH,
    _SMARTMONTOOLS_DIR,
    OnboardedHost,
    ScannedHost,
    _collect_expected_services,
    _create_or_update_host,
    _create_service_discovery_rules,
    _establish_ssh_access,
    _expected_open_ports_by_hostname,
    _looks_loopback,
    _network_scan_attributes,
    _password_problems,
    _ping_only_hostnames,
    _prompt_change_cmkadmin_password,
    _resolve_agent_registration_server,
    _smart_posix_plugin_path,
    _valid_checkmk_host,
    _verify_expected_services,
    phase2_folders,
    phase3_discovery,
    phase4_classification,
    phase5_onboarding,
    phase6_discovery,
)

CONN = CheckmkConnection(host="cmk.example", site="mysite", username="automation", secret="s3cret")
BASE = "http://cmk.example/mysite/check_mk/api/v1"


def _mock_no_ssh_and_skip_services(monkeypatch):
    """Every ask_async() call returns "" — falsy, so it also works for
    Phase 5's "Attempt automated SSH..." confirm on the (now rare, since
    it's skipped entirely when no onboarded host is Linux) chance it's
    still asked — and .strip()-safe for the manual expected-services text
    prompt a windows/no-SSH host falls back to."""

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return ""

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)


def test_delete_site_choice_value_survives_as_sentinel():
    # Regression test for a live-verified real bug: questionary.Choice's
    # own __init__ default for `value` is also None, so `value=None` is
    # indistinguishable from omitting it — Choice then falls back to using
    # the *title string* as the value. phase1_site_bringup()'s "Delete a
    # site..." menu choice used to pass value=None, so selecting it
    # returned the literal title string (not None), which the code's
    # `is not None` check treated as a real site name — skipping the
    # entire delete flow and the new-site-name prompt, landing straight on
    # the host prompt. Must use a dedicated sentinel instead.
    choice = questionary.Choice("Delete a site, then create a new one", value=_DELETE_SITE)
    assert choice.value is _DELETE_SITE
    assert choice.value != "Delete a site, then create a new one"


@pytest.mark.parametrize(
    "name,valid",
    [
        ("mysite", True),
        ("my_site_1", True),
        ("a", True),
        ("a" * 16, True),
        ("a" * 17, False),  # too long
        ("1site", False),  # must start with a letter
        ("my-site", False),  # hyphen not allowed
        ("my site", False),  # space not allowed
        ("", False),
    ],
)
def test_site_name_validation(name, valid):
    assert bool(_SITE_NAME_RE.match(name)) is valid


@pytest.mark.parametrize(
    "name,valid",
    [
        ("vlan10", True),
        ("my_folder", True),
        ("my-folder", True),  # hyphen allowed, unlike site names
        ("1folder", True),  # digit-first allowed, unlike site names
        ("my folder", False),  # space not allowed
        ("my.folder", False),  # dot not allowed, unlike hostnames
        ("", False),
    ],
)
def test_folder_name_validation(name, valid):
    # Live-verified against a real Checkmk 2.4.0p35 CE site: POST
    # .../folder_config/collections/all rejects "my folder"/"my.folder"
    # with pattern '^[-\w]*\Z'.
    assert bool(_FOLDER_NAME_RE.match(name)) is valid


@pytest.mark.parametrize(
    "password,expect_ok",
    [
        ("Str0ng!Passw0rd", True),  # >=12 chars, 4 groups
        ("abcDEF123456", True),  # >=12 chars, 3 groups (lower/upper/digit)
        ("short1A!", False),  # too short (<12)
        ("alllowercase12", False),  # only 2 groups (lower + digit)
    ],
)
def test_password_problems_length_and_complexity(password, expect_ok):
    problems = _password_problems(password, "cmkadmin")
    assert (not problems) == expect_ok


def test_password_problems_rejects_username_as_password():
    assert _password_problems("cmkadmin", "cmkadmin")
    assert _password_problems("CMKADMIN", "cmkadmin")  # case-insensitive match


def test_password_problems_rejects_null_byte():
    problems = _password_problems("Str0ng!Pass\x00word", "cmkadmin")
    assert any("null byte" in p for p in problems)


@pytest.mark.asyncio
async def test_prompt_change_cmkadmin_password_declines_keeps_original(monkeypatch):
    answers = iter([False])  # decline to change

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)

    result = await _prompt_change_cmkadmin_password("cmk.example", "mysite", "original-pw")
    assert result == "original-pw"


@pytest.mark.asyncio
async def test_prompt_change_cmkadmin_password_rejects_weak_then_succeeds(monkeypatch):
    # First candidate is too short/simple and must be rejected locally
    # (no API call for it); the second passes validation, gets confirmed,
    # and is sent to the API.
    answers = iter([True, "short", "Str0ng!Passw0rd", "Str0ng!Passw0rd"])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)

    calls = []

    async def fake_change(host, site, current, new, **kwargs):
        calls.append((host, site, current, new))

    monkeypatch.setattr("checkmk_wizard.wizard.change_cmkadmin_password", fake_change)

    result = await _prompt_change_cmkadmin_password("cmk.example", "mysite", "original-pw")

    assert result == "Str0ng!Passw0rd"
    assert calls == [("cmk.example", "mysite", "original-pw", "Str0ng!Passw0rd")]


@pytest.mark.asyncio
async def test_prompt_change_cmkadmin_password_mismatch_then_blank_cancels(monkeypatch):
    answers = iter([True, "Str0ng!Passw0rd", "Different!Pass1", ""])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)

    result = await _prompt_change_cmkadmin_password("cmk.example", "mysite", "original-pw")
    assert result == "original-pw"


@pytest.mark.asyncio
async def test_prompt_change_cmkadmin_password_retries_after_api_rejection(monkeypatch):
    answers = iter([True, "Str0ng!Passw0rd", "Str0ng!Passw0rd", "An0ther!Passw0rd", "An0ther!Passw0rd"])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)

    call_log = []

    async def fake_change(host, site, current, new, **kwargs):
        call_log.append(new)
        if new == "Str0ng!Passw0rd":
            raise CheckmkAPIError("PUT", "url", 400, "password policy violation")

    monkeypatch.setattr("checkmk_wizard.wizard.change_cmkadmin_password", fake_change)

    result = await _prompt_change_cmkadmin_password("cmk.example", "mysite", "original-pw")

    assert call_log == ["Str0ng!Passw0rd", "An0ther!Passw0rd"]
    assert result == "An0ther!Passw0rd"


@pytest.mark.parametrize(
    "name,valid",
    [
        ("myhost123", True),
        ("my-host", True),
        ("my_host", True),
        ("myhost.example.com", True),  # dots allowed, for FQDNs
        ("192.168.1.1", True),
        ("my host", False),  # space not allowed
        ("host@name", False),
        ("", False),
    ],
)
def test_host_name_validation(name, valid):
    # Live-verified against a real Checkmk 2.4.0p35 CE site: POST
    # .../host_config/collections/all rejects "my host"/"host@name" with
    # pattern '^[-0-9a-zA-Z_.]+\Z'.
    assert bool(_HOST_NAME_RE.match(name)) is valid


@pytest.mark.parametrize(
    "value,valid",
    [
        ("localhost", True),
        ("my-host.example.com", True),
        ("192.168.1.1", True),
        ("::1", True),  # IPv6
        ("my host", False),
        ("-badstart.example.com", False),
        ("bad-.example.com", False),
        ("a" * 64, False),  # label too long
        ("", False),
    ],
)
def test_valid_checkmk_host(value, valid):
    assert _valid_checkmk_host(value) is valid


@pytest.mark.asyncio
async def test_create_or_update_host_creates_when_new():
    with respx.mock:
        create_route = respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(
            return_value=Response(200, json={})
        )
        async with CheckmkClient(CONN) as client:
            await _create_or_update_host(client, "newhost", "/", {"ipaddress": "10.0.0.1"})
    assert create_route.called


@pytest.mark.asyncio
async def test_create_or_update_host_falls_back_to_update_on_collision():
    # Simulates Phase 3 having already staged this host_name — the create
    # collides, so the fallback must PUT the same attributes instead of
    # silently dropping them.
    with respx.mock:
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(
            return_value=Response(400, json={"title": "already exists"})
        )
        respx.get(f"{BASE}/objects/host_config/existinghost").mock(
            return_value=Response(200, json={}, headers={"ETag": "abc123"})
        )
        update_route = respx.put(f"{BASE}/objects/host_config/existinghost").mock(
            return_value=Response(200, json={})
        )
        async with CheckmkClient(CONN) as client:
            await _create_or_update_host(
                client, "existinghost", "/", {"ipaddress": "10.0.0.2", "tag_agent": "cmk-agent"}
            )
    assert update_route.called
    assert update_route.calls.last.request.headers["If-Match"] == "abc123"


@pytest.mark.asyncio
async def test_phase3_stages_hosts_inert(monkeypatch):
    # Every host Phase 3 stages must come up with no active monitoring
    # (tag_agent="no-agent", tag_snmp_ds="no-snmp") rather than Checkmk's
    # implicit default ("API integrations if configured, else Checkmk
    # agent") — nothing is actually configured yet at staging time.
    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return ""  # ports prompt -> default DEFAULT_PORTS

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)

    async def fake_scan_network(cidr, ports=None, on_progress=None):
        return [HostScanResult(ip="10.0.0.50", open_ports=[22])]

    monkeypatch.setattr("checkmk_wizard.wizard.scan_network", fake_scan_network)

    with respx.mock:
        create_route = respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(
            return_value=Response(200, json={})
        )
        async with CheckmkClient(CONN) as client:
            await phase3_discovery(client, {"/vlan10": "10.0.0.0/24"})

    body = json.loads(create_route.calls.last.request.content)
    assert body["attributes"] == {"ipaddress": "10.0.0.50", "tag_agent": "no-agent", "tag_snmp_ds": "no-snmp"}


@pytest.mark.asyncio
async def test_phase5_agent_host_sets_no_snmp(monkeypatch):
    # A linux/windows host must explicitly declare tag_snmp_ds="no-snmp"
    # rather than leaving it unset — every wizard-created host declares
    # its monitoring method explicitly, never relying on Checkmk defaults.
    _mock_no_ssh_and_skip_services(monkeypatch)

    host = OnboardedHost(ip="10.0.0.7", hostname="10.0.0.7", folder="/", os_family="windows")

    with respx.mock:
        create_route = respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(
            return_value=Response(200, json={})
        )
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [host], [])

    body = json.loads(create_route.calls.last.request.content)
    assert body["attributes"] == {"ipaddress": "10.0.0.7", "tag_agent": "cmk-agent", "tag_snmp_ds": "no-snmp"}


@pytest.mark.asyncio
async def test_phase5_ping_host_sets_no_agent_no_snmp(monkeypatch):
    # "simple ping" hosts get no agent and no SNMP — Checkmk's default
    # host check (ICMP ping) is the only monitoring, same tag pair Phase 3
    # already uses for its inert placeholder hosts.
    _mock_no_ssh_and_skip_services(monkeypatch)

    host = OnboardedHost(ip="10.0.0.8", hostname="pinghost", folder="/", os_family="ping")

    with respx.mock:
        respx.delete(f"{BASE}/objects/host_config/10.0.0.8").mock(return_value=Response(204))
        create_route = respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(
            return_value=Response(200, json={})
        )
        # "ping" hosts always get an explicit PING active-check rule
        # (see _ping_only_hostnames) — not under test here, just needs a route.
        respx.post(f"{BASE}/domain-types/rule/collections/all").mock(return_value=Response(200, json={}))
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [host], [])

    body = json.loads(create_route.calls.last.request.content)
    assert body["attributes"] == {"ipaddress": "10.0.0.8", "tag_agent": "no-agent", "tag_snmp_ds": "no-snmp"}


@pytest.mark.asyncio
async def test_phase5_skips_ssh_prompt_when_no_linux_hosts(monkeypatch):
    # snmp/ping-only batches have no host that would ever use SSH creds —
    # the "Attempt automated SSH..." confirm must not be asked at all.
    async def fail_if_asked(self, patch_stdout=False, kbi_msg=""):
        raise AssertionError("no prompt should be asked for a snmp-only host batch")

    monkeypatch.setattr(questionary.Question, "ask_async", fail_if_asked)

    host = OnboardedHost(
        ip="10.0.0.9", hostname="switch3", folder="/", os_family="snmp", snmp_version="v2c", snmp_community="public"
    )

    with respx.mock:
        respx.delete(f"{BASE}/objects/host_config/10.0.0.9").mock(return_value=Response(204))
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(return_value=Response(200, json={}))
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [host], [])  # must not raise


@pytest.mark.asyncio
async def test_phase4_offers_ping_monitoring_method(monkeypatch):
    scanned = ScannedHost(ip="10.0.0.12", open_ports=[], folder="/")
    answers = iter([[scanned], "10.0.0.12", "ping", ""])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)

    onboarded = await phase4_classification([scanned])
    assert onboarded[0].os_family == "ping"


@pytest.mark.asyncio
async def test_phase5_deletes_ip_placeholder_when_host_renamed(monkeypatch):
    # Regression test for a live-reported real bug: Phase 3 stages every
    # scanned IP as a placeholder host under its own name (inert
    # tag_agent="no-agent"/tag_snmp_ds="no-snmp" — no monitoring until
    # Phase 4/5 knows its real method). When Phase 4 renames it, Phase 5
    # used to create the new,
    # properly-configured host under the new name without ever touching
    # the IP-named placeholder — leaving both visible in Checkmk. Phase 5
    # must delete the placeholder whenever hostname != ip.
    async def no_ssh(self, patch_stdout=False, kbi_msg=""):
        return False  # "Attempt automated SSH firewall + agent install?" -> No

    monkeypatch.setattr(questionary.Question, "ask_async", no_ssh)

    host = OnboardedHost(
        ip="10.0.0.5",
        hostname="myserver",
        folder="/",
        os_family="snmp",
        snmp_version="v2c",
        snmp_community="public",
    )

    with respx.mock:
        delete_route = respx.delete(f"{BASE}/objects/host_config/10.0.0.5").mock(return_value=Response(204))
        create_route = respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(
            return_value=Response(200, json={})
        )
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [host], [])

    assert delete_route.called
    assert create_route.called
    assert b"myserver" in create_route.calls.last.request.content


@pytest.mark.asyncio
async def test_phase5_does_not_delete_when_hostname_equals_ip(monkeypatch):
    # The common case (Phase 4 keeps the default hostname == IP): the
    # Phase 3 placeholder IS the final host, so it must NOT be deleted.
    async def no_ssh(self, patch_stdout=False, kbi_msg=""):
        return False

    monkeypatch.setattr(questionary.Question, "ask_async", no_ssh)

    host = OnboardedHost(
        ip="10.0.0.6",
        hostname="10.0.0.6",
        folder="/",
        os_family="snmp",
        snmp_version="v2c",
        snmp_community="public",
    )

    with respx.mock:
        delete_route = respx.delete(f"{BASE}/objects/host_config/10.0.0.6").mock(return_value=Response(204))
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(return_value=Response(200, json={}))
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [host], [])

    assert not delete_route.called


@pytest.mark.parametrize(
    "cidr,expected_network",
    [
        ("192.168.10.0/24", "192.168.10.0/24"),
        ("192.168.10.5/24", "192.168.10.0/24"),  # host bits stripped by ip_network(strict=False)
    ],
)
def test_network_scan_attributes_ipv4(cidr, expected_network):
    attrs = _network_scan_attributes(cidr)
    scan = attrs["network_scan"]
    assert scan["addresses"] == [{"type": "network_range", "network": expected_network}]
    assert scan["time_allowed"] == [{"start": "00:00", "end": "23:59"}]
    assert scan["tag_criticality"] == "offline"


def test_network_scan_attributes_ipv6_unsupported():
    # Checkmk's network_scan `addresses` field is IPv4-only (live-verified
    # against the schema) — must not send an unsupported payload.
    assert _network_scan_attributes("2001:db8::/32") is None


@pytest.mark.asyncio
async def test_phase2_folders_configures_network_scan(monkeypatch):
    # Regression/feature test: a folder given a subnet should come out of
    # Phase 2 with Checkmk's own Network Scan configured on it, so new
    # hosts keep getting found without re-running the wizard.
    answers = iter([True, "vlan10", "192.168.10.0/24", ""])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)

    with respx.mock:
        create_route = respx.post(f"{BASE}/domain-types/folder_config/collections/all").mock(
            return_value=Response(200, json={"id": "~vlan10"})
        )
        respx.get(f"{BASE}/objects/folder_config/~vlan10").mock(
            return_value=Response(200, json={}, headers={"ETag": "etag1"})
        )
        update_route = respx.put(f"{BASE}/objects/folder_config/~vlan10").mock(return_value=Response(200, json={}))
        async with CheckmkClient(CONN) as client:
            result = await phase2_folders(client)

    assert result == {"/vlan10": "192.168.10.0/24"}
    assert update_route.called
    assert update_route.calls.last.request.headers["If-Match"] == "etag1"
    sent = json.loads(update_route.calls.last.request.content)
    assert sent["update_attributes"]["network_scan"]["tag_criticality"] == "offline"
    # Every host landing in this folder — including one the live Network
    # Scan creates on its own, outside this wizard's control — must
    # inherit inert defaults rather than Checkmk's implicit "cmk-agent".
    create_body = json.loads(create_route.calls.last.request.content)
    assert create_body["attributes"] == {"tag_agent": "no-agent", "tag_snmp_ds": "no-snmp"}


@pytest.mark.asyncio
async def test_phase2_folders_skips_network_scan_without_subnet(monkeypatch):
    # A folder with no subnet given must not get a network scan configured
    # at all — no CIDR means there's nothing to scan.
    answers = iter([True, "vlan10", "", ""])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)

    with respx.mock:
        respx.post(f"{BASE}/domain-types/folder_config/collections/all").mock(
            return_value=Response(200, json={"id": "~vlan10"})
        )
        get_route = respx.get(f"{BASE}/objects/folder_config/~vlan10").mock(
            return_value=Response(200, json={}, headers={"ETag": "etag1"})
        )
        async with CheckmkClient(CONN) as client:
            await phase2_folders(client)

    assert not get_route.called


@pytest.mark.asyncio
async def test_phase2_folders_network_scan_failure_does_not_lose_folder(monkeypatch):
    # If configuring the network scan fails (e.g. a site without the
    # standard "criticality" tag group), the folder itself must still be
    # reported created — network scan setup must never take it down.
    answers = iter([True, "vlan10", "192.168.10.0/24", ""])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)

    with respx.mock:
        respx.post(f"{BASE}/domain-types/folder_config/collections/all").mock(
            return_value=Response(200, json={"id": "~vlan10"})
        )
        respx.get(f"{BASE}/objects/folder_config/~vlan10").mock(
            return_value=Response(200, json={}, headers={"ETag": "etag1"})
        )
        respx.put(f"{BASE}/objects/folder_config/~vlan10").mock(
            return_value=Response(400, json={"title": "tag_criticality must be specified"})
        )
        async with CheckmkClient(CONN) as client:
            result = await phase2_folders(client)

    assert result == {"/vlan10": "192.168.10.0/24"}


@pytest.mark.asyncio
async def test_phase4_prompts_expected_open_ports_default_from_scan(monkeypatch):
    # The expected-open-ports prompt should default to what Phase 3's scan
    # actually found open on this IP.
    scanned = ScannedHost(ip="10.0.0.9", open_ports=[80, 443], folder="/")
    answers = iter([[scanned], "10.0.0.9", "linux", "80,443"])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)

    onboarded = await phase4_classification([scanned])

    assert len(onboarded) == 1
    assert onboarded[0].expected_open_ports == [80, 443]


@pytest.mark.asyncio
async def test_phase4_expected_open_ports_blank_skips(monkeypatch):
    scanned = ScannedHost(ip="10.0.0.10", open_ports=[], folder="/")
    answers = iter([[scanned], "10.0.0.10", "linux", ""])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)

    onboarded = await phase4_classification([scanned])
    assert onboarded[0].expected_open_ports == []


@pytest.mark.asyncio
async def test_phase4_rejects_out_of_range_port(monkeypatch):
    scanned = ScannedHost(ip="10.0.0.11", open_ports=[], folder="/")
    answers = iter([[scanned], "10.0.0.11", "linux", "99999", "443"])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)

    onboarded = await phase4_classification([scanned])
    assert onboarded[0].expected_open_ports == [443]


@pytest.mark.asyncio
async def test_phase5_creates_tcp_rule_for_expected_open_ports(monkeypatch):
    # Regression/feature test: each expected-open port from Phase 4 must
    # become its own active_checks:tcp rule scoped to that host.
    _mock_no_ssh_and_skip_services(monkeypatch)

    host = OnboardedHost(
        ip="10.0.0.20",
        hostname="webserver",
        folder="/",
        os_family="windows",  # avoids a real network probe (linux path pings the host)
        expected_open_ports=[80, 443],
    )
    scan_results = [ScannedHost(ip="10.0.0.20", open_ports=[80, 443], folder="/")]

    with respx.mock:
        respx.delete(f"{BASE}/objects/host_config/10.0.0.20").mock(return_value=Response(204))
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(return_value=Response(200, json={}))
        rule_route = respx.post(f"{BASE}/domain-types/rule/collections/all").mock(
            return_value=Response(200, json={"id": "r1"})
        )
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [host], scan_results)

    assert rule_route.call_count == 2
    bodies = [json.loads(c.request.content) for c in rule_route.calls]
    ports_created = sorted(json.loads(b["value_raw"])["port"] for b in bodies)
    assert ports_created == [80, 443]
    assert bodies[0]["ruleset"] == "active_checks:tcp"
    assert bodies[0]["conditions"] == {"host_name": {"match_on": ["webserver"], "operator": "one_of"}}
    assert bodies[0]["folder"] == "/"


@pytest.mark.asyncio
async def test_phase5_groups_shared_expected_open_port_into_one_rule(monkeypatch):
    # Two hosts both expecting port 22 open must share a single
    # active_checks:tcp rule (host_name condition listing both), not get
    # one rule each — even when they live in different Phase 2 folders.
    _mock_no_ssh_and_skip_services(monkeypatch)

    host_a = OnboardedHost(
        ip="10.0.0.40", hostname="host-a", folder="/vlan10", os_family="windows", expected_open_ports=[22]
    )
    host_b = OnboardedHost(
        ip="10.0.0.41", hostname="host-b", folder="/vlan20", os_family="windows", expected_open_ports=[22, 443]
    )
    scan_results = [
        ScannedHost(ip="10.0.0.40", open_ports=[22], folder="/vlan10"),
        ScannedHost(ip="10.0.0.41", open_ports=[22, 443], folder="/vlan20"),
    ]

    with respx.mock:
        respx.delete(f"{BASE}/objects/host_config/10.0.0.40").mock(return_value=Response(204))
        respx.delete(f"{BASE}/objects/host_config/10.0.0.41").mock(return_value=Response(204))
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(return_value=Response(200, json={}))
        rule_route = respx.post(f"{BASE}/domain-types/rule/collections/all").mock(
            return_value=Response(200, json={"id": "r1"})
        )
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [host_a, host_b], scan_results)

    # One rule for port 22 (both hosts), one rule for port 443 (host_b only).
    assert rule_route.call_count == 2
    bodies = [json.loads(c.request.content) for c in rule_route.calls]
    by_port = {json.loads(b["value_raw"])["port"]: b for b in bodies}
    assert sorted(by_port[22]["conditions"]["host_name"]["match_on"]) == ["host-a", "host-b"]
    assert by_port[443]["conditions"]["host_name"]["match_on"] == ["host-b"]
    assert by_port[22]["folder"] == "/"


@pytest.mark.asyncio
async def test_phase5_creates_tcp_rule_for_snmp_host(monkeypatch):
    async def no_ssh(self, patch_stdout=False, kbi_msg=""):
        return False

    monkeypatch.setattr(questionary.Question, "ask_async", no_ssh)

    host = OnboardedHost(
        ip="10.0.0.21",
        hostname="switch1",
        folder="/",
        os_family="snmp",
        snmp_version="v2c",
        snmp_community="public",
        expected_open_ports=[161],
    )
    scan_results = [ScannedHost(ip="10.0.0.21", open_ports=[161], folder="/")]

    with respx.mock:
        respx.delete(f"{BASE}/objects/host_config/10.0.0.21").mock(return_value=Response(204))
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(return_value=Response(200, json={}))
        rule_route = respx.post(f"{BASE}/domain-types/rule/collections/all").mock(
            return_value=Response(200, json={"id": "r1"})
        )
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [host], scan_results)

    assert rule_route.call_count == 1
    body = json.loads(rule_route.calls.last.request.content)
    assert json.loads(body["value_raw"]) == {"port": 161, "svc_description": "TCP Port 161 (expected open)"}


@pytest.mark.asyncio
async def test_phase5_no_rule_when_no_expected_ports(monkeypatch):
    _mock_no_ssh_and_skip_services(monkeypatch)

    host = OnboardedHost(ip="10.0.0.22", hostname="10.0.0.22", folder="/", os_family="windows")
    scan_results = [ScannedHost(ip="10.0.0.22", open_ports=[], folder="/")]

    with respx.mock:
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(return_value=Response(200, json={}))
        rule_route = respx.post(f"{BASE}/domain-types/rule/collections/all").mock(return_value=Response(200, json={}))
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [host], scan_results)

    assert not rule_route.called


def test_expected_open_ports_by_hostname_prefers_promoted_over_scan():
    # A promoted host uses its (possibly Phase-4-edited) expected_open_ports
    # under its new hostname; an un-promoted scan result falls back to the
    # scan's own raw open_ports under the scanned IP.
    scan_results = [
        ScannedHost(ip="10.0.0.70", open_ports=[22, 80], folder="/"),  # never promoted
        ScannedHost(ip="10.0.0.71", open_ports=[22, 80], folder="/"),  # promoted, ports edited down
    ]
    onboarded = [
        OnboardedHost(
            ip="10.0.0.71", hostname="edited-host", folder="/", os_family="ping", expected_open_ports=[443]
        )
    ]

    result = _expected_open_ports_by_hostname(scan_results, onboarded)

    assert result == {"10.0.0.70": [22, 80], "edited-host": [443]}


def test_expected_open_ports_by_hostname_skips_hosts_with_no_ports():
    scan_results = [ScannedHost(ip="10.0.0.72", open_ports=[], folder="/")]
    assert _expected_open_ports_by_hostname(scan_results, []) == {}


def test_ping_only_hostnames_includes_ping_and_never_promoted():
    # A "ping"-classified promoted host and an un-promoted scan result both
    # end up agent-less/SNMP-less in Checkmk, so both need the explicit
    # PING rule. A promoted linux/windows/snmp host does not.
    scan_results = [
        ScannedHost(ip="10.0.0.80", open_ports=[22], folder="/"),  # never promoted
        ScannedHost(ip="10.0.0.81", open_ports=[], folder="/"),  # promoted as "ping"
        ScannedHost(ip="10.0.0.82", open_ports=[], folder="/"),  # promoted as "linux"
    ]
    onboarded = [
        OnboardedHost(ip="10.0.0.81", hostname="ping-host", folder="/", os_family="ping"),
        OnboardedHost(ip="10.0.0.82", hostname="linux-host", folder="/", os_family="linux"),
    ]

    result = _ping_only_hostnames(scan_results, onboarded)

    assert sorted(result) == ["10.0.0.80", "ping-host"]


def test_ping_only_hostnames_empty_when_nothing_qualifies():
    scan_results = [ScannedHost(ip="10.0.0.83", open_ports=[], folder="/")]
    onboarded = [OnboardedHost(ip="10.0.0.83", hostname="linux-host", folder="/", os_family="linux")]
    assert _ping_only_hostnames(scan_results, onboarded) == []


def test_smartmontools_packages_bundled_for_every_mapped_ubuntu_release():
    # Regression guard: remote.smartmontools_deb_filename()'s hardcoded
    # filenames must always resolve to a real file under docs/smart/, or
    # the wizard would crash mid-onboarding trying to read a nonexistent
    # bundled package.
    from checkmk_wizard.remote import _SMARTMONTOOLS_DEB_BY_UBUNTU_VERSION

    for filename in _SMARTMONTOOLS_DEB_BY_UBUNTU_VERSION.values():
        assert (_SMARTMONTOOLS_DIR / filename).is_file()


def test_smart_posix_plugin_path_uses_connected_site_name():
    path = _smart_posix_plugin_path("mysite")
    assert str(path) == "/omd/sites/mysite/share/check_mk/agents/plugins/smart_posix"


@pytest.mark.parametrize(
    "host,expected",
    [
        ("localhost", True),
        ("LOCALHOST", True),  # case-insensitive
        ("127.0.0.1", True),
        ("::1", True),
        ("192.168.1.10", False),
        ("cmk.example.com", False),
    ],
)
def test_looks_loopback(host, expected):
    assert _looks_loopback(host) is expected


@pytest.mark.asyncio
async def test_resolve_agent_registration_server_unchanged_when_not_loopback():
    hosts = [OnboardedHost(ip="10.0.0.5", hostname="10.0.0.5", folder="/", os_family="linux")]
    assert await _resolve_agent_registration_server(hosts, "cmk.example.com") == "cmk.example.com"


@pytest.mark.asyncio
async def test_resolve_agent_registration_server_unchanged_when_every_target_is_loopback_too():
    # No genuinely remote target — "localhost" is actually correct, no
    # prompt should even fire (would raise if ask_async() were called
    # without a monkeypatched Question.ask_async).
    hosts = [OnboardedHost(ip="127.0.0.1", hostname="127.0.0.1", folder="/", os_family="linux")]
    assert await _resolve_agent_registration_server(hosts, "localhost") == "localhost"


@pytest.mark.asyncio
async def test_resolve_agent_registration_server_offers_discovered_candidates(monkeypatch):
    # A real remote host + a loopback Checkmk address is the exact live-
    # reported bug: cmk-agent-ctl register --server localhost, run on the
    # remote target, tries to contact itself and fails registration every
    # time. Rather than asking the operator to go find and type an
    # address, this machine's own non-loopback addresses are discovered
    # and offered as ready-to-pick options.
    monkeypatch.setattr("checkmk_wizard.wizard._local_ipv4_addresses", lambda: ["192.168.1.10", "10.0.0.1"])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return "192.168.1.10"

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)

    hosts = [OnboardedHost(ip="10.0.0.5", hostname="test-linux", folder="/", os_family="linux")]
    assert await _resolve_agent_registration_server(hosts, "localhost") == "192.168.1.10"


@pytest.mark.asyncio
async def test_resolve_agent_registration_server_falls_back_to_manual_entry_when_chosen(monkeypatch):
    # Selecting "Enter a different address" from the discovered candidates
    # falls through to the free-text prompt, e.g. for a NAT/firewalled
    # address none of this machine's own interfaces would show.
    monkeypatch.setattr("checkmk_wizard.wizard._local_ipv4_addresses", lambda: ["192.168.1.10"])

    answers = iter([_MANUAL_REGISTRATION_ADDRESS, "cmk.example.com"])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)

    hosts = [OnboardedHost(ip="10.0.0.5", hostname="test-linux", folder="/", os_family="linux")]
    assert await _resolve_agent_registration_server(hosts, "localhost") == "cmk.example.com"


@pytest.mark.asyncio
async def test_resolve_agent_registration_server_prompts_manually_when_no_candidates_found(monkeypatch):
    # No local interface candidates discovered at all — falls straight to
    # the free-text prompt (no selection menu with nothing useful to pick).
    monkeypatch.setattr("checkmk_wizard.wizard._local_ipv4_addresses", list)

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return "cmk.example.com"

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)

    hosts = [OnboardedHost(ip="10.0.0.5", hostname="test-linux", folder="/", os_family="linux")]
    assert await _resolve_agent_registration_server(hosts, "localhost") == "cmk.example.com"


@pytest.mark.asyncio
async def test_resolve_agent_registration_server_keeps_loopback_when_prompt_left_blank(monkeypatch):
    monkeypatch.setattr("checkmk_wizard.wizard._local_ipv4_addresses", list)

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return ""

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)

    hosts = [OnboardedHost(ip="10.0.0.5", hostname="test-linux", folder="/", os_family="linux")]
    assert await _resolve_agent_registration_server(hosts, "localhost") == "localhost"


@pytest.mark.asyncio
async def test_establish_ssh_access_succeeds_on_first_try(monkeypatch):
    answers = iter(["root", "password", "secret"])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)
    monkeypatch.setattr("checkmk_wizard.wizard.remote.check_ssh_reachable", lambda *a, **k: _ready(True))
    monkeypatch.setattr("checkmk_wizard.wizard.remote.check_sudo", lambda *a, **k: _ready(True))

    creds = await _establish_ssh_access("10.0.0.60")

    assert creds == SSHCredentials(username="root", password="secret")


@pytest.mark.asyncio
async def test_establish_ssh_access_retries_credentials_after_ssh_failure(monkeypatch):
    # First SSH attempt fails (e.g. a typo'd password); operator re-enters
    # credentials and the second attempt succeeds.
    answers = iter(
        ["root", "password", "wrong", _RETRY_SSH_CREDENTIALS, "root", "password", "right"]
    )

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)

    ssh_attempts = []

    async def fake_check_ssh_reachable(host, creds):
        ssh_attempts.append(creds.password)
        return creds.password == "right"

    monkeypatch.setattr("checkmk_wizard.wizard.remote.check_ssh_reachable", fake_check_ssh_reachable)
    monkeypatch.setattr("checkmk_wizard.wizard.remote.check_sudo", lambda *a, **k: _ready(True))

    creds = await _establish_ssh_access("10.0.0.61")

    assert ssh_attempts == ["wrong", "right"]
    assert creds == SSHCredentials(username="root", password="right")


@pytest.mark.asyncio
async def test_establish_ssh_access_returns_none_when_skipped_after_ssh_failure(monkeypatch):
    answers = iter(["root", "password", "wrong", _SKIP_AUTOMATED_SSH])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)
    monkeypatch.setattr("checkmk_wizard.wizard.remote.check_ssh_reachable", lambda *a, **k: _ready(False))

    def fail_if_called(*a, **k):
        raise AssertionError("sudo must not be checked once SSH itself never succeeded")

    monkeypatch.setattr("checkmk_wizard.wizard.remote.check_sudo", fail_if_called)

    assert await _establish_ssh_access("10.0.0.62") is None


@pytest.mark.asyncio
async def test_establish_ssh_access_prompts_for_sudo_password_when_needed(monkeypatch):
    # SSH login works immediately, but this account needs a sudo password —
    # first candidate is wrong, second is accepted.
    answers = iter(["root", "password", "secret", "wrong-sudo-pw", _RETRY_SUDO_PASSWORD, "right-sudo-pw"])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)
    monkeypatch.setattr("checkmk_wizard.wizard.remote.check_ssh_reachable", lambda *a, **k: _ready(True))

    sudo_attempts = []

    async def fake_check_sudo(host, creds):
        sudo_attempts.append(creds.sudo_password)
        return creds.sudo_password == "right-sudo-pw"

    monkeypatch.setattr("checkmk_wizard.wizard.remote.check_sudo", fake_check_sudo)

    creds = await _establish_ssh_access("10.0.0.63")

    # First attempt (sudo_password=None) is the initial "does this account
    # even need a password" probe, before any password prompt fires.
    assert sudo_attempts == [None, "wrong-sudo-pw", "right-sudo-pw"]
    assert creds == SSHCredentials(username="root", password="secret", sudo_password="right-sudo-pw")


@pytest.mark.asyncio
async def test_establish_ssh_access_returns_none_when_skipped_after_sudo_failure(monkeypatch):
    answers = iter(["root", "password", "secret", "wrong-sudo-pw", _SKIP_AUTOMATED_SSH])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)
    monkeypatch.setattr("checkmk_wizard.wizard.remote.check_ssh_reachable", lambda *a, **k: _ready(True))
    monkeypatch.setattr("checkmk_wizard.wizard.remote.check_sudo", lambda *a, **k: _ready(False))

    assert await _establish_ssh_access("10.0.0.64") is None


def _mock_linux_ssh_agent_install(monkeypatch, *, os_release: OSRelease):
    """Stub every remote.py SSH mechanic the Linux/SSH onboarding path calls
    so it never touches a real network or the real /omd filesystem:
    connectivity/sudo checks (from `_establish_ssh_access()`), probing,
    firewall, OS-compat detection (fixed to `os_release`), agent install,
    and agent-status verification all report success. Returns the raw
    monkeypatch handle so callers can further stub/spy on top (e.g. the new
    smartmontools/plugin calls)."""
    monkeypatch.setattr("checkmk_wizard.wizard.remote.check_ssh_reachable", lambda *a, **k: _ready(True))
    monkeypatch.setattr("checkmk_wizard.wizard.remote.check_sudo", lambda *a, **k: _ready(True))
    monkeypatch.setattr("checkmk_wizard.wizard.remote.list_running_systemd_services", lambda *a, **k: _none())
    monkeypatch.setattr(
        "checkmk_wizard.wizard.remote.probe_port",
        lambda *a, **k: _ready(PortProbeResult(reachable=True, classification="open")),
    )
    monkeypatch.setattr(
        "checkmk_wizard.wizard.remote.fix_firewall_linux",
        lambda *a, **k: _ready(ActionResult(Outcome.AUTOMATED, "firewall ok")),
    )
    monkeypatch.setattr(
        "checkmk_wizard.wizard.remote.check_os_compatibility",
        lambda *a, **k: _ready(
            CompatibilityCheck(compatible=True, target=os_release, package_family="deb", message="ok")
        ),
    )
    monkeypatch.setattr("checkmk_wizard.wizard.remote.check_agent_installed", lambda *a, **k: _ready(False))
    monkeypatch.setattr(
        "checkmk_wizard.wizard.remote.install_agent_linux",
        lambda *a, **k: _ready(ActionResult(Outcome.AUTOMATED, "agent installed")),
    )
    monkeypatch.setattr(
        "checkmk_wizard.wizard.remote.check_agent_status",
        lambda *a, **k: _ready(AgentStatusCheck(verified=True, detail="connected")),
    )
    monkeypatch.setattr(
        "checkmk_wizard.wizard.remote.verify_smartmontools",
        lambda *a, **k: _ready(ActionResult(Outcome.AUTOMATED, "smartctl 7+ confirmed; SMART enabled on 1/1 device(s)")),
    )


async def _none():
    return None


async def _ready(value):
    return value


@pytest.mark.asyncio
async def test_phase5_uses_corrected_registration_server_for_loopback_checkmk_host(monkeypatch):
    # Live-reported bug: a Checkmk site configured as "localhost" (Phase
    # 1's default, correct only when testing entirely on one machine)
    # produces a `cmk-agent-ctl register --server localhost` command that,
    # run on a genuinely remote target, tries to contact itself and always
    # fails registration. _onboard_hosts() must use the corrected address
    # from _resolve_agent_registration_server(), not connection.host
    # directly, for the actual register command.
    loopback_conn = CheckmkConnection(host="localhost", site="mysite", username="automation", secret="s3cret")

    # "cmk.example.com": corrected registration-server prompt (fires first
    # in _onboard_hosts); True: attempt SSH; False: decline smartmontools;
    # "root"/"password"/"secret": SSH creds; "": expected-services prompt.
    answers = iter(["cmk.example.com", True, False, "root", "password", "secret", ""])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)
    _mock_linux_ssh_agent_install(monkeypatch, os_release=OSRelease(id="ubuntu", version_id="22.04"))

    captured = {}

    async def fake_install_agent_linux(host, creds, package_bytes, package_filename, register_cmd):
        captured["register_cmd"] = register_cmd
        return ActionResult(Outcome.AUTOMATED, "agent installed")

    monkeypatch.setattr("checkmk_wizard.wizard.remote.install_agent_linux", fake_install_agent_linux)

    host = OnboardedHost(ip="10.0.0.70", hostname="10.0.0.70", folder="/", os_family="linux")
    loopback_base = "http://localhost/mysite/check_mk/api/v1"

    with respx.mock:
        respx.post(f"{loopback_base}/domain-types/host_config/collections/all").mock(
            return_value=Response(200, json={})
        )
        respx.get(f"{loopback_base}/domain-types/agent/actions/download/invoke").mock(
            return_value=Response(200, content=b"agent-package-bytes")
        )
        async with CheckmkClient(loopback_conn) as client:
            await phase5_onboarding(client, loopback_conn, [host], [])

    assert "--server cmk.example.com" in captured["register_cmd"]
    assert "localhost" not in captured["register_cmd"]


@pytest.mark.asyncio
async def test_phase5_skips_package_install_when_agent_already_present(monkeypatch):
    # A host that already has check-mk-agent (e.g. a re-run, or baked into
    # its base image) must not get a redundant download/upload/dpkg-i —
    # only registration should run.
    answers = iter([True, False, "root", "password", "secret", ""])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)
    _mock_linux_ssh_agent_install(monkeypatch, os_release=OSRelease(id="ubuntu", version_id="22.04"))
    monkeypatch.setattr("checkmk_wizard.wizard.remote.check_agent_installed", lambda *a, **k: _ready(True))

    def fail_if_called(*a, **k):
        raise AssertionError("install_agent_linux must not run when the agent is already installed")

    monkeypatch.setattr("checkmk_wizard.wizard.remote.install_agent_linux", fail_if_called)

    register_calls = []

    async def fake_register_agent_linux(host, creds, register_cmd):
        register_calls.append((host, register_cmd))
        return ActionResult(Outcome.AUTOMATED, "Agent already installed; registered")

    monkeypatch.setattr("checkmk_wizard.wizard.remote.register_agent_linux", fake_register_agent_linux)

    host = OnboardedHost(ip="10.0.0.71", hostname="10.0.0.71", folder="/", os_family="linux")

    with respx.mock:
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(return_value=Response(200, json={}))
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [host], [])

    assert len(register_calls) == 1
    assert register_calls[0][0] == "10.0.0.71"


@pytest.mark.asyncio
async def test_phase5_installs_smartmontools_and_smart_plugin_for_linux_host(monkeypatch, tmp_path):
    # True: attempt SSH; True: also install smartmontools; "root": SSH
    # username; "password": SSH auth method; "secret": SSH password;
    # "": manual expected-services prompt (no systemd scan result -> blank/skip).
    answers = iter([True, True, "root", "password", "secret", ""])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)
    _mock_linux_ssh_agent_install(monkeypatch, os_release=OSRelease(id="ubuntu", version_id="22.04"))

    plugin_file = tmp_path / "smart_posix"
    plugin_file.write_bytes(b"fake plugin script")
    monkeypatch.setattr("checkmk_wizard.wizard._smart_posix_plugin_path", lambda site: plugin_file)

    smartmontools_calls = []
    plugin_calls = []

    async def fake_install_smartmontools(host, creds, package_bytes, package_filename):
        smartmontools_calls.append((host, creds, package_bytes, package_filename))
        return ActionResult(Outcome.AUTOMATED, "smartmontools installed")

    async def fake_deploy_agent_plugin(host, creds, plugin_bytes, plugin_name):
        plugin_calls.append((host, creds, plugin_bytes, plugin_name))
        return ActionResult(Outcome.AUTOMATED, "plugin deployed")

    monkeypatch.setattr("checkmk_wizard.wizard.remote.install_smartmontools", fake_install_smartmontools)
    monkeypatch.setattr("checkmk_wizard.wizard.remote.deploy_agent_plugin", fake_deploy_agent_plugin)

    host = OnboardedHost(ip="10.0.0.50", hostname="10.0.0.50", folder="/", os_family="linux")

    with respx.mock:
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(return_value=Response(200, json={}))
        respx.get(f"{BASE}/domain-types/agent/actions/download/invoke").mock(
            return_value=Response(200, content=b"agent-package-bytes")
        )
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [host], [])

    assert len(smartmontools_calls) == 1
    host_arg, creds_arg, package_bytes, package_filename = smartmontools_calls[0]
    assert host_arg == "10.0.0.50"
    assert creds_arg == SSHCredentials(username="root", password="secret")
    assert package_filename == "smartmontools.deb"
    assert package_bytes == (_SMARTMONTOOLS_DIR / "smartmontools_7.2-1build2_amd64(Jammy).deb").read_bytes()

    assert len(plugin_calls) == 1
    host_arg, creds_arg, plugin_bytes, plugin_name = plugin_calls[0]
    assert host_arg == "10.0.0.50"
    assert plugin_bytes == b"fake plugin script"
    assert plugin_name == "smart_posix"


@pytest.mark.asyncio
async def test_phase5_skips_plugin_deploy_when_smartctl_verify_fails(monkeypatch):
    # `dpkg -i` exiting 0 doesn't confirm smartctl actually runs — if the
    # post-install verification can't confirm that, copying the plugin
    # that reads smartctl's output is pointless; must skip it, not deploy
    # blindly.
    answers = iter([True, True, "root", "password", "secret", ""])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)
    _mock_linux_ssh_agent_install(monkeypatch, os_release=OSRelease(id="ubuntu", version_id="22.04"))

    monkeypatch.setattr(
        "checkmk_wizard.wizard.remote.install_smartmontools",
        lambda *a, **k: _ready(ActionResult(Outcome.AUTOMATED, "smartmontools installed")),
    )
    monkeypatch.setattr(
        "checkmk_wizard.wizard.remote.verify_smartmontools",
        lambda *a, **k: _ready(
            ActionResult(Outcome.FAILED_FALLBACK_MANUAL, "smartctl did not report version 7+ after install")
        ),
    )

    def fail_if_called(*a, **k):
        raise AssertionError("plugin deploy must not run when smartctl verification fails")

    monkeypatch.setattr("checkmk_wizard.wizard.remote.deploy_agent_plugin", fail_if_called)

    host = OnboardedHost(ip="10.0.0.53", hostname="10.0.0.53", folder="/", os_family="linux")

    with respx.mock:
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(return_value=Response(200, json={}))
        respx.get(f"{BASE}/domain-types/agent/actions/download/invoke").mock(
            return_value=Response(200, content=b"agent-package-bytes")
        )
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [host], [])


@pytest.mark.asyncio
async def test_phase5_skips_smartmontools_when_declined(monkeypatch):
    # Same Linux/SSH host, but the operator declines the second confirm —
    # smartmontools/plugin install must never be attempted.
    answers = iter([True, False, "root", "password", "secret", ""])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)
    _mock_linux_ssh_agent_install(monkeypatch, os_release=OSRelease(id="ubuntu", version_id="22.04"))

    def fail_if_called(*a, **k):
        raise AssertionError("smartmontools/plugin install must not run when declined")

    monkeypatch.setattr("checkmk_wizard.wizard.remote.install_smartmontools", fail_if_called)
    monkeypatch.setattr("checkmk_wizard.wizard.remote.deploy_agent_plugin", fail_if_called)

    host = OnboardedHost(ip="10.0.0.51", hostname="10.0.0.51", folder="/", os_family="linux")

    with respx.mock:
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(return_value=Response(200, json={}))
        respx.get(f"{BASE}/domain-types/agent/actions/download/invoke").mock(
            return_value=Response(200, content=b"agent-package-bytes")
        )
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [host], [])


@pytest.mark.asyncio
async def test_phase5_skips_smartmontools_for_unbundled_os(monkeypatch):
    # Agent install still succeeds on e.g. Debian (same "deb" package
    # family as Ubuntu), but there's no bundled smartmontools .deb for it —
    # must skip cleanly rather than erroring.
    answers = iter([True, True, "root", "password", "secret", ""])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)
    _mock_linux_ssh_agent_install(monkeypatch, os_release=OSRelease(id="debian", version_id="12"))

    def fail_if_called(*a, **k):
        raise AssertionError("smartmontools/plugin install must not run for an unbundled OS")

    monkeypatch.setattr("checkmk_wizard.wizard.remote.install_smartmontools", fail_if_called)
    monkeypatch.setattr("checkmk_wizard.wizard.remote.deploy_agent_plugin", fail_if_called)

    host = OnboardedHost(ip="10.0.0.52", hostname="10.0.0.52", folder="/", os_family="linux")

    with respx.mock:
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(return_value=Response(200, json={}))
        respx.get(f"{BASE}/domain-types/agent/actions/download/invoke").mock(
            return_value=Response(200, content=b"agent-package-bytes")
        )
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [host], [])


@pytest.mark.asyncio
async def test_phase5_creates_grouped_tcp_rules_for_never_promoted_scanned_hosts(monkeypatch):
    # A host the user never promoted in Phase 4 stays a bare IP-named
    # placeholder object (Phase 3 already created it), but the scan still
    # found real open ports on it — those must still get
    # active_checks:tcp rules, grouped by port with promoted hosts too.
    _mock_no_ssh_and_skip_services(monkeypatch)

    scan_results = [
        ScannedHost(ip="10.0.0.60", open_ports=[22, 80], folder="/"),  # never promoted
        ScannedHost(ip="10.0.0.61", open_ports=[22], folder="/"),  # promoted, renamed
    ]
    promoted_host = OnboardedHost(
        ip="10.0.0.61", hostname="promoted-host", folder="/", os_family="ping", expected_open_ports=[22]
    )

    with respx.mock:
        respx.delete(f"{BASE}/objects/host_config/10.0.0.61").mock(return_value=Response(204))
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(return_value=Response(200, json={}))
        rule_route = respx.post(f"{BASE}/domain-types/rule/collections/all").mock(
            return_value=Response(200, json={"id": "r1"})
        )
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [promoted_host], scan_results)

    # port 22 (both hosts), port 80 (10.0.0.60 only), plus one shared
    # explicit PING rule (both hosts are agent-less/SNMP-less).
    assert rule_route.call_count == 3
    bodies = [json.loads(c.request.content) for c in rule_route.calls]
    tcp_bodies = [b for b in bodies if b["ruleset"] == "active_checks:tcp"]
    icmp_bodies = [b for b in bodies if b["ruleset"] == "active_checks:icmp"]
    by_port = {json.loads(b["value_raw"])["port"]: b for b in tcp_bodies}
    assert sorted(by_port[22]["conditions"]["host_name"]["match_on"]) == ["10.0.0.60", "promoted-host"]
    assert by_port[80]["conditions"]["host_name"]["match_on"] == ["10.0.0.60"]
    assert len(icmp_bodies) == 1
    assert sorted(icmp_bodies[0]["conditions"]["host_name"]["match_on"]) == ["10.0.0.60", "promoted-host"]


@pytest.mark.asyncio
async def test_phase5_creates_rules_for_scanned_hosts_even_when_none_promoted(monkeypatch):
    # If the user promotes zero hosts in Phase 4, Phase 5 must still create
    # expected-open-port rules for whatever the scan found — this isn't
    # limited to "hosts the user explicitly onboarded."
    scan_results = [ScannedHost(ip="10.0.0.62", open_ports=[443], folder="/")]

    async def fail_if_asked(self, patch_stdout=False, kbi_msg=""):
        raise AssertionError("no prompt should be asked with zero promoted hosts")

    monkeypatch.setattr(questionary.Question, "ask_async", fail_if_asked)

    with respx.mock:
        rule_route = respx.post(f"{BASE}/domain-types/rule/collections/all").mock(
            return_value=Response(200, json={"id": "r1"})
        )
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [], scan_results)

    # One TCP-port rule plus the never-promoted host's explicit PING rule.
    assert rule_route.call_count == 2
    bodies = [json.loads(c.request.content) for c in rule_route.calls]
    tcp_body = next(b for b in bodies if b["ruleset"] == "active_checks:tcp")
    icmp_body = next(b for b in bodies if b["ruleset"] == "active_checks:icmp")
    assert json.loads(tcp_body["value_raw"]) == {"port": 443, "svc_description": "TCP Port 443 (expected open)"}
    assert tcp_body["conditions"] == {"host_name": {"match_on": ["10.0.0.62"], "operator": "one_of"}}
    assert icmp_body["conditions"] == {"host_name": {"match_on": ["10.0.0.62"], "operator": "one_of"}}


@pytest.mark.asyncio
async def test_create_service_discovery_rules_linux_strips_service_suffix_and_anchors():
    # Regression test for a live-debugged real bug: Checkmk's systemd
    # discovery strips the ".service" suffix from the unit name before
    # matching a discovery rule against it (confirmed by installing the
    # real Checkmk agent on a live systemd host and reading its
    # discovery-parsing source) — a rule built from the raw
    # "apache2.service" form silently discovers nothing, no error at all.
    # Also live-verified: a bare (non-"~"-prefixed) name entry requires an
    # *exact* string match rather than being treated as a regex, so every
    # entry must be "~"-prefixed to reliably match.
    host = OnboardedHost(ip="10.0.0.30", hostname="webhost", folder="/vlan10", os_family="linux")
    with respx.mock:
        rule_route = respx.post(f"{BASE}/domain-types/rule/collections/all").mock(
            return_value=Response(200, json={"id": "r1"})
        )
        async with CheckmkClient(CONN) as client:
            await _create_service_discovery_rules(client, host, ["apache2.service", "cron"])

    body = json.loads(rule_route.calls.last.request.content)
    assert body["ruleset"] == "discovery_systemd_units_services"
    assert body["folder"] == "/vlan10"
    assert json.loads(body["value_raw"]) == {"names": ["~^apache2$", "~^cron$"]}
    assert body["conditions"] == {"host_name": {"match_on": ["webhost"], "operator": "one_of"}}


@pytest.mark.asyncio
async def test_create_service_discovery_rules_windows_no_tilde_prefix():
    # Windows's `inventory_services_rules` ("services" list) treats every
    # entry as a regex already — confirmed via the check plugin's own
    # discovery function — so no "~" prefix is used (unlike systemd).
    host = OnboardedHost(ip="10.0.0.31", hostname="dbhost", folder="/", os_family="windows")
    with respx.mock:
        rule_route = respx.post(f"{BASE}/domain-types/rule/collections/all").mock(
            return_value=Response(200, json={"id": "r1"})
        )
        async with CheckmkClient(CONN) as client:
            await _create_service_discovery_rules(client, host, ["MSSQLSERVER"])

    body = json.loads(rule_route.calls.last.request.content)
    assert body["ruleset"] == "inventory_services_rules"
    assert json.loads(body["value_raw"]) == {"services": ["^MSSQLSERVER$"]}


@pytest.mark.asyncio
async def test_create_service_discovery_rules_noop_when_empty():
    host = OnboardedHost(ip="10.0.0.32", hostname="h", folder="/", os_family="linux")
    with respx.mock:
        rule_route = respx.post(f"{BASE}/domain-types/rule/collections/all").mock(return_value=Response(200, json={}))
        async with CheckmkClient(CONN) as client:
            await _create_service_discovery_rules(client, host, [])
    assert not rule_route.called


@pytest.mark.asyncio
async def test_collect_expected_services_ssh_scan_presents_checkbox(monkeypatch):
    async def fake_scan(ip, creds):
        return ["apache2", "cron", "dbus"]

    monkeypatch.setattr("checkmk_wizard.wizard.remote.list_running_systemd_services", fake_scan)

    async def fake_checkbox_ask(self, patch_stdout=False, kbi_msg=""):
        return ["apache2", "cron"]

    monkeypatch.setattr(questionary.Question, "ask_async", fake_checkbox_ask)

    result = await _collect_expected_services("webhost", "10.0.0.30", "linux", SSHCredentials(username="u"))
    assert result == ["apache2", "cron"]


@pytest.mark.asyncio
async def test_collect_expected_services_falls_back_to_manual_when_scan_empty(monkeypatch):
    async def fake_scan(ip, creds):
        return []  # SSH worked but found nothing running (or scan failed) -> manual fallback

    monkeypatch.setattr("checkmk_wizard.wizard.remote.list_running_systemd_services", fake_scan)

    async def fake_text_ask(self, patch_stdout=False, kbi_msg=""):
        return "nginx, redis"

    monkeypatch.setattr(questionary.Question, "ask_async", fake_text_ask)

    result = await _collect_expected_services("webhost", "10.0.0.30", "linux", SSHCredentials(username="u"))
    assert result == ["nginx", "redis"]


@pytest.mark.asyncio
async def test_collect_expected_services_manual_when_no_ssh_creds(monkeypatch):
    async def fake_text_ask(self, patch_stdout=False, kbi_msg=""):
        return "MSSQLSERVER"

    monkeypatch.setattr(questionary.Question, "ask_async", fake_text_ask)

    result = await _collect_expected_services("dbhost", "10.0.0.31", "windows", None)
    assert result == ["MSSQLSERVER"]


@pytest.mark.asyncio
async def test_collect_expected_services_blank_input_skips(monkeypatch):
    async def fake_text_ask(self, patch_stdout=False, kbi_msg=""):
        return ""

    monkeypatch.setattr(questionary.Question, "ask_async", fake_text_ask)

    result = await _collect_expected_services("dbhost", "10.0.0.31", "windows", None)
    assert result == []


def test_verify_expected_services_reports_monitored_and_missing(capsys):
    host = OnboardedHost(
        ip="10.0.0.30", hostname="webhost", folder="/", os_family="linux",
        expected_services=["apache2", "ghost-service"],
    )
    discovery_result = {
        "extensions": {
            "check_table": {
                "systemd_units_services-apache2": {
                    "value": "monitored",
                    "extensions": {"service_name": "Systemd Service apache2"},
                },
            }
        }
    }
    _verify_expected_services(host, discovery_result)
    out = capsys.readouterr().out
    assert "apache2" in out and "is now monitored" in out
    assert "ghost-service" in out and "NOT picked up" in out


def test_verify_expected_services_background_job_no_false_failure(capsys):
    host = OnboardedHost(
        ip="10.0.0.30", hostname="webhost", folder="/", os_family="linux",
        expected_services=["apache2"],
    )
    _verify_expected_services(host, {})  # api.py returns {} for the 204/303 background-job case
    out = capsys.readouterr().out
    assert "could not verify" in out
    assert "NOT picked up" not in out


def test_verify_expected_services_noop_without_expected_services(capsys):
    host = OnboardedHost(ip="10.0.0.30", hostname="webhost", folder="/", os_family="linux")
    _verify_expected_services(host, {"extensions": {"check_table": {}}})
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
async def test_phase5_windows_manual_service_entry_creates_rule(monkeypatch):
    # End-to-end through phase5_onboarding for the windows (always-manual)
    # path: manual service-name entry -> inventory_services_rules rule.
    # No linux host in this batch, so Phase 5's "Attempt automated SSH..."
    # confirm is skipped entirely — the first (and only) prompt is the
    # manual expected-services text field for the windows host.
    answers = iter(["MSSQLSERVER, W3SVC"])

    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return next(answers)

    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)

    host = OnboardedHost(ip="10.0.0.33", hostname="winhost", folder="/", os_family="windows")

    with respx.mock:
        respx.delete(f"{BASE}/objects/host_config/10.0.0.33").mock(return_value=Response(204))
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(return_value=Response(200, json={}))
        rule_route = respx.post(f"{BASE}/domain-types/rule/collections/all").mock(
            return_value=Response(200, json={"id": "r1"})
        )
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [host], [])

    assert host.expected_services == ["MSSQLSERVER", "W3SVC"]
    body = json.loads(rule_route.calls.last.request.content)
    assert body["ruleset"] == "inventory_services_rules"
    assert json.loads(body["value_raw"]) == {"services": ["^MSSQLSERVER$", "^W3SVC$"]}


@pytest.mark.asyncio
async def test_phase6_discovery_verifies_expected_services(monkeypatch, capsys):
    host = OnboardedHost(
        ip="10.0.0.30", hostname="webhost", folder="/", os_family="linux",
        expected_services=["apache2"],
    )
    with respx.mock:
        respx.post(f"{BASE}/domain-types/service_discovery_run/actions/start/invoke").mock(
            return_value=Response(
                200,
                json={
                    "extensions": {
                        "check_table": {
                            "systemd_units_services-apache2": {
                                "value": "monitored",
                                "extensions": {"service_name": "Systemd Service apache2"},
                            }
                        }
                    }
                },
            )
        )
        async with CheckmkClient(CONN) as client:
            await phase6_discovery(client, [host])

    out = capsys.readouterr().out
    assert "is now monitored" in out
