"""Manual fallback: provision the narrowly-scoped `topology_editor` Checkmk
role and automation user the dashboard uses for topology writes.

Amended 2026-09-30 (quick 260930-hpy): the wizard now provisions/rotates
this role and user automatically right after Phase 1 (see
`src/checkmk_wizard/wizard.py:_provision_topology_editor`), reading the
same `TOPOLOGY_EDITOR_SECRET` env var this script reads. This script
remains only as a manual fallback for an operator who wants to
(re)provision it without running the whole wizard. The credential itself
no longer lives in the dashboard's browser bundle at all -- it lives in
`deploy/.env` and is injected server-side by the dashboard's nginx on an
allow-list of the exact REST calls the dashboard makes
(`deploy/dashboard-nginx.conf`). This supersedes Phase 13 D-04's
client-embedded credential.

Why a separate scoped user, not the wizard's admin automation user
--------------------------------------------------------------------
The dashboard's write path must never carry the wizard's own full
`admin`-role `automation` user from `bootstrap_automation_user()`
(`src/checkmk_wizard/api.py`) -- a compromised topology_editor credential
would otherwise carry full admin power (user management, global settings,
rulesets), not just "edit hosts and activate my own changes".
`TOPOLOGY_EDITOR_PERMISSIONS` (`src/checkmk_wizard/api.py`) is scoped to
exactly those ids (13-01 VERDICT V-PERMS) and nothing more (RESEARCH.md
Anti-Patterns, Security Domain V4): `wato.activateforeign` and every
`wato.users`/`wato.global`/`wato.rulesets` id are deliberately excluded.

Role clone body shape: source-verified, not live-HTTP-tested
-----------------------------------------------------------------
13-01's probe (`scripts/probe_topology_rest.py`) confirmed the role
create/edit endpoints EXIST (VERDICT V-ROLE: REST) but its
`parse_openapi_paths()` only scanned path/method availability, not
request body schemas -- there is no pasted OpenAPI excerpt naming the
exact field names anywhere in this repo's history, and no live Checkmk
site was reachable from this execution environment to probe further.
Rather than guess, the request bodies implemented in
`CheckmkClient.ensure_topology_editor_role()` were read directly from the
actual installed Checkmk 2.4.0p35 REST endpoint source found on this
machine (2026-09-23):
  `/opt/omd/versions/2.4.0p35.cre/lib/python3/cmk/gui/openapi/endpoints/user_role/__init__.py`
  `/opt/omd/versions/2.4.0p35.cre/lib/python3/cmk/gui/openapi/endpoints/user_role/request_schemas.py`
-- the literal server code that executes the request, a stronger source
than a live HTTP round trip would even be, consistent with this
codebase's "Checkmk's live behaviour, not its docs, is the source of
truth" rule (`src/checkmk_wizard/api.py`). Findings:
  - `CreateUserRole` (POST body): `role_id` (the EXISTING role to clone
    FROM, required), `new_role_id` (the new role's id, optional), and
    `new_alias` (optional).
  - `EditUserRole` (PUT body): `new_permissions`, a dict of permission id
    -> `"yes"`/`"no"`/`"default"`, among other optional fields this
    script does not use.
  - `edit_userrole`'s `@Endpoint(...)` registration passes no `etag=`
    argument, so `ETagBehaviour` defaults to `None` -- unlike
    `host_config`'s PUT, no `If-Match` header is required or sent here.

This script now goes through `CheckmkClient`/`CheckmkConnection`
(`src/checkmk_wizard/api.py`) instead of a bare standard-library HTTP
client, so every REST call is normalized into `CheckmkAPIError` the same
way the wizard's own calls are -- consistent with this codebase's
single-choke-point rule
(`api.py:_request`).

Configuration is env-var only, the same names as the worker compose
service and `scripts/mqtt_poller.py`: `CMK_REST_HOST` (default `checkmk`),
`CMK_REST_PORT` (default `5000`), `CMK_SITE_ID` (default `dmc`),
`CMK_REST_USERNAME` (default `automation`, the wizard's own admin
automation user -- used here server-side only, to provision the new
scoped credential), `CMK_REST_SECRET` (required), and
`TOPOLOGY_EDITOR_SECRET` (optional -- when set, create-or-rotate to this
exact value; when unset, generate one on first create and print it once).

The `Authorization` header and any automation secret are never printed,
except a freshly-generated `topology_editor` secret when
`TOPOLOGY_EDITOR_SECRET` was not pre-chosen -- printed exactly once at
creation time (mirrors `wizard.py`'s `_print_automation_secret_created()`,
OPS-02) -- this is the one value the operator needs and cannot recover
any other way.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys

from checkmk_wizard.api import (
    TOPOLOGY_EDITOR_PERMISSIONS as REQUIRED_PERMISSIONS,
)
from checkmk_wizard.api import (
    TOPOLOGY_EDITOR_ROLE_ALIAS,
    TOPOLOGY_EDITOR_ROLE_ID,
    TOPOLOGY_EDITOR_USER_ID,
    CheckmkAPIError,
    CheckmkClient,
    CheckmkConnection,
    build_role_permissions,
)
from checkmk_wizard.api import (
    build_topology_editor_user_body as build_user_body,
)

# build_role_permissions/build_user_body/REQUIRED_PERMISSIONS are no longer
# called from this module -- CheckmkClient.provision_topology_editor() and
# CheckmkClient.ensure_topology_editor_role() own that logic now -- but stay
# importable here (tests/test_provision_topology_editor.py) as a stable,
# documented re-export of the api.py names this script used to define itself.
__all__ = [
    "REQUIRED_PERMISSIONS",
    "build_role_permissions",
    "build_user_body",
    "generate_secret",
    "main",
    "redact_auth_header",
]

DEFAULT_REST_HOST = "checkmk"
DEFAULT_REST_PORT = "5000"
DEFAULT_SITE_ID = "dmc"
DEFAULT_REST_USERNAME = "automation"

# Mirrors bootstrap_automation_user()'s own bounded poll
# (`src/checkmk_wizard/api.py`): 30 attempts * 0.3s.
_ACTIVATION_POLL_ATTEMPTS = 30
_ACTIVATION_POLL_INTERVAL_SECONDS = 0.3


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
    """A fresh URL-safe automation secret, sized to comfortably clear a
    32-character floor -- kept local (api.py has no standalone equivalent;
    `bootstrap_automation_user()` inlines its own shorter `token_urlsafe(24)`
    call) so this script's secret length stays independently pinned.
    """
    return secrets.token_urlsafe(32)


async def _activate_own_changes(client: CheckmkClient, site_id: str) -> None:
    """Best-effort: activate this script's own pending change (the new
    user/role).

    Mirrors `bootstrap_automation_user()`'s activation sequence: GET the
    pending-changes ETag, POST `activate-changes/invoke` with
    `force_foreign_changes: false`, poll `is_running`. A 401 here means
    Checkmk sees OTHER operators' foreign changes also pending -- this
    script must not force those through, so it prints a warning and
    leaves them for the operator to activate via the GUI, rather than
    escalating to `force_foreign_changes: true`.
    """
    try:
        etag, _ = await client.get_pending_changes()
        run = await client.activate_changes([site_id], etag, force_foreign_changes=False)
    except CheckmkAPIError as exc:
        if exc.status_code == 401:
            print(
                "[activate] other operators' changes are also pending and were NOT forced through "
                "-- activate them yourself in the Checkmk GUI (Setup > Activate pending changes)"
            )
            return
        raise

    run_id = run.get("id")
    is_running = run.get("extensions", {}).get("is_running", False)
    for _ in range(_ACTIVATION_POLL_ATTEMPTS):
        if not is_running or not run_id:
            break
        await asyncio.sleep(_ACTIVATION_POLL_INTERVAL_SECONDS)
        run = await client.get_activation_run(run_id)
        is_running = run.get("extensions", {}).get("is_running", False)
    print("[activate] activation complete")


async def _provision(connection: CheckmkConnection, site_id: str, topology_secret: str) -> int:
    async with CheckmkClient(connection) as client:
        if topology_secret:
            created = await client.provision_topology_editor(topology_secret)
            verb = "created" if created else "rotated"
            print(f"{TOPOLOGY_EDITOR_USER_ID} automation user {verb} from TOPOLOGY_EDITOR_SECRET.")
            await _activate_own_changes(client, site_id)
            return 0

        await client.ensure_topology_editor_role()
        if await client.user_exists(TOPOLOGY_EDITOR_USER_ID):
            print(
                f"{TOPOLOGY_EDITOR_USER_ID} already exists — secret not rotated "
                "(set TOPOLOGY_EDITOR_SECRET to rotate)"
            )
            return 0

        secret = generate_secret()
        await client.upsert_automation_user(
            TOPOLOGY_EDITOR_USER_ID, secret, roles=[TOPOLOGY_EDITOR_ROLE_ID], fullname=TOPOLOGY_EDITOR_ROLE_ALIAS
        )
        print(f"{TOPOLOGY_EDITOR_USER_ID} automation user created.")
        print(
            f"Secret: {secret}\n"
            "Put this into deploy/.env as TOPOLOGY_EDITOR_SECRET, then recreate the dashboard "
            "(podman compose down && podman compose up -d)."
        )
        await _activate_own_changes(client, site_id)
        return 0


def main() -> int:
    rest_host = os.environ.get("CMK_REST_HOST", DEFAULT_REST_HOST)
    rest_port = os.environ.get("CMK_REST_PORT", DEFAULT_REST_PORT)
    site_id = os.environ.get("CMK_SITE_ID", DEFAULT_SITE_ID)
    username = os.environ.get("CMK_REST_USERNAME", DEFAULT_REST_USERNAME)
    secret = os.environ.get("CMK_REST_SECRET", "")
    topology_secret = os.environ.get("TOPOLOGY_EDITOR_SECRET", "").strip()

    if not secret:
        print("[FAIL] CMK_REST_SECRET is not set", file=sys.stderr)
        return 1

    connection = CheckmkConnection(
        host=rest_host, site=site_id, username=username, secret=secret, port=int(rest_port)
    )
    print(f"REST base URL: {connection.base_url}")
    print(f"Authorization: {redact_auth_header(f'Bearer {username} {secret}')}")

    try:
        return asyncio.run(_provision(connection, site_id, topology_secret))
    except CheckmkAPIError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
