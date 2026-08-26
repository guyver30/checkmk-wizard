"""Checkmk REST API client.

Endpoints and payloads verified against live Checkmk docs via context7
(docs.checkmk.com, REST API reference) — see docs/CHECKMK_SETUP_CONFIGURATOR_PLAN.md
for the source citations.
"""

from __future__ import annotations

import asyncio
import re
import secrets
from dataclasses import dataclass
from typing import Any, Self

import httpx


class CheckmkAPIError(RuntimeError):
    """Raised when the Checkmk REST API returns an error response."""

    def __init__(self, method: str, url: str, status_code: int, body: Any):
        self.method = method
        self.url = url
        self.status_code = status_code
        self.body = body
        super().__init__(f"{method} {url} -> {status_code}: {body}")


@dataclass
class CheckmkConnection:
    host: str
    site: str
    username: str
    secret: str
    proto: str = "http"
    # Credential used for `cmk-agent-ctl register` (Phase 5.2), kept
    # separate from `username`/`secret` (used for all REST API calls) so a
    # least-privilege registration-only user can be used when available.
    # Defaults to the REST credential if no dedicated one was found — see
    # docs/PLAN-CONFORMANCE-AUDIT.md, Phase 5, credential-scope finding.
    registration_user: str | None = None
    registration_secret: str | None = None

    def __post_init__(self) -> None:
        if self.registration_user is None:
            self.registration_user = self.username
        if self.registration_secret is None:
            self.registration_secret = self.secret

    @property
    def base_url(self) -> str:
        return f"{self.proto}://{self.host}/{self.site}/check_mk/api/v1"


class CheckmkClient:
    """Thin async wrapper around the Checkmk v1 REST API."""

    def __init__(self, connection: CheckmkConnection, timeout: float = 30.0):
        self._conn = connection
        self._client = httpx.AsyncClient(
            base_url=connection.base_url,
            headers={
                "Authorization": f"Bearer {connection.username} {connection.secret}",
                "Accept": "application/json",
            },
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        expect: tuple[int, ...] = (200, 201),
    ) -> httpx.Response:
        headers = {"Content-Type": "application/json"} if json_body is not None else {}
        if extra_headers:
            headers.update(extra_headers)
        # Network-level failures (unreachable host, DNS failure, timeout,
        # connection reset, ...) raise httpx.HTTPError subclasses, not
        # CheckmkAPIError — live-verified an unreachable/malformed
        # `checkmk_host` raises a raw httpx.ConnectError straight through
        # every CheckmkClient method, uncaught by any of the wizard's
        # `except CheckmkAPIError` call sites (every phase has one).
        # Wrapping it here, once, at the single choke point every method
        # goes through, means every existing `except CheckmkAPIError`
        # already in the codebase now also catches connectivity failures —
        # no call site needs to change. status_code=0 signals "no HTTP
        # response was ever received" (no real status code applies).
        try:
            resp = await self._client.request(
                method, path, json=json_body, params=params, headers=headers
            )
        except httpx.HTTPError as exc:
            raise CheckmkAPIError(method, f"{self._client.base_url}{path.lstrip('/')}", 0, str(exc)) from exc
        if resp.status_code not in expect and resp.status_code != 204:
            try:
                body: Any = resp.json()
            except ValueError:
                body = resp.text
            raise CheckmkAPIError(method, str(resp.url), resp.status_code, body)
        return resp

    # -- Phase 1: connectivity -------------------------------------------------

    async def get_version(self) -> dict[str, Any]:
        resp = await self._request("GET", "/version")
        return resp.json()

    # -- Phase 2: folders --------------------------------------------------

    async def create_folder(
        self, name: str, title: str, parent: str = "/", attributes: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        body = {
            "name": name,
            "title": title,
            "parent": parent,
            "attributes": attributes or {},
        }
        resp = await self._request(
            "POST", "/domain-types/folder_config/collections/all", json_body=body
        )
        return resp.json()

    async def list_folders(self) -> list[dict[str, Any]]:
        """List every folder on the site. Collection GET endpoints return
        `{"domainType": ..., "value": [...]}` (verified via context7:
        docs.checkmk.com/latest/en/rest_api.html, pending-changes collection
        example) — same shape as the object this returns from `value`.
        """
        resp = await self._request("GET", "/domain-types/folder_config/collections/all")
        return resp.json().get("value", [])

    # -- Phase 3/5: hosts ----------------------------------------------------

    async def create_host(
        self, host_name: str, folder: str = "/", attributes: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        body = {
            "host_name": host_name,
            "folder": folder,
            "attributes": attributes or {},
        }
        resp = await self._request(
            "POST",
            "/domain-types/host_config/collections/all",
            json_body=body,
            params={"bake_agent": False},
        )
        return resp.json()

    async def list_hosts(self) -> list[dict[str, Any]]:
        """List every host on the site, with its folder and attributes."""
        resp = await self._request("GET", "/domain-types/host_config/collections/all")
        return resp.json().get("value", [])

    async def update_host_attributes(
        self, host_name: str, attributes: dict[str, Any], etag: str
    ) -> dict[str, Any]:
        resp = await self._request(
            "PUT",
            f"/objects/host_config/{host_name}",
            json_body={"attributes": attributes},
            extra_headers={"If-Match": etag},
        )
        return resp.json()

    async def get_host(self, host_name: str) -> httpx.Response:
        return await self._request("GET", f"/objects/host_config/{host_name}")

    async def delete_host(self, host_name: str) -> None:
        # Live-verified against a real Checkmk 2.4.0p35 CE site: DELETE
        # .../host_config/{name} returns 204 with no If-Match/ETag needed,
        # and 404 (raised as CheckmkAPIError) if the host doesn't exist.
        await self._request("DELETE", f"/objects/host_config/{host_name}")

    # -- Phase 5.2: agent download ------------------------------------------

    async def download_agent(self, os_type: str) -> bytes:
        resp = await self._request(
            "GET",
            "/domain-types/agent/actions/download/invoke",
            params={"os_type": os_type},
            extra_headers={"Accept": "application/octet-stream"},
        )
        return resp.content

    # -- Phase 6: service discovery ------------------------------------------

    async def start_service_discovery(self, host_name: str, mode: str = "refresh") -> dict[str, Any]:
        # 303 means Checkmk ran discovery as a background job instead of
        # synchronously (documented behavior of this endpoint) — that's a
        # success, not an error.
        resp = await self._request(
            "POST",
            "/domain-types/service_discovery_run/actions/start/invoke",
            json_body={"host_name": host_name, "mode": mode},
            expect=(200, 201, 303),
        )
        if resp.status_code in (204, 303):
            return {}
        return resp.json()

    # -- Phase 7: activation --------------------------------------------------

    async def get_pending_changes_etag(self) -> str:
        resp = await self._request("GET", "/domain-types/activation_run/collections/pending_changes")
        etag = resp.headers.get("ETag")
        if not etag:
            raise CheckmkAPIError("GET", str(resp.url), resp.status_code, "missing ETag header")
        return etag

    async def activate_changes(
        self, sites: list[str], etag: str, force_foreign_changes: bool = False
    ) -> dict[str, Any]:
        resp = await self._request(
            "POST",
            "/domain-types/activation_run/actions/activate-changes/invoke",
            json_body={
                "redirect": False,
                "sites": sites,
                "force_foreign_changes": force_foreign_changes,
            },
            extra_headers={"If-Match": etag},
            expect=(200, 201, 204),
        )
        if resp.status_code == 204:
            return {}
        return resp.json()


# -- Phase 1: bootstrap the 'automation' REST user ---------------------------

_CSRF_TOKEN_RE = re.compile(r'global_csrf_token\s*=\s*"([^"]+)"')


async def bootstrap_automation_user(
    host: str,
    site: str,
    cmkadmin_password: str,
    proto: str = "http",
    username: str = "automation",
    cmkadmin_user: str = "cmkadmin",
) -> None:
    """Auto-provision the REST 'automation' user right after a fresh site is
    created, instead of requiring the operator to click through Setup >
    Users manually. A fresh Checkmk site does NOT ship a general-purpose
    'automation' user by default — only the narrowly-scoped
    'agent_registration' one (live-verified on a real 2.4.0p35 CE site: its
    `etc/check_mk/multisite.d/wato/users.mk` lists only `cmkadmin` and
    `agent_registration`) — so this has to bootstrap via `cmkadmin`, the
    only credential available immediately after `omd create`.

    `cmkadmin` only has a login password, not an automation secret, so it
    can't Bearer-auth the REST API. Instead this logs in via the GUI's
    session-cookie flow (`login.py`) and uses that cookie to call
    `POST /domain-types/user_config/collections/all` with
    `auth_option.store_automation_secret: true`, which writes the secret
    in cleartext to the exact path `site.read_automation_secret()` already
    reads — so the caller doesn't need to thread the secret through, it's
    picked up on the next `get_site_credentials()` call same as any other
    site-provisioned automation user.

    Checkmk's generic REST API docs (context7) don't cover this exact
    request body or the login-page CSRF flow — both were verified instead
    against a live 2.4.0p35 CE site's own OpenAPI spec
    (`<site>/check_mk/api/1.0/openapi-doc.yaml`) and end-to-end against a
    real running site (login → create user → Bearer-auth with the new
    secret → automation.secret file appears on disk).

    Raises `CheckmkAPIError` on any failure (wrong password, unexpected
    HTML, non-2xx response) — this is best-effort; the caller should treat
    a failure here as "fall back to the existing manual instructions",
    never as fatal.
    """
    base = f"{proto}://{host}/{site}/check_mk"
    login_url = f"{base}/login.py"
    async with httpx.AsyncClient() as client:
        # Unlike CheckmkClient (whose single _request() choke point wraps
        # network-level failures into CheckmkAPIError), this function talks
        # to httpx directly — same live-verified risk (an unreachable/
        # malformed `host` raises a raw httpx.ConnectError) applies here
        # too, so it's wrapped explicitly to keep this function's own
        # documented contract ("raises CheckmkAPIError on any failure")
        # actually true.
        try:
            get_resp = await client.get(login_url)
            match = _CSRF_TOKEN_RE.search(get_resp.text)
            if not match:
                raise CheckmkAPIError("GET", login_url, get_resp.status_code, "no CSRF token found on login page")

            post_resp = await client.post(
                login_url,
                data={
                    "_username": cmkadmin_user,
                    "_password": cmkadmin_password,
                    "_login": "1",
                    "filled_in": "login",
                    "_origtarget": "index.py",
                    "_csrf_token": match.group(1),
                },
            )
            if not client.cookies.get(f"auth_{site}"):
                raise CheckmkAPIError("POST", login_url, post_resp.status_code, "cmkadmin login failed")

            create_resp = await client.post(
                f"{base}/api/v1/domain-types/user_config/collections/all",
                json={
                    "username": username,
                    "fullname": "Wizard Automation User",
                    "auth_option": {
                        "auth_type": "automation",
                        "secret": secrets.token_urlsafe(24),
                        "store_automation_secret": True,
                    },
                    # Matches CHECKMK_SETUP_CONFIGURATOR_PLAN.md's own stated
                    # fallback: a scoped custom role is best practice, but
                    # admin is acceptable for a single-operator setup tool —
                    # there's no built-in role with the general folder/host/
                    # discovery/activation permissions this wizard needs short
                    # of admin.
                    "roles": ["admin"],
                },
                headers={"Accept": "application/json"},
            )
            if create_resp.status_code not in (200, 201):
                try:
                    body: Any = create_resp.json()
                except ValueError:
                    body = create_resp.text
                raise CheckmkAPIError("POST", str(create_resp.url), create_resp.status_code, body)
        except httpx.HTTPError as exc:
            raise CheckmkAPIError("GET/POST", login_url, 0, str(exc)) from exc

        # The user-creation call above is itself a pending WATO change,
        # attributed to cmkadmin (this session) — not to the new automation
        # user. Left un-activated, Phase 7's later activate_changes() call
        # (authenticated as the new automation user, force_foreign_changes
        # left at its safe default of False) fails with 401 "There are
        # changes from other users and foreign changes are not allowed" —
        # live-verified: GET pending_changes right after user creation
        # showed exactly one entry, user_id=cmkadmin, action edit-users.
        # Activate it now, while still authenticated as cmkadmin activating
        # its own change (no foreign-changes issue), so it's never still
        # pending by the time anything else needs to activate changes.
        #
        # activate-changes runs as an async background job (the response
        # comes back "is_running": true immediately) — live-verified that
        # NOT waiting for it leaves a real race: a follow-up
        # activate_changes() call moments later (e.g. Phase 2's very first
        # folder create + an immediate activation) can still see the
        # cmkadmin change as pending/in-progress and hit the same 401.
        #
        # Checkmk's response includes a "wait-for-completion" link, but
        # live-verified it's a redirect-based long-poll (302 while running,
        # not a single blocking call) — httpx doesn't follow redirects by
        # default, and blindly following them hits `TooManyRedirects`
        # rather than actually waiting. Polling the activation_run object's
        # own `is_running` flag directly is simpler and fully under our
        # control; live-verified this single-change activation completes
        # in a few seconds.
        #
        # Best-effort throughout: the automation user is already created
        # and usable even if this cleanup step fails or times out, so
        # failures here are swallowed rather than raised — worst case,
        # whatever calls activate_changes next hits the same
        # foreign-changes error this wizard had before auto-provisioning
        # existed, no worse off.
        try:
            pending_resp = await client.get(
                f"{base}/api/v1/domain-types/activation_run/collections/pending_changes"
            )
            etag = pending_resp.headers.get("ETag")
            if etag:
                activate_resp = await client.post(
                    f"{base}/api/v1/domain-types/activation_run/actions/activate-changes/invoke",
                    json={"redirect": False, "sites": [site], "force_foreign_changes": False},
                    headers={"Accept": "application/json", "If-Match": etag},
                )
                activation = activate_resp.json()
                self_url = next(
                    (link["href"] for link in activation.get("links", []) if link.get("rel") == "self"),
                    None,
                )
                is_running = activation.get("extensions", {}).get("is_running", False)
                for _ in range(30):
                    if not is_running or not self_url:
                        break
                    await asyncio.sleep(0.3)
                    status_resp = await client.get(self_url, headers={"Accept": "application/json"})
                    is_running = status_resp.json().get("extensions", {}).get("is_running", False)
        except httpx.HTTPError:
            pass
