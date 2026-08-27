import asyncio

import pytest

from checkmk_wizard.remote import (
    AGENT_PLUGINS_DIR,
    OSRelease,
    agent_status_shows_connection,
    linux_register_command,
    package_family,
    probe_port,
    smartmontools_deb_filename,
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
    assert parsed.id_like == ""


def test_os_release_parse_id_like():
    text = 'ID=rocky\nID_LIKE="rhel centos fedora"\nVERSION_ID="9.3"\n'
    parsed = OSRelease.parse(text)
    assert parsed.id_like == "rhel centos fedora"


def test_package_family_deb_direct_id():
    assert package_family(OSRelease(id="debian", version_id="12")) == "deb"
    assert package_family(OSRelease(id="ubuntu", version_id="22.04")) == "deb"


def test_package_family_deb_via_id_like():
    # Linux Mint identifies as its own distro but is Ubuntu/Debian-based.
    assert package_family(OSRelease(id="linuxmint", version_id="21", id_like="ubuntu debian")) == "deb"


def test_package_family_rpm_direct_id():
    assert package_family(OSRelease(id="rhel", version_id="9")) == "rpm"
    assert package_family(OSRelease(id="opensuse", version_id="15")) == "rpm"


def test_package_family_rpm_via_id_like():
    # Rocky Linux identifies as its own distro but is RHEL-based.
    assert package_family(OSRelease(id="rocky", version_id="9.3", id_like="rhel centos fedora")) == "rpm"


def test_package_family_unknown_for_unrecognized_distro():
    assert package_family(OSRelease(id="alpine", version_id="3.19")) is None


@pytest.mark.parametrize(
    "version_id,expected_substring",
    [
        ("20.04", "Focal"),
        ("22.04", "Jammy"),
        ("24.04", "Noble"),
    ],
)
def test_smartmontools_deb_filename_matches_bundled_ubuntu_releases(version_id, expected_substring):
    filename = smartmontools_deb_filename(OSRelease(id="ubuntu", version_id=version_id))
    assert filename is not None
    assert expected_substring in filename
    assert filename.endswith(".deb")


def test_smartmontools_deb_filename_none_for_unbundled_ubuntu_version():
    assert smartmontools_deb_filename(OSRelease(id="ubuntu", version_id="18.04")) is None


def test_smartmontools_deb_filename_none_for_non_ubuntu():
    # Debian is deb-family (package_family() would say "deb"), but the
    # bundled smartmontools .debs are built specifically against Ubuntu
    # releases — a Debian target has no bundled match.
    assert smartmontools_deb_filename(OSRelease(id="debian", version_id="12")) is None


def test_agent_plugins_dir_is_the_documented_checkmk_agent_path():
    assert AGENT_PLUGINS_DIR == "/usr/lib/check_mk_agent/plugins"


def test_agent_status_shows_connection_true():
    output = (
        "Version: 2.3.0b1\n"
        "Agent socket: operational\n"
        "IP allowlist: any\n\n\n"
        "Connection: myserver/mysite\n"
        "\tUUID: b11af975-40a8-4574-b6cd-12dc11c6f273\n"
    )
    assert agent_status_shows_connection(output, "mysite") is True


def test_agent_status_shows_connection_false_wrong_site():
    output = "Connection: myserver/othersite\n"
    assert agent_status_shows_connection(output, "mysite") is False


def test_agent_status_shows_connection_false_when_absent():
    output = "Version: 2.3.0b1\nAgent socket: operational\n"
    assert agent_status_shows_connection(output, "mysite") is False


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
    assert "--hostname 'winhost'" in cmd
    assert "--server 'cmk.example'" in cmd


def test_windows_register_command_quotes_embedded_single_quote():
    cmd = windows_register_command("winhost", "cmk.example", "mysite", "automation", "p'ss")
    # PowerShell escapes an embedded single quote by doubling it.
    assert "--password 'p''ss'" in cmd


def test_windows_firewall_instructions_uses_given_port():
    text = windows_firewall_instructions(8000)
    assert "New-NetFirewallRule" in text
    assert "8000" in text
