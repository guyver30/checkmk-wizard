"""Diagnostic probe: closes Phase 13's REST capability unknowns before code
depends on them.

Targets a live Checkmk 2.4.0p35/p36 CE site and answers six questions that
13-RESEARCH.md's Assumptions A1-A4 (and its Open Questions 1-2) leave
unresolved, consistent with this project's own rule that Checkmk's live
server behaviour, not its docs, is the source of truth (`api.py:200-206`,
`scripts/probe_host_attribute_merge.py`).

Questions this script answers (RESEARCH.md section in parentheses):
- P1 (A4, Open Question 1): does the live `openapi-doc.yaml` expose a create
  endpoint for user roles, an edit endpoint for user roles, a create
  endpoint for custom host attribute definitions, and an update endpoint
  for host tag groups? RESEARCH.md's Pitfalls 1/2/4 assume all four are
  absent, sourced only from pre-2.4 community forum threads, not a direct
  read of this site's own spec.
- P2 (A1): what tag ids does each built-in tag group (`agent`, `snmp_ds`,
  `address_family`, `device_type`) actually expose on this site.
- P3 (A1, D-06): the exact host-attribute dict that produces a zero-service
  unmanaged-switch host (no-ip, no-agent, no-snmp, device_type
  NetworkDevice) plus a `map_position`/`unmanaged_switch` label pair.
- P4: whether `parents` and host labels (`map_position`) round-trip through
  a GET -> merge -> PUT -> GET cycle, and whether labels are visible on the
  `host_config` *collection* endpoint the poller already polls (A2).
- P5: whether a browser on another origin can even reach this REST API
  (CORS preflight) -- unasked by RESEARCH.md's Assumptions Log but needed
  before D-04's browser-writes-directly-to-Checkmk design can work at all.
- P6 (A3): the admin role's enabled `wato.*` permission ids, needed to
  scope the write-capable `topology_editor` role RESEARCH.md Pitfall 4
  recommends.

This script creates two throwaway hosts, module constants `PROBE_PARENT`
(`gsd-probe-topo-parent`) and `PROBE_CHILD` (`gsd-probe-topo-child`), and
deletes both in a `finally` block, child first, tolerating a 404 on delete
(the host may never have been created if an earlier step failed). It never
calls Checkmk's changes-activation endpoint: as
`scripts/probe_host_attribute_merge.py` already established, a
create-then-delete pair on the same throwaway host within one run leaves a
self-cancelling pending change in WATO, safe for the operator to activate
or discard later at their own pace, without this script forcing an
unreviewed activation of unrelated changes.

Stdlib-only (urllib.request, urllib.error, json, os, sys, re) so it runs
with bare `python3` inside the `automation-worker` container as well as
under `uv run` on the host, matching
`scripts/probe_host_attribute_merge.py`'s "standalone, dependency-light"
constraint. Does not import `httpx`, `requests`, or the wizard's own
installable package.

Configuration is env-var only, the same five names as the worker compose
service: `CMK_REST_HOST` (default `checkmk`), `CMK_REST_PORT` (default
`5000`), `CMK_SITE_ID` (default `dmc`), `CMK_REST_USERNAME` (default
`automation`), `CMK_REST_SECRET` (required).

The `Authorization` header and the raw secret are never printed. If shown
at all, the header is rendered as `Bearer <username> ***`, following
`scripts/probe_host_attribute_merge.py`'s redaction precedent.

Live-verified against a real Checkmk 2.4.0p35/p36 CE site on 2026-09-23 (the
running site's exact patch version was not printed by this probe;
"2.4.0p35/p36" repeats this docstring's own targeting statement above
rather than a version banner read from output):

VERDICT V-ROLE: REST. P1 printed `user_role create: AVAILABLE` and
`user_role edit: AVAILABLE (matched paths: ['/objects/user_role/{role_id}'])`
-- both role-management endpoints exist, so plan 13-04's `topology_editor`
role can be created and edited over REST, with no manual GUI step required.

VERDICT V-PERMS: `wato.use`, `wato.edit`, `wato.all_folders`,
`wato.edit_hosts`, `wato.manage_hosts`, `wato.activate` -- all six are
present in P6's admin `wato.*` permission list, covering using Setup,
making changes, writing to every folder, modifying existing hosts, adding
hosts, and activating one's own changes respectively. `wato.activateforeign`
is present on the admin role too but is deliberately EXCLUDED from what
`topology_editor` should be granted -- a scoped write role must only
activate its own changes, never someone else's.

VERDICT V-SWITCH: {'tag_address_family': 'no-ip', 'tag_agent': 'no-agent',
'tag_snmp_ds': 'no-snmp', 'tag_device_type': 'NetworkDevice'} -- P3's first
attempt was accepted on the first try (status 200), so no fallback variant
without `tag_device_type` or `tag_address_family` was needed.

VERDICT V-PARENTS: parents round-trip OK (['gsd-probe-topo-parent']) -- a
GET-merge-PUT of `parents` on `host_config` round-trips exactly as sent.

VERDICT V-LABELS: label values with comma and minus accepted: YES (P3
map_position='120,-40' accepted=True; P4 map_position='0,0' accepted=True)
-- both label values, one with a comma and a minus sign and one with only
a comma, were accepted and echoed back unchanged.

VERDICT V-LABELS-IN-COLLECTION: YES -- P4's collection GET showed
`extensions.attributes.labels` present on both probe hosts' collection
entries (`gsd-probe-topo-child` value `{'map_position': '0,0'}`,
`gsd-probe-topo-parent` value `{'map_position': '120,-40',
'unmanaged_switch': 'yes'}`).

VERDICT V-CORS: NOT ALLOWED -- P5's OPTIONS preflight returned status 405
with no `Access-Control-*` response headers at all.

VERDICT V-CUSTOMATTR: P1 printed `custom host attribute definition: ABSENT
(matched paths: [])`. map_position is stored as a host label regardless
(plan decision: labels need no per-site provisioning; D-07's intent of
Checkmk-owned storage on the checkmk_data volume is met identically).

VERDICT V-TAGPUT: P1 printed `host_tag_group update: AVAILABLE (matched
paths: ['/objects/host_tag_group/{name}'])`. unmanaged switches reuse
device_type NetworkDevice (RESEARCH Pitfall 2).

Consequences for plans 13-04/13-05/13-06: plan 13-04 must create and edit
the `topology_editor` role over REST (`POST
/domain-types/user_role/collections/all`, `PUT
/objects/user_role/{role_id}`), granted exactly the six `wato.*` ids listed
under V-PERMS and never `wato.activateforeign` (V-ROLE). Plan 13-04's
poller can read `map_position` and other labels directly from the
`host_config` collection response it already polls, with no extra
per-host GET (V-LABELS-IN-COLLECTION). Plan 13-05 must set
`UNMANAGED_SWITCH_ATTRIBUTES` to exactly `{'tag_address_family': 'no-ip',
'tag_agent': 'no-agent', 'tag_snmp_ds': 'no-snmp', 'tag_device_type':
'NetworkDevice'}`, the dict accepted on the first attempt with no fallback
needed (V-SWITCH). The browser cannot reach Checkmk cross-origin -- CORS is
not enabled -- so plan 13-05's dashboard write path requires a same-origin
proxy in front of Checkmk rather than a direct browser fetch (V-CORS).
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_REST_HOST = "checkmk"
DEFAULT_REST_PORT = "5000"
DEFAULT_SITE_ID = "dmc"
DEFAULT_REST_USERNAME = "automation"
DEFAULT_TIMEOUT_SECONDS = 10.0

# Throwaway hosts this probe creates and deletes -- never real site hostnames.
PROBE_PARENT = "gsd-probe-topo-parent"
PROBE_CHILD = "gsd-probe-topo-child"

# P3's candidate no-ip/no-agent/no-snmp attribute bodies, tried in order on a
# 400 until one is accepted. Each also carries the P3 label pair (see
# _SWITCH_LABELS) so a single accepted attempt answers both V-SWITCH and half
# of V-LABELS (the comma-and-minus value) at once.
_SWITCH_ATTEMPTS: tuple[dict[str, str], ...] = (
    {
        "tag_address_family": "no-ip",
        "tag_agent": "no-agent",
        "tag_snmp_ds": "no-snmp",
        "tag_device_type": "NetworkDevice",
    },
    {
        "tag_address_family": "no-ip",
        "tag_agent": "no-agent",
        "tag_snmp_ds": "no-snmp",
    },
    {
        "tag_agent": "no-agent",
        "tag_snmp_ds": "no-snmp",
    },
)

_SWITCH_LABELS = {"map_position": "120,-40", "unmanaged_switch": "yes"}

# Built-in tag groups P2 inspects.
_TARGET_TAG_GROUPS = ("agent", "snmp_ds", "address_family", "device_type")

# Informational-only candidate permission ids for P6 -- printed for easy
# scanning against the admin role's real, live permission list. The executor
# must not treat this list itself as confirmed.
_CANDIDATE_WATO_PERMISSIONS = (
    "wato.use",
    "wato.edit",
    "wato.all_folders",
    "wato.edit_hosts",
    "wato.manage_hosts",
    "wato.activate",
    "wato.activateforeign",
    "wato.see_all_folders",
)

_PATH_KEY_RE = re.compile(r"^\s*(?P<path>/\S+):\s*$")
_METHOD_KEY_RE = re.compile(r"^\s*(?P<method>get|post|put|delete|patch|options|head):\s*$")


class ProbeError(RuntimeError):
    """Raised for a connection-level REST failure (not an HTTP status)."""


def _redact_auth_header(username: str) -> str:
    return f"Bearer {username} ***"


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
    """Single choke point for every REST call this probe makes.

    Returns `(status_code, parsed_json_or_raw_text, response_headers)`
    instead of raising on non-2xx -- most steps below deliberately inspect
    4xx/404 responses (P1's/P3's rejection diagnostics, cleanup's tolerated
    404). `response_headers` is the raw `email.message.Message`-like object
    urllib hands back, so callers can do a case-insensitive `.get("ETag",
    "")`. Only connection-level failures raise `ProbeError`, mirroring
    `scripts/probe_host_attribute_merge.py`'s `_rest` helper.
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
        raise ProbeError(f"{method} {url} failed: {exc}") from exc
    text = raw.decode(errors="replace")
    try:
        parsed = json.loads(text) if text else None
    except (json.JSONDecodeError, ValueError):
        parsed = text
    return status, parsed, resp_headers


def parse_openapi_paths(yaml_text: str) -> dict[str, set[str]]:
    """Map each OpenAPI `paths:` key to the HTTP methods defined under it.

    No YAML library is used (stdlib-only constraint) -- this scans purely
    on indentation. A path entry matches `_PATH_KEY_RE`; its indentation is
    captured on first sighting and reused to detect the next path at the
    same level. Any `_METHOD_KEY_RE` line seen at greater indentation
    before the next same-indent path key belongs to the path above it.
    Scanning stops as soon as a line returns to indent 0 (leaving the
    top-level `paths:` mapping for a sibling top-level key like
    `components:`).
    """
    result: dict[str, set[str]] = {}
    in_paths = False
    path_indent: int | None = None
    current_path: str | None = None
    for raw_line in yaml_text.splitlines():
        if not raw_line.strip():
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if not in_paths:
            if raw_line.strip() == "paths:" and indent == 0:
                in_paths = True
            continue
        if indent == 0:
            break
        path_match = _PATH_KEY_RE.match(raw_line)
        if path_match and (path_indent is None or indent == path_indent):
            path_indent = indent
            current_path = path_match.group("path")
            result.setdefault(current_path, set())
            continue
        if current_path is None or path_indent is None or indent <= path_indent:
            continue
        method_match = _METHOD_KEY_RE.match(raw_line)
        if method_match:
            result[current_path].add(method_match.group("method"))
    return result


def _has_method(paths: dict[str, set[str]], path: str, method: str) -> bool:
    return method in paths.get(path, set())


def _find_item_paths(paths: dict[str, set[str]], prefix: str) -> list[str]:
    """Every path key of the form '<prefix>/{<any-placeholder-name>}'."""
    pattern = re.compile(rf"^{re.escape(prefix)}/\{{[^}}]+\}}$")
    return sorted(p for p in paths if pattern.match(p))


def probe_openapi_capabilities(base_url: str, auth_header: str) -> None:
    print("=== P1: openapi-doc.yaml capability scan ===")
    status, body, _headers = _rest(
        "GET",
        "/openapi-doc.yaml",
        base_url=base_url,
        auth_header=auth_header,
        extra_headers={"Accept": "*/*"},
    )
    print(f"[P1] GET openapi-doc.yaml status: {status}")
    if status != 200 or not isinstance(body, str):
        print(f"[P1] could not fetch openapi-doc.yaml as text (body type={type(body)})")
        print("[P1] user_role create: ABSENT (could not scan)")
        print("[P1] user_role edit: ABSENT (could not scan)")
        print("[P1] custom host attribute definition: ABSENT (could not scan)")
        print("[P1] host_tag_group update: ABSENT (could not scan)")
        return

    paths = parse_openapi_paths(body)

    role_create = _has_method(paths, "/domain-types/user_role/collections/all", "post")
    print(f"[P1] user_role create: {'AVAILABLE' if role_create else 'ABSENT'}")

    role_item_paths = _find_item_paths(paths, "/objects/user_role")
    role_edit = any(_has_method(paths, p, "put") for p in role_item_paths)
    print(
        f"[P1] user_role edit: {'AVAILABLE' if role_edit else 'ABSENT'} "
        f"(matched paths: {role_item_paths})"
    )

    attr_paths = sorted(p for p in paths if "host_attribute" in p or "custom_attribute" in p)
    attr_create = any(_has_method(paths, p, "post") for p in attr_paths)
    print(
        f"[P1] custom host attribute definition: "
        f"{'AVAILABLE' if attr_create else 'ABSENT'} (matched paths: {attr_paths})"
    )

    tag_group_item_paths = _find_item_paths(paths, "/objects/host_tag_group")
    tag_group_update = any(_has_method(paths, p, "put") for p in tag_group_item_paths)
    print(
        f"[P1] host_tag_group update: "
        f"{'AVAILABLE' if tag_group_update else 'ABSENT'} "
        f"(matched paths: {tag_group_item_paths})"
    )


def probe_tag_groups(base_url: str, auth_header: str) -> None:
    print("=== P2: built-in tag groups ===")
    status, body, _headers = _rest(
        "GET",
        "/domain-types/host_tag_group/collections/all",
        base_url=base_url,
        auth_header=auth_header,
    )
    print(f"[P2] collection GET status: {status}")
    groups_by_id: dict[str, Any] = {}
    if status == 200 and isinstance(body, dict):
        for entry in body.get("value", []):
            gid = entry.get("id")
            if gid:
                groups_by_id[gid] = entry

    for gid in _TARGET_TAG_GROUPS:
        entry = groups_by_id.get(gid)
        if entry is not None:
            tags = entry.get("extensions", {}).get("tags", [])
            tag_ids = [t.get("id") for t in tags if isinstance(t, dict)]
            print(f"[P2] group '{gid}': tag ids = {tag_ids}")
            continue
        print(f"[P2] group '{gid}' not in collection; trying GET /objects/host_tag_group/{gid}")
        status2, body2, _headers2 = _rest(
            "GET",
            f"/objects/host_tag_group/{gid}",
            base_url=base_url,
            auth_header=auth_header,
        )
        print(f"[P2] GET host_tag_group/{gid} status: {status2}")
        if status2 == 200 and isinstance(body2, dict):
            tags2 = body2.get("extensions", {}).get("tags", [])
            tag_ids2 = [t.get("id") for t in tags2 if isinstance(t, dict)]
            print(f"[P2] group '{gid}' (via objects endpoint): tag ids = {tag_ids2}")
        else:
            print(f"[P2] group '{gid}' response: {body2}")


def probe_switch_shape(base_url: str, auth_header: str) -> tuple[bool, dict[str, str] | None]:
    print("=== P3: unmanaged-switch attribute shape ===")
    for attempt_num, attrs in enumerate(_SWITCH_ATTEMPTS, start=1):
        body_attrs: dict[str, Any] = dict(attrs)
        body_attrs["labels"] = dict(_SWITCH_LABELS)
        status, resp_body, _headers = _rest(
            "POST",
            "/domain-types/host_config/collections/all?bake_agent=false",
            base_url=base_url,
            auth_header=auth_header,
            body={"host_name": PROBE_PARENT, "folder": "/", "attributes": body_attrs},
        )
        print(f"[P3] attempt {attempt_num} attributes={attrs} status={status}")
        if status in (200, 201):
            echoed = {}
            if isinstance(resp_body, dict):
                echoed = resp_body.get("extensions", {}).get("attributes", {})
            print(f"[P3] echoed attributes: {echoed}")
            print(f"VERDICT V-SWITCH: {attrs}")
            return True, attrs
        detail = None
        if isinstance(resp_body, dict):
            detail = (
                resp_body.get("fields") or resp_body.get("detail") or resp_body.get("title")
            )
        print(f"[P3] attempt {attempt_num} rejected -- detail: {detail}")
        print(f"[P3] attempt {attempt_num} full response body: {resp_body}")
    print("VERDICT V-SWITCH: NONE ACCEPTED (all attempts rejected)")
    return False, None


def probe_parents_and_labels(
    base_url: str, auth_header: str, *, switch_labels_accepted: bool
) -> bool:
    print("=== P4: parents + label merge round-trip ===")
    child_attrs = {
        "tag_address_family": "no-ip",
        "tag_agent": "no-agent",
        "tag_snmp_ds": "no-snmp",
    }
    status, resp_body, _headers = _rest(
        "POST",
        "/domain-types/host_config/collections/all?bake_agent=false",
        base_url=base_url,
        auth_header=auth_header,
        body={"host_name": PROBE_CHILD, "folder": "/", "attributes": child_attrs},
    )
    print(f"[P4] create {PROBE_CHILD} status: {status}")
    if status not in (200, 201):
        print(f"[P4] create failed, body: {resp_body}")
        print("VERDICT V-PARENTS: FAILED (could not create child host)")
        print("VERDICT V-LABELS: FAILED (could not create child host)")
        return False

    child_created = True

    status, resp_body, headers = _rest(
        "GET",
        f"/objects/host_config/{PROBE_CHILD}",
        base_url=base_url,
        auth_header=auth_header,
    )
    print(f"[P4] GET {PROBE_CHILD} status: {status}")
    if status != 200 or not isinstance(resp_body, dict):
        print("VERDICT V-PARENTS: FAILED (could not GET child host)")
        print("VERDICT V-LABELS: FAILED (could not GET child host)")
        return child_created

    etag = headers.get("ETag", "") if headers is not None else ""
    attributes = dict(resp_body.get("extensions", {}).get("attributes", {}))
    attributes.pop("meta_data", None)
    attributes["parents"] = [PROBE_PARENT]
    attributes["labels"] = {"map_position": "0,0"}

    status, resp_body, _headers = _rest(
        "PUT",
        f"/objects/host_config/{PROBE_CHILD}",
        base_url=base_url,
        auth_header=auth_header,
        body={"attributes": attributes},
        extra_headers={"If-Match": etag},
    )
    print(f"[P4] PUT parents+labels status: {status}")
    if status not in (200, 204):
        print(f"[P4] PUT rejected, body: {resp_body}")
        print("VERDICT V-PARENTS: FAILED (PUT rejected)")
        print("VERDICT V-LABELS: FAILED (PUT rejected)")
        return child_created

    status, resp_body, _headers = _rest(
        "GET",
        f"/objects/host_config/{PROBE_CHILD}",
        base_url=base_url,
        auth_header=auth_header,
    )
    print(f"[P4] re-GET {PROBE_CHILD} status: {status}")
    after_attrs: dict[str, Any] = {}
    if status == 200 and isinstance(resp_body, dict):
        after_attrs = resp_body.get("extensions", {}).get("attributes", {})
    parents_after = after_attrs.get("parents")
    labels_after = after_attrs.get("labels")
    print(f"[P4] parents: {parents_after}")
    print(f"[P4] labels: {labels_after}")

    parents_ok = parents_after == [PROBE_PARENT]
    print(
        f"VERDICT V-PARENTS: parents round-trip {'OK' if parents_ok else 'FAILED'} "
        f"({parents_after})"
    )

    child_label_value = (
        labels_after.get("map_position") if isinstance(labels_after, dict) else None
    )
    child_label_ok = child_label_value == "0,0"
    comma_minus_ok = switch_labels_accepted and child_label_ok
    print(
        "VERDICT V-LABELS: label values with comma and minus accepted: "
        f"{'YES' if comma_minus_ok else 'NO'} "
        f"(P3 map_position='120,-40' accepted={switch_labels_accepted}; "
        f"P4 map_position='0,0' accepted={child_label_ok})"
    )

    status, resp_body, _headers = _rest(
        "GET",
        "/domain-types/host_config/collections/all",
        base_url=base_url,
        auth_header=auth_header,
    )
    print(f"[P4] collection GET status: {status}")
    labels_in_collection = False
    if status == 200 and isinstance(resp_body, dict):
        for entry in resp_body.get("value", []):
            entry_id = entry.get("id") or entry.get("title")
            if entry_id not in (PROBE_PARENT, PROBE_CHILD):
                continue
            entry_attrs = entry.get("extensions", {}).get("attributes", {})
            present = isinstance(entry_attrs, dict) and "labels" in entry_attrs
            entry_label_value = entry_attrs.get("labels") if present else None
            print(
                f"[P4] collection entry {entry_id}: labels present={present} "
                f"value={entry_label_value}"
            )
            if entry_id == PROBE_CHILD and present:
                labels_in_collection = True
    print(f"VERDICT V-LABELS-IN-COLLECTION: {'YES' if labels_in_collection else 'NO'}")

    return child_created


def probe_cors(base_url: str) -> None:
    print("=== P5: CORS preflight ===")
    url = f"{base_url}/objects/host_config/{PROBE_CHILD}"
    headers = {
        "Origin": "http://dashboard.invalid:8090",
        "Access-Control-Request-Method": "PUT",
        "Access-Control-Request-Headers": "authorization,content-type,if-match",
    }
    req = urllib.request.Request(url, method="OPTIONS", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
            status = resp.getcode()
            resp_headers = resp.headers
    except urllib.error.HTTPError as exc:
        status = exc.code
        resp_headers = exc.headers
    except (urllib.error.URLError, OSError) as exc:
        print(f"[P5] OPTIONS request failed: {exc}")
        print("VERDICT V-CORS: NOT ALLOWED (request failed)")
        return

    print(f"[P5] status: {status}")
    header_items = list(resp_headers.items()) if resp_headers is not None else []
    cors_headers = {k: v for k, v in header_items if k.lower().startswith("access-control-")}
    for name, value in cors_headers.items():
        print(f"[P5] header {name}: {value}")

    allow_origin = next(
        (v for k, v in cors_headers.items() if k.lower() == "access-control-allow-origin"), None
    )
    allow_headers = next(
        (v for k, v in cors_headers.items() if k.lower() == "access-control-allow-headers"), ""
    )
    allowed = bool(allow_origin) and "authorization" in (allow_headers or "").lower()
    print(f"VERDICT V-CORS: {'ALLOWED' if allowed else 'NOT ALLOWED'}")


def probe_permissions(base_url: str, auth_header: str) -> None:
    print("=== P6: role permissions ===")
    admin_perms: list[str] = []
    for role_id in ("user", "admin"):
        status, body, _headers = _rest(
            "GET",
            f"/objects/user_role/{role_id}",
            base_url=base_url,
            auth_header=auth_header,
        )
        print(f"[P6] GET user_role/{role_id} status: {status}")
        if status != 200 or not isinstance(body, dict):
            print(f"[P6] {role_id} response: {body}")
            continue
        extensions = body.get("extensions", {})
        ext_keys = sorted(extensions.keys()) if isinstance(extensions, dict) else extensions
        print(f"[P6] {role_id} extensions top-level keys: {ext_keys}")
        if role_id != "admin":
            continue
        perms_raw = None
        for candidate_key in ("permissions", "enabled_permissions", "permission_list"):
            if isinstance(extensions, dict) and candidate_key in extensions:
                perms_raw = extensions[candidate_key]
                print(f"[P6] admin permissions found under extensions['{candidate_key}']")
                break
        if perms_raw is None:
            print(f"[P6] no known permissions key found; full admin extensions: {extensions}")
            perms_raw = []
        if isinstance(perms_raw, list):
            admin_perms = sorted(p for p in perms_raw if isinstance(p, str) and p.startswith("wato."))

    print(f"[P6] admin wato.* permission ids (sorted): {admin_perms}")
    print("[P6] candidate permission presence (informational only, not confirmed):")
    for candidate in _CANDIDATE_WATO_PERMISSIONS:
        present = candidate in admin_perms
        print(f"[P6]   {candidate}: {'present' if present else 'absent'}")


def probe_pending_changes(base_url: str, auth_header: str) -> None:
    print("=== Finally: pending changes ===")
    status, body, headers = _rest(
        "GET",
        "/domain-types/activation_run/collections/pending_changes",
        base_url=base_url,
        auth_header=auth_header,
    )
    print(f"[Finally] status: {status}")
    count = None
    if status == 200 and isinstance(body, dict):
        count = len(body.get("value", []))
    print(f"[Finally] pending changes count: {count}")
    etag = headers.get("ETag") if headers is not None else None
    print(f"[Finally] ETag present: {bool(etag)}")


def delete_probe_host(base_url: str, auth_header: str, host_name: str) -> int:
    status, resp_body, _headers = _rest(
        "DELETE",
        f"/objects/host_config/{host_name}",
        base_url=base_url,
        auth_header=auth_header,
    )
    print(f"[cleanup] DELETE {host_name} status: {status}")
    if status not in (200, 204, 404):
        print(f"[cleanup] unexpected delete status for {host_name}, body: {resp_body}")
        print(f"[cleanup] remove {host_name} by hand in Checkmk Setup -> Hosts if needed")
    return status


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
    print(f"Authorization: {_redact_auth_header(username)}")

    exit_code = 0
    parent_created = False
    child_created = False
    try:
        probe_openapi_capabilities(base_url, auth_header)
        probe_tag_groups(base_url, auth_header)
        parent_created, _accepted_switch_attrs = probe_switch_shape(base_url, auth_header)
        child_created = probe_parents_and_labels(
            base_url, auth_header, switch_labels_accepted=parent_created
        )
        probe_cors(base_url)
        probe_permissions(base_url, auth_header)
        probe_pending_changes(base_url, auth_header)
    except ProbeError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        print("=== Cleanup ===")
        if child_created:
            status = delete_probe_host(base_url, auth_header, PROBE_CHILD)
            if status not in (200, 204, 404):
                exit_code = 1
        else:
            print(f"[cleanup] {PROBE_CHILD} skipped -- never created")
        if parent_created:
            status = delete_probe_host(base_url, auth_header, PROBE_PARENT)
            if status not in (200, 204, 404):
                exit_code = 1
        else:
            print(f"[cleanup] {PROBE_PARENT} skipped -- never created")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
