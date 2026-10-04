"""Grant test for the rendered Mosquitto ACL and the render script's guard.

The ACL is rendered at broker start from deploy/mosquitto.acl.template with
CMK_SITE_ID. A wrong grant here is a cross-site data leak on a shared broker,
so the exact permission set is asserted, not just spot-checked.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deploy" / "mosquitto.acl.template"
SCRIPT = ROOT / "deploy" / "render-mosquitto-acl.sh"
COMPOSE = ROOT / "deploy" / "compose.yaml"


def _render(tmp_path: Path, site: str | None):
    out = tmp_path / "mosquitto.acl"
    env = {k: v for k, v in os.environ.items() if k != "CMK_SITE_ID"}
    if site is not None:
        env["CMK_SITE_ID"] = site
    proc = subprocess.run(
        ["sh", str(SCRIPT), str(TEMPLATE), str(out)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc, out


def _parse(text: str) -> dict[str, set[tuple[str, str]]]:
    grants: dict[str, set[tuple[str, str]]] = {}
    user = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "user":
            user = parts[1]
            grants[user] = set()
        elif parts[0] == "topic":
            # A topic line outside a user block would apply to anonymous clients.
            assert user is not None, f"topic outside user block: {line}"
            grants[user].add((parts[1], parts[2]))
        else:
            pytest.fail(f"unexpected ACL line: {line}")
    return grants


def test_rendered_grants_are_exact(tmp_path):
    proc, out = _render(tmp_path, "testsite")
    assert proc.returncode == 0, proc.stderr
    text = out.read_text()
    assert "@SITE_ID@" not in text
    assert _parse(text) == {
        "poller": {("readwrite", "sites/testsite/#")},
        "wsreader": {("read", "sites/testsite/lan/#")},
        "wsadmin": {
            ("read", "sites/testsite/lan/#"),
            ("read", "sites/testsite/admin/ack"),
            ("read", "sites/testsite/admin/faked"),
            ("write", "sites/testsite/admin/cmd"),
        },
        "analytics": {
            ("read", "sites/testsite/lan/#"),
            ("read", "sites/testsite/needs/triage/cmd"),
            ("write", "sites/testsite/lan/needs/#"),
            ("write", "sites/testsite/lan/forecasts/#"),
            ("write", "sites/testsite/lan/incidents/+/narration"),
        },
        "wstriage": {("write", "sites/testsite/needs/triage/cmd")},
    }


def test_no_grant_on_bare_wildcard(tmp_path):
    _, out = _render(tmp_path, "testsite")
    for perms in _parse(out.read_text()).values():
        assert all(topic != "#" for _, topic in perms)


@pytest.mark.parametrize("site", ["dmc", "Site_01"])
def test_valid_site_ids_render(tmp_path, site):
    proc, out = _render(tmp_path, site)
    assert proc.returncode == 0, proc.stderr
    assert out.exists()


@pytest.mark.parametrize(
    "site",
    [
        None,
        "",
        "a/b",
        "a b",
        "a#",
        "a+",
        "x;rm",
        "1abc",
        "a" * 17,
        "a\nb",
    ],
)
def test_invalid_site_ids_are_rejected(tmp_path, site):
    proc, out = _render(tmp_path, site)
    assert proc.returncode != 0
    assert not out.exists()
    assert not list(tmp_path.iterdir())


def test_compose_wires_the_renderer():
    text = COMPOSE.read_text()
    assert "./mosquitto.acl.template:/mosquitto/acl.template:ro,z" in text
    assert "./render-mosquitto-acl.sh:/mosquitto/render-acl.sh:ro,z" in text
    assert "CMK_SITE_ID=${CMK_SITE_ID:-dmc}" in text
    assert (
        "render-acl.sh /mosquitto/acl.template /mosquitto/config/mosquitto.acl"
        in text
    )
    assert "./mosquitto.acl:" not in text


def test_analytics_cannot_write_incident_status(tmp_path):
    # incidents/+/status is the poller's topic; analytics only owns narration.
    _, out = _render(tmp_path, "testsite")
    for access, topic in _parse(out.read_text())["analytics"]:
        if access in ("write", "readwrite"):
            assert not topic.endswith("incidents/+/status"), topic
            assert topic != "sites/testsite/lan/#", topic


def test_compose_creates_new_broker_users():
    text = COMPOSE.read_text()
    chown = text.index("chown mosquitto:mosquitto /mosquitto/config/mosquitto.passwd")
    for user, var in (("analytics", "MQTT_ANALYTICS_PASSWORD"), ("wstriage", "TRIAGE_WS_PASSWORD")):
        line = (
            f'mosquitto_passwd -b /mosquitto/config/mosquitto.passwd {user} "$${var}"'
        )
        assert line in text
        assert text.index(line) < chown
