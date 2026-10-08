"""Tests for scripts/smoke_test_broker.py: opt-in restart and honest summary line.

WR-05 (phase 14.2 review): a plain run used to restart the broker container, which
on 2026-10-02 turned every real host DOWN, and it printed "all checks passed" even
when whole password-gated groups were skipped.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "smoke_test_broker", Path(__file__).resolve().parents[1] / "scripts" / "smoke_test_broker.py"
)
smoke = importlib.util.module_from_spec(_SPEC)
sys.modules["smoke_test_broker"] = smoke
_SPEC.loader.exec_module(smoke)


@pytest.fixture
def calls(monkeypatch):
    """Stub every check and the cleanup; record which ran. `fail` names checks that return False."""
    recorded = {"ran": [], "fail": set()}

    def make(name):
        def stub(*args, **kwargs):
            recorded["ran"].append(name)
            return name not in recorded["fail"]

        return stub

    for name in [n for n in dir(smoke) if n.startswith("check_")]:
        monkeypatch.setattr(smoke, name, make(name))
    monkeypatch.setattr(smoke, "_cleanup", lambda *a, **k: None)
    for var in ("ADMIN_WS_PASSWORD", "MQTT_ANALYTICS_PASSWORD", "TRIAGE_WS_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    return recorded


def _run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["smoke_test_broker.py", "--site-id", "testsite", *argv])
    return smoke.main()


def test_plain_run_never_restarts_broker(calls, monkeypatch, capsys):
    # WR-05 / 2026-10-02 single-container-restart incident: restart must be opt-in.
    assert _run(monkeypatch) == 0
    assert "check_persistence_across_restart" not in calls["ran"]
    assert "[SKIP] persistence_across_restart (pass --with-restart to run it)" in capsys.readouterr().out


def test_with_restart_runs_restart_check(calls, monkeypatch):
    # WR-05: the opt-in flag still runs the persistence check.
    assert _run(monkeypatch, "--with-restart") == 0
    assert "check_persistence_across_restart" in calls["ran"]


def test_skip_restart_still_accepted_and_wins(calls, monkeypatch):
    # WR-05: existing documented commands pass --skip-restart; it stays a harmless flag.
    assert _run(monkeypatch, "--skip-restart", "--with-restart") == 0
    assert "check_persistence_across_restart" not in calls["ran"]


def test_summary_counts_passed_and_skipped(calls, monkeypatch, capsys):
    # WR-05: skipped password groups used to be hidden behind "all checks passed".
    assert _run(monkeypatch) == 0
    out = capsys.readouterr().out
    skips = out.count("[SKIP]")
    assert skips == 4  # wsadmin, analytics, wstriage, restart
    assert out.strip().splitlines()[-1] == f"[SUMMARY] {len(calls['ran'])} checks passed, {skips} skipped"


def test_failure_exit_code_and_summary(calls, monkeypatch, capsys):
    # WR-05: a failing check exits 1 and the summary names failed, passed and skipped counts.
    calls["fail"].add("check_ws_subscribe")
    assert _run(monkeypatch) == 1
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert last == f"[SUMMARY] 1 checks failed, {len(calls['ran']) - 1} passed, 4 skipped"
