"""Minimal Livestatus client for the Phase 7 post-activation health check.

Queries the site's local Livestatus UNIX socket
(/omd/sites/<site>/tmp/run/live) using the standard LQL text protocol:
a query terminated by a blank line, response requested as CSV via
OutputFormat/ColumnHeaders headers.
"""

from __future__ import annotations

import socket


def socket_path(site: str) -> str:
    return f"/omd/sites/{site}/tmp/run/live"


def query_host_states(site: str, host_names: list[str]) -> dict[str, int]:
    """Return {host_name: state} for the given hosts (0=UP, 1=DOWN, 2=UNREACHABLE).

    Hosts not yet known to Livestatus (e.g. not yet activated) are omitted
    from the result.
    """
    if not host_names:
        return {}

    query = (
        "GET hosts\n"
        "Columns: name state\n"
        "OutputFormat: csv\n"
        "ColumnHeaders: off\n"
        "\n"
    )
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(socket_path(site))
        sock.sendall(query.encode())
        sock.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)

    text = b"".join(chunks).decode(errors="replace")
    states: dict[str, int] = {}
    wanted = set(host_names)
    for line in text.splitlines():
        if not line.strip():
            continue
        name, _, state = line.partition(";")
        if name in wanted:
            try:
                states[name] = int(state)
            except ValueError:
                continue
    return states
