"""Diagnostic probe for Checkmk REST/Livestatus payload shapes Phase 10 needs.

Targets a live Checkmk 2.4.0p36 CE site and answers three questions
10-RESEARCH.md could only source from a forum post and an Ansible module,
consistent with this project's own rule that Checkmk's live server
behaviour, not its docs, is the source of truth (`api.py:200-206`,
`scripts/mqtt_poller.py:69-90`):

1. What JSON body does `POST /domain-types/host_tag_group/collections/all`
   actually accept on 2.4.0p36 -- `id` or `ident`, at the group level and
   inside each tags entry? (RESEARCH.md Assumption A1)
2. Does `GET /domain-types/host_config/collections/all` expose a per-host
   `extensions.folder` field, and does a newly created tag group's
   first-tag default show up as an explicit `extensions.attributes` key
   or stay implicit? (Assumption A2)
3. Does Livestatus's `hosts.tags` column key custom tag groups by their
   bare id or with a `tag_` prefix? (Assumption A3)

This script creates a throwaway tag group (`gsd_probe_device_type`) and
deletes it again in a `finally` block. It deliberately never creates the
real `device_type` group -- that is plan 10-02's job, and creating it
here would suppress the "N pre-existing hosts defaulted" count D-08 asks
for.

Stdlib-only (urllib.request, json, socket, os, argparse) so it runs with
bare `python3` inside the poller container as well as under `uv run` on
the host, matching `scripts/mqtt_poller.py`'s "standalone,
dependency-light" constraint.

Live-verified against a real Checkmk 2.4.0p36 CE site on 2026-09-11 (run inside
the `automation-worker` container, REST base
`http://checkmk:5000/dmc/check_mk/api/1.0`, site `dmc`, Checkmk 2.4.0-latest
check-mk-raw):

A1 (tag-group POST body shape) -- CONFIRMED as RESEARCH.md predicted: `id` (not
`ident`) is the accepted top-level key, both at the group level and inside each
`tags[]` entry. The `id`-shape attempt succeeded on the first try (no `ident`
retry needed), HTTP 200. The exact top-level body keys sent and accepted were
`id`, `title`, `tags` (each tag entry: `id`, `title`, `aux_tags: []`). Note:
RESEARCH.md's candidate body also listed a `topic` key -- this probe never
sends one, and it was not required; Checkmk silently defaulted
`extensions.topic` to `"Tags"` in the P3 readback without it being supplied.
The P3 readback round-tripped the same `id`/`title`/`tags` shape.

A2 (host_config folder field) -- CONFIRMED `extensions.folder` IS present on
`host_config` collection entries, closing Pattern 3 Candidate A: observed value
`'/folder2'` for host `192.168.0.1` (a plain `str`, leading slash, no trailing
slash). No `folder_config` link href was found anywhere in the entry's `links`
array (`folder_config link href: none found`) -- Pattern 3 Candidate B is NOT
available on this site/version. Plan 10-03 must implement Candidate A
(`extensions.folder`) directly; there is no link-based fallback to consult.

Tag-group default materialization -- a newly created tag group's implicit
first-tag default does NOT appear as an explicit `extensions.attributes` key.
After creating `gsd_probe_device_type` with `other` as `tags[0]`, the probed
host's `extensions.attributes` still listed only `['ipaddress', 'meta_data',
'tag_agent', 'tag_snmp_ds']` -- no `tag_gsd_probe_device_type` key appeared.
Consequence for plan 10-02: its backfill count must count hosts LACKING an
explicit `tag_device_type` attribute (the default stays implicit and writes
nothing), not hosts whose attribute equals `other`.

A3 (Livestatus tags key shape) -- the three sampled hosts (`test-machine`,
`checkmk_wizard`, `192.168.0.67`) all returned bare (unprefixed) `tags` keys
(`agent`, `snmp_ds`, `criticality`, `ip-v4`, `networking`, `piggyback`, `ping`,
`site`, `address_family`), consistent with a bare-id shape for `device_type`
too by inference from sibling tag groups. This is NOT a full confirmation for
the `device_type` key specifically: no host carried a `device_type` or
`tag_device_type` tag at probe time (Phase 10 has not created the real group
yet), so it is strong inference, not direct observation. Plan 10-06 re-runs
this probe after the wizard has set a real device-type tag to close A3 fully.

Cleanup: DELETE returned 204 and the throwaway `gsd_probe_device_type` group
was removed; the live site was left unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import socket
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_REST_HOST = "checkmk"
DEFAULT_REST_PORT = 5000
DEFAULT_SITE_ID = "dmc"
DEFAULT_LIVESTATUS_HOST = "checkmk"
DEFAULT_LIVESTATUS_PORT = 6557
DEFAULT_TIMEOUT_SECONDS = 10.0

# Throwaway id this probe creates and deletes -- never the real group id
# plan 10-02 creates, so this probe run never suppresses D-08's backfill count.
PROBE_GROUP_ID = "gsd_probe_device_type"

_DEVICE_TYPES_PATH = pathlib.Path(__file__).resolve().parents[1] / "device_types.json"


class ProbeError(RuntimeError):
    """Raised for a connection-level REST/Livestatus failure (not an HTTP status)."""


def _load_device_types() -> list[str]:
    return json.loads(_DEVICE_TYPES_PATH.read_text())


def _rest(
    method: str,
    path: str,
    *,
    base_url: str,
    auth_header: str,
    body: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[int, Any]:
    """Single choke point for every REST call in this probe.

    Returns `(status_code, parsed_json_or_raw_text)` instead of raising on
    non-2xx, since several probes below are deliberately measuring 4xx/404
    responses. Only connection-level failures (`URLError`/`OSError`) raise
    `ProbeError` -- mirrors `mqtt_poller.py`'s `_livestatus_request`
    "normalize every failure into one exception type" shape.
    """
    url = f"{base_url}{path}"
    headers = {"Accept": "application/json", "Authorization": auth_header}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
    except (urllib.error.URLError, OSError) as exc:
        raise ProbeError(f"{method} {url} failed: {exc}") from exc
    text = raw.decode(errors="replace")
    try:
        parsed = json.loads(text) if text else None
    except (json.JSONDecodeError, ValueError):
        parsed = text
    return status, parsed


def probe_real_group_absent(base_url: str, auth_header: str, timeout: float) -> int:
    print("=== P1 probe_real_group_absent ===")
    status, _body = _rest(
        "GET", "/objects/host_tag_group/device_type", base_url=base_url, auth_header=auth_header, timeout=timeout
    )
    print(f"status: {status}")
    if status == 404:
        print("verdict: the real group does not exist yet (expected)")
    elif status == 200:
        print(
            "[WARN] the real group ALREADY EXISTS on this site -- "
            "plan 10-02's backfill count (D-08) will not fire on this site"
        )
    else:
        print(f"verdict: unexpected status {status}")
    return status


def probe_tag_group_create_shape(
    base_url: str, auth_header: str, timeout: float, device_types: list[str]
) -> str | None:
    print("=== P2 probe_tag_group_create_shape ===")
    tags_id = [{"id": c, "title": c, "aux_tags": []} for c in device_types]
    body_id = {"id": PROBE_GROUP_ID, "title": "GSD probe device type", "tags": tags_id}
    status, resp_body = _rest(
        "POST",
        "/domain-types/host_tag_group/collections/all",
        body=body_id,
        base_url=base_url,
        auth_header=auth_header,
        timeout=timeout,
    )
    print(f"id-shape (Checkmk >=2.4.0 candidate) status: {status}")
    print(f"id-shape body: {resp_body}")

    if status in (200, 201):
        print("verdict: accepted key spelling = 'id'")
        return "id"

    if 400 <= status < 500:
        tags_ident = [{"ident": c, "title": c, "aux_tags": []} for c in device_types]
        body_ident = {"ident": PROBE_GROUP_ID, "title": "GSD probe device type", "tags": tags_ident}
        status2, resp_body2 = _rest(
            "POST",
            "/domain-types/host_tag_group/collections/all",
            body=body_ident,
            base_url=base_url,
            auth_header=auth_header,
            timeout=timeout,
        )
        print(f"ident-shape (Checkmk <2.4.0 candidate) status: {status2}")
        print(f"ident-shape body: {resp_body2}")
        if status2 in (200, 201):
            print("verdict: accepted key spelling = 'ident'")
            return "ident"

    print("verdict: neither 'id' nor 'ident' shape was accepted")
    return None


def probe_tag_group_readback(base_url: str, auth_header: str, timeout: float) -> None:
    print("=== P3 probe_tag_group_readback ===")
    status, body = _rest(
        "GET",
        f"/objects/host_tag_group/{PROBE_GROUP_ID}",
        base_url=base_url,
        auth_header=auth_header,
        timeout=timeout,
    )
    print(f"status: {status}")
    print(f"body: {body}")


def probe_host_config_folder_shape(base_url: str, auth_header: str, timeout: float) -> None:
    print("=== P4 probe_host_config_folder_shape ===")
    status, body = _rest(
        "GET",
        "/domain-types/host_config/collections/all",
        base_url=base_url,
        auth_header=auth_header,
        timeout=timeout,
    )
    print(f"status: {status}")
    if status != 200 or not isinstance(body, dict):
        print("verdict: could not read host_config collection -- no host to inspect")
        return
    values = body.get("value", [])
    if not values:
        print("verdict: host_config collection is empty -- no host to inspect")
        return
    entry = values[0]
    print(f"entry id: {entry.get('id')}")
    extensions = entry.get("extensions", {}) if isinstance(entry.get("extensions"), dict) else {}
    print(f"extensions keys: {sorted(extensions.keys())}")

    folder_present = "folder" in extensions
    if folder_present:
        folder_value = extensions["folder"]
        print(f"extensions.folder value: {folder_value!r} (type {type(folder_value).__name__})")
    else:
        print("extensions.folder: ABSENT")

    attributes = extensions.get("attributes", {}) if isinstance(extensions.get("attributes"), dict) else {}
    print(f"extensions.attributes keys: {sorted(attributes.keys())}")
    tag_attribute_key = f"tag_{PROBE_GROUP_ID}"
    tag_materialised = tag_attribute_key in attributes
    print(f"{tag_attribute_key} in extensions.attributes: {tag_materialised}")

    links = entry.get("links", []) if isinstance(entry.get("links"), list) else []
    folder_config_hrefs = [
        link.get("href") for link in links if isinstance(link, dict) and "folder_config" in (link.get("rel") or "")
    ]
    for href in folder_config_hrefs:
        print(f"folder_config link href: {href}")
    if not folder_config_hrefs:
        print("folder_config link href: none found")

    print(
        f"verdict: extensions.folder present={folder_present}; "
        f"{tag_attribute_key} materialised as an explicit attribute={tag_materialised}"
    )


def probe_livestatus_tags_keys(host: str, port: int, timeout: float) -> None:
    print("=== P5 probe_livestatus_tags_keys ===")
    query = "GET hosts\nColumns: name tags\nOutputFormat: json\n\n"
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(query.encode())
            sock.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
    except (TimeoutError, OSError) as exc:
        raise ProbeError(f"Livestatus request to {host}:{port} failed: {exc}") from exc
    text = b"".join(chunks).decode(errors="replace")
    if not text.strip():
        print("verdict: no rows returned -- cannot inspect tags key shape")
        return
    try:
        rows = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ProbeError(f"Malformed Livestatus response from {host}:{port}: {exc}") from exc

    sample = rows[:3]
    for row in sample:
        name, tags = row[0], row[1]
        print(f"host {name}: tags keys = {sorted(tags.keys())}")
    any_prefixed = any(key.startswith("tag_") for row in sample for key in row[1])
    print(
        f"verdict: sampled tags keys are {'tag_-prefixed' if any_prefixed else 'bare (unprefixed)'} "
        "-- no host carried a device-type tag at probe time, so this cannot fully close "
        "Assumption A3 for that specific key; plan 10-06 re-runs this probe after the "
        "wizard has set one"
    )


def cleanup_probe_tag_group(base_url: str, auth_header: str, timeout: float) -> int:
    print("=== P6 cleanup_probe_tag_group ===")
    status, _body = _rest(
        "DELETE",
        f"/objects/host_tag_group/{PROBE_GROUP_ID}",
        base_url=base_url,
        auth_header=auth_header,
        timeout=timeout,
    )
    print(f"delete status: {status}")
    if status not in (200, 204):
        print(f"[FAIL] cleanup did not return 200/204 -- remove {PROBE_GROUP_ID} by hand in Checkmk Setup -> Tags")
    else:
        print("cleanup succeeded")
    return status


def _redact_auth_header(username: str) -> str:
    return f"Bearer {username} ***"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe a live Checkmk 2.4.0p36 CE site's REST API and Livestatus for "
        "the exact payload shapes Phase 10 needs (tag-group POST body, host_config folder "
        "field, Livestatus tags key shape). Creates and deletes a throwaway tag group.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--rest-host", default=os.environ.get("CMK_REST_HOST", DEFAULT_REST_HOST))
    parser.add_argument("--rest-port", type=int, default=int(os.environ.get("CMK_REST_PORT", DEFAULT_REST_PORT)))
    parser.add_argument("--site-id", default=os.environ.get("CMK_SITE_ID", DEFAULT_SITE_ID))
    parser.add_argument("--rest-username", default=os.environ.get("CMK_REST_USERNAME", ""))
    parser.add_argument("--rest-secret", default=os.environ.get("CMK_REST_SECRET", ""))
    parser.add_argument(
        "--livestatus-host", default=os.environ.get("LIVESTATUS_HOST", DEFAULT_LIVESTATUS_HOST)
    )
    parser.add_argument(
        "--livestatus-port",
        type=int,
        default=int(os.environ.get("LIVESTATUS_PORT", DEFAULT_LIVESTATUS_PORT)),
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args()

    if not args.rest_username:
        print("[FAIL] CMK_REST_USERNAME is not set (env var or --rest-username)", file=sys.stderr)
        return 1
    if not args.rest_secret:
        print("[FAIL] CMK_REST_SECRET is not set (env var or --rest-secret)", file=sys.stderr)
        return 1

    base_url = f"http://{args.rest_host}:{args.rest_port}/{args.site_id}/check_mk/api/1.0"
    auth_header = f"Bearer {args.rest_username} {args.rest_secret}"
    print(f"REST base URL: {base_url}")
    print(f"Authorization: {_redact_auth_header(args.rest_username)}")

    device_types = _load_device_types()

    results: dict[str, bool] = {}
    connection_failure = False

    try:
        try:
            probe_real_group_absent(base_url, auth_header, args.timeout)
            results["P1"] = True
        except ProbeError as exc:
            print(f"[FAIL] P1: {exc}")
            results["P1"] = False
            connection_failure = True

        try:
            accepted_shape = probe_tag_group_create_shape(base_url, auth_header, args.timeout, device_types)
            results["P2"] = accepted_shape is not None
        except ProbeError as exc:
            print(f"[FAIL] P2: {exc}")
            results["P2"] = False
            connection_failure = True

        try:
            probe_tag_group_readback(base_url, auth_header, args.timeout)
            results["P3"] = True
        except ProbeError as exc:
            print(f"[FAIL] P3: {exc}")
            results["P3"] = False
            connection_failure = True

        try:
            probe_host_config_folder_shape(base_url, auth_header, args.timeout)
            results["P4"] = True
        except ProbeError as exc:
            print(f"[FAIL] P4: {exc}")
            results["P4"] = False
            connection_failure = True

        try:
            probe_livestatus_tags_keys(args.livestatus_host, args.livestatus_port, args.timeout)
            results["P5"] = True
        except ProbeError as exc:
            print(f"[FAIL] P5: {exc}")
            results["P5"] = False
            connection_failure = True
    finally:
        try:
            cleanup_status = cleanup_probe_tag_group(base_url, auth_header, args.timeout)
            results["P6"] = cleanup_status in (200, 204)
        except ProbeError as exc:
            print(f"[FAIL] P6 cleanup: {exc}")
            results["P6"] = False
            connection_failure = True

    print("=== [SUMMARY] ===")
    for name, produced in results.items():
        print(f"{name}: {'produced a finding' if produced else 'FAILED'}")

    return 1 if connection_failure else 0


if __name__ == "__main__":
    sys.exit(main())
