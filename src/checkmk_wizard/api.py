"""Checkmk REST API client.

Endpoints and payloads verified against live Checkmk docs via context7
(docs.checkmk.com, REST API reference) — see docs/CHECKMK_SETUP_CONFIGURATOR_PLAN.md
for the source citations.
"""

from __future__ import annotations

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
        resp = await self._client.request(
            method, path, json=json_body, params=params, headers=headers
        )
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
