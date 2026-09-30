import importlib.util
import json
import sys
from pathlib import Path

import respx
from httpx import Response

# scripts/ is not an importable package -- same reasoning and pattern as
# tests/test_mqtt_poller.py's own module-loading header.
_SPEC = importlib.util.spec_from_file_location(
    "provision_topology_editor",
    Path(__file__).resolve().parents[1] / "scripts" / "provision_topology_editor.py",
)
provisioner = importlib.util.module_from_spec(_SPEC)
sys.modules["provision_topology_editor"] = provisioner
_SPEC.loader.exec_module(provisioner)

_BASE = "http://cmk.example:5000/mysite/check_mk/api/v1"


def _set_rest_env(monkeypatch):
    monkeypatch.setenv("CMK_REST_SECRET", "automation-secret")
    monkeypatch.setenv("CMK_REST_HOST", "cmk.example")
    monkeypatch.setenv("CMK_REST_PORT", "5000")
    monkeypatch.setenv("CMK_SITE_ID", "mysite")
    monkeypatch.setenv("CMK_REST_USERNAME", "automation")


# --- build_role_permissions --------------------------------------------------


def test_build_role_permissions_enables_exactly_the_given_ids():
    result = provisioner.build_role_permissions(provisioner.REQUIRED_PERMISSIONS)
    assert result == {perm_id: "yes" for perm_id in provisioner.REQUIRED_PERMISSIONS}


def test_build_role_permissions_never_contains_activateforeign_or_excluded_prefixes():
    result = provisioner.build_role_permissions(provisioner.REQUIRED_PERMISSIONS)
    assert "wato.activateforeign" not in result
    excluded_prefixes = ("wato.users", "wato.global", "wato.rulesets")
    assert not any(perm_id.startswith(prefix) for perm_id in result for prefix in excluded_prefixes)


def test_build_role_permissions_matches_live_verified_v_perms():
    # 13-01 VERDICT V-PERMS, corrected by live UAT (2026-09-23): the original
    # six-id verdict (derived from the admin role's own enabled permissions,
    # never live-tested against the scoped role) was missing
    # wato.see_all_folders -- without it a freshly-provisioned role with no
    # folder contact-group membership 404s on every host, since
    # wato.all_folders only grants WRITE access, not the ability to SEE a
    # host at all. See scripts/provision_topology_editor.py's
    # REQUIRED_PERMISSIONS comment and scripts/probe_topology_rest.py's
    # V-PERMS CORRECTION for the full account.
    assert provisioner.REQUIRED_PERMISSIONS == (
        "wato.use",
        "wato.edit",
        "wato.all_folders",
        "wato.see_all_folders",
        "wato.edit_hosts",
        "wato.manage_hosts",
        "wato.activate",
    )


# --- build_user_body ----------------------------------------------------------


def test_build_user_body_shape():
    body = provisioner.build_user_body("topology_editor", "s3cr3t-value")
    assert body["roles"] == ["topology_editor"]
    assert body["auth_option"]["auth_type"] == "automation"
    assert body["auth_option"]["secret"] == "s3cr3t-value"
    assert body["auth_option"]["store_automation_secret"] is True
    assert "admin" not in body["roles"]


def test_build_user_body_username_field_matches_input():
    body = provisioner.build_user_body("topology_editor", "secret")
    assert body["username"] == "topology_editor"


# --- redact_auth_header --------------------------------------------------------


def test_redact_auth_header_masks_secret_keeps_username():
    assert provisioner.redact_auth_header("Bearer topology_editor abc") == "Bearer topology_editor ***"


def test_redact_auth_header_handles_malformed_header():
    assert provisioner.redact_auth_header("garbage") == "Bearer *** ***"


# --- generate_secret ------------------------------------------------------------


def test_generate_secret_is_url_safe_and_at_least_32_chars():
    secret = provisioner.generate_secret()
    assert len(secret) >= 32
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert set(secret) <= allowed


def test_generate_secret_differs_between_calls():
    assert provisioner.generate_secret() != provisioner.generate_secret()


# --- main() CLI gate ------------------------------------------------------------


def test_main_fails_fast_when_secret_env_var_missing(monkeypatch):
    monkeypatch.delenv("CMK_REST_SECRET", raising=False)
    assert provisioner.main() == 1


def test_main_provisions_with_topology_editor_secret_creates_when_missing(monkeypatch, capsys):
    _set_rest_env(monkeypatch)
    monkeypatch.setenv("TOPOLOGY_EDITOR_SECRET", "topo-secret-value")
    with respx.mock:
        respx.get(f"{_BASE}/objects/user_role/topology_editor").mock(return_value=Response(200, json={}))
        respx.put(f"{_BASE}/objects/user_role/topology_editor").mock(return_value=Response(204))
        respx.get(f"{_BASE}/objects/user_config/topology_editor").mock(
            return_value=Response(404, json={"title": "Not Found"})
        )
        create_route = respx.post(f"{_BASE}/domain-types/user_config/collections/all").mock(
            return_value=Response(200, json={})
        )
        respx.get(f"{_BASE}/domain-types/activation_run/collections/pending_changes").mock(
            return_value=Response(200, json={"value": []}, headers={"ETag": '"etag1"'})
        )
        respx.post(f"{_BASE}/domain-types/activation_run/actions/activate-changes/invoke").mock(
            return_value=Response(200, json={"id": "run1", "extensions": {"is_running": False}})
        )
        result = provisioner.main()

    assert result == 0
    body = json.loads(create_route.calls.last.request.content)
    assert body["auth_option"]["secret"] == "topo-secret-value"
    out = capsys.readouterr().out
    assert "topo-secret-value" not in out


def test_main_provisions_with_topology_editor_secret_rotates_when_existing(monkeypatch, capsys):
    _set_rest_env(monkeypatch)
    monkeypatch.setenv("TOPOLOGY_EDITOR_SECRET", "topo-secret-value")
    with respx.mock:
        respx.get(f"{_BASE}/objects/user_role/topology_editor").mock(return_value=Response(200, json={}))
        respx.put(f"{_BASE}/objects/user_role/topology_editor").mock(return_value=Response(204))
        respx.get(f"{_BASE}/objects/user_config/topology_editor").mock(
            return_value=Response(200, json={}, headers={"ETag": '"u-etag"'})
        )
        put_route = respx.put(f"{_BASE}/objects/user_config/topology_editor").mock(
            return_value=Response(200, json={})
        )
        respx.get(f"{_BASE}/domain-types/activation_run/collections/pending_changes").mock(
            return_value=Response(200, json={"value": []}, headers={"ETag": '"etag1"'})
        )
        respx.post(f"{_BASE}/domain-types/activation_run/actions/activate-changes/invoke").mock(
            return_value=Response(200, json={"id": "run1", "extensions": {"is_running": False}})
        )
        result = provisioner.main()

    assert result == 0
    assert put_route.calls.last.request.headers["If-Match"] == '"u-etag"'
    body = json.loads(put_route.calls.last.request.content)
    assert body["auth_option"]["secret"] == "topo-secret-value"
    out = capsys.readouterr().out
    assert "topo-secret-value" not in out


def test_main_without_topology_editor_secret_reports_existing_user_not_rotated(monkeypatch, capsys):
    _set_rest_env(monkeypatch)
    monkeypatch.delenv("TOPOLOGY_EDITOR_SECRET", raising=False)
    with respx.mock:
        respx.get(f"{_BASE}/objects/user_role/topology_editor").mock(return_value=Response(200, json={}))
        respx.put(f"{_BASE}/objects/user_role/topology_editor").mock(return_value=Response(204))
        respx.get(f"{_BASE}/objects/user_config/topology_editor").mock(return_value=Response(200, json={}))
        result = provisioner.main()

    assert result == 0
    assert "secret not rotated" in capsys.readouterr().out


def test_main_without_topology_editor_secret_creates_and_prints_generated_secret(monkeypatch, capsys):
    _set_rest_env(monkeypatch)
    monkeypatch.delenv("TOPOLOGY_EDITOR_SECRET", raising=False)
    with respx.mock:
        respx.get(f"{_BASE}/objects/user_role/topology_editor").mock(return_value=Response(200, json={}))
        respx.put(f"{_BASE}/objects/user_role/topology_editor").mock(return_value=Response(204))
        respx.get(f"{_BASE}/objects/user_config/topology_editor").mock(
            return_value=Response(404, json={"title": "Not Found"})
        )
        create_route = respx.post(f"{_BASE}/domain-types/user_config/collections/all").mock(
            return_value=Response(200, json={})
        )
        respx.get(f"{_BASE}/domain-types/activation_run/collections/pending_changes").mock(
            return_value=Response(200, json={"value": []}, headers={"ETag": '"etag1"'})
        )
        respx.post(f"{_BASE}/domain-types/activation_run/actions/activate-changes/invoke").mock(
            return_value=Response(200, json={"id": "run1", "extensions": {"is_running": False}})
        )
        result = provisioner.main()

    assert result == 0
    body = json.loads(create_route.calls.last.request.content)
    out = capsys.readouterr().out
    assert body["auth_option"]["secret"] in out
    assert "TOPOLOGY_EDITOR_SECRET" in out
