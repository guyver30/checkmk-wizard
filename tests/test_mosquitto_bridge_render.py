"""Tests for the cloud bridge renderer and its compose wiring.

The bridge file is broker config built from operator-supplied values, so every
malformed value must fail closed without writing a file.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deploy" / "mosquitto.bridge.template"
SCRIPT = ROOT / "deploy" / "render-mosquitto-bridge.sh"
COMPOSE = ROOT / "deploy" / "compose.yaml"

_VARS = (
    "SITE_SEN",
    "CMK_SITE_ID",
    "CLOUD_BROKER_HOST",
    "CLOUD_BROKER_PORT",
    "CLOUD_BROKER_PASSWORD",
    "CLOUD_BROKER_CAFILE",
    "MQTT_BRIDGE_PASSWORD",
)
_GOOD_PW = "aB3_x.y~z=q+r-1"


def _render(tmp_path: Path, **overrides: str | None):
    """Render into tmp_path/out/bridge.conf; the CA file lives in tmp_path/ca."""
    ca_dir = tmp_path / "ca"
    out_dir = tmp_path / "out"
    ca_dir.mkdir(exist_ok=True)
    out_dir.mkdir(exist_ok=True)
    ca = ca_dir / "cloud-ca.pem"
    ca.write_text("dummy")
    values: dict[str, str | None] = {
        "SITE_SEN": "123",
        "CMK_SITE_ID": "dmc",
        "CLOUD_BROKER_HOST": "cloud.example.com",
        "CLOUD_BROKER_PORT": None,
        "CLOUD_BROKER_PASSWORD": _GOOD_PW,
        "CLOUD_BROKER_CAFILE": str(ca),
        "MQTT_BRIDGE_PASSWORD": "Zz9" + _GOOD_PW,
    }
    values.update(overrides)
    env = {k: v for k, v in os.environ.items() if k not in _VARS}
    env.update({k: v for k, v in values.items() if v is not None})
    out = out_dir / "bridge.conf"
    proc = subprocess.run(
        ["sh", str(SCRIPT), str(TEMPLATE), str(out)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc, out


def _assert_rejected(proc, out: Path):
    assert proc.returncode != 0
    assert not out.exists()
    assert not list(out.parent.iterdir())


def test_valid_render(tmp_path):
    proc, out = _render(tmp_path)
    assert proc.returncode == 0, proc.stderr
    text = out.read_text()
    for line in (
        "connection cloud-123-dmc",
        "address cloud.example.com:8883",
        "bridge_protocol_version mqttv50",
        "remote_clientid bridge-123-dmc",
        "remote_username 123",
        "cleansession false",
        "notifications false",
        "topic # out 1 sites/dmc/ app/123/dmc/",
    ):
        assert line in text.splitlines(), line
    assert "@" not in text
    assert stat.S_IMODE(out.stat().st_mode) == 0o600


def test_custom_port(tmp_path):
    proc, out = _render(tmp_path, CLOUD_BROKER_PORT="8884")
    assert proc.returncode == 0, proc.stderr
    assert "address cloud.example.com:8884" in out.read_text()


@pytest.mark.parametrize("host", [None, ""])
def test_disabled_removes_output(tmp_path, host):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "bridge.conf").write_text("old")
    proc, out = _render(tmp_path, CLOUD_BROKER_HOST=host)
    assert proc.returncode == 0
    assert "cloud bridge disabled" in proc.stderr
    assert not out.exists()
    assert list((tmp_path / "out").iterdir()) == []


@pytest.mark.parametrize(
    "sen",
    ["", "0", "007", "-1", "abc", "1 2", "1/2", "12345678901234567890", "1\n2"],
)
def test_invalid_sen_rejected(tmp_path, sen):
    proc, out = _render(tmp_path, SITE_SEN=sen)
    _assert_rejected(proc, out)


def test_missing_sen_rejected(tmp_path):
    proc, out = _render(tmp_path, SITE_SEN=None)
    _assert_rejected(proc, out)


@pytest.mark.parametrize("site", ["1abc", "a/b", "", "a" * 17])
def test_invalid_site_id_rejected(tmp_path, site):
    proc, out = _render(tmp_path, CMK_SITE_ID=site)
    _assert_rejected(proc, out)


@pytest.mark.parametrize("host", ["bad host", "a|b", "-lead", "a/b"])
def test_invalid_host_rejected(tmp_path, host):
    proc, out = _render(tmp_path, CLOUD_BROKER_HOST=host)
    _assert_rejected(proc, out)


@pytest.mark.parametrize("port", ["0", "70000", "x", "-1", "88 83"])
def test_invalid_port_rejected(tmp_path, port):
    proc, out = _render(tmp_path, CLOUD_BROKER_PORT=port)
    _assert_rejected(proc, out)


@pytest.mark.parametrize("var", ["CLOUD_BROKER_PASSWORD", "MQTT_BRIDGE_PASSWORD"])
@pytest.mark.parametrize("pw", ["a&b", "a|b", "a/b", "a\\b", "a b", "", "a" * 257])
def test_invalid_password_rejected(tmp_path, var, pw):
    proc, out = _render(tmp_path, **{var: pw})
    _assert_rejected(proc, out)
    assert var in proc.stderr
    if pw:
        assert pw not in proc.stderr


def test_missing_cafile_rejected(tmp_path):
    proc, out = _render(tmp_path, CLOUD_BROKER_CAFILE=str(tmp_path / "nope.pem"))
    _assert_rejected(proc, out)


def test_wrong_argument_count():
    proc = subprocess.run(["sh", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 2


def test_template_is_out_only():
    topics = [
        ln for ln in TEMPLATE.read_text().splitlines() if ln.startswith("topic ")
    ]
    assert topics
    for line in topics:
        assert line.split()[2] == "out", line


def test_compose_wires_the_bridge_renderer():
    text = COMPOSE.read_text()
    assert (
        "sh /mosquitto/render-bridge.sh /mosquitto/bridge.template "
        "/mosquitto/config/conf.d/bridge.conf" in text
    )
    assert "./mosquitto.bridge.template:/mosquitto/bridge.template:ro,z" in text
    assert "./render-mosquitto-bridge.sh:/mosquitto/render-bridge.sh:ro,z" in text
    assert "./certs:/mosquitto/certs:ro,z" in text
    assert text.count("SITE_SEN=${SITE_SEN:-}") >= 4
