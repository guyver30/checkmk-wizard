"""Minimal Livestatus client for the Phase 7 post-activation health check.

Connects to the site's Livestatus port over TCP — not the local UNIX
socket — so the wizard can run from a different container/host than the
Checkmk site itself. `site.enable_livestatus_tcp()` turns this on for
every site the wizard creates or reuses. Uses the standard LQL text
protocol: a query terminated by a blank line, response requested as CSV
via OutputFormat/ColumnHeaders headers.
"""

from __future__ import annotations

import socket

DEFAULT_PORT = 6557


def query_host_states(host: str, host_names: list[str], port: int = DEFAULT_PORT) -> dict[str, int]:
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
    with socket.create_connection((host, port), timeout=10) as sock:
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
