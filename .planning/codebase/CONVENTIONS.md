# Coding Conventions

**Analysis Date:** 2026-08-24

## Naming Patterns

**Files:**
- `snake_case.py` for module files (e.g., `api.py`, `scanner.py`, `remote.py`)
- Test files: `test_*.py` (e.g., `test_api.py`, `test_remote.py`)

**Functions:**
- `snake_case` for all function and method names (e.g., `get_version()`, `scan_host()`, `create_folder()`)
- Private functions/methods prefixed with single underscore (e.g., `_probe_port()`, `_connect()`, `_request()`)

**Variables:**
- `snake_case` for all local and instance variables (e.g., `open_ports`, `host_names`, `scan_results`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_PORTS`, `AGENT_RECEIVER_PORT`, `DEFAULT_TIMEOUT`)

**Classes:**
- `PascalCase` for all class names (e.g., `CheckmkClient`, `HostScanResult`, `OSRelease`)
- Exceptions: `PascalCase` with `Error` suffix (e.g., `CheckmkAPIError`, `SiteBootstrapError`)

**Dataclass fields:**
- `snake_case` for all fields in dataclasses (e.g., `host_name`, `folder`, `automation_secret`)

**Enum members:**
- `UPPER_SNAKE_CASE` for enum values (e.g., `Outcome.AUTOMATED`, `Outcome.MANUAL_REQUIRED`)

## Code Style

**Imports:**
- Use `from __future__ import annotations` at the top of all modules to enable modern type hint syntax
- Organize imports in groups: standard library → third-party → local modules
- Example from `src/checkmk_wizard/api.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Self

import httpx

from checkmk_wizard.api import CheckmkError, CheckmkClient, CheckmkConnection
```

**Type Hints:**
- Full type hints for all functions, method parameters, and return types required
- Use modern Python 3.11+ syntax with `|` for unions (e.g., `str | None` instead of `Optional[str]`)
- Use generic types from `typing` module (e.g., `dict[str, Any]`, `list[int]`)
- Example from `src/checkmk_wizard/remote.py`:
```python
async def probe_port(host: str, port: int, timeout: float = 3.0) -> PortProbeResult:
```

**Dataclasses:**
- Use `@dataclass` decorator for simple data containers
- Use `field(default_factory=list)` for mutable default values
- Example from `src/checkmk_wizard/scanner.py`:
```python
@dataclass
class HostScanResult:
    ip: str
    open_ports: list[int] = field(default_factory=list)
```

**Async Code:**
- Use `async`/`await` for I/O-bound operations (HTTP, SSH, socket operations)
- Use `asyncio.Semaphore` for concurrency control (e.g., in `scan_host()`)
- Use context managers with `async with` for resource management

**String Formatting:**
- Use f-strings for string interpolation (e.g., `f"Scanned {chunk} — {alive}/{total} responsive"`)
- Use raw strings for shell commands where needed

## Error Handling

**Custom Exceptions:**
- Create domain-specific exception classes inheriting from appropriate base class
- Include detailed context in exception initialization
- Example from `src/checkmk_wizard/api.py`:
```python
class CheckmkAPIError(RuntimeError):
    """Raised when the Checkmk REST API returns an error response."""

    def __init__(self, method: str, url: str, status_code: int, body: Any):
        self.method = method
        self.url = url
        self.status_code = status_code
        self.body = body
        super().__init__(f"{method} {url} -> {status_code}: {body}")
```

**Error Handling Pattern:**
- Catch specific exceptions, not bare `except:` clauses
- Use `check=False` for subprocess calls to handle errors manually
- Provide graceful fallbacks to manual processes when automation fails
- Example from `src/checkmk_wizard/remote.py`:
```python
try:
    async with await _connect(host, creds) as conn:
        # perform operation
except (OSError, asyncssh.Error) as exc:
    return ActionResult(Outcome.FAILED_FALLBACK_MANUAL, str(exc), manual)
```

**HTTP Error Handling:**
- Check specific status codes; handle 204 (No Content) separately
- Raise `CheckmkAPIError` for non-2xx responses
- Example from `src/checkmk_wizard/api.py`:
```python
if resp.status_code not in expect and resp.status_code != 204:
    try:
        body: Any = resp.json()
    except ValueError:
        body = resp.text
    raise CheckmkAPIError(method, str(resp.url), resp.status_code, body)
```

## Comments and Documentation

**Module Docstrings:**
- Required at the top of every module
- Describe purpose, key responsibilities, and verified facts
- Example from `src/checkmk_wizard/api.py`:
```python
"""Checkmk REST API client.

Endpoints and payloads verified against live Checkmk docs via context7
(docs.checkmk.com, REST API reference) — see docs/CHECKMK_SETUP_CONFIGURATOR_PLAN.md
for the source citations.
"""
```

**Function/Method Docstrings:**
- Use for public functions and important private functions
- Include parameter descriptions and return type info if not obvious from type hints
- Example from `src/checkmk_wizard/remote.py`:
```python
async def probe_port(host: str, port: int, timeout: float = 3.0) -> PortProbeResult:
    """Distinguish an open port from a closed (RST) vs. filtered/unreachable one.

    A plain TCP connect can make this distinction without raw sockets:
    ConnectionRefusedError means the remote stack sent RST (port closed);
    a timeout means no response came back at all (filtered or host down).
    """
```

**Inline Comments:**
- Use sparingly; explain *why*, not *what*
- Use for non-obvious logic and workarounds
- Example from `src/checkmk_wizard/wizard.py`:
```python
# shlex.quote must protect the space and embedded quote in the password
assert "p@ss w'ord" not in cmd or "'\"'\"'" in cmd
```

**Phase Organization:**
- Use phase-numbered section comments to organize wizard workflow
- Example from `src/checkmk_wizard/api.py`:
```python
# -- Phase 1: connectivity -------------------------------------------------

async def get_version(self) -> dict[str, Any]:
    # ...

# -- Phase 2: folders --------------------------------------------------

async def create_folder(self, ...):
    # ...
```

## Function Design

**Parameter Order:**
- Required parameters first, optional parameters with defaults last
- Use keyword-only arguments (after `*`) for clarity when many parameters
- Example from `src/checkmk_wizard/api.py`:
```python
async def _request(
    self,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
    expect: tuple[int, ...] = (200, 201),
) -> httpx.Response:
```

**Return Values:**
- Use structured return types (dataclasses, typed dicts) when returning multiple values
- Return `None` explicitly for no-op cases; don't use bare `return`
- Return empty dict `{}` or empty list `[]` instead of `None` when appropriate

**Size Guidelines:**
- Keep functions focused and concise
- Break up long async chains into separate functions

## Module Design

**Exports:**
- All public functions/classes are module-level
- No barrel files (no `__all__` exports used in this codebase)
- Import specific symbols: `from checkmk_wizard.api import CheckmkClient, CheckmkConnection`

**Separation of Concerns:**
- `api.py`: REST API client and connection management
- `scanner.py`: Network discovery and port scanning
- `remote.py`: SSH automation, firewall, agent installation
- `site.py`: Local OMD site lifecycle
- `livestatus.py`: Livestatus query client
- `wizard.py`: Interactive terminal orchestration (phases 1-7)

**Context Managers:**
- Use `async with` for async context managers (e.g., HTTP clients, SSH connections)
- Implement `__aenter__` and `__aexit__` for resource cleanup
- Example from `src/checkmk_wizard/api.py`:
```python
async def __aenter__(self) -> Self:
    return self

async def __aexit__(self, *exc_info: object) -> None:
    await self.close()
```

## Linting/Formatting

**Configuration:**
- No explicit `.ruff.toml` or `.flake8` config present
- Project uses `uv` as build system (configured in `pyproject.toml`)
- Expected to follow PEP 8 conventions by default
- Line length: Not explicitly configured; assume default (likely 88 or 100)

**Expected conventions:**
- 4-space indentation (Python standard)
- Trailing commas in multi-line structures
- Docstrings in triple double-quotes

---

*Convention analysis: 2026-08-24*
