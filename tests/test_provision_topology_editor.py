import importlib.util
import sys
from pathlib import Path

# scripts/ is not an importable package -- same reasoning and pattern as
# tests/test_mqtt_poller.py's own module-loading header.
_SPEC = importlib.util.spec_from_file_location(
    "provision_topology_editor",
    Path(__file__).resolve().parents[1] / "scripts" / "provision_topology_editor.py",
)
provisioner = importlib.util.module_from_spec(_SPEC)
sys.modules["provision_topology_editor"] = provisioner
_SPEC.loader.exec_module(provisioner)


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
