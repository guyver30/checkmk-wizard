import asyncio
import ipaddress

import pytest

from checkmk_wizard.scanner import chunk_network, scan_host


def test_chunk_network_small_range_unchanged():
    net = ipaddress.ip_network("10.0.0.0/24")
    assert chunk_network(net) == [net]


def test_chunk_network_splits_larger_range():
    net = ipaddress.ip_network("10.0.0.0/22")
    chunks = chunk_network(net)
    assert len(chunks) == 4
    assert all(c.prefixlen == 24 for c in chunks)


@pytest.mark.asyncio
async def test_scan_host_no_open_ports():
    # Port 1 is a privileged, essentially-never-open port in test environments.
    sem = asyncio.Semaphore(10)
    result = await scan_host("127.0.0.1", (1,), timeout=0.2, sem=sem)
    assert result.open_ports == []
    assert result.is_alive is False


@pytest.mark.asyncio
async def test_scan_host_detects_open_port():
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        sem = asyncio.Semaphore(10)
        result = await scan_host("127.0.0.1", (port,), timeout=1.0, sem=sem)
        assert result.open_ports == [port]
        assert result.is_alive is True
    finally:
        server.close()
        await server.wait_closed()
