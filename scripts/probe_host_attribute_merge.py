"""Diagnostic probe: does a partial host-attribute PUT merge or replace?

Targets a live Checkmk 2.4.0p36 CE site and answers the single
highest-risk unknown in Phase 10.1 (10.1-RESEARCH.md Assumption A1 / Open
Question 1), consistent with this project's own rule that Checkmk's live
server behaviour, not its docs, is the source of truth (`api.py:200-206`).

Question: when `CheckmkClient.update_host_attributes()` PUTs
`{"attributes": {...}}` to `/objects/host_config/{name}`
(`api.py:214-223`), does Checkmk MERGE the given keys
into the host's existing attribute set, or REPLACE that set wholesale?
The only existing call site (`wizard.py:1085-1092`) always sends the
complete attribute set it would have passed to `create_host()`, so this
codebase has never exercised a true partial update. If the semantics are
REPLACE, Phase 10.1's bulk retag flow (TAG-04) -- which intends to send
only `tag_device_type` + `alias` -- would silently strip `ipaddress`,
`tag_agent`, `tag_snmp_ds` and `snmp_community` off every retagged host:
exactly the "overwrites the host's existing monitoring method" failure
TAG-04 exists to prevent (10-06-SUMMARY.md finding 1).

This script creates a throwaway host (`gsd-probe-merge-host`, module
constant `PROBE_HOST_NAME`) with a rich attribute set, PUTs a two-key
partial update, diffs the before/after attributes, then separately tests
the replace-safe fallback (echoing the host's full attribute dict back
minus `meta_data`, which is Checkmk-computed and not operator-writable).
It deletes the throwaway host in a `finally` block. It never touches any
real host on the site.

This probe never triggers Checkmk's pending-changes activation step: a
create-then-delete pair on the same throwaway host within one run leaves
a self-cancelling pending change in WATO, which is safe for the operator
to activate or discard later, at their own pace, without this script
forcing an unreviewed activation of unrelated changes.

Stdlib-only (urllib.request, urllib.error, json, os, sys) so it runs with
bare `python3` inside the `automation-worker` container as well as under
`uv run` on the host, matching `scripts/mqtt_poller.py`'s "standalone,
dependency-light" constraint. Does not import `httpx`, `requests`, or the
wizard's own installable package.

Configuration is env-var only: `CMK_REST_HOST` (default `checkmk`),
`CMK_REST_PORT` (default `5000`), `CMK_SITE_ID` (default `dmc`),
`CMK_REST_USERNAME` (default `automation`), `CMK_REST_SECRET` (required).

The `Authorization` header and the raw secret are never printed. If shown
at all, the header is rendered as `Bearer <username> ***`, following
`scripts/probe_checkmk_rest_shapes.py` and `PollerConfig`'s existing
redaction precedent.

Findings: not yet run against a live site
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_REST_HOST = "checkmk"
DEFAULT_REST_PORT = "5000"
DEFAULT_SITE_ID = "dmc"
DEFAULT_REST_USERNAME = "automation"
DEFAULT_TIMEOUT_SECONDS = 10.0

# Throwaway host this probe creates and deletes -- never a real site hostname.
PROBE_HOST_NAME = "gsd-probe-merge-host"

# The rich attribute set P1 creates the probe host with. If the partial PUT
# in P4 is a REPLACE, these three (besides alias, which P4 always overrides
# on purpose) would silently revert/disappear.
_BEFORE_ATTRIBUTES = {
    "ipaddress": "127.0.0.99",
    "tag_agent": "no-agent",
    "tag_snmp_ds": "no-snmp",
    "alias": "gsd-probe-before",
}

# The keys P5 checks for survival to decide MERGE vs REPLACE.
_MERGE_SURVIVAL_KEYS = ("ipaddress", "tag_agent", "tag_snmp_ds")


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
    instead of raising on non-2xx -- several steps below deliberately
    inspect 4xx responses (P3's tag-group existence check, P4/P6's
    rejection diagnostics). `response_headers` is the raw
    `email.message.Message`-like object urllib hands back, so callers can
    do a case-insensitive `.get("ETag", "")`. Only connection-level
    failures raise `ProbeError`, mirroring
    `scripts/probe_checkmk_rest_shapes.py`'s `_rest` helper.
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


def create_probe_host(base_url: str, auth_header: str) -> int:
    print("[P1] Creating throwaway host with a rich attribute set")
    body = {
        "host_name": PROBE_HOST_NAME,
        "folder": "/",
        "attributes": dict(_BEFORE_ATTRIBUTES),
    }
    status, resp_body, _headers = _rest(
        "POST",
        "/domain-types/host_config/collections/all?bake_agent=false",
        base_url=base_url,
        auth_header=auth_header,
        body=body,
    )
    print(f"[P1] status: {status}")
    if status not in (200, 201):
        print(f"[P1] response body: {resp_body}")
    return status


def get_host_state(base_url: str, auth_header: str, label: str) -> tuple[dict[str, Any], str]:
    status, resp_body, headers = _rest(
        "GET", f"/objects/host_config/{PROBE_HOST_NAME}", base_url=base_url, auth_header=auth_header
    )
    print(f"[{label}] GET status: {status}")
    if status != 200 or not isinstance(resp_body, dict):
        raise ProbeError(f"GET host_config/{PROBE_HOST_NAME} returned {status}: {resp_body}")
    extensions = resp_body.get("extensions", {})
    attributes = extensions.get("attributes", {}) if isinstance(extensions, dict) else {}
    etag = headers.get("ETag", "") if headers is not None else ""
    print(f"[{label}] attributes: {attributes}")
    print(f"[{label}] ETag: {etag}")
    return attributes, etag


def detect_device_type_tag_group(base_url: str, auth_header: str) -> bool:
    print("[P3] Checking whether the device_type tag group exists")
    status, _resp_body, _headers = _rest(
        "GET", "/objects/host_tag_group/device_type", base_url=base_url, auth_header=auth_header
    )
    print(f"[P3] GET host_tag_group/device_type status: {status}")
    exists = status == 200
    print(f"[P3] device_type tag group exists: {exists}")
    return exists


def build_partial_body(device_type_exists: bool) -> dict[str, str]:
    if device_type_exists:
        print(
            "[P3] Using body WITH tag_device_type (the group exists on this site) -- "
            "the strongest available evidence for the verdict"
        )
        return {"tag_device_type": "other", "alias": "gsd-probe-after"}
    print(
        "[P3] Using body WITHOUT tag_device_type (the group is absent on this site) -- "
        "the verdict is still meaningful (it rests on ipaddress/tag_agent/tag_snmp_ds "
        "survival) but is slightly weaker evidence without the tag key present"
    )
    return {"alias": "gsd-probe-after"}


def put_partial_attributes(base_url: str, auth_header: str, etag: str, partial_body: dict[str, str]) -> int:
    print(f"[P4] PUT partial attributes: {partial_body}")
    status, resp_body, _headers = _rest(
        "PUT",
        f"/objects/host_config/{PROBE_HOST_NAME}",
        base_url=base_url,
        auth_header=auth_header,
        body={"attributes": partial_body},
        extra_headers={"If-Match": etag},
    )
    print(f"[P4] status: {status}")
    if status not in (200, 204):
        print(f"[P4] response body: {resp_body}")
    return status


def diff_and_verdict(before: dict[str, Any], after: dict[str, Any]) -> str:
    print("[P5] Diffing before/after attributes")
    before_keys = set(before)
    after_keys = set(after)
    removed = before_keys - after_keys
    added = after_keys - before_keys
    changed = {k for k in before_keys & after_keys if before[k] != after[k]}
    print(f"[P5] removed: {sorted(removed)}")
    print(f"[P5] changed: {sorted(changed)}")
    print(f"[P5] added: {sorted(added)}")
    survived = all(after.get(key) == before[key] for key in _MERGE_SURVIVAL_KEYS if key in before)
    if survived:
        print("VERDICT: MERGE")
        return "MERGE"
    print("VERDICT: REPLACE")
    return "REPLACE"


def echo_put_fallback(base_url: str, auth_header: str) -> int:
    """Test the replace-safe fallback plan 10.1-03 would need if P5 finds REPLACE.

    Re-GETs the host for its current attributes and a fresh ETag (P4 already
    consumed the P2 ETag), drops `meta_data` (Checkmk-computed, not
    operator-writable), overrides `alias`, and PUTs the whole dict back.
    """
    print("[P6] Testing replace-safe fallback: echo the full attribute dict back")
    current_attrs, etag = get_host_state(base_url, auth_header, "P6-refresh")
    echo_attrs = dict(current_attrs)
    echo_attrs.pop("meta_data", None)
    echo_attrs["alias"] = "gsd-probe-echo"
    status, resp_body, _headers = _rest(
        "PUT",
        f"/objects/host_config/{PROBE_HOST_NAME}",
        base_url=base_url,
        auth_header=auth_header,
        body={"attributes": echo_attrs},
        extra_headers={"If-Match": etag},
    )
    print(f"[P6] status: {status}")
    if status in (200, 204):
        print("ECHO-PUT: ACCEPTED")
        return status
    print(f"[P6] response body (verbatim): {resp_body}")
    if isinstance(resp_body, dict):
        rejected_detail = resp_body.get("fields") or resp_body.get("detail") or resp_body.get("title")
        print(f"[P6] rejection detail (names the rejected keys, if Checkmk reported them): {rejected_detail}")
    print(f"ECHO-PUT: REJECTED ({status})")
    return status


def delete_probe_host(base_url: str, auth_header: str) -> int:
    print("[P7] Deleting throwaway host")
    status, resp_body, _headers = _rest(
        "DELETE", f"/objects/host_config/{PROBE_HOST_NAME}", base_url=base_url, auth_header=auth_header
    )
    print(f"[P7] status: {status}")
    if status not in (200, 204):
        print(f"[FAIL] cleanup did not return 200/204 -- remove {PROBE_HOST_NAME} by hand in Checkmk Setup -> Hosts")
        print(f"[P7] response body: {resp_body}")
    else:
        print("[P7] cleanup succeeded")
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
    host_created = False
    try:
        create_status = create_probe_host(base_url, auth_header)
        if create_status not in (200, 201):
            print(f"[FAIL] could not create probe host, status {create_status}", file=sys.stderr)
            return 1
        host_created = True

        before_attrs, etag = get_host_state(base_url, auth_header, "P2")

        device_type_exists = detect_device_type_tag_group(base_url, auth_header)
        partial_body = build_partial_body(device_type_exists)

        put_status = put_partial_attributes(base_url, auth_header, etag, partial_body)
        if put_status not in (200, 204):
            print(f"[FAIL] partial PUT failed with status {put_status}", file=sys.stderr)
            exit_code = 1
        else:
            after_attrs, _etag_after = get_host_state(base_url, auth_header, "P5")
            diff_and_verdict(before_attrs, after_attrs)
            echo_put_fallback(base_url, auth_header)
    except ProbeError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        if host_created:
            delete_status = delete_probe_host(base_url, auth_header)
            if delete_status not in (200, 204):
                exit_code = 1
        else:
            print("[P7] skipped -- probe host was never created")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
