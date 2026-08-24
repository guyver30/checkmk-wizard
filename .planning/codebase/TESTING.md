# Testing Patterns

**Analysis Date:** 2026-08-24

## Test Framework

**Runner:**
- pytest 9.1.1+
- Config: `pyproject.toml` (minimal configuration)
- No `pytest.ini`, `setup.cfg`, or `conftest.py` — using pytest defaults

**Async Testing:**
- pytest-asyncio 1.4.0+ for async test support
- Async tests marked with `@pytest.mark.asyncio` decorator
- Enables `async def test_*` function definitions

**HTTP Mocking:**
- respx 0.23.1+ for mocking httpx requests
- Pattern: `with respx.mock:` context manager wraps tests using HTTP calls

**Run Commands:**
```bash
# Run all tests
pytest

# Watch mode (if installed)
pytest --watch

# Coverage report
pytest --cov=src --cov-report=html
```

## Test File Organization

**Location:**
- Test files co-located in `tests/` directory parallel to `src/`
- Structure: `tests/` contains test modules

**Naming:**
- Test file pattern: `test_*.py` (e.g., `test_api.py`, `test_remote.py`, `test_scanner.py`)
- Test function pattern: `test_*` or `async def test_*`

**Directory Structure:**
```
/home/kone/claude_projects/checkmk-config/
├── src/
│   └── checkmk_wizard/
│       ├── api.py
│       ├── scanner.py
│       ├── remote.py
│       ├── site.py
│       ├── livestatus.py
│       └── wizard.py
├── tests/
│   ├── test_api.py
│   ├── test_remote.py
│   └── test_scanner.py
└── pyproject.toml
```

## Test Structure

**Test Pattern — Arrange-Act-Assert:**

```python
@pytest.mark.asyncio
async def test_get_version():
    # Arrange: Set up mock
    with respx.mock:
        respx.get(f"{BASE}/version").mock(
            return_value=Response(200, json={"versions": {"checkmk": "2.4.0p34"}})
        )
        
        # Act: Call function
        async with CheckmkClient(CONN) as client:
            result = await client.get_version()
    
    # Assert: Verify behavior
    assert result["versions"]["checkmk"] == "2.4.0p34"
```

**Module-Level Setup:**
- Constants defined at module level for reuse
- Example from `tests/test_api.py`:
```python
CONN = CheckmkConnection(host="cmk.example", site="mysite", username="automation", secret="s3cret")
BASE = "http://cmk.example/mysite/check_mk/api/v1"
```

**Async Test Execution:**
- Use `@pytest.mark.asyncio` for all async test functions
- Example from `tests/test_api.py`:
```python
@pytest.mark.asyncio
async def test_get_version():
    with respx.mock:
        # test body
```

**Mixed Sync and Async Tests:**
- Both sync and async tests allowed in same test file
- Sync tests: no decorator needed
- Async tests: require `@pytest.mark.asyncio`
- Example from `tests/test_remote.py`:
```python
def test_os_release_parse():  # Sync
    # test body

@pytest.mark.asyncio
async def test_probe_port_open():  # Async
    # test body
```

## Mocking

**Framework:** respx for HTTP mocking

**HTTP Mocking Pattern:**
```python
with respx.mock:
    # Define mock route
    route = respx.get(f"{BASE}/version").mock(
        return_value=Response(200, json={"versions": {"checkmk": "2.4.0p34"}})
    )
    
    # Execute code
    async with CheckmkClient(CONN) as client:
        result = await client.get_version()
    
    # Assert on request details
    assert route.calls.last.request.headers["Authorization"] == "Bearer automation s3cret"
```

**Verifying Request Details:**
- Access last request via `route.calls.last.request`
- Check headers: `route.calls.last.request.headers["X-Header"]`
- Check body: `route.calls.last.request.content`
- Check params: `route.calls.last.request.url.params["key"]`

**What to Mock:**
- External HTTP APIs (Checkmk REST API)
- Network services reachable over HTTP/HTTPS

**What NOT to Mock:**
- Async utilities like `asyncio.Semaphore`, `asyncio.open_connection`
- TCP socket operations (use real sockets with temporary test servers)
- Subprocess operations (use `check=False` to handle exit codes)

**Real Server Testing for TCP:**
- Use `asyncio.start_server()` for port scanning tests
- Example from `tests/test_scanner.py`:
```python
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
```

## Fixtures and Test Data

**Test Data:**
- No factory fixtures or shared test data files used
- Constants defined at module level (e.g., `CONN`, `BASE` in `test_api.py`)
- Use immediate values for small test cases

**No conftest.py:**
- No pytest fixtures or shared setup/teardown
- Each test is self-contained

## Coverage

**Requirements:** Not enforced; no coverage configuration in pyproject.toml

**Current Coverage:**
- Core API client (`api.py`): Comprehensive tests in `test_api.py`
- Scanner module (`scanner.py`): Unit tests in `test_scanner.py`
- Remote SSH/firewall (`remote.py`): Unit tests in `test_remote.py`
- Wizard orchestration (`wizard.py`): No dedicated tests (interactive CLI)
- Site lifecycle (`site.py`): No dedicated tests (system integration)
- Livestatus client (`livestatus.py`): No dedicated tests

## Test Types

**Unit Tests:**
- Scope: Individual functions and methods
- Example: `test_get_version()` tests the `CheckmkClient.get_version()` method
- Approach: Mock external dependencies (HTTP, network)
- Location: `tests/test_api.py`, `tests/test_scanner.py`, `tests/test_remote.py`

**Integration Tests:**
- Scope: API client + HTTP layer interaction via respx mocking
- Example: `test_get_version_sends_bearer_auth()` verifies authentication headers
- Approach: Mock HTTP endpoints but verify request/response contract
- Location: `tests/test_api.py` (respx-based)

**Network Integration Tests:**
- Scope: Real TCP connection testing (not mocked)
- Example: `test_probe_port_open()` uses real socket connections
- Approach: Spin up temporary test servers, no external services
- Location: `tests/test_scanner.py`, `tests/test_remote.py` (asyncio.start_server)

**No E2E Tests:**
- Full end-to-end interactive wizard testing not automated
- Wizard (Phase 1-7) is interactive CLI; manual testing required
- System integration tests (site creation, SSH connectivity) manual

## Common Patterns

**Async Testing:**
```python
@pytest.mark.asyncio
async def test_probe_port_open():
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        result = await probe_port("127.0.0.1", port)
        assert result.reachable is True
    finally:
        server.close()
        await server.wait_closed()
```

**Error Path Testing:**
```python
@pytest.mark.asyncio
async def test_error_response_raises():
    with respx.mock:
        respx.post(f"{BASE}/domain-types/host_config/collections/all").mock(
            return_value=Response(400, json={"title": "bad request"})
        )
        async with CheckmkClient(CONN) as client:
            with pytest.raises(CheckmkAPIError):
                await client.create_host("badhost")
```

**Context Manager Testing:**
```python
@pytest.mark.asyncio
async def test_get_version():
    with respx.mock:
        # Mock setup
        respx.get(f"{BASE}/version").mock(return_value=Response(200, json={}))
        
        # Test context manager usage
        async with CheckmkClient(CONN) as client:
            result = await client.get_version()
        
        # Assertions
        assert result == {}
```

**Request Detail Assertions:**
```python
@pytest.mark.asyncio
async def test_download_agent_uses_os_type_param():
    with respx.mock:
        route = respx.get(f"{BASE}/domain-types/agent/actions/download/invoke").mock(
            return_value=Response(200, content=b"binary-agent-data")
        )
        async with CheckmkClient(CONN) as client:
            data = await client.download_agent("linux_deb")
        
        # Verify request parameters
        assert route.calls.last.request.url.params["os_type"] == "linux_deb"
```

## Status

**Test Execution:**
- Run tests: `pytest` (no special configuration needed)
- Tests are isolated and do not require external services
- Async tests automatically run in event loop via pytest-asyncio

**Known Gaps:**
- No tests for `wizard.py` (interactive CLI)
- No tests for `site.py` (local system integration)
- No tests for `livestatus.py` (Livestatus socket client)
- Consider adding tests for these modules if making changes

---

*Testing analysis: 2026-08-24*
