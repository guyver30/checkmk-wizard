"""Phase 3: custom async TCP port scanner.

Native Checkmk "Networks to scan" is a background cronjob (checked once a
minute, ping+DNS only, no TCP port checks — verified via context7 against
live Checkmk docs), so it can't serve the wizard's need for immediate,
port-level classification data during an interactive session. This module
replaces it with a bounded-concurrency asyncio TCP-connect sweep, plus an
ICMP echo probe so hosts with none of the scanned ports open (printers,
cameras, switches) are still found. ICMP goes through the system `ping`
binary because raw sockets need root/CAP_NET_RAW; if `ping` is missing the
probe silently reports "no reply" and the scan degrades to TCP-only.
"""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Callable
from dataclasses import dataclass, field

DEFAULT_PORTS: tuple[int, ...] = (22, 80, 443)
DEFAULT_TIMEOUT = 1.5
DEFAULT_CONCURRENCY = 256


@dataclass
class HostScanResult:
    ip: str
    open_ports: list[int] = field(default_factory=list)
    icmp_alive: bool = False

    @property
    def is_alive(self) -> bool:
        return bool(self.open_ports) or self.icmp_alive


async def _probe_port(ip: str, port: int, timeout: float, sem: asyncio.Semaphore) -> bool:
    async with sem:
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=timeout
            )
        except (TimeoutError, OSError):
            return False
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        return True


async def _probe_icmp(ip: str, timeout: float, sem: asyncio.Semaphore) -> bool:
    """True if one ICMP echo to `ip` is answered within `timeout` seconds."""
    async with sem:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", "1", "-W", str(max(1, round(timeout))), ip,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError:
            return False  # no ping binary / not executable: TCP-only scan
        try:
            return await asyncio.wait_for(proc.wait(), timeout=timeout + 2) == 0
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return False


async def scan_host(
    ip: str, ports: tuple[int, ...], timeout: float, sem: asyncio.Semaphore
) -> HostScanResult:
    *results, icmp_alive = await asyncio.gather(
        *(_probe_port(ip, p, timeout, sem) for p in ports),
        _probe_icmp(ip, timeout, sem),
    )
    open_ports = [p for p, ok in zip(ports, results) if ok]
    return HostScanResult(ip=ip, open_ports=open_ports, icmp_alive=icmp_alive)


def chunk_network(network: ipaddress.IPv4Network) -> list[ipaddress.IPv4Network]:
    """Split a network larger than a /24 into /24-sized chunks."""
    if network.prefixlen >= 24:
        return [network]
    return list(network.subnets(new_prefix=24))


async def scan_network(
    cidr: str,
    ports: tuple[int, ...] = DEFAULT_PORTS,
    timeout: float = DEFAULT_TIMEOUT,
    concurrency: int = DEFAULT_CONCURRENCY,
    on_progress: Callable[[ipaddress.IPv4Network, int, int], None] | None = None,
) -> list[HostScanResult]:
    """Scan a CIDR range, chunked into /24s, and return only responsive hosts."""
    network = ipaddress.ip_network(cidr, strict=False)
    sem = asyncio.Semaphore(concurrency)
    results: list[HostScanResult] = []

    for chunk in chunk_network(network):
        hosts = [str(h) for h in chunk.hosts()]
        chunk_results = await asyncio.gather(
            *(scan_host(ip, ports, timeout, sem) for ip in hosts)
        )
        alive = [r for r in chunk_results if r.is_alive]
        results.extend(alive)
        if on_progress:
            on_progress(chunk, len(alive), len(hosts))

    return results
