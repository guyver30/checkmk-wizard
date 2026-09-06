import importlib.util
import json
import sys
from pathlib import Path
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
        {"id": "a", "parents": ["b"], "device_type": "server", "folder": "vlan10"},
        {"id": "b", "parents": [], "device_type": "switch", "folder": "vlan10"},
    ]
    shuffled = list(reversed(nodes))
    assert poller.topology_signature(nodes) == poller.topology_signature(shuffled)


def test_topology_signature_differs_on_parent_change():
    base = [{"id": "a", "parents": ["b"], "device_type": "server", "folder": "vlan10"}]
    changed = [{"id": "a", "parents": ["c"], "device_type": "server", "folder": "vlan10"}]
    assert poller.topology_signature(base) != poller.topology_signature(changed)


def test_topology_signature_differs_on_add_or_remove():
    base = [{"id": "a", "parents": [], "device_type": "server", "folder": ""}]
    added = base + [{"id": "b", "parents": [], "device_type": "server", "folder": ""}]
    assert poller.topology_signature(base) != poller.topology_signature(added)
    assert poller.topology_signature(added) != poller.topology_signature([])


def test_topology_signature_differs_on_device_type_change():
    base = [{"id": "a", "parents": [], "device_type": "server", "folder": ""}]
    changed = [{"id": "a", "parents": [], "device_type": "switch", "folder": ""}]
    assert poller.topology_signature(base) != poller.topology_signature(changed)


# --- derive_folder -------------------------------------------------------------


def test_derive_folder_extracts_segment_after_wato():
    assert (
        poller.derive_folder("/omd/sites/dmc/etc/check_mk/conf.d/wato/vlan10/hosts.mk")
        == "vlan10"
    )


def test_derive_folder_returns_empty_string_when_no_wato_segment():
    assert poller.derive_folder("/some/other/path/hosts.mk") == ""


# --- extract_device_type --------------------------------------------------------


def test_extract_device_type_prefers_device_type_tag():
    assert poller.extract_device_type({"device_type": "switch"}) == "switch"


def test_extract_device_type_falls_back_to_tag_device_type():
    assert poller.extract_device_type({"tag_device_type": "router"}) == "router"


def test_extract_device_type_defaults_to_unknown():
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
        "filename",
    ]
    row = [
        "web1",
        0,
        1,
        True,
        2,
        ["switch-01"],
        {"device_type": "server"},
        "/omd/sites/dmc/etc/check_mk/conf.d/wato/vlan10/hosts.mk",
    ]
    sock = _fake_connection(json.dumps([row]).encode())
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.id == "web1"
    assert snapshot.state == "CRIT"
    assert snapshot.in_downtime is True
    assert snapshot.acknowledged is True
    assert snapshot.device_type == "server"
    assert snapshot.folder == "vlan10"
    assert snapshot.parents == ["switch-01"]


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


def test_query_devices_skips_topic_unsafe_host_name():
    columns = ["name", "state"]
    sock = _fake_connection(b'[["lan/rogue", 0], ["web1", 0]]')
    with patch("socket.create_connection", return_value=sock):
        snapshots = poller.query_devices("checkmk", poller.DEFAULT_LIVESTATUS_PORT, columns, 10)
    ids = [snapshot.id for snapshot in snapshots]
    assert "lan/rogue" not in ids
    assert "web1" in ids


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
        "timestamp",
    }
    assert kwargs["qos"] == 0
    assert kwargs["retain"] is True


def test_publish_topology_uses_qos1_and_devices_envelope():
    mock_client = MagicMock()
    nodes = [{"id": "a", "parents": [], "device_type": "server", "folder": ""}]
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
