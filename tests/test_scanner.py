import asyncio
import ipaddress

import pytest

from checkmk_wizard import scanner
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
async def test_scan_host_no_open_ports(monkeypatch):
    # Port 1 is a privileged, essentially-never-open port in test environments.
    async def no_reply(ip, timeout, sem):
        return False

    monkeypatch.setattr(scanner, "_probe_icmp", no_reply)
    sem = asyncio.Semaphore(10)
    result = await scan_host("127.0.0.1", (1,), timeout=0.2, sem=sem)
    assert result.open_ports == []
    assert result.is_alive is False


@pytest.mark.asyncio
async def test_scan_host_icmp_only_host_is_alive(monkeypatch):
    # Regression guard for hosts that answer ping but have none of the scanned
    # TCP ports open (printers, cameras): they must still be reported.
    async def replies(ip, timeout, sem):
        return True

    monkeypatch.setattr(scanner, "_probe_icmp", replies)
    result = await scan_host("127.0.0.1", (1,), timeout=0.2, sem=asyncio.Semaphore(10))
    assert result.open_ports == []
    assert result.icmp_alive is True
    assert result.is_alive is True


@pytest.mark.asyncio
async def test_probe_icmp_loopback_and_missing_ping(monkeypatch):
    sem = asyncio.Semaphore(10)
    assert await scanner._probe_icmp("127.0.0.1", 1.0, sem) is True

    async def boom(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
    assert await scanner._probe_icmp("127.0.0.1", 1.0, sem) is False


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
