import pytest
import respx
from httpx import Response

from checkmk_wizard.api import CheckmkAPIError, CheckmkClient, CheckmkConnection

CONN = CheckmkConnection(host="cmk.example", site="mysite", username="automation", secret="s3cret")
BASE = "http://cmk.example/mysite/check_mk/api/v1"


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
async def test_error_response_raises():
    with respx.mock:
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(
            return_value=Response(400, json={"title": "bad request"})
        )
        async with CheckmkClient(CONN) as client:
            with pytest.raises(CheckmkAPIError):
                await client.create_host("badhost")


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
