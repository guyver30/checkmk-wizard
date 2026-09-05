import socket
from unittest.mock import MagicMock, patch

from checkmk_wizard import livestatus


def _fake_connection(response: bytes) -> MagicMock:
    sock = MagicMock()
    chunks = [response, b""]
    sock.recv.side_effect = chunks
    sock.__enter__.return_value = sock
    sock.__exit__.return_value = False
    return sock


def test_query_host_states_empty_when_no_hosts_requested():
    with patch("socket.create_connection") as mock_connect:
        result = livestatus.query_host_states("checkmk", [])
    mock_connect.assert_not_called()
    assert result == {}


def test_query_host_states_connects_over_tcp_to_default_port():
    sock = _fake_connection(b"web1;0\n")
    with patch("socket.create_connection", return_value=sock) as mock_connect:
        livestatus.query_host_states("checkmk", ["web1"])
    mock_connect.assert_called_once_with(("checkmk", livestatus.DEFAULT_PORT), timeout=10)


def test_query_host_states_uses_custom_port():
    sock = _fake_connection(b"web1;0\n")
    with patch("socket.create_connection", return_value=sock) as mock_connect:
        livestatus.query_host_states("checkmk", ["web1"], port=7000)
    mock_connect.assert_called_once_with(("checkmk", 7000), timeout=10)


def test_query_host_states_parses_csv_response():
    sock = _fake_connection(b"web1;0\nweb2;1\nweb3;2\n")
    with patch("socket.create_connection", return_value=sock):
        result = livestatus.query_host_states("checkmk", ["web1", "web2", "web3"])
    assert result == {"web1": 0, "web2": 1, "web3": 2}


def test_query_host_states_omits_hosts_not_in_wanted_set():
    sock = _fake_connection(b"web1;0\nother;1\n")
    with patch("socket.create_connection", return_value=sock):
        result = livestatus.query_host_states("checkmk", ["web1"])
    assert result == {"web1": 0}


def test_query_host_states_skips_malformed_state():
    sock = _fake_connection(b"web1;not-a-number\nweb2;1\n")
    with patch("socket.create_connection", return_value=sock):
        result = livestatus.query_host_states("checkmk", ["web1", "web2"])
    assert result == {"web2": 1}


def test_query_host_states_sends_expected_lql_query():
    sock = _fake_connection(b"")
    with patch("socket.create_connection", return_value=sock):
        livestatus.query_host_states("checkmk", ["web1"])
    sent = sock.sendall.call_args[0][0].decode()
    assert sent == (
        "GET hosts\n"
        "Columns: name state\n"
        "OutputFormat: csv\n"
        "ColumnHeaders: off\n"
        "\n"
    )
    sock.shutdown.assert_called_once_with(socket.SHUT_WR)
