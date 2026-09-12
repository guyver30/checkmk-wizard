import importlib.util
import json
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# scripts/ is not an importable package (no precedent in this repo for
# importing a scripts/*.py module from tests/ — scripts/smoke_test_broker.py
# has no test file at all), so load it directly from its file path.
_SPEC = importlib.util.spec_from_file_location(
    "mqtt_poller", Path(__file__).resolve().parents[1] / "scripts" / "mqtt_poller.py"
)
poller = importlib.util.module_from_spec(_SPEC)
# Register in sys.modules before exec: @dataclass (with `from __future__
# import annotations` in mqtt_poller.py) looks up its own module via
# sys.modules[cls.__module__] while processing fields, which fails with
# a bare AttributeError if the module was never registered.
sys.modules["mqtt_poller"] = poller
_SPEC.loader.exec_module(poller)


def _fake_connection(response: bytes) -> MagicMock:
    sock = MagicMock()
    sock.recv.side_effect = [response, b""]
    sock.__enter__.return_value = sock
    sock.__exit__.return_value = False
    return sock


# --- compute_overall_state --------------------------------------------------


def test_compute_overall_state_ok_warn_crit_unknown():
    assert poller.compute_overall_state(0, 0) == "OK"
    assert poller.compute_overall_state(0, 1) == "WARN"
    assert poller.compute_overall_state(0, 2) == "CRIT"
    assert poller.compute_overall_state(0, 3) == "UNKNOWN"


def test_compute_overall_state_host_down_or_unreachable_wins_outright():
    assert poller.compute_overall_state(1, 0) == "DOWN"
    assert poller.compute_overall_state(2, 0) == "DOWN"


def test_compute_overall_state_unmapped_service_state_degrades_to_unknown():
    assert poller.compute_overall_state(0, 99) == "UNKNOWN"


# --- is_publishable_device_id -----------------------------------------------


def test_is_publishable_device_id_rejects_topic_unsafe_and_empty_names():
    assert poller.is_publishable_device_id("lan/rogue") is False
    assert poller.is_publishable_device_id("host+1") is False
    assert poller.is_publishable_device_id("host#2") is False
    assert poller.is_publishable_device_id("") is False
    assert poller.is_publishable_device_id("   ") is False


def test_is_publishable_device_id_accepts_normal_hostnames():
    assert poller.is_publishable_device_id("web1") is True
    assert poller.is_publishable_device_id("switch-01.lan") is True


# --- append_bounded ----------------------------------------------------------


def test_append_bounded_keeps_newest_drops_oldest():
    assert poller.append_bounded([{"a": 1}], {"a": 2}, 1) == [{"a": 2}]


# --- topology_signature -------------------------------------------------------


def test_topology_signature_is_order_independent():
    nodes = [
        {"id": "a", "parents": ["b"], "device_type": "server", "folder": "vlan10", "alias": ""},
        {"id": "b", "parents": [], "device_type": "switch", "folder": "vlan10", "alias": ""},
    ]
    shuffled = list(reversed(nodes))
    assert poller.topology_signature(nodes) == poller.topology_signature(shuffled)


def test_topology_signature_differs_on_parent_change():
    base = [{"id": "a", "parents": ["b"], "device_type": "server", "folder": "vlan10", "alias": ""}]
    changed = [{"id": "a", "parents": ["c"], "device_type": "server", "folder": "vlan10", "alias": ""}]
    assert poller.topology_signature(base) != poller.topology_signature(changed)


def test_topology_signature_differs_on_add_or_remove():
    base = [{"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}]
    added = base + [{"id": "b", "parents": [], "device_type": "server", "folder": "", "alias": ""}]
    assert poller.topology_signature(base) != poller.topology_signature(added)
    assert poller.topology_signature(added) != poller.topology_signature([])


def test_topology_signature_differs_on_device_type_change():
    base = [{"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}]
    changed = [{"id": "a", "parents": [], "device_type": "switch", "folder": "", "alias": ""}]
    assert poller.topology_signature(base) != poller.topology_signature(changed)


def test_topology_signature_differs_on_alias_change():
    base = [{"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": "Old Name"}]
    changed = [{"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": "New Name"}]
    assert poller.topology_signature(base) != poller.topology_signature(changed)


# --- extract_device_type --------------------------------------------------------


def test_extract_device_type_reads_bare_key():
    # Live-confirmed 2026-09-11 (plan 10-06, Checkmk 2.4.0p36.cre): Livestatus
    # keys a custom tag group by its bare group id, not the `tag_` prefix the
    # REST API uses for the same attribute.
    assert poller.extract_device_type({"device_type": "switch"}) == "switch"


def test_extract_device_type_resolves_livestatus_group_default():
    # Live-confirmed 2026-09-11 (plan 10-06): Livestatus resolves a tag
    # group's configured default for an untagged host (`other`) rather
    # than omitting the key, unlike the REST API's `extensions.attributes`.
    assert poller.extract_device_type({"device_type": "other"}) == "other"


def test_extract_device_type_defaults_to_unknown_when_key_absent():
    # `UNKNOWN_DEVICE_TYPE` is the exceptional case: the `device_type` tag
    # group doesn't exist on this site at all, not a normal untagged host.
    assert poller.extract_device_type({}) == "unknown"


# --- PollerConfig.from_env ---------------------------------------------------


_ENV_VARS = (
    "LIVESTATUS_HOST",
    "LIVESTATUS_PORT",
    "MQTT_HOST",
    "MQTT_PORT",
    "MQTT_USERNAME",
    "MQTT_PASSWORD",
    "POLL_INTERVAL_SECONDS",
    "HISTORY_MAX_ENTRIES",
    "EVENTS_MAX_ENTRIES",
    "RECONCILE_TIMEOUT_SECONDS",
    "LOG_LEVEL",
    "CMK_REST_HOST",
    "CMK_REST_PORT",
    "CMK_SITE_ID",
    "CMK_REST_USERNAME",
    "CMK_REST_SECRET",
)


def _clear_poller_env(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_poller_config_from_env_defaults_with_empty_environment(monkeypatch):
    _clear_poller_env(monkeypatch)
    config = poller.PollerConfig.from_env()
    assert config.poll_interval_seconds == 60
    assert config.history_max_entries == 20
    assert config.events_max_entries == 50
    assert config.livestatus_port == 6557
    assert config.mqtt_port == 1883
    assert config.reconcile_timeout_seconds == 5.0


def test_poller_config_repr_never_contains_the_password_value(monkeypatch):
    _clear_poller_env(monkeypatch)
    monkeypatch.setenv("MQTT_USERNAME", "someuser")
    monkeypatch.setenv("MQTT_PASSWORD", "supersecret")
    config = poller.PollerConfig.from_env()
    rendered = repr(config)
    assert "***" in rendered
    assert "supersecret" not in rendered


def test_poller_config_from_env_reads_rest_credentials_with_defaults(monkeypatch):
    _clear_poller_env(monkeypatch)
    config = poller.PollerConfig.from_env()
    assert config.cmk_rest_host == "checkmk"
    assert config.cmk_rest_port == 5000
    assert config.cmk_site_id == "dmc"
    assert config.cmk_rest_username == ""
    assert config.cmk_rest_secret == ""


def test_poller_config_repr_never_contains_the_rest_secret_value(monkeypatch):
    _clear_poller_env(monkeypatch)
    monkeypatch.setenv("CMK_REST_USERNAME", "automation")
    monkeypatch.setenv("CMK_REST_SECRET", "s3cr3t-value")
    config = poller.PollerConfig.from_env()
    rendered = repr(config)
    assert "s3cr3t-value" not in rendered
    assert "'***'" in rendered
    # Non-secret REST fields must still render in the clear.
    assert "cmk_rest_host='checkmk'" in rendered
    assert "cmk_rest_port=5000" in rendered
    assert "cmk_site_id='dmc'" in rendered
    assert "cmk_rest_username='automation'" in rendered


# --- cmk_rest_base_url / fetch_host_folders ---------------------------------


def _fake_urlopen(body: bytes, status_code: int = 200):
    response = MagicMock()
    response.read.return_value = body
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def test_cmk_rest_base_url_builds_expected_shape():
    config = _make_config(
        cmk_rest_host="checkmk", cmk_rest_port=5000, cmk_site_id="dmc"
    )
    assert poller.cmk_rest_base_url(config) == "http://checkmk:5000/dmc/check_mk/api/1.0"


def test_fetch_host_folders_parses_extensions_folder_from_collection():
    body = json.dumps(
        {
            "value": [
                {"id": "web1", "extensions": {"folder": "/vlan10"}},
                {"id": "web2", "extensions": {"folder": "/tower1/sub"}},
            ]
        }
    ).encode()
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(body)):
        result = poller.fetch_host_folders("http://checkmk:5000/dmc/check_mk/api/1.0", "user", "secret", 10)
    assert result == {"web1": "vlan10", "web2": "tower1/sub"}


def test_fetch_host_folders_missing_folder_field_maps_to_empty_string():
    body = json.dumps({"value": [{"id": "web1", "extensions": {}}]}).encode()
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(body)):
        result = poller.fetch_host_folders("http://checkmk:5000/dmc/check_mk/api/1.0", "user", "secret", 10)
    assert result == {"web1": ""}


def test_fetch_host_folders_raises_rest_error_on_connection_failure():
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        try:
            poller.fetch_host_folders("http://checkmk:5000/dmc/check_mk/api/1.0", "user", "secret", 10)
        except poller.RestError as exc:
            assert isinstance(exc.__cause__, OSError)
        else:
            raise AssertionError("expected RestError")


def test_fetch_host_folders_raises_rest_error_on_malformed_json():
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(b"not-json{{{")):
        try:
            poller.fetch_host_folders("http://checkmk:5000/dmc/check_mk/api/1.0", "user", "secret", 10)
        except poller.RestError:
            pass
        else:
            raise AssertionError("expected RestError, not a bare json.JSONDecodeError")


def test_fetch_host_folders_401_error_message_never_contains_username_or_secret():
    http_error = urllib.error.HTTPError(
        url="http://checkmk:5000/dmc/check_mk/api/1.0/domain-types/host_config/collections/all",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=None,
    )
    with patch("urllib.request.urlopen", side_effect=http_error):
        try:
            poller.fetch_host_folders(
                "http://checkmk:5000/dmc/check_mk/api/1.0", "secretuser", "supersecretvalue", 10
            )
        except poller.RestError as exc:
            message = str(exc)
            assert "secretuser" not in message
            assert "supersecretvalue" not in message
        else:
            raise AssertionError("expected RestError")


# --- build_hosts_query / select_host_columns --------------------------------


def test_build_hosts_query_produces_exact_lql_text():
    assert poller.build_hosts_query(["name", "state"]) == (
        "GET hosts\nColumns: name state\nOutputFormat: json\n\n"
    )


def test_select_host_columns_orders_required_then_available_optional():
    result = poller.select_host_columns({"name", "state", "parents"})
    assert result == ["name", "state", "parents"]


def test_select_host_columns_raises_on_missing_required_column():
    try:
        poller.select_host_columns({"state"})
    except poller.LivestatusError as exc:
        assert "name" in str(exc)
    else:
        raise AssertionError("expected LivestatusError")


def test_select_host_columns_omits_unavailable_optional_columns():
    result = poller.select_host_columns({"name", "state"})
    assert result == ["name", "state"]


# --- available_host_columns ---------------------------------------------------


def test_available_host_columns_sends_expected_lql_query():
    sock = _fake_connection(b'[["name"], ["state"]]')
    with patch("socket.create_connection", return_value=sock):
        result = poller.available_host_columns("checkmk", poller.DEFAULT_LIVESTATUS_PORT, 10)
    sent = sock.sendall.call_args[0][0].decode()
    assert sent == "GET columns\nColumns: name\nFilter: table = hosts\nOutputFormat: json\n\n"
    assert result == {"name", "state"}


# --- query_devices --------------------------------------------------------------


def test_query_devices_parses_full_row_into_device_snapshot():
    columns = [
        "name",
        "state",
        "scheduled_downtime_depth",
        "acknowledged",
        "worst_service_state",
        "parents",
        "tags",
        "alias",
    ]
    row = [
        "web1",
        0,
        1,
        True,
        2,
        ["switch-01"],
        {"device_type": "server"},
        "Web Server 1",
    ]
    sock = _fake_connection(json.dumps([row]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices(
            "checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10, folders={"web1": "vlan10"}
        )
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.id == "web1"
    assert snapshot.state == "CRIT"
    assert snapshot.in_downtime is True
    assert snapshot.acknowledged is True
    assert snapshot.device_type == "server"
    assert snapshot.folder == "vlan10"
    assert snapshot.parents == ["switch-01"]
    assert snapshot.alias == "Web Server 1"


def test_query_devices_folder_maps_to_empty_string_when_host_absent_from_mapping():
    snapshots = None
    sock = _fake_connection(b'[["web1", 0]]')
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices(
            "checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["name", "state"], 10, folders={"other-host": "vlan10"}
        )
    assert snapshots[0].folder == ""


def test_query_devices_folder_maps_to_empty_string_when_no_mapping_supplied():
    sock = _fake_connection(b'[["web1", 0]]')
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["name", "state"], 10)
    assert snapshots[0].folder == ""


def test_query_devices_wr07_site_named_wato_produces_correct_folder():
    # Regression test for WR-07: the retired filename-string derive_folder()
    # located a literal "wato" segment in the Livestatus filename path,
    # which broke when the Checkmk site id was itself "wato" (a second,
    # unrelated "wato" segment then appears earlier in the same path).
    # The REST-sourced folder mapping has no filesystem-path parsing at
    # all, so a site id of "wato" cannot perturb it.
    sock = _fake_connection(b'[["web1", 0]]')
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices(
            "checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["name", "state"], 10, folders={"web1": "vlan10"}
        )
    assert snapshots[0].folder == "vlan10"


def test_query_devices_uses_safe_defaults_when_optional_columns_absent():
    columns = ["name", "state"]
    sock = _fake_connection(b'[["web1", 0]]')
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.in_downtime is False
    assert snapshot.acknowledged is False
    assert snapshot.parents == []
    assert snapshot.device_type == "unknown"
    assert snapshot.folder == ""
    assert snapshot.alias == ""


def test_query_devices_alias_defaults_to_empty_string_when_column_absent():
    columns = ["name", "state", "tags"]
    sock = _fake_connection(json.dumps([["web1", 0, {}]]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].alias == ""


def test_query_devices_alias_defaults_to_empty_string_when_row_truncated():
    columns = ["name", "state", "tags", "alias"]
    # Row ends before the alias column's position.
    truncated_row = ["web1", 0, {}]
    sock = _fake_connection(json.dumps([truncated_row]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].alias == ""


def test_query_devices_alias_coerces_non_string_value_to_empty_string():
    columns = ["name", "state", "alias"]
    sock = _fake_connection(json.dumps([["web1", 0, None]]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert snapshots[0].alias == ""


def test_query_devices_skips_topic_unsafe_host_name():
    columns = ["name", "state"]
    sock = _fake_connection(b'[["lan/rogue", 0], ["web1", 0]]')
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    ids = [snapshot.id for snapshot in snapshots]
    assert "lan/rogue" not in ids
    assert "web1" in ids


def test_query_devices_survives_row_truncated_after_worst_service_state():
    # Regression test for CR-01: `parents`/`tags`/`acknowledged` extractions
    # were previously unguarded `row[index[...]]` lookups, so a row shorter
    # than the requested column list raised an uncaught IndexError that
    # escaped the poll loop entirely instead of being skipped/defaulted per
    # the function's own documented contract.
    columns = [
        "name",
        "state",
        "scheduled_downtime_depth",
        "acknowledged",
        "worst_service_state",
        "parents",
        "tags",
    ]
    # Present through worst_service_state (index 4); parents/tags missing.
    truncated_row = ["web1", 0, 1, True, 2]
    full_row = [
        "web2",
        0,
        1,
        True,
        2,
        ["switch-01"],
        {"device_type": "server"},
    ]
    sock = _fake_connection(json.dumps([truncated_row, full_row]).encode())
    with patch("socket.create_connection", return_value=sock):
        # Must not raise IndexError: the truncated row falls back to safe
        # defaults for its missing trailing columns rather than crashing.
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    ids = [snapshot.id for snapshot in snapshots]
    assert "web1" in ids
    assert "web2" in ids
    web1 = next(snapshot for snapshot in snapshots if snapshot.id == "web1")
    assert web1.in_downtime is True
    assert web1.acknowledged is True
    assert web1.parents == []
    assert web1.device_type == "unknown"
    assert web1.folder == ""


def test_query_devices_raises_livestatus_error_on_malformed_json():
    sock = _fake_connection(b"not-json{{{")
    with patch("socket.create_connection", return_value=sock):
        try:
            poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["name", "state"], 10)
        except poller.LivestatusError:
            pass
        else:
            raise AssertionError("expected LivestatusError")


def test_query_devices_raises_livestatus_error_on_socket_failure():
    with patch("socket.create_connection", side_effect=OSError("connection refused")):
        try:
            poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["name", "state"], 10)
        except poller.LivestatusError as exc:
            assert isinstance(exc.__cause__, OSError)
        else:
            raise AssertionError("expected LivestatusError")


def test_query_devices_connects_with_configured_timeout():
    sock = _fake_connection(b"[]")
    with patch("socket.create_connection", return_value=sock) as mock_connect:
        poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, ["name", "state"], 7.5)
    mock_connect.assert_called_once_with(("checkmk", poller.DEFAULT_LIVESTATUS_PORT), timeout=7.5)


# --- MQTT client lifecycle and publish helpers ------------------------------


def _make_config(**overrides) -> "poller.PollerConfig":
    defaults = {
        "livestatus_host": "checkmk",
        "livestatus_port": poller.DEFAULT_LIVESTATUS_PORT,
        "mqtt_host": "mosquitto",
        "mqtt_port": poller.DEFAULT_MQTT_PORT,
        "mqtt_username": "poller",
        "mqtt_password": "secret",
        "poll_interval_seconds": 60,
        "history_max_entries": 2,
        "events_max_entries": 3,
        "reconcile_timeout_seconds": 5.0,
        "log_level": "INFO",
    }
    defaults.update(overrides)
    return poller.PollerConfig(**defaults)


def test_build_mqtt_client_will_set_before_connect_with_offline_payload():
    with patch.object(poller, "mqtt") as mock_mqtt:
        mock_client = mock_mqtt.Client.return_value
        result = poller.build_mqtt_client(_make_config())

    assert result is mock_client
    call_names = [name for name, _args, _kwargs in mock_client.mock_calls]
    assert call_names.index("will_set") < call_names.index("connect")

    args, kwargs = mock_client.will_set.call_args
    assert args[0] == poller.TOPIC_POLLER_STATUS
    assert json.loads(kwargs["payload"]) == {"status": "offline"}
    assert kwargs["qos"] == 1
    assert kwargs["retain"] is True


def test_build_mqtt_client_configures_reconnect_backoff_and_starts_loop():
    with patch.object(poller, "mqtt") as mock_mqtt:
        mock_client = mock_mqtt.Client.return_value
        poller.build_mqtt_client(_make_config())

    mock_client.reconnect_delay_set.assert_called_once_with(min_delay=1, max_delay=120)
    mock_client.loop_start.assert_called_once()


def test_build_mqtt_client_uses_version2_callback_api():
    with patch.object(poller, "mqtt") as mock_mqtt:
        poller.build_mqtt_client(_make_config())

    mock_mqtt.Client.assert_called_once_with(mock_mqtt.CallbackAPIVersion.VERSION2)


def test_build_mqtt_client_on_connect_publishes_online_birth_message():
    with patch.object(poller, "mqtt") as mock_mqtt:
        mock_client = mock_mqtt.Client.return_value
        poller.build_mqtt_client(_make_config())
        on_connect = mock_client.on_connect
        mock_client.publish.reset_mock()
        on_connect(mock_client, None, {}, 0, None)

    args, kwargs = mock_client.publish.call_args
    assert args[0] == poller.TOPIC_POLLER_STATUS
    payload = json.loads(args[1])
    assert payload["status"] == "online"
    assert payload["last_poll"] is None
    assert kwargs["qos"] == 1
    assert kwargs["retain"] is True


def test_shutdown_mqtt_client_publishes_offline_before_disconnecting():
    # Regression test for CR-02: a graceful client.disconnect() suppresses
    # the LWT, so every intentional shutdown path must explicitly publish
    # the offline status itself before stopping the loop/disconnecting.
    mock_client = MagicMock()

    poller.shutdown_mqtt_client(mock_client)

    call_names = [name for name, _args, _kwargs in mock_client.mock_calls]
    assert "publish" in call_names
    assert call_names.index("publish") < call_names.index("loop_stop")
    assert call_names.index("loop_stop") < call_names.index("disconnect")

    args, kwargs = mock_client.publish.call_args
    assert args[0] == poller.TOPIC_POLLER_STATUS
    assert json.loads(args[1]) == {"status": "offline"}
    assert kwargs["qos"] == 1
    assert kwargs["retain"] is True


def test_publish_device_status_uses_qos0_and_exact_payload_keys():
    mock_client = MagicMock()
    snapshot = poller.DeviceSnapshot(
        id="web1",
        state="OK",
        in_downtime=False,
        acknowledged=False,
        device_type="server",
        folder="vlan10",
        parents=[],
        alias="Web Server 1",
    )
    poller.publish_device_status(mock_client, snapshot, "2026-09-06T00:00:00+00:00")

    args, kwargs = mock_client.publish.call_args
    assert args[0] == "lan/devices/web1/status"
    payload = json.loads(args[1])
    assert set(payload.keys()) == {
        "id",
        "state",
        "in_downtime",
        "acknowledged",
        "device_type",
        "folder",
        "alias",
        "timestamp",
    }
    assert payload["alias"] == "Web Server 1"
    assert kwargs["qos"] == 0
    assert kwargs["retain"] is True


def test_publish_topology_uses_qos1_and_devices_envelope():
    mock_client = MagicMock()
    nodes = [{"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}]
    poller.publish_topology(mock_client, nodes, "2026-09-06T00:00:00+00:00")

    args, kwargs = mock_client.publish.call_args
    assert args[0] == poller.TOPIC_TOPOLOGY
    payload = json.loads(args[1])
    assert payload == {"devices": nodes, "timestamp": "2026-09-06T00:00:00+00:00"}
    assert kwargs["qos"] == 1
    assert kwargs["retain"] is True


def test_publish_history_publishes_full_array():
    mock_client = MagicMock()
    entries = [{"timestamp": "t1", "from": "OK", "to": "CRIT"}]
    poller.publish_history(mock_client, "web1", entries)

    args, kwargs = mock_client.publish.call_args
    assert args[0] == "lan/devices/web1/history"
    assert json.loads(args[1]) == entries
    assert kwargs["qos"] == 1
    assert kwargs["retain"] is True


def test_publish_events_publishes_full_array():
    mock_client = MagicMock()
    entries = [{"timestamp": "t1", "device_id": "web1", "event": "added", "from": None, "to": "OK"}]
    poller.publish_events(mock_client, entries)

    args, kwargs = mock_client.publish.call_args
    assert args[0] == poller.TOPIC_EVENTS
    assert json.loads(args[1]) == entries
    assert kwargs["qos"] == 1
    assert kwargs["retain"] is True


def test_publish_tombstone_clears_both_status_and_history_topics():
    mock_client = MagicMock()
    poller.publish_tombstone(mock_client, "web1")

    calls = mock_client.publish.call_args_list
    assert len(calls) == 2
    topics = {call.args[0] for call in calls}
    assert topics == {"lan/devices/web1/status", "lan/devices/web1/history"}
    for call in calls:
        assert call.kwargs["payload"] is None
        assert call.kwargs["retain"] is True
        assert call.kwargs["qos"] == 1


def test_publish_poller_status_payload_shape():
    mock_client = MagicMock()
    poller.publish_poller_status(mock_client, since="t0", last_poll="t1", device_count=5)

    args, kwargs = mock_client.publish.call_args
    assert args[0] == poller.TOPIC_POLLER_STATUS
    payload = json.loads(args[1])
    assert payload == {"status": "online", "since": "t0", "last_poll": "t1", "device_count": 5}
    assert kwargs["qos"] == 1
    assert kwargs["retain"] is True


def test_publish_json_swallows_oserror_from_client():
    mock_client = MagicMock()
    mock_client.publish.side_effect = OSError("broker down")
    poller.publish_events(mock_client, [{"event": "added"}])  # must not raise


# --- parse_topology_payload / parse_events_payload --------------------------


def test_parse_topology_payload_empty_returns_empty_dict():
    assert poller.parse_topology_payload(b"") == {}


def test_parse_topology_payload_parses_devices_keyed_by_id():
    payload = json.dumps(
        {"devices": [{"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}], "timestamp": "t"}
    ).encode()
    assert poller.parse_topology_payload(payload) == {
        "a": {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    }


def test_parse_topology_payload_malformed_json_returns_empty_dict():
    assert poller.parse_topology_payload(b"not-json{{{") == {}


# Regression: a retained topology message written by a PRE-Phase-10 poller has
# no `alias` key. Before this was fixed, the first cycle after an upgrade blew
# up with `KeyError: 'alias'` inside topology_signature() — and because the
# retained message is re-read on every start, `restart: unless-stopped` turned
# that into a crash-loop. Caught on a live deployment at Phase 10's checkpoint;
# the payload is valid JSON, so the malformed-JSON guard above never saw it.
def test_parse_topology_payload_backfills_fields_missing_from_older_schema():
    payload = json.dumps(
        {"devices": [{"id": "a", "parents": ["p"], "device_type": "server", "folder": "/f"}]}
    ).encode()
    restored = poller.parse_topology_payload(payload)
    assert restored["a"]["alias"] == ""
    # Pre-existing fields must survive untouched.
    assert restored["a"]["parents"] == ["p"]
    assert restored["a"]["device_type"] == "server"
    assert restored["a"]["folder"] == "/f"


def test_topology_signature_survives_node_restored_from_older_schema():
    """The exact crash: signature-comparing fresh nodes against restored ones."""
    restored = poller.parse_topology_payload(
        json.dumps({"devices": [{"id": "a", "device_type": "server", "folder": "/f"}]}).encode()
    )
    fresh = [{"id": "a", "parents": [], "device_type": "server", "folder": "/f", "alias": ""}]
    # Must not raise, and an alias-less old node must compare equal to a fresh
    # node that has no alias either — no spurious republish on every restart.
    assert poller.topology_signature(fresh) == poller.topology_signature(list(restored.values()))


# Regression (CR-06, Phase 10 code review): the first crash-loop fix backfilled
# missing keys but not wrong types, so these malformed-but-valid-JSON retained
# payloads still broke the cold-start-not-crash-loop contract.
def test_parse_topology_payload_skips_node_with_non_str_id():
    """A list id raised `TypeError: unhashable type` inside the parser itself."""
    payload = json.dumps({"devices": [{"id": ["x"]}, {"id": "good"}]}).encode()
    restored = poller.parse_topology_payload(payload)
    assert list(restored) == ["good"]


def test_parse_topology_payload_coerces_string_parents_to_empty_list():
    """`parents: "router1"` made topology_signature sort a string into chars."""
    payload = json.dumps({"devices": [{"id": "a", "parents": "router1"}]}).encode()
    restored = poller.parse_topology_payload(payload)
    assert restored["a"]["parents"] == []
    sig = poller.topology_signature(list(restored.values()))
    assert sig == (("a", (), poller.UNKNOWN_DEVICE_TYPE, "", ""),)


def test_parse_topology_payload_coerces_non_str_folder_and_alias():
    payload = json.dumps({"devices": [{"id": "a", "folder": 123, "alias": None}]}).encode()
    restored = poller.parse_topology_payload(payload)
    assert restored["a"]["folder"] == ""
    assert restored["a"]["alias"] == ""


def test_topology_signature_differs_when_restored_node_gains_an_alias():
    """One republish after an upgrade that adds an alias is correct, not noise."""
    restored = poller.parse_topology_payload(
        json.dumps({"devices": [{"id": "a", "device_type": "server", "folder": "/f"}]}).encode()
    )
    fresh = [{"id": "a", "parents": [], "device_type": "server", "folder": "/f", "alias": "core-sw"}]
    assert poller.topology_signature(fresh) != poller.topology_signature(list(restored.values()))


def test_parse_events_payload_empty_returns_empty_list():
    assert poller.parse_events_payload(b"") == []


def test_parse_events_payload_parses_list():
    payload = json.dumps([{"event": "added"}]).encode()
    assert poller.parse_events_payload(payload) == [{"event": "added"}]


def test_parse_events_payload_malformed_json_returns_empty_list():
    assert poller.parse_events_payload(b"not-json{{{") == []


# --- reconcile_state ----------------------------------------------------------


def _make_message(topic: str, payload: bytes):
    return SimpleNamespace(topic=topic, payload=payload)


def test_reconcile_state_does_not_set_a_will():
    with patch.object(poller, "mqtt") as mock_mqtt:
        mock_client = mock_mqtt.Client.return_value
        poller.reconcile_state(_make_config(reconcile_timeout_seconds=0.01))

    mock_client.will_set.assert_not_called()


def test_reconcile_state_returns_cold_start_state_when_nothing_retained():
    with patch.object(poller, "mqtt"):
        state = poller.reconcile_state(_make_config(reconcile_timeout_seconds=0.01))

    assert state.previous_nodes == {}
    assert state.last_status == {}
    assert state.events == []


def test_reconcile_state_seeds_previous_nodes_from_retained_topology():
    topology_payload = json.dumps(
        {"devices": [{"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}], "timestamp": "t"}
    ).encode()

    with patch.object(poller, "mqtt") as mock_mqtt:
        mock_client = mock_mqtt.Client.return_value

        def _subscribe(topic, qos=None):
            if topic == poller.TOPIC_TOPOLOGY:
                mock_client.on_message(
                    mock_client, None, _make_message(poller.TOPIC_TOPOLOGY, topology_payload)
                )

        mock_client.subscribe.side_effect = _subscribe
        state = poller.reconcile_state(_make_config(reconcile_timeout_seconds=0.01))

    assert state.previous_nodes == {"a": {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}}


# --- run_cycle ------------------------------------------------------------------


def _snapshot(
    id_,
    state="OK",
    parents=None,
    device_type="server",
    folder="",
    in_downtime=False,
    acknowledged=False,
):
    return poller.DeviceSnapshot(
        id=id_,
        state=state,
        in_downtime=in_downtime,
        acknowledged=acknowledged,
        device_type=device_type,
        folder=folder,
        parents=parents or [],
    )


def _poller_state(previous_nodes=None, last_status=None, history=None, events=None):
    return poller.PollerState(
        previous_nodes=previous_nodes or {},
        last_status=last_status or {},
        history=history or {},
        events=events if events is not None else [],
        since="2026-09-06T00:00:00+00:00",
    )


def _published(mock_client, topic):
    return [call for call in mock_client.publish.call_args_list if call.args[0] == topic]


def test_run_cycle_publishes_one_status_per_snapshot_with_retain():
    client = MagicMock()
    state = _poller_state()

    poller.run_cycle(client, _make_config(), state, [_snapshot("a"), _snapshot("b")])

    status_calls = _published(client, "lan/devices/a/status") + _published(client, "lan/devices/b/status")
    assert len(status_calls) == 2
    for call in status_calls:
        assert call.kwargs["retain"] is True


def test_run_cycle_skips_topology_publish_when_unchanged():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"})

    poller.run_cycle(client, _make_config(), state, [_snapshot("a")])

    assert _published(client, poller.TOPIC_TOPOLOGY) == []


def test_run_cycle_publishes_topology_on_cold_start():
    client = MagicMock()
    state = _poller_state()

    poller.run_cycle(client, _make_config(), state, [_snapshot("a")])

    assert len(_published(client, poller.TOPIC_TOPOLOGY)) == 1


def test_run_cycle_publishes_topology_on_reparent():
    client = MagicMock()
    node_a = {"id": "a", "parents": ["x"], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"})

    poller.run_cycle(client, _make_config(), state, [_snapshot("a", parents=["y"])])

    assert len(_published(client, poller.TOPIC_TOPOLOGY)) == 1


def test_run_cycle_publishes_topology_on_add():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"})

    poller.run_cycle(client, _make_config(), state, [_snapshot("a"), _snapshot("b")])

    assert len(_published(client, poller.TOPIC_TOPOLOGY)) == 1


def test_run_cycle_publishes_topology_on_remove():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"})

    poller.run_cycle(client, _make_config(), state, [])

    assert len(_published(client, poller.TOPIC_TOPOLOGY)) == 1


def test_run_cycle_removed_device_tombstones_status_and_history_and_events():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"}, history={"a": []})

    poller.run_cycle(client, _make_config(), state, [])

    tombstones = [c for c in client.publish.call_args_list if c.kwargs.get("payload", "unset") is None]
    assert {c.args[0] for c in tombstones} == {"lan/devices/a/status", "lan/devices/a/history"}
    for call in tombstones:
        assert call.kwargs["retain"] is True
        assert call.kwargs["qos"] == 1
    assert "a" not in state.last_status
    assert "a" not in state.history

    events_calls = _published(client, poller.TOPIC_EVENTS)
    assert len(events_calls) == 1
    entry = json.loads(events_calls[0].args[1])[-1]
    assert entry["device_id"] == "a"
    assert entry["event"] == "removed"
    assert entry["from"] == "OK"
    assert entry["to"] is None


def test_run_cycle_added_device_appends_added_event():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"})

    poller.run_cycle(client, _make_config(), state, [_snapshot("a"), _snapshot("b", state="WARN")])

    events_calls = _published(client, poller.TOPIC_EVENTS)
    assert len(events_calls) == 1
    entries = json.loads(events_calls[0].args[1])
    entry = next(e for e in entries if e["device_id"] == "b")
    assert entry["event"] == "added"
    assert entry["from"] is None
    assert entry["to"] == "WARN"


def test_run_cycle_state_change_appends_history_and_event_and_publishes_both_topics():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"}, history={"a": []})

    poller.run_cycle(client, _make_config(), state, [_snapshot("a", state="CRIT")])

    history_calls = _published(client, "lan/devices/a/history")
    assert len(history_calls) == 1
    history_entries = json.loads(history_calls[0].args[1])
    assert history_entries[-1]["from"] == "OK"
    assert history_entries[-1]["to"] == "CRIT"

    events_calls = _published(client, poller.TOPIC_EVENTS)
    assert len(events_calls) == 1
    entry = json.loads(events_calls[0].args[1])[-1]
    assert entry["event"] == "state_change"
    assert entry["from"] == "OK"
    assert entry["to"] == "CRIT"


def test_run_cycle_no_changes_publishes_no_history_or_events():
    client = MagicMock()
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(previous_nodes={"a": node_a}, last_status={"a": "OK"}, history={"a": []})

    poller.run_cycle(client, _make_config(), state, [_snapshot("a", state="OK")])

    assert _published(client, poller.TOPIC_EVENTS) == []
    assert _published(client, "lan/devices/a/history") == []


def test_run_cycle_cold_start_emits_no_state_change_events():
    client = MagicMock()
    state = _poller_state()

    poller.run_cycle(client, _make_config(), state, [_snapshot("a")])

    events_calls = _published(client, poller.TOPIC_EVENTS)
    if events_calls:
        entries = json.loads(events_calls[0].args[1])
        assert all(entry["event"] != "state_change" for entry in entries)


def test_run_cycle_truncates_history_and_events_to_configured_bounds():
    client = MagicMock()
    config = _make_config(history_max_entries=2, events_max_entries=1)
    node_a = {"id": "a", "parents": [], "device_type": "server", "folder": "", "alias": ""}
    state = _poller_state(
        previous_nodes={"a": node_a},
        last_status={"a": "OK"},
        history={"a": [{"timestamp": "t0", "from": "UNKNOWN", "to": "OK"}]},
        events=[{"timestamp": "t0", "device_id": "z", "event": "added", "from": None, "to": "OK"}],
    )

    poller.run_cycle(client, config, state, [_snapshot("a", state="CRIT")])

    assert len(state.history["a"]) <= 2
    assert len(state.events) <= 1


def test_run_cycle_publishes_heartbeat_with_refreshed_last_poll_and_device_count():
    client = MagicMock()
    state = _poller_state()

    poller.run_cycle(client, _make_config(), state, [_snapshot("a"), _snapshot("b")])

    status_calls = _published(client, poller.TOPIC_POLLER_STATUS)
    assert len(status_calls) == 1
    payload = json.loads(status_calls[0].args[1])
    assert payload["device_count"] == 2
    assert payload["last_poll"] is not None
    assert payload["status"] == "online"


# --- run_forever ---------------------------------------------------------------


class _OneShotEvent:
    """Fake `threading.Event` that reports "stop" after its first `wait()` call.

    Lets a `run_forever` test exercise exactly one loop iteration without
    real signal delivery or real sleeping.
    """

    def __init__(self):
        self._stopped = False

    def is_set(self):
        return self._stopped

    def set(self):
        self._stopped = True

    def wait(self, timeout=None):
        self._stopped = True
        return False


def test_run_forever_survives_livestatus_error_and_does_not_raise():
    fake_client = MagicMock()

    with (
        patch.object(poller, "reconcile_state", return_value=_poller_state()),
        patch.object(poller, "build_mqtt_client", return_value=fake_client),
        patch.object(poller, "available_host_columns", return_value={"name", "state"}),
        patch.object(poller, "select_host_columns", return_value=["name", "state"]),
        patch.object(poller, "fetch_host_folders", return_value={}),
        patch.object(poller, "query_devices", side_effect=poller.LivestatusError("boom")),
        patch.object(poller, "run_cycle") as mock_run_cycle,
        patch.object(poller.threading, "Event", return_value=_OneShotEvent()),
        patch.object(poller.signal, "signal"),
    ):
        result = poller.run_forever(_make_config())

    assert result == 0
    mock_run_cycle.assert_not_called()


def test_run_forever_publishes_offline_status_on_fatal_startup_failure():
    # Regression test for CR-02: the one-time startup column probe failing
    # must still leave the retained poller status as "offline" -- a bare
    # client.disconnect() here previously left it stuck at "online" forever
    # since a graceful disconnect suppresses the LWT. OPS-03's bounded
    # startup retry means this now exercises every retry attempt before
    # the probe is treated as fatal -- poller.time.sleep is patched so the
    # retry backoff doesn't slow the test down.
    fake_client = MagicMock()

    with (
        patch.object(poller, "reconcile_state", return_value=_poller_state()),
        patch.object(poller, "build_mqtt_client", return_value=fake_client),
        patch.object(
            poller, "available_host_columns", side_effect=poller.LivestatusError("no columns")
        ),
        patch.object(poller.time, "sleep"),
    ):
        result = poller.run_forever(_make_config())

    assert result == 1
    status_calls = _published(fake_client, poller.TOPIC_POLLER_STATUS)
    assert len(status_calls) == 1
    assert json.loads(status_calls[0].args[1]) == {"status": "offline"}
    fake_client.disconnect.assert_called_once()


def test_run_forever_startup_probe_retries_then_recovers(caplog):
    # OPS-03: a transient startup Livestatus failure (e.g. a Checkmk
    # container restart racing the poller's own start) must not be fatal
    # -- the probe is retried, and a warning (not an error) is logged for
    # the failed attempt.
    fake_client = MagicMock()

    with (
        patch.object(poller, "reconcile_state", return_value=_poller_state()),
        patch.object(poller, "build_mqtt_client", return_value=fake_client),
        patch.object(
            poller,
            "available_host_columns",
            side_effect=[poller.LivestatusError("boom"), {"name", "state"}],
        ),
        patch.object(poller, "fetch_host_folders", return_value={}),
        patch.object(poller, "query_devices", return_value=[]),
        patch.object(poller, "run_cycle"),
        patch.object(poller.threading, "Event", return_value=_OneShotEvent()),
        patch.object(poller.signal, "signal"),
        patch.object(poller.time, "sleep") as mock_sleep,
        caplog.at_level("WARNING", logger=poller._logger.name),
    ):
        result = poller.run_forever(_make_config())

    assert result != 1
    mock_sleep.assert_called_once_with(poller._STARTUP_RETRY_DELAYS_SECONDS[0])
    assert not any(record.levelname == "ERROR" for record in caplog.records)
    assert any(
        record.levelname == "WARNING" and "attempt" in record.getMessage()
        for record in caplog.records
    )


def test_run_forever_startup_probe_retry_exhausted_is_fatal():
    # OPS-03: a permanently unreachable Livestatus site must still fail
    # loudly after every retry is exhausted, preserving the pre-existing
    # offline-status/disconnect contract.
    fake_client = MagicMock()

    with (
        patch.object(poller, "reconcile_state", return_value=_poller_state()),
        patch.object(poller, "build_mqtt_client", return_value=fake_client),
        patch.object(
            poller, "available_host_columns", side_effect=poller.LivestatusError("still down")
        ) as mock_probe,
        patch.object(poller.time, "sleep"),
    ):
        result = poller.run_forever(_make_config())

    assert result == 1
    assert mock_probe.call_count == len(poller._STARTUP_RETRY_DELAYS_SECONDS) + 1
    status_calls = _published(fake_client, poller.TOPIC_POLLER_STATUS)
    assert len(status_calls) == 1
    assert json.loads(status_calls[0].args[1]) == {"status": "offline"}
    fake_client.disconnect.assert_called_once()


def test_run_forever_rest_failure_reuses_last_known_good_folder_map():
    # A REST hiccup must degrade only the folder field for that cycle
    # (T-10-11/T-10-12): the cycle still runs, and query_devices still
    # receives the previous cycle's folder map rather than an empty one.
    fake_client = MagicMock()
    captured_folders: list[dict] = []

    def _fake_query_devices(host, port, columns, timeout, *, folders=None):
        captured_folders.append(folders)
        return []

    class _TwoShotEvent(_OneShotEvent):
        """Lets run_forever execute exactly two loop iterations."""

        def __init__(self):
            super().__init__()
            self._calls = 0

        def wait(self, timeout=None):
            self._calls += 1
            if self._calls >= 2:
                self._stopped = True
            return False

    with (
        patch.object(poller, "reconcile_state", return_value=_poller_state()),
        patch.object(poller, "build_mqtt_client", return_value=fake_client),
        patch.object(poller, "available_host_columns", return_value={"name", "state"}),
        patch.object(poller, "select_host_columns", return_value=["name", "state"]),
        patch.object(
            poller,
            "fetch_host_folders",
            side_effect=[{"web1": "vlan10"}, poller.RestError("REST hiccup")],
        ),
        patch.object(poller, "query_devices", side_effect=_fake_query_devices),
        patch.object(poller, "run_cycle"),
        patch.object(poller.threading, "Event", return_value=_TwoShotEvent()),
        patch.object(poller.signal, "signal"),
    ):
        result = poller.run_forever(_make_config())

    assert result == 0
    assert captured_folders == [{"web1": "vlan10"}, {"web1": "vlan10"}]


def test_run_forever_rest_never_succeeded_leaves_folders_empty_and_still_runs_cycle():
    fake_client = MagicMock()
    captured_folders: list[dict] = []

    def _fake_query_devices(host, port, columns, timeout, *, folders=None):
        captured_folders.append(folders)
        return []

    with (
        patch.object(poller, "reconcile_state", return_value=_poller_state()),
        patch.object(poller, "build_mqtt_client", return_value=fake_client),
        patch.object(poller, "available_host_columns", return_value={"name", "state"}),
        patch.object(poller, "select_host_columns", return_value=["name", "state"]),
        patch.object(poller, "fetch_host_folders", side_effect=poller.RestError("never up")),
        patch.object(poller, "query_devices", side_effect=_fake_query_devices),
        patch.object(poller, "run_cycle") as mock_run_cycle,
        patch.object(poller.threading, "Event", return_value=_OneShotEvent()),
        patch.object(poller.signal, "signal"),
    ):
        result = poller.run_forever(_make_config())

    assert result == 0
    assert captured_folders == [{}]
    mock_run_cycle.assert_called_once()


# Regression (CR-04, Phase 10 code review): `--once` called query_devices without
# `folders=`, so the documented one-shot verification path published retained
# `status` AND `topology` with every folder blank, overwriting correct retained
# values on the broker. `run_forever` passed folders correctly; only this branch
# did not, and nothing covered `--once` at all.
def test_once_branch_enriches_snapshots_with_folder_map(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["mqtt_poller.py", "--once"])
    with (
        patch.object(poller.PollerConfig, "from_env", staticmethod(lambda: _make_config())),
        patch.object(poller, "configure_logging"),
        patch.object(poller, "reconcile_state", return_value=poller.PollerState(previous_nodes={}, last_status={}, history={}, events=[], since="t")),
        patch.object(poller, "build_mqtt_client"),
        patch.object(poller, "shutdown_mqtt_client"),
        patch.object(poller, "available_host_columns", return_value={"name", "state", "alias"}),
        patch.object(poller, "select_host_columns", return_value=["name", "state", "alias"]),
        patch.object(poller, "fetch_host_folders", return_value={"192.168.0.1": "folder2"}),
        patch.object(poller, "query_devices", return_value=[]) as mock_query,
        patch.object(poller, "run_cycle"),
    ):
        assert poller.main() == 0
    assert mock_query.call_args.kwargs["folders"] == {"192.168.0.1": "folder2"}


def test_once_branch_degrades_when_folder_fetch_fails(monkeypatch):
    """A REST failure must not abort the one-shot run -- same posture as run_forever."""
    monkeypatch.setattr(sys, "argv", ["mqtt_poller.py", "--once"])
    with (
        patch.object(poller.PollerConfig, "from_env", staticmethod(lambda: _make_config())),
        patch.object(poller, "configure_logging"),
        patch.object(poller, "reconcile_state", return_value=poller.PollerState(previous_nodes={}, last_status={}, history={}, events=[], since="t")),
        patch.object(poller, "build_mqtt_client"),
        patch.object(poller, "shutdown_mqtt_client"),
        patch.object(poller, "available_host_columns", return_value={"name", "state"}),
        patch.object(poller, "select_host_columns", return_value=["name", "state"]),
        patch.object(poller, "fetch_host_folders", side_effect=poller.RestError("401")),
        patch.object(poller, "query_devices", return_value=[]) as mock_query,
        patch.object(poller, "run_cycle"),
    ):
        assert poller.main() == 0
    assert mock_query.call_args.kwargs["folders"] == {}
