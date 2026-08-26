import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
from httpx import Response

from checkmk_wizard.api import CheckmkAPIError, CheckmkClient, CheckmkConnection, bootstrap_automation_user

CONN = CheckmkConnection(host="cmk.example", site="mysite", username="automation", secret="s3cret")
BASE = "http://cmk.example/mysite/check_mk/api/v1"
LOGIN_URL = "http://cmk.example/mysite/check_mk/login.py"
LOGIN_PAGE_HTML = '<script>var global_csrf_token = "the-csrf-token";</script>'


def test_connection_registration_credential_defaults_to_rest_credential():
    conn = CheckmkConnection(host="cmk.example", site="mysite", username="automation", secret="s3cret")
    assert conn.registration_user == "automation"
    assert conn.registration_secret == "s3cret"


def test_connection_registration_credential_can_be_overridden():
    conn = CheckmkConnection(
        host="cmk.example",
        site="mysite",
        username="automation",
        secret="s3cret",
        registration_user="agent_registration",
        registration_secret="r3g-s3cret",
    )
    assert conn.registration_user == "agent_registration"
    assert conn.registration_secret == "r3g-s3cret"
    # REST credential is untouched by the override.
    assert conn.username == "automation"
    assert conn.secret == "s3cret"


@pytest.mark.asyncio
async def test_get_version():
    with respx.mock:
        respx.get(f"{BASE}/version").mock(return_value=Response(200, json={"versions": {"checkmk": "2.4.0p34"}}))
        async with CheckmkClient(CONN) as client:
            result = await client.get_version()
    assert result["versions"]["checkmk"] == "2.4.0p34"


@pytest.mark.asyncio
async def test_get_version_sends_bearer_auth():
    with respx.mock:
        route = respx.get(f"{BASE}/version").mock(return_value=Response(200, json={}))
        async with CheckmkClient(CONN) as client:
            await client.get_version()
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == "Bearer automation s3cret"


@pytest.mark.asyncio
async def test_create_host():
    with respx.mock:
        route = respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(
            return_value=Response(200, json={"id": "myhost"})
        )
        async with CheckmkClient(CONN) as client:
            result = await client.create_host("myhost", folder="/", attributes={"ipaddress": "10.0.0.5"})
    assert result["id"] == "myhost"
    sent_body = route.calls.last.request.content
    assert b"myhost" in sent_body
    assert b"10.0.0.5" in sent_body


@pytest.mark.asyncio
async def test_delete_host():
    # Live-verified against a real Checkmk 2.4.0p35 CE site: DELETE
    # .../host_config/{name} returns 204 with no If-Match/ETag needed.
    with respx.mock:
        route = respx.delete(f"{BASE}/objects/host_config/myhost").mock(return_value=Response(204))
        async with CheckmkClient(CONN) as client:
            await client.delete_host("myhost")
    assert route.called


@pytest.mark.asyncio
async def test_delete_host_missing_raises():
    with respx.mock:
        respx.delete(f"{BASE}/objects/host_config/ghost").mock(
            return_value=Response(404, json={"title": "Not Found"})
        )
        async with CheckmkClient(CONN) as client:
            with pytest.raises(CheckmkAPIError):
                await client.delete_host("ghost")


@pytest.mark.asyncio
async def test_list_hosts_returns_value_array():
    with respx.mock:
        respx.get(f"{BASE}/domain-types/host_config/collections/all").mock(
            return_value=Response(200, json={"domainType": "host_config", "value": [{"id": "host1"}, {"id": "host2"}]})
        )
        async with CheckmkClient(CONN) as client:
            hosts = await client.list_hosts()
    assert hosts == [{"id": "host1"}, {"id": "host2"}]


@pytest.mark.asyncio
async def test_get_folder_uses_tilde_encoded_id():
    with respx.mock:
        route = respx.get(f"{BASE}/objects/folder_config/~vlan10").mock(
            return_value=Response(200, json={"id": "~vlan10"}, headers={"ETag": "xyz"})
        )
        async with CheckmkClient(CONN) as client:
            resp = await client.get_folder("vlan10")
    assert route.called
    assert resp.headers["ETag"] == "xyz"


@pytest.mark.asyncio
async def test_update_folder_attributes_sends_update_attributes_and_etag():
    with respx.mock:
        route = respx.put(f"{BASE}/objects/folder_config/~vlan10").mock(return_value=Response(200, json={}))
        async with CheckmkClient(CONN) as client:
            await client.update_folder_attributes("vlan10", {"network_scan": {"scan_interval": 86400}}, "etag123")
    assert route.called
    assert route.calls.last.request.headers["If-Match"] == "etag123"
    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body == {"update_attributes": {"network_scan": {"scan_interval": 86400}}}


@pytest.mark.asyncio
async def test_create_rule_sends_ruleset_folder_conditions():
    with respx.mock:
        route = respx.post(f"{BASE}/domain-types/rule/collections/all").mock(
            return_value=Response(200, json={"id": "rule1"})
        )
        async with CheckmkClient(CONN) as client:
            result = await client.create_rule(
                ruleset="active_checks:tcp",
                folder="/",
                value_raw='{"port": 443}',
                conditions={"host_name": {"match_on": ["myhost"], "operator": "one_of"}},
            )
    assert result["id"] == "rule1"
    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body == {
        "ruleset": "active_checks:tcp",
        "folder": "/",
        "value_raw": '{"port": 443}',
        "conditions": {"host_name": {"match_on": ["myhost"], "operator": "one_of"}},
    }


@pytest.mark.asyncio
async def test_list_folders_returns_value_array():
    with respx.mock:
        respx.get(f"{BASE}/domain-types/folder_config/collections/all").mock(
            return_value=Response(200, json={"domainType": "folder_config", "value": [{"id": "/vlan10"}]})
        )
        async with CheckmkClient(CONN) as client:
            folders = await client.list_folders()
    assert folders == [{"id": "/vlan10"}]


@pytest.mark.asyncio
async def test_error_response_raises():
    with respx.mock:
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(
            return_value=Response(400, json={"title": "bad request"})
        )
        async with CheckmkClient(CONN) as client:
            with pytest.raises(CheckmkAPIError):
                await client.create_host("badhost")


@pytest.mark.asyncio
async def test_network_error_wrapped_as_checkmk_api_error():
    # A raw httpx.HTTPError (unreachable host, DNS failure, timeout, ...)
    # must never escape as-is — every CheckmkClient call site in the
    # wizard only catches CheckmkAPIError.
    with respx.mock:
        respx.get(f"{BASE}/version").mock(side_effect=httpx.ConnectError("Name or service not known"))
        async with CheckmkClient(CONN) as client:
            with pytest.raises(CheckmkAPIError, match="Name or service not known"):
                await client.get_version()


@pytest.mark.asyncio
async def test_start_service_discovery_uses_refresh_mode():
    with respx.mock:
        route = respx.post(f"{BASE}/domain-types/service_discovery_run/actions/start/invoke").mock(
            return_value=Response(200, json={})
        )
        async with CheckmkClient(CONN) as client:
            await client.start_service_discovery("myhost")
    assert b'"mode": "refresh"' in route.calls.last.request.content or b'"mode":"refresh"' in route.calls.last.request.content


@pytest.mark.asyncio
async def test_start_service_discovery_accepts_303_background_job():
    with respx.mock:
        respx.post(f"{BASE}/domain-types/service_discovery_run/actions/start/invoke").mock(
            return_value=Response(303, headers={"location": f"{BASE}/objects/background_job/foo"})
        )
        async with CheckmkClient(CONN) as client:
            result = await client.start_service_discovery("myhost", mode="fix_all")
    assert result == {}


@pytest.mark.asyncio
async def test_activate_changes_sends_if_match_etag():
    with respx.mock:
        route = respx.post(f"{BASE}/domain-types/activation_run/actions/activate-changes/invoke").mock(
            return_value=Response(200, json={"id": "run1"})
        )
        async with CheckmkClient(CONN) as client:
            result = await client.activate_changes(["mysite"], etag='"abc123"')
    assert result["id"] == "run1"
    assert route.calls.last.request.headers["If-Match"] == '"abc123"'


@pytest.mark.asyncio
async def test_activate_changes_handles_204():
    with respx.mock:
        respx.post(f"{BASE}/domain-types/activation_run/actions/activate-changes/invoke").mock(
            return_value=Response(204)
        )
        async with CheckmkClient(CONN) as client:
            result = await client.activate_changes(["mysite"], etag='"abc123"')
    assert result == {}


@pytest.mark.asyncio
async def test_get_pending_changes_etag():
    with respx.mock:
        respx.get(f"{BASE}/domain-types/activation_run/collections/pending_changes").mock(
            return_value=Response(200, json={}, headers={"ETag": '"the-etag"'})
        )
        async with CheckmkClient(CONN) as client:
            etag = await client.get_pending_changes_etag()
    assert etag == '"the-etag"'


@pytest.mark.asyncio
async def test_download_agent_uses_os_type_param():
    with respx.mock:
        route = respx.get(f"{BASE}/domain-types/agent/actions/download/invoke").mock(
            return_value=Response(200, content=b"binary-agent-data")
        )
        async with CheckmkClient(CONN) as client:
            data = await client.download_agent("linux_deb")
    assert data == b"binary-agent-data"
    assert route.calls.last.request.url.params["os_type"] == "linux_deb"


@pytest.mark.asyncio
async def test_bootstrap_automation_user_success():
    with respx.mock:
        respx.get(LOGIN_URL).mock(return_value=Response(200, text=LOGIN_PAGE_HTML))
        respx.post(LOGIN_URL).mock(
            return_value=Response(200, headers={"set-cookie": "auth_mysite=cmkadmin:xyz; Path=/"})
        )
        create_route = respx.post(f"{BASE}/domain-types/user_config/collections/all").mock(
            return_value=Response(200, json={})
        )
        respx.get(f"{BASE}/domain-types/activation_run/collections/pending_changes").mock(
            return_value=Response(200, json={"value": []}, headers={"ETag": '"the-etag"'})
        )
        self_url = f"{BASE}/objects/activation_run/run-id"
        activate_route = respx.post(f"{BASE}/domain-types/activation_run/actions/activate-changes/invoke").mock(
            return_value=Response(
                200,
                json={
                    "links": [{"rel": "self", "href": self_url}],
                    "extensions": {"is_running": False},
                },
            )
        )
        status_route = respx.get(self_url)
        await bootstrap_automation_user("cmk.example", "mysite", "adminpw")

    body = json.loads(create_route.calls.last.request.content)
    assert body["username"] == "automation"
    assert body["auth_option"]["auth_type"] == "automation"
    assert body["auth_option"]["store_automation_secret"] is True
    assert body["roles"] == ["admin"]

    # The user-creation call is itself a pending change attributed to
    # cmkadmin — must be activated (as cmkadmin, so it's not "foreign")
    # before it can block a later activate_changes() call as "automation".
    assert activate_route.called
    assert activate_route.calls.last.request.headers["If-Match"] == '"the-etag"'
    activate_body = json.loads(activate_route.calls.last.request.content)
    assert activate_body["force_foreign_changes"] is False
    # Activation already reported done (is_running: false) — no need to poll.
    assert not status_route.called


@pytest.mark.asyncio
async def test_bootstrap_automation_user_polls_until_activation_completes():
    with respx.mock:
        respx.get(LOGIN_URL).mock(return_value=Response(200, text=LOGIN_PAGE_HTML))
        respx.post(LOGIN_URL).mock(
            return_value=Response(200, headers={"set-cookie": "auth_mysite=cmkadmin:xyz; Path=/"})
        )
        respx.post(f"{BASE}/domain-types/user_config/collections/all").mock(
            return_value=Response(200, json={})
        )
        respx.get(f"{BASE}/domain-types/activation_run/collections/pending_changes").mock(
            return_value=Response(200, json={"value": []}, headers={"ETag": '"the-etag"'})
        )
        self_url = f"{BASE}/objects/activation_run/run-id"
        respx.post(f"{BASE}/domain-types/activation_run/actions/activate-changes/invoke").mock(
            return_value=Response(
                200,
                json={"links": [{"rel": "self", "href": self_url}], "extensions": {"is_running": True}},
            )
        )
        status_route = respx.get(self_url)
        status_route.side_effect = [
            Response(200, json={"extensions": {"is_running": True}}),
            Response(200, json={"extensions": {"is_running": False}}),
        ]
        with patch("checkmk_wizard.api.asyncio.sleep", new=AsyncMock()):
            await bootstrap_automation_user("cmk.example", "mysite", "adminpw")

    assert status_route.call_count == 2


@pytest.mark.asyncio
async def test_bootstrap_automation_user_succeeds_even_if_self_activation_fails():
    # The self-cleanup activation is best-effort: the automation user is
    # already created and usable at that point, so a failure here must not
    # be raised as a bootstrap failure.
    with respx.mock:
        respx.get(LOGIN_URL).mock(return_value=Response(200, text=LOGIN_PAGE_HTML))
        respx.post(LOGIN_URL).mock(
            return_value=Response(200, headers={"set-cookie": "auth_mysite=cmkadmin:xyz; Path=/"})
        )
        respx.post(f"{BASE}/domain-types/user_config/collections/all").mock(
            return_value=Response(200, json={})
        )
        respx.get(f"{BASE}/domain-types/activation_run/collections/pending_changes").mock(
            return_value=Response(500, json={"title": "internal error"})
        )
        # No route registered for activate-changes — must not be called
        # (no ETag to extract from the failed GET above), and the missing
        # mock must not raise assert-all-mocked either.
        await bootstrap_automation_user("cmk.example", "mysite", "adminpw")


@pytest.mark.asyncio
async def test_bootstrap_automation_user_raises_without_csrf_token():
    with respx.mock:
        respx.get(LOGIN_URL).mock(return_value=Response(200, text="<html>no token here</html>"))
        with pytest.raises(CheckmkAPIError):
            await bootstrap_automation_user("cmk.example", "mysite", "adminpw")


@pytest.mark.asyncio
async def test_bootstrap_automation_user_wraps_network_error():
    with respx.mock:
        respx.get(LOGIN_URL).mock(side_effect=httpx.ConnectError("Name or service not known"))
        with pytest.raises(CheckmkAPIError, match="Name or service not known"):
            await bootstrap_automation_user("cmk.example", "mysite", "adminpw")


@pytest.mark.asyncio
async def test_bootstrap_automation_user_raises_on_failed_login():
    with respx.mock:
        respx.get(LOGIN_URL).mock(return_value=Response(200, text=LOGIN_PAGE_HTML))
        # No auth_<site> cookie set — wrong password / login rejected.
        respx.post(LOGIN_URL).mock(return_value=Response(200, text="login page again"))
        with pytest.raises(CheckmkAPIError):
            await bootstrap_automation_user("cmk.example", "mysite", "wrongpw")


@pytest.mark.asyncio
async def test_bootstrap_automation_user_raises_on_create_failure():
    with respx.mock:
        respx.get(LOGIN_URL).mock(return_value=Response(200, text=LOGIN_PAGE_HTML))
        respx.post(LOGIN_URL).mock(
            return_value=Response(200, headers={"set-cookie": "auth_mysite=cmkadmin:xyz; Path=/"})
        )
        respx.post(f"{BASE}/domain-types/user_config/collections/all").mock(
            return_value=Response(400, json={"title": "already exists"})
        )
        with pytest.raises(CheckmkAPIError):
            await bootstrap_automation_user("cmk.example", "mysite", "adminpw")
