from unittest.mock import patch

from checkmk_wizard import site


def test_omd_installed_true_when_on_path():
    with patch("shutil.which", return_value="/usr/bin/omd"):
        assert site.omd_installed() is True


def test_omd_installed_false_when_missing():
    with patch("shutil.which", return_value=None):
        assert site.omd_installed() is False
