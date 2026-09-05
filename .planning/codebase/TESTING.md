# Testing Patterns

**Analysis Date:** 2026-09-05

## Test Framework

**Runner:**
- `pytest` >= 9.1.1 (`pyproject.toml:26`, `[dependency-groups].dev`)
- `pytest-asyncio` >= 1.4.0 for async test support (`pyproject.toml:27`)
- `respx` >= 0.23.1 for mocking `httpx` calls (`pyproject.toml:28`)
- No `pytest.ini`, no `[tool.pytest.ini_options]` in `pyproject.toml`, no `conftest.py` anywhere in the repo — configuration is entirely defaults plus per-test `@pytest.mark.asyncio` markers (asyncio_mode defaults to "strict": every async test must be explicitly marked, auto-detection is not enabled).

**Assertion Library:**
- Plain `assert` statements only (pytest's assertion rewriting) — no `unittest.TestCase`-style `self.assertX`, no third-party assertion library.

**Run Commands:**
```bash
uv run pytest              # Run all tests (per README.md:144)
uv run pytest -q           # Quiet output, used for quick verification
uv run pytest tests/test_api.py    # Run a single file
```
No watch-mode or coverage command is documented in `README.md` or configured in `pyproject.toml` — coverage is not currently tracked (`pytest-cov` is not a dependency).

## Test File Organization

**Location:**
- Fully separate top-level `tests/` directory, not co-located with source (`tests/` mirrors `src/checkmk_wizard/` file-for-file).

**Naming:**
- One test file per source module: `test_<module>.py` (`tests/test_api.py` ↔ `src/checkmk_wizard/api.py`, etc.).
- Test function names are full sentences describing behavior and (often) the specific scenario: `test_delete_host_missing_raises`, `test_omd_start_on_already_running_site_is_not_an_error` (style), `test_probe_livestatus_tcp_false_when_connection_refused`. The name alone should make the assertion's intent clear without reading the body.

**Structure:**
```
tests/
├── test_api.py          # CheckmkClient + bootstrap_* functions (509 lines, respx-based)
├── test_livestatus.py   # query_host_states() (70 lines, socket mocking)
├── test_remote.py       # SSH/OS-detection/command-building pure functions + real-socket probe_port (165 lines)
├── test_scanner.py      # chunk_network/scan_host, real ephemeral-port sockets (41 lines)
├── test_site.py         # OMD subprocess wrappers, subprocess.run mocked (249 lines)
└── test_wizard.py       # Interactive phase orchestration, questionary + all lower layers mocked (2150 lines, largest by far)
```
No `fixtures/` or `factories/` directory — every test builds its own minimal input inline or via small local helper functions defined at the top of its file.

## Test Structure

**Suite Organization:**
Tests are flat functions, not grouped into classes. Each file groups related tests by proximity (declaration order), not by explicit `class Test...:` blocks:

```python
# tests/test_api.py:24-44 — plain function-per-behavior, no shared class/fixture
def test_connection_registration_credential_defaults_to_rest_credential():
    conn = CheckmkConnection(host="cmk.example", site="mysite", username="automation", secret="s3cret")
    assert conn.registration_user == "automation"
    assert conn.registration_secret == "s3cret"
```

**Patterns:**
- Setup: module-level constants (`CONN`, `BASE`, `LOGIN_URL`, `LOGIN_PAGE_HTML` in `tests/test_api.py:18-21`) stand in for shared fixtures rather than `@pytest.fixture`. No `@pytest.fixture` decorator is used anywhere in the test suite.
- Teardown: `respx.mock` and `patch(...)` are used as context managers (`with respx.mock: ...`), so cleanup is automatic on block exit — no explicit teardown code.
- Real ephemeral resources (sockets, servers) are cleaned up manually in a `try/finally`: `server.close(); await server.wait_closed()` (`tests/test_scanner.py:32-41`, `tests/test_remote.py:114-123`).
- Assertion style: arrange inputs, act via one call inside a `with` block, then assert on plain return values or on the mock's recorded call args, outside the `with` block once possible.

## Mocking

**Framework:** `unittest.mock` (`patch`, `MagicMock`, `AsyncMock`, `monkeypatch` fixture) plus `respx` specifically for `httpx`-based HTTP calls.

**Patterns:**

HTTP layer — `respx` intercepts at the transport level, asserting both the response handling and the exact outgoing request:
```python
# tests/test_api.py:65-76
@pytest.mark.asyncio
async def test_create_host():
    with respx.mock:
        route = respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(
            return_value=Response(200, json={"id": "myhost"})
        )
        async with CheckmkClient(CONN) as client:
            result = await client.create_host("myhost", folder="/", attributes={"ipaddress": "10.0.0.5"})
    assert result["id"] == "myhost"
    sent_body = route.calls.last.request.content
    assert b"myhost" in sent_body
    assert b"10.0.0.5" in sent_body
```

Subprocess layer — `unittest.mock.patch("subprocess.run", return_value=subprocess.CompletedProcess(...))`, then assert both the return value and the exact argv `subprocess.run` was called with:
```python
# tests/test_site.py:32-41
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
```

Socket layer — a hand-rolled `MagicMock` standing in for a `socket.socket`, driving `recv()` via `side_effect` chunks and asserting `sendall`'s exact wire-protocol bytes:
```python
# tests/test_livestatus.py:7-13, 58-70
def _fake_connection(response: bytes) -> MagicMock:
    sock = MagicMock()
    chunks = [response, b""]
    sock.recv.side_effect = chunks
    sock.__enter__.return_value = sock
    sock.__exit__.return_value = False
    return sock

def test_query_host_states_sends_expected_lql_query():
    sock = _fake_connection(b"")
    with patch("socket.create_connection", return_value=sock):
        livestatus.query_host_states("checkmk", ["web1"])
    sent = sock.sendall.call_args[0][0].decode()
    assert sent == "GET hosts\nColumns: name state\nOutputFormat: csv\nColumnHeaders: off\n\n"
```

Interactive prompts — `monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)` replaces the entire prompt-answering mechanism with an async fake that returns canned answers, rather than mocking `questionary.text`/`questionary.select` individually. This is the single most common mocking pattern in `tests/test_wizard.py`:
```python
# tests/test_wizard.py:67-77
def _mock_no_ssh_and_skip_services(monkeypatch):
    async def fake_ask(self, patch_stdout=False, kbi_msg=""):
        return ""
    monkeypatch.setattr(questionary.Question, "ask_async", fake_ask)
```
When a test needs to assert *what prompt text was shown* (not just supply an answer), it also wraps the real `questionary.text`/`questionary.select` factory to record the call before delegating to the original (`tests/test_wizard.py:96-114`).

Deep call-chain isolation — `wizard.py` tests monkeypatch collaborator functions at the point they're imported into `wizard.py` (`checkmk_wizard.wizard.X`), not at their original definition site, since `wizard.py` does `from checkmk_wizard.api import bootstrap_automation_user` etc.:
```python
# tests/test_wizard.py:221
monkeypatch.setattr("checkmk_wizard.wizard.bootstrap_automation_user", fake_bootstrap)
```
This is a load-bearing pattern: patching `checkmk_wizard.api.bootstrap_automation_user` instead would silently not affect `wizard.py`'s already-bound reference.

"Must not be called" guards — a fixture/helper installs a fake that raises if invoked, to assert a code path is skipped entirely, not just that its result is ignored:
```python
# tests/test_wizard.py:238 (fail_if_called_for_automation) / :616 (fail_if_asked) — pattern
monkeypatch.setattr(questionary.Question, "ask_async", fail_if_asked)
```

Sleep suppression — `asyncio.sleep` is patched with `AsyncMock()` so retry/poll loops run instantly in tests instead of actually waiting:
```python
# tests/test_api.py:330
with patch("checkmk_wizard.api.asyncio.sleep", new=AsyncMock()):
```

**What to Mock:**
- Anything crossing a process/OS/network boundary: `subprocess.run`, `socket.create_connection`, HTTP via `respx`, `asyncssh` connections, `questionary` prompt answers.
- Collaborator functions imported into the module under test, when isolating one phase function from the ones it calls (`_gui_login`, `bootstrap_automation_user`, `site.get_site_credentials`, etc. inside `wizard.py` tests).

**What NOT to Mock:**
- Pure functions and dataclasses are exercised directly with real inputs, no mocking: `OSRelease.parse()`, `package_family()`, `chunk_network()`, `_password_problems()`, `_valid_checkmk_host()`.
- Low-level async networking is sometimes tested against a *real* ephemeral local socket/server rather than mocked, when the behavior under test is genuinely about OS-level TCP semantics (open vs. RST vs. timeout): `probe_port()` in `tests/test_remote.py:113-137` starts a real `asyncio.start_server` on port 0 and a real connection-refused scenario, rather than faking `asyncio.open_connection`. Same approach in `tests/test_scanner.py:21-41` for `scan_host()`.

## Fixtures and Factories

**Test Data:**
No `@pytest.fixture`-based fixtures or dedicated factory module exist. Reusable setup is a plain module-level constant or a plain helper function called explicitly at the top of each test:
```python
# tests/test_api.py:18-21
CONN = CheckmkConnection(host="cmk.example", site="mysite", username="automation", secret="s3cret")
BASE = "http://cmk.example/mysite/check_mk/api/v1"
LOGIN_URL = "http://cmk.example/mysite/check_mk/login.py"
LOGIN_PAGE_HTML = '<script>var global_csrf_token = "the-csrf-token";</script>'
```
```python
# tests/test_wizard.py:138-164 — local helper returning a list callers can inspect afterward
def _mock_container_mode_omd_calls(monkeypatch):
    ...
```

**Location:**
- Inline in each test file, near the top (module constants) or immediately before first use (helper functions). No sharing of fixtures/helpers across test files — each file is self-contained.

## Coverage

**Requirements:** None enforced — no `pytest-cov`/`coverage` dependency, no CI config found, no coverage threshold anywhere in the repo.

**View Coverage:**
Not currently possible without adding `pytest-cov`. To add it: `uv add --group dev pytest-cov` then `uv run pytest --cov=checkmk_wizard`.

## Test Types

**Unit Tests:**
- The overwhelming majority of the suite (222 tests total, all in `tests/`). Each targets one function or one small behavior of it, at the module boundary (calling public/private functions directly, not through the CLI).

**Integration Tests:**
- A handful of tests exercise a slightly larger slice via real OS primitives instead of mocks — real TCP sockets/servers for `probe_port()`/`scan_host()` (see above) — but nothing exercises a real Checkmk site or real SSH host; those are always mocked or comment-annotated as "live-verified" during manual development rather than in the automated suite. There is no test marker distinguishing these from pure unit tests (no `@pytest.mark.integration`).

**E2E Tests:**
- Not used. No browser/CLI-driving E2E framework is present; the `docs/` prose comments ("Live-verified against a real Checkmk 2.4.0p35 CE site") document manual verification the author did against a real instance, not automated E2E coverage.

## Common Patterns

**Async Testing:**
```python
# tests/test_api.py:46-52 — standard shape for every async test
@pytest.mark.asyncio
async def test_get_version():
    with respx.mock:
        respx.get(f"{BASE}/version").mock(return_value=Response(200, json={"versions": {"checkmk": "2.4.0p34"}}))
        async with CheckmkClient(CONN) as client:
            result = await client.get_version()
    assert result["versions"]["checkmk"] == "2.4.0p34"
```
Every async test carries an explicit `@pytest.mark.asyncio` — the suite relies on strict mode, so a missing marker means the test silently doesn't run as a coroutine (would fail with a "coroutine was never awaited" warning, not a clean skip) — always add the marker when writing a new `async def test_...`.

**Error Testing:**
```python
# tests/test_api.py:90-98
@pytest.mark.asyncio
async def test_delete_host_missing_raises():
    with respx.mock:
        respx.delete(f"{BASE}/objects/host_config/ghost").mock(
            return_value=Response(404, json={"title": "Not Found"})
        )
        async with CheckmkClient(CONN) as client:
            with pytest.raises(CheckmkAPIError):
                await client.delete_host("ghost")
```
For errors that need message inspection, the pattern captures the exception via `as exc_info` and asserts on `str(exc_info.value)`:
```python
# tests/test_site.py:44-54
with pytest.raises(site.SiteBootstrapError) as exc_info:
    site.remove_site("mysite")
assert "Stopping apache...failed" in str(exc_info.value)
assert "no such site" in str(exc_info.value)
```

**Parametrized Tests:**
```python
# tests/test_remote.py:62-74
@pytest.mark.parametrize(
    "version_id,expected_substring",
    [("20.04", "Focal"), ("22.04", "Jammy"), ("24.04", "Noble")],
)
def test_smartmontools_deb_filename_matches_bundled_ubuntu_releases(version_id, expected_substring):
    filename = smartmontools_deb_filename(OSRelease(id="ubuntu", version_id=version_id))
    assert filename is not None
    assert expected_substring in filename
```
Used when the same assertion shape repeats across a small enumerable set of inputs (OS versions here); otherwise, a scenario gets its own explicitly named test function rather than being folded into a parametrize table, since names double as documentation of behavior.

**Regression Tests:**
A real, previously-shipped bug gets its own permanently-kept test with a comment explaining the bug, even after the underlying code has moved on — see `test_delete_site_choice_value_survives_as_sentinel` (`tests/test_wizard.py:80-92`) and `_parse_host_attributes`'s AST-parsing test coverage tied to `site.py`'s "Bug fixed 2026-08-27" comment. When fixing a live-reported bug, add a test named `test_<subject>_<regression behavior>` with a comment describing the original failure mode, not just a test of the new correct behavior in isolation.

---

*Testing analysis: 2026-09-05*
