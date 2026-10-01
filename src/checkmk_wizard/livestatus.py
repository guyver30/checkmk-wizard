"""Minimal Livestatus client for the Phase 7 post-activation health check.

Also writes external commands (`send_commands`), used by demo mode to fake
host/service check results.

Connects to the site's Livestatus port over TCP — not the local UNIX
socket — so the wizard can run from a different container/host than the
Checkmk site itself. `site.enable_livestatus_tcp()` turns this on (plain text,
TLS off) for every site the wizard creates or reuses. Uses the standard
LQL text protocol: a query terminated by a blank line, response requested as CSV
via OutputFormat/ColumnHeaders headers.
"""

from __future__ import annotations

import socket
import time

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


def send_commands(host: str, commands: list[str], port: int = DEFAULT_PORT) -> None:
    """Send external commands (e.g. ``PROCESS_HOST_CHECK_RESULT;h;0;text``).

    Each command goes out as ``COMMAND [<unix ts>] <cmd>`` followed by a blank
    line. State codes: hosts 0=UP, 1=DOWN, 2=UNREACHABLE; services 0=OK.

    One connection per command, deliberately: a Livestatus connection without
    ``KeepAlive: on`` ends after a single request, so several COMMAND lines on
    one socket are not reliably processed. Commands produce no response, so
    none is read. Network errors (OSError) propagate; callers treat them as
    best-effort. CR/LF in a command is rejected so a value cannot smuggle in a
    second LQL request.
    """
    for command in commands:
        if "\n" in command or "\r" in command:
            raise ValueError(f"Livestatus command must not contain newlines: {command!r}")
    for command in commands:
        payload = f"COMMAND [{int(time.time())}] {command}\n\n"
        with socket.create_connection((host, port), timeout=10) as sock:
            sock.sendall(payload.encode())
            sock.shutdown(socket.SHUT_WR)
