"""One-time provisioning: a narrowly-scoped `topology_editor` Checkmk role
plus automation user for the dashboard's direct-to-Checkmk write path (D-04).

Why a separate scoped user, not the wizard's admin automation user
--------------------------------------------------------------------
D-04 flagged this explicitly: the dashboard's browser bundle embeds this
credential client-side (T-13-09), so it must never be the wizard's own
full `admin`-role `automation` user from `bootstrap_automation_user()`
(`src/checkmk_wizard/api.py:386`) -- a leaked/exfiltrated secret from
DevTools would otherwise carry full admin power (user management, global
settings, rulesets), not just "edit hosts and activate my own changes".
`topology_editor` is scoped to exactly the ids in `REQUIRED_PERMISSIONS`
below (13-01 VERDICT V-PERMS) and nothing more (RESEARCH.md Anti-Patterns,
Security Domain V4): `wato.activateforeign` and every `wato.users`/
`wato.global`/`wato.rulesets` id are deliberately excluded.

Role clone body shape: source-verified, not live-HTTP-tested
-----------------------------------------------------------------
13-01's probe (`scripts/probe_topology_rest.py`) confirmed the role
create/edit endpoints EXIST (VERDICT V-ROLE: REST) but its
`parse_openapi_paths()` only scanned path/method availability, not
request body schemas -- there is no pasted OpenAPI excerpt naming the
exact field names anywhere in this repo's history, and no live Checkmk
site was reachable from this execution environment to probe further.
Rather than guess, this script's request bodies were read directly from
the actual installed Checkmk 2.4.0p35 REST endpoint source found on this
machine (2026-09-23):
  `/opt/omd/versions/2.4.0p35.cre/lib/python3/cmk/gui/openapi/endpoints/user_role/__init__.py`
  `/opt/omd/versions/2.4.0p35.cre/lib/python3/cmk/gui/openapi/endpoints/user_role/request_schemas.py`
-- the literal server code that executes the request, a stronger source
than a live HTTP round trip would even be, consistent with this
codebase's "Checkmk's live behaviour, not its docs, is the source of
truth" rule (`src/checkmk_wizard/api.py:200-206`). Findings:
  - `CreateUserRole` (POST body): `role_id` (the EXISTING role to clone
    FROM, required), `new_role_id` (the new role's id, optional), and
    `new_alias` (optional).
  - `EditUserRole` (PUT body): `new_permissions`, a dict of permission id
    -> `"yes"`/`"no"`/`"default"`, among other optional fields this
    script does not use.
  - `edit_userrole`'s `@Endpoint(...)` registration passes no `etag=`
    argument, so `ETagBehaviour` defaults to `None` -- unlike
    `host_config`'s PUT, no `If-Match` header is required or sent here.
If a future Checkmk version changes this shape, the POST/PUT below 400s
and this script prints the full rejection body (mirroring
`scripts/probe_topology_rest.py`'s diagnostic style) rather than
silently believing it succeeded.

User creation and change-activation body shapes reuse
`bootstrap_automation_user()`'s already-live-proven shapes
(`src/checkmk_wizard/api.py:386-535`) verbatim: `auth_option.auth_type`/
`store_automation_secret` for the user, and the
`pending_changes` ETag -> `activate-changes/invoke` -> poll `is_running`
sequence for activation.

Stdlib-only (urllib.request, urllib.error, json, os, secrets, sys) so it
runs with bare `python3` inside the `automation-worker` container as well
as under `uv run` on the host, matching `scripts/probe_topology_rest.py`'s
"standalone, dependency-light" constraint. Does not import `httpx`,
`requests`, or the wizard's own installable package.

Configuration is env-var only, the same names as the worker compose
service and `scripts/mqtt_poller.py`: `CMK_REST_HOST` (default `checkmk`),
`CMK_REST_PORT` (default `5000`), `CMK_SITE_ID` (default `dmc`),
`CMK_REST_USERNAME` (default `automation`, the wizard's own admin
automation user -- used here server-side only, to provision the new
scoped credential), `CMK_REST_SECRET` (required).

The `Authorization` header and the raw secret are never printed, except
the freshly-generated `topology_editor` secret itself, printed exactly
once at creation time (mirrors `wizard.py`'s
`_print_automation_secret_created()`, OPS-02) -- this is the one value
the operator needs and cannot recover any other way.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_REST_HOST = "checkmk"
DEFAULT_REST_PORT = "5000"
DEFAULT_SITE_ID = "dmc"
DEFAULT_REST_USERNAME = "automation"
DEFAULT_TIMEOUT_SECONDS = 10.0

ROLE_ID = "topology_editor"
ROLE_ALIAS = "Topology editor (dashboard)"
# The built-in role topology_editor is cloned from -- least-privileged
# non-admin built-in role (RESEARCH.md Pitfall 4: "clone user, name it
# e.g. topology_editor, enable only host-edit and activate-changes
# permissions").
BASE_ROLE_ID = "user"
USER_ID = "topology_editor"

# 13-01's VERDICT V-PERMS (2026-09-23) listed six ids derived from which
# wato.* permissions the ADMIN role happened to have enabled -- it never
# live-tested the scoped role itself. Live UAT (2026-09-23) found that six
# was incomplete: a freshly-cloned role with no folder contact-group
# membership got a blanket 404 on GET /objects/host_config/{name} for
# every host, because `wato.all_folders` only grants WRITE access to every
# folder -- it does not make the role able to SEE (discover) a host it
# isn't a contact for in the first place. `wato.see_all_folders` is the
# separate "see" counterpart to `wato.all_folders`'s "write", and without
# it a scoped role can edit nothing because it can't find anything.
# `wato.activateforeign` is present on the admin role too but is
# deliberately EXCLUDED -- a scoped write role must only activate its own
# changes, never someone else's.
REQUIRED_PERMISSIONS: tuple[str, ...] = (
    "wato.use",
    "wato.edit",
    "wato.all_folders",
    "wato.see_all_folders",
    "wato.edit_hosts",
    "wato.manage_hosts",
    "wato.activate",
)

# Mirrors bootstrap_automation_user()'s own bounded poll
# (`src/checkmk_wizard/api.py:525-528`): 30 attempts * 0.3s.
_ACTIVATION_POLL_ATTEMPTS = 30
_ACTIVATION_POLL_INTERVAL_SECONDS = 0.3


class ProvisionError(RuntimeError):
    """Raised for a connection-level REST failure (not an HTTP status)."""


def redact_auth_header(header: str) -> str:
    """Mask the secret in a full `Authorization` header value.

    `"Bearer <username> <secret>"` -> `"Bearer <username> ***"`. A header
    that doesn't parse into exactly that three-part shape is fully masked
    rather than partially leaking something unexpected.
    """
    parts = header.split(" ", 2)
    if len(parts) == 3 and parts[0] == "Bearer":
        return f"{parts[0]} {parts[1]} ***"
    return "Bearer *** ***"


def generate_secret() -> str:
    """A fresh URL-safe automation secret, mirroring
    `bootstrap_automation_user()`'s `secrets.token_urlsafe(24)`
    (`api.py:432`) but sized up to comfortably clear a 32-character floor.
    """
    return secrets.token_urlsafe(32)


def build_role_permissions(perm_ids: tuple[str, ...]) -> dict[str, str]:
    """Map each permission id to `"yes"` (enabled) -- `EditUserRole.new_permissions`' shape."""
    return {perm_id: "yes" for perm_id in perm_ids}


def build_user_body(username: str, secret: str) -> dict[str, Any]:
    """`POST /domain-types/user_config/collections/all` body, `roles: [ROLE_ID]` --
    never `["admin"]` (T-13-09). Shape otherwise identical to
    `bootstrap_automation_user()`'s proven-working body
    (`api.py:446-464`).
    """
    return {
        "username": username,
        "fullname": ROLE_ALIAS,
        "auth_option": {
            "auth_type": "automation",
            "secret": secret,
            "store_automation_secret": True,
        },
        "roles": [ROLE_ID],
    }


def _rest(
    method: str,
    path: str,
    *,
    base_url: str,
    auth_header: str,
    body: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[int, Any, Any]:
    """Single choke point for every REST call this script makes.

    Returns `(status_code, parsed_json_or_raw_text, response_headers)`
    instead of raising on non-2xx, mirroring
    `scripts/probe_topology_rest.py`'s `_rest()` helper -- several steps
    below deliberately inspect 4xx/404 (idempotent "already exists"
    checks, rejection diagnostics). Only connection-level failures raise
    `ProvisionError`.
    """
    url = f"{base_url}{path}"
    headers = {"Accept": "application/json", "Authorization": auth_header}
    if extra_headers:
        headers.update(extra_headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            raw = resp.read()
            resp_headers = resp.headers
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
        resp_headers = exc.headers
    except (urllib.error.URLError, OSError) as exc:
        raise ProvisionError(f"{method} {url} failed: {exc}") from exc
    text = raw.decode(errors="replace")
    try:
        parsed = json.loads(text) if text else None
    except (json.JSONDecodeError, ValueError):
        parsed = text
    return status, parsed, resp_headers


def _print_rejection(label: str, status: int, body: Any) -> None:
    print(f"[{label}] rejected -- status {status}")
    if isinstance(body, dict):
        detail = body.get("fields") or body.get("detail") or body.get("title")
        print(f"[{label}] detail: {detail}")
    print(f"[{label}] full response body: {body}")


def ensure_role(base_url: str, auth_header: str) -> bool:
    """Idempotently create/clone `ROLE_ID` and (re)assert its permissions.

    Skips the clone step (only) if `GET /objects/user_role/{ROLE_ID}`
    already returns 200 -- the permission PUT always runs regardless, so
    a re-run always re-asserts the exact `REQUIRED_PERMISSIONS` set even
    if it drifted via the GUI.
    """
    status, _body, _headers = _rest(
        "GET", f"/objects/user_role/{ROLE_ID}", base_url=base_url, auth_header=auth_header
    )
    if status == 200:
        print(f"[role] {ROLE_ID} already exists -- skipping clone")
    else:
        print(f"[role] cloning {BASE_ROLE_ID} -> {ROLE_ID}")
        status, body, _headers = _rest(
            "POST",
            "/domain-types/user_role/collections/all",
            base_url=base_url,
            auth_header=auth_header,
            body={"role_id": BASE_ROLE_ID, "new_role_id": ROLE_ID, "new_alias": ROLE_ALIAS},
        )
        if status not in (200, 201):
            _print_rejection("role-clone", status, body)
            return False
        print(f"[role] {ROLE_ID} created")

    print(f"[role] setting permissions: {sorted(REQUIRED_PERMISSIONS)}")
    status, body, _headers = _rest(
        "PUT",
        f"/objects/user_role/{ROLE_ID}",
        base_url=base_url,
        auth_header=auth_header,
        body={"new_permissions": build_role_permissions(REQUIRED_PERMISSIONS)},
    )
    if status not in (200, 204):
        _print_rejection("role-edit", status, body)
        return False
    print("[role] permissions set")
    return True


def activate_own_changes(base_url: str, auth_header: str, site_id: str) -> None:
    """Best-effort: activate this script's own pending change (the new user/role).

    Mirrors `bootstrap_automation_user()`'s activation sequence
    (`api.py:508-532`): GET the pending-changes ETag, POST
    `activate-changes/invoke` with `force_foreign_changes: false`, poll
    `is_running`. A 401 here means Checkmk sees OTHER operators' foreign
    changes also pending -- this script must not force those through, so
    it prints a warning and leaves them for the operator to activate via
    the GUI (plan 13-04's own instruction), rather than escalating to
    `force_foreign_changes: true`.
    """
    status, _body, headers = _rest(
        "GET",
        "/domain-types/activation_run/collections/pending_changes",
        base_url=base_url,
        auth_header=auth_header,
    )
    etag = headers.get("ETag", "") if status == 200 and headers is not None else ""
    if not etag:
        print("[activate] no pending changes ETag -- nothing to activate")
        return

    status, body, _headers = _rest(
        "POST",
        "/domain-types/activation_run/actions/activate-changes/invoke",
        base_url=base_url,
        auth_header=auth_header,
        body={"redirect": False, "sites": [site_id], "force_foreign_changes": False},
        extra_headers={"If-Match": etag},
    )
    if status == 401:
        print(
            "[activate] other operators' changes are also pending and were NOT forced through "
            "-- activate them yourself in the Checkmk GUI (Setup > Activate pending changes)"
        )
        return
    if status not in (200, 303):
        _print_rejection("activate", status, body)
        return

    self_url = None
    is_running = False
    if isinstance(body, dict):
        self_url = next(
            (link["href"] for link in body.get("links", []) if link.get("rel") == "self"), None
        )
        is_running = body.get("extensions", {}).get("is_running", False)
    for _ in range(_ACTIVATION_POLL_ATTEMPTS):
        if not is_running or not self_url:
            break
        time.sleep(_ACTIVATION_POLL_INTERVAL_SECONDS)
        status, poll_body, _headers = _rest(
            "GET", self_url.replace(base_url, ""), base_url=base_url, auth_header=auth_header
        )
        is_running = (
            poll_body.get("extensions", {}).get("is_running", False)
            if isinstance(poll_body, dict)
            else False
        )
    print("[activate] activation complete")


def ensure_user(base_url: str, auth_header: str, site_id: str) -> int:
    """Idempotently create `USER_ID`, printing its secret exactly once.

    Returns a process exit code: 0 on success (created or already
    existed), 1 on a rejected create.
    """
    status, _body, _headers = _rest(
        "GET", f"/objects/user_config/{USER_ID}", base_url=base_url, auth_header=auth_header
    )
    if status == 200:
        print(f"{USER_ID} already exists — secret not rotated")
        return 0

    secret = generate_secret()
    status, body, _headers = _rest(
        "POST",
        "/domain-types/user_config/collections/all",
        base_url=base_url,
        auth_header=auth_header,
        body=build_user_body(USER_ID, secret),
    )
    if status not in (200, 201):
        _print_rejection("user-create", status, body)
        return 1

    print(f"{USER_ID} automation user created.")
    print(
        f"Secret: {secret}\n"
        "Paste this into TOPOLOGY_EDITOR_SECRET in dashboard-react/src/lib/config.ts "
        "— it will not be shown again."
    )
    activate_own_changes(base_url, auth_header, site_id)
    return 0


def main() -> int:
    rest_host = os.environ.get("CMK_REST_HOST", DEFAULT_REST_HOST)
    rest_port = os.environ.get("CMK_REST_PORT", DEFAULT_REST_PORT)
    site_id = os.environ.get("CMK_SITE_ID", DEFAULT_SITE_ID)
    username = os.environ.get("CMK_REST_USERNAME", DEFAULT_REST_USERNAME)
    secret = os.environ.get("CMK_REST_SECRET", "")

    if not secret:
        print("[FAIL] CMK_REST_SECRET is not set", file=sys.stderr)
        return 1

    base_url = f"http://{rest_host}:{rest_port}/{site_id}/check_mk/api/1.0"
    auth_header = f"Bearer {username} {secret}"
    print(f"REST base URL: {base_url}")
    print(f"Authorization: {redact_auth_header(auth_header)}")

    try:
        if not ensure_role(base_url, auth_header):
            return 1
        return ensure_user(base_url, auth_header, site_id)
    except ProvisionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
