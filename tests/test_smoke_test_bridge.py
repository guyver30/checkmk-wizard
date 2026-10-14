"""Tests for the pure config builders in scripts/smoke_test_bridge.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "smoke_test_bridge",
    Path(__file__).resolve().parents[1] / "scripts" / "smoke_test_bridge.py",
)
smoke = importlib.util.module_from_spec(_SPEC)
sys.modules["smoke_test_bridge"] = smoke
_SPEC.loader.exec_module(smoke)


def test_cloud_conf_requires_auth_and_acl():
    text = smoke.cloud_conf()
    for needle in ("allow_anonymous false", "listener 1883", "password_file", "acl_file"):
        assert needle in text


def test_cloud_acl_confines_sen_and_lets_archiver_read():
    text = smoke.cloud_acl()
    assert "pattern write app/%u/#" in text
    assert "user archiver" in text
    assert "topic read app/#" in text


def test_local_conf_includes_dir_and_queue_limit_precedes_listener():
    text = smoke.local_conf()
    assert "include_dir /mosquitto/config/conf.d" in text
    assert "max_queued_messages" in text
    assert text.index("max_queued_messages") < text.index("listener")


def test_local_acl_scopes_each_user():
    text = smoke.local_acl("s1")
    assert "user poller\ntopic readwrite sites/s1/#" in text
    assert "user bridge\ntopic read sites/s1/#" in text
    assert "user other\ntopic readwrite sites/s2/#" in text


def test_bridge_conf_lines():
    lines = smoke.bridge_conf("123", "s1", "cloud", "rpw", "bpw").splitlines()
    for expected in (
        "bridge_protocol_version mqttv50",
        "cleansession false",
        "notifications false",
        "remote_clientid bridge-123-s1",
        "remote_username 123",
        "topic # out 1 sites/s1/ app/123/s1/",
    ):
        assert expected in lines


def test_required_checks_passed_ignores_a3():
    results = {name: True for name in smoke.REQUIRED_CHECKS}
    assert smoke.required_checks_passed(results)
    results["A3"] = False
    assert smoke.required_checks_passed(results)
    results["A1"] = False
    assert not smoke.required_checks_passed(results)
    assert not smoke.required_checks_passed({})
    assert "A3" not in smoke.REQUIRED_CHECKS
