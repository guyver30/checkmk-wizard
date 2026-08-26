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
    _create_or_update_host,
    _valid_checkmk_host,
    phase5_onboarding,
)

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
async def test_phase5_deletes_ip_placeholder_when_host_renamed(monkeypatch):
    # Regression test for a live-reported real bug: Phase 3 stages every
    # scanned IP as a placeholder host under its own name (bare
    # `ipaddress` attribute, no tag_agent/tag_snmp_ds — default monitoring
    # settings). When Phase 4 renames it, Phase 5 used to create the new,
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
