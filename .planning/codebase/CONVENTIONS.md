# Coding Conventions

**Analysis Date:** 2026-09-05

## Naming Patterns

**Files:**
- One module per pipeline concern, named after its domain, not its phase: `src/checkmk_wizard/api.py` (REST client), `src/checkmk_wizard/site.py` (OMD/site shell-outs), `src/checkmk_wizard/remote.py` (SSH/agent automation), `src/checkmk_wizard/scanner.py` (async TCP port scanner), `src/checkmk_wizard/livestatus.py` (Livestatus TCP client), `src/checkmk_wizard/wizard.py` (interactive orchestration of all phases).
- Test files mirror source files 1:1: `tests/test_api.py`, `tests/test_site.py`, `tests/test_remote.py`, `tests/test_scanner.py`, `tests/test_livestatus.py`, `tests/test_wizard.py`. No `conftest.py` exists — shared fixtures/helpers are defined per-file instead (e.g. `_mock_no_ssh_and_skip_services` in `tests/test_wizard.py:67`).

**Functions:**
- `snake_case` throughout, no exceptions.
- Module-private helpers prefixed with a single underscore: `_request`, `_gui_login` (`src/checkmk_wizard/api.py:79,289`); `_probe_port`, `_valid_checkmk_host`, `_password_problems`, `_prompt_new_site_name` (`src/checkmk_wizard/scanner.py:32`, `src/checkmk_wizard/wizard.py:88,123`). These are still imported directly by tests (e.g. `tests/test_wizard.py:20-61` imports two dozen underscore-prefixed names) — leading underscore signals "internal to the package", not "untestable".
- Phase entry points in `wizard.py` are named `phaseN_<name>`: `phase1_site_bringup`, `phase2_folders`, `phase3_discovery`, `phase4_classification`, `phase5_onboarding`, `phase6_discovery` (`src/checkmk_wizard/wizard.py`, imported in `tests/test_wizard.py:55-60`).
- Boolean-returning functions read as predicates: `omd_installed()`, `site_exists()`, `livestatus_tcp_enabled()`, `site_running()`, `agent_status_shows_connection()` (`src/checkmk_wizard/site.py:45,54,117,128`, `src/checkmk_wizard/remote.py`).

**Variables:**
- `snake_case` for locals and parameters; module-level constants are `UPPER_SNAKE_CASE`: `DEFAULT_PORTS`, `DEFAULT_TIMEOUT`, `DEFAULT_CONCURRENCY` (`src/checkmk_wizard/scanner.py:17-19`), `AGENT_RECEIVER_PORT` (`src/checkmk_wizard/remote.py:31`), `DEFAULT_PORT` (`src/checkmk_wizard/livestatus.py:15`).
- Compiled regexes are module-level constants named `_XXX_RE`: `_CSRF_TOKEN_RE` (`src/checkmk_wizard/api.py:286`), `_SITE_NAME_RE`, `_FOLDER_NAME_RE`, `_HOST_NAME_RE`, `_HOSTNAME_RE` (`src/checkmk_wizard/wizard.py:63,72,77,83`).
- Test constants that stand in for fixtures are hoisted to module scope in ALL_CAPS: `CONN`, `BASE`, `LOGIN_URL`, `LOGIN_PAGE_HTML` (`tests/test_api.py:18-21`).

**Types:**
- `PascalCase` for classes and dataclasses: `CheckmkConnection`, `CheckmkClient`, `CheckmkAPIError` (`src/checkmk_wizard/api.py`); `HostScanResult` (`src/checkmk_wizard/scanner.py:22`); `SSHCredentials`, `PortProbeResult`, `ActionResult`, `OSRelease`, `CompatibilityCheck`, `AgentStatusCheck` (`src/checkmk_wizard/remote.py`); `SiteCredentials` (`src/checkmk_wizard/site.py:26`); `ScannedHost`, `OnboardedHost` (`src/checkmk_wizard/wizard.py:139,146`).
- Enums subclass `str, Enum` so values compare/serialize as plain strings: `class Outcome(str, Enum)` (`src/checkmk_wizard/remote.py:34`).
- Custom exceptions subclass the closest built-in and end in `Error`: `CheckmkAPIError(RuntimeError)` (`src/checkmk_wizard/api.py:19`), `SiteBootstrapError(RuntimeError)` (`src/checkmk_wizard/site.py:21`).

## Code Style

**Formatting:**
- No `.prettierrc`/formatter config file found; no `black`/`ruff format` section in `pyproject.toml`. A `.ruff_cache/` directory exists (evidence `ruff` is run, likely via `uvx ruff check` per the linting default) but no `[tool.ruff]` section is committed to `pyproject.toml` — ruff runs with its own defaults (line length 88, double quotes).
- Observed style is consistent with ruff/black defaults: double-quoted strings throughout, trailing commas in multi-line calls, 4-space indentation.
- Every module starts with `from __future__ import annotations` (`src/checkmk_wizard/api.py:8`, `site.py:12`, `scanner.py:10`, `livestatus.py:11`, `remote.py:21`, `wizard.py:5`) — enables `X | None` union syntax and forward references under Python 3.11's runtime, and is required before it for classes referencing themselves (e.g. `OSRelease.parse(cls) -> OSRelease` in `src/checkmk_wizard/remote.py:73`).
- Long lines wrap function signatures one-parameter-per-line when they exceed ~100 chars; short calls stay on one line (see `create_folder`/`create_host` in `src/checkmk_wizard/api.py:125-137,168-182`).

**Linting:**
- `.ruff_cache/0.16.4/` confirms ruff 0.16.4 is the linter in use, run with default rule set (no project-level rule overrides found).
- `python-version` pinned via `.python-version` (contents: `3.11`-family) and `requires-python = ">=3.11"` in `pyproject.toml:9`.

## Import Organization

**Order (per PEP 8 / isort-style grouping, observed consistently):**
1. `from __future__ import annotations` (always first, alone)
2. Standard library imports, alphabetized: `asyncio`, `re`, `secrets`, `dataclasses`, `typing` (`src/checkmk_wizard/api.py:10-14`)
3. Third-party imports: `httpx`, `asyncssh`, `questionary`, `rich.*` (`src/checkmk_wizard/api.py:16`, `src/checkmk_wizard/remote.py:29`, `src/checkmk_wizard/wizard.py:19-22`)
4. Local package imports last, using absolute `checkmk_wizard.X` paths, never relative (`from checkmk_wizard import livestatus, remote, site` and `from checkmk_wizard.api import (...)` in `src/checkmk_wizard/wizard.py:24-33`)

Blank line separates each group. Multi-name imports from one module use parenthesized multi-line form, one name per line, alphabetized (`src/checkmk_wizard/wizard.py:25-32`).

**Path Aliases:** None — this is a plain `src/`-layout package (`src/checkmk_wizard/`) installed via `uv`/`hatchling`-style build; no bundler or `tsconfig`-style alias system applies.

## Error Handling

**Patterns:**
- One error type per subsystem, both wrapping enough context to act on: `CheckmkAPIError(method, url, status_code, body)` (`src/checkmk_wizard/api.py:19-27`) and `SiteBootstrapError(RuntimeError)` (`src/checkmk_wizard/site.py:21-22`), the latter carrying combined `stdout`+`stderr` text in its message rather than structured fields.
- All HTTP calls funnel through one choke point — `CheckmkClient._request()` (`src/checkmk_wizard/api.py:79-115`) — so every network failure (including raw `httpx.HTTPError`/`ConnectError`) is normalized into `CheckmkAPIError` exactly once; call sites never need their own try/except for connectivity. New `CheckmkClient` methods should be added by calling `self._request(...)`, not `self._client.request(...)` directly, to preserve this guarantee.
- Functions that shell out (`subprocess.run(..., check=False)`) always pass `check=False` explicitly and inspect `returncode` themselves, because `omd`'s exit codes are non-standard (e.g. `omd start` returns 2 on an already-running site, which is not a failure — `src/checkmk_wizard/site.py:101-114`). Raising is done by hand: `if result.returncode != 0: raise SiteBootstrapError(...)`. When a false-positive nonzero code is possible, the raise condition additionally greps the captured stdout for the literal word `"failed"` (`site.py:112,161`) rather than trusting the exit code alone.
- "Best-effort" operations that must never abort the caller's flow catch broadly and swallow: `except httpx.HTTPError: pass` around the post-bootstrap activation poll in `bootstrap_automation_user()` (`src/checkmk_wizard/api.py:458-459`) — always accompanied by a comment explaining why swallowing is safe here specifically, not applied as a blanket habit.
- Narrow except clauses elsewhere: `except (TimeoutError, OSError)` to distinguish real network conditions (`src/checkmk_wizard/scanner.py:38`, `src/checkmk_wizard/remote.py:168`), `except ValueError` when a `.json()` parse may fail and should fall back to raw text (`api.py:111-113,394-396`).
- `raise X from exc` is used whenever an exception is translated from a lower-level one, preserving the original traceback (`api.py:108,399,544,620`).
- Domain validation returns lists of human-readable problem strings instead of raising, so callers can display every issue at once: `_password_problems(pw, username) -> list[str]` (`src/checkmk_wizard/wizard.py:123-136`).

## Comments

**When to Comment:**
- Every non-obvious behavior is documented with *why*, frequently citing a live-verification source: "Live-verified against a real Checkmk 2.4.0p35 CE site: ..." (`src/checkmk_wizard/api.py:204-206`) or a context7 doc citation ("verified via context7: docs.checkmk.com/..." — `src/checkmk_wizard/scanner.py:3-7`, `src/checkmk_wizard/remote.py:5-18`). New code that depends on undocumented/reverse-engineered API or CLI behavior should cite how it was verified (live test, source file read, or docs URL) the same way.
- Bug-fix commits leave a dated post-mortem comment at the fix site explaining the old broken behavior and why the new approach avoids the whole class of bug, not just the symptom: `_parse_host_attributes()`'s AST-based rewrite explicitly describes the previous greedy-regex bug it replaced (`src/checkmk_wizard/site.py:191-202`, "Bug fixed 2026-08-27").
- Regression tests get an explanatory comment naming the real bug they guard against, not just a description of the assertion: `test_delete_site_choice_value_survives_as_sentinel` (`tests/test_wizard.py:80-92`).
- Best-effort/fallback code explicitly states the fallback contract in a docstring line ("this is best-effort; the caller should treat a failure here as 'fall back to the existing manual instructions', never as fatal" — `src/checkmk_wizard/api.py:353-356`).

**Docstrings:**
- Every public module has a module-level docstring stating its phase/purpose and citing verification sources (`site.py:1-10`, `scanner.py:1-8`, `livestatus.py:1-9`, `remote.py:1-19`, `wizard.py:1-3`).
- Public functions with non-trivial behavior get a docstring explaining *why* they exist and *why* the implementation looks the way it does — not just parameter descriptions (`bootstrap_automation_user()` in `api.py:324-357` is the densest example: rationale, verification method, failure contract, all in prose). Trivial one-liners (`site_home`, `site_exists`) have no docstring at all.
- No formal docstring format (no Google/NumPy/Sphinx style enforced) — plain prose paragraphs, sometimes with inline backtick-quoted identifiers.

## Function Design

**Size:** Functions are kept to a single responsibility; `wizard.py`'s phase functions are the largest (each drives one interactive phase end-to-end, ~100-250 lines each) but delegate validation/formatting/API calls to small helper functions (`_password_problems`, `_valid_checkmk_host`, `_network_scan_attributes`, etc.) rather than inlining logic.

**Parameters:** Keyword-only parameters (`*`) are used once a function has more than 2-3 optional args, to force call sites to be self-documenting: `CheckmkClient._request(self, method, path, *, json_body=None, params=None, extra_headers=None, expect=(200, 201))` (`api.py:79-88`). Required positional args come first, optional ones with defaults after `*`.

**Return Values:** Async I/O functions return typed dataclasses or `dict[str, Any]`/`list[dict[str, Any]]` mirroring the JSON shape, never raw `httpx.Response` except where the caller explicitly needs headers (`get_folder`, `get_host` return `httpx.Response` specifically so callers can read `ETag` — `api.py:148,200`). Absence is modeled as `None` (`read_automation_secret() -> str | None`, `site.py:257`) rather than raising, when "not found" is an expected, recoverable case.

## Module Design

**Exports:** No `__all__` lists anywhere — modules rely on the underscore-prefix convention to signal public vs. internal, and tests import private names directly when needed (see `tests/test_wizard.py:20-61`).

**Barrel Files:** `src/checkmk_wizard/__init__.py` is empty — no re-export barrel. `src/checkmk_wizard/__main__.py` is a 4-line shim delegating to `wizard.main()`, enabling `python -m checkmk_wizard`; the `[project.scripts]` entry point in `pyproject.toml:18` (`checkmk-wizard = "checkmk_wizard.wizard:main"`) is the primary CLI entry.

## Dataclass Conventions

- `@dataclass` is the default modeling tool for structured data, used pervasively instead of `TypedDict`, `NamedTuple`, or Pydantic (no Pydantic dependency exists): `CheckmkConnection`, `HostScanResult`, `SSHCredentials`, `PortProbeResult`, `ActionResult`, `OSRelease`, `CompatibilityCheck`, `AgentStatusCheck`, `SiteCredentials`, `ScannedHost`, `OnboardedHost`.
- Post-init defaulting logic goes in `__post_init__`, not the field default itself, when one field's default depends on another field's value: `CheckmkConnection.__post_init__` defaults `registration_user`/`registration_secret` to `username`/`secret` when unset (`api.py:45-49`).
- Mutable-default fields use `field(default_factory=...)`: `HostScanResult.open_ports: list[int] = field(default_factory=list)` (`scanner.py:25`).
- Dataclasses may still carry computed `@property` methods for derived booleans: `HostScanResult.is_alive` (`scanner.py:27-29`).

---

*Convention analysis: 2026-09-05*
