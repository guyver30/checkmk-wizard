import asyncio

import pytest

from checkmk_wizard.remote import (
    OSRelease,
    linux_register_command,
    probe_port,
    windows_firewall_instructions,
    windows_register_command,
)


def test_os_release_parse():
    text = 'ID=ubuntu\nVERSION_ID="22.04"\nPRETTY_NAME="Ubuntu 22.04"\n'
    parsed = OSRelease.parse(text)
    assert parsed.id == "ubuntu"
    assert parsed.version_id == "22.04"


def test_os_release_parse_missing_fields_defaults_unknown():
    parsed = OSRelease.parse("SOMETHING=else\n")
    assert parsed.id == "unknown"
    assert parsed.version_id == "unknown"


@pytest.mark.asyncio
async def test_probe_port_open():
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        result = await probe_port("127.0.0.1", port)
        assert result.reachable is True
        assert result.classification == "open"
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_probe_port_closed_is_refused():
    # Bind and immediately close to get a port nothing is listening on,
    # which should trigger a connection-refused (RST) locally.
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()

    result = await probe_port("127.0.0.1", port, timeout=1.0)
    assert result.reachable is False
    assert result.classification == "closed_rst"


def test_linux_register_command_quotes_args():
    cmd = linux_register_command("my host", "cmk.example", "mysite", "automation", "p@ss w'ord")
    assert "cmk-agent-ctl register" in cmd
    assert "--hostname" in cmd
    # shlex.quote must protect the space and embedded quote in the password
    assert "p@ss w'ord" not in cmd or "'\"'\"'" in cmd


def test_windows_register_command_contains_flags():
    cmd = windows_register_command("winhost", "cmk.example", "mysite", "automation", "secret")
    assert "cmk-agent-ctl.exe" in cmd
    assert "register" in cmd
    assert "--hostname winhost" in cmd
    assert "--server cmk.example" in cmd


def test_windows_firewall_instructions_uses_given_port():
    text = windows_firewall_instructions(8000)
    assert "New-NetFirewallRule" in text
    assert "8000" in text
