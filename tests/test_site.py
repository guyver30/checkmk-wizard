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
