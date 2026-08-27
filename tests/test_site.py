import subprocess
from unittest.mock import patch

import pytest

from checkmk_wizard import site


def test_omd_installed_true_when_on_path():
    with patch("shutil.which", return_value="/usr/bin/omd"):
        assert site.omd_installed() is True


def test_omd_installed_false_when_missing():
    with patch("shutil.which", return_value=None):
        assert site.omd_installed() is False


def test_list_sites_returns_sorted_directory_names(tmp_path):
    (tmp_path / "sitea").mkdir()
    (tmp_path / "siteb").mkdir()
    (tmp_path / "not_a_site.txt").write_text("x")
    with patch("checkmk_wizard.site.Path", return_value=tmp_path):
        assert site.list_sites() == ["sitea", "siteb"]


def test_list_sites_empty_when_root_missing(tmp_path):
    with patch("checkmk_wizard.site.Path", return_value=tmp_path / "does_not_exist"):
        assert site.list_sites() == []


def test_remove_site_runs_omd_rm_force():
    with patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, stdout="Stopping crontab...OK\n"),
    ) as mock_run:
        output = site.remove_site("mysite")
    mock_run.assert_called_once_with(
        ["omd", "-f", "rm", "mysite"], capture_output=True, text=True, check=False
    )
    assert output == "Stopping crontab...OK\n"


def test_remove_site_raises_on_failure_with_stdout_and_stderr():
    with patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess(
            [], 1, stdout="Stopping apache...failed", stderr="no such site"
        ),
    ):
        with pytest.raises(site.SiteBootstrapError) as exc_info:
            site.remove_site("mysite")
    assert "Stopping apache...failed" in str(exc_info.value)
    assert "no such site" in str(exc_info.value)


def test_create_site_returns_stdout():
    with patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, stdout="Created new site mysite.\n"),
    ):
        output = site.create_site("mysite", "adminpw")
    assert output == "Created new site mysite.\n"


def test_create_site_raises_on_failure_with_stdout_and_stderr():
    with patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess(
            [], 1, stdout="Executing post-create script...failed", stderr="script error"
        ),
    ):
        with pytest.raises(site.SiteBootstrapError) as exc_info:
            site.create_site("mysite", "adminpw")
    assert "Executing post-create script...failed" in str(exc_info.value)
    assert "script error" in str(exc_info.value)


def test_start_site_returns_stdout():
    with patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, stdout="Starting apache...OK\n"),
    ):
        output = site.start_site("mysite")
    assert output == "Starting apache...OK\n"


def test_start_site_raises_on_failure_with_stdout_and_stderr():
    with patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess(
            [], 2, stdout="Starting apache.............failed", stderr="Address already in use"
        ),
    ):
        with pytest.raises(site.SiteBootstrapError) as exc_info:
            site.start_site("mysite")
    assert "Starting apache.............failed" in str(exc_info.value)
    assert "Address already in use" in str(exc_info.value)


def _real_hosts_mk_content(host_attributes_body: str) -> str:
    """A realistic WATO hosts.mk file — same shape as a real Checkmk 2.4
    CE site produces (live-captured), critically including the
    `folder_attributes.update({})` call *after* `host_attributes.update`
    that a naive greedy-regex parse would run past (see
    `_parse_host_attributes()`'s docstring for the bug this reproduces)."""
    return (
        "# Created by HostStorage\n\n"
        "all_hosts += ['placeholder']\n\n"
        "host_tags.update({'placeholder': {}})\n\n"
        "host_labels.update({'placeholder': {}})\n\n"
        "# ipaddresses\n"
        "ipaddresses.update({'placeholder': '0.0.0.0'})\n\n"
        "# Host attributes (needed for WATO)\n"
        f"host_attributes.update({host_attributes_body})\n\n"
        "folder_attributes.update({})\n"
    )


def test_list_agent_registered_hosts_returns_only_cmk_agent_hosts_across_wato_folders(tmp_path):
    root_wato = tmp_path / "etc" / "check_mk" / "conf.d" / "wato"
    root_wato.mkdir(parents=True)
    (root_wato / "hosts.mk").write_text(
        _real_hosts_mk_content("{'checkmk': {'ipaddress': '192.168.1.1', 'tag_agent': 'no-agent'}}")
    )

    subfolder_wato = root_wato / "vlan10"
    subfolder_wato.mkdir()
    (subfolder_wato / "hosts.mk").write_text(
        _real_hosts_mk_content(
            "{'test-linux': {'ipaddress': '192.168.1.2', 'tag_agent': 'cmk-agent'}, "
            "'test-windows': {'ipaddress': '192.168.1.3', 'tag_agent': 'cmk-agent'}}"
        )
    )

    with patch("checkmk_wizard.site.Path", return_value=tmp_path):
        result = site.list_agent_registered_hosts("mysite")

    assert result == [("test-linux", "192.168.1.2"), ("test-windows", "192.168.1.3")]


def test_list_agent_registered_hosts_empty_when_no_wato_dir(tmp_path):
    with patch("checkmk_wizard.site.Path", return_value=tmp_path / "does_not_exist"):
        assert site.list_agent_registered_hosts("mysite") == []


def test_list_agent_registered_hosts_empty_when_hosts_mk_malformed(tmp_path):
    wato_root = tmp_path / "etc" / "check_mk" / "conf.d" / "wato"
    wato_root.mkdir(parents=True)
    (wato_root / "hosts.mk").write_text("not a recognizable hosts.mk format at all\n")

    with patch("checkmk_wizard.site.Path", return_value=tmp_path):
        assert site.list_agent_registered_hosts("mysite") == []


def test_start_site_does_not_raise_when_already_running():
    # Live-verified: `omd start` on an already-fully-running site returns
    # a nonzero exit code even though nothing actually failed — every
    # daemon reports "already running"/"already started". Must not raise.
    already_running_stdout = (
        "Starting agent-receiver...already running.\n"
        "npcd already started...\n"
        "Starting apache...(already running: 12345)...OK\n"
    )
    with patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess([], 2, stdout=already_running_stdout),
    ):
        output = site.start_site("mysite")
    assert output == already_running_stdout
