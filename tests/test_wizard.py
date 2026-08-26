import json

import pytest
import questionary
import respx
from httpx import Response

from checkmk_wizard.api import CheckmkClient, CheckmkConnection
from checkmk_wizard.wizard import (
    _DELETE_SITE,
    _FOLDER_NAME_RE,
    _HOST_NAME_RE,
    _SITE_NAME_RE,
    OnboardedHost,
    ScannedHost,
    _create_or_update_host,
    _network_scan_attributes,
    _valid_checkmk_host,
    phase2_folders,
    phase3_discovery,
    phase4_classification,
    phase5_onboarding,
)
from checkmk_wizard.scanner import HostScanResult

CONN = CheckmkConnection(host="cmk.example", site="mysite", username="automation", secret="s3cret")
BASE = "http://cmk.example/mysite/check_mk/api/v1"


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
    async def no_ssh(self, patch_stdout=False, kbi_msg=""):
        return False

    monkeypatch.setattr(questionary.Question, "ask_async", no_ssh)

    host = OnboardedHost(ip="10.0.0.7", hostname="10.0.0.7", folder="/", os_family="windows")

    with respx.mock:
        create_route = respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(
            return_value=Response(200, json={})
        )
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [host])

    body = json.loads(create_route.calls.last.request.content)
    assert body["attributes"] == {"ipaddress": "10.0.0.7", "tag_agent": "cmk-agent", "tag_snmp_ds": "no-snmp"}


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
            await phase5_onboarding(client, CONN, [host])

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
            await phase5_onboarding(client, CONN, [host])

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
    async def no_ssh(self, patch_stdout=False, kbi_msg=""):
        return False

    monkeypatch.setattr(questionary.Question, "ask_async", no_ssh)

    host = OnboardedHost(
        ip="10.0.0.20",
        hostname="webserver",
        folder="/",
        os_family="windows",  # avoids a real network probe (linux path pings the host)
        expected_open_ports=[80, 443],
    )

    with respx.mock:
        respx.delete(f"{BASE}/objects/host_config/10.0.0.20").mock(return_value=Response(204))
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(return_value=Response(200, json={}))
        rule_route = respx.post(f"{BASE}/domain-types/rule/collections/all").mock(
            return_value=Response(200, json={"id": "r1"})
        )
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [host])

    assert rule_route.call_count == 2
    bodies = [json.loads(c.request.content) for c in rule_route.calls]
    ports_created = sorted(json.loads(b["value_raw"])["port"] for b in bodies)
    assert ports_created == [80, 443]
    assert bodies[0]["ruleset"] == "active_checks:tcp"
    assert bodies[0]["conditions"] == {"host_name": {"match_on": ["webserver"], "operator": "one_of"}}


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

    with respx.mock:
        respx.delete(f"{BASE}/objects/host_config/10.0.0.21").mock(return_value=Response(204))
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(return_value=Response(200, json={}))
        rule_route = respx.post(f"{BASE}/domain-types/rule/collections/all").mock(
            return_value=Response(200, json={"id": "r1"})
        )
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [host])

    assert rule_route.call_count == 1
    body = json.loads(rule_route.calls.last.request.content)
    assert json.loads(body["value_raw"]) == {"port": 161, "svc_description": "TCP Port 161 (expected open)"}


@pytest.mark.asyncio
async def test_phase5_no_rule_when_no_expected_ports(monkeypatch):
    async def no_ssh(self, patch_stdout=False, kbi_msg=""):
        return False

    monkeypatch.setattr(questionary.Question, "ask_async", no_ssh)

    host = OnboardedHost(ip="10.0.0.22", hostname="10.0.0.22", folder="/", os_family="windows")

    with respx.mock:
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(return_value=Response(200, json={}))
        rule_route = respx.post(f"{BASE}/domain-types/rule/collections/all").mock(return_value=Response(200, json={}))
        async with CheckmkClient(CONN) as client:
            await phase5_onboarding(client, CONN, [host])

    assert not rule_route.called
