<!-- GSD:project-start source:PROJECT.md -->
## Project

**checkmk-wizard**

An interactive terminal wizard that configures a fresh Checkmk Community Edition site from scratch — network discovery, host onboarding, agent installation, and activation — running either directly on a Checkmk host or from a separate "worker" container alongside a containerized Checkmk deployment. This milestone extends the project with a live MQTT bridge and a lightweight web dashboard that visualizes the resulting Checkmk-monitored network topology and device status in real time.

**Core Value:** A single Python-based toolchain takes a bare Checkmk install all the way to a fully onboarded, monitored network — and now also to a live, at-a-glance visual picture of that network's topology and health, without needing to duplicate Checkmk's own UI.

### Constraints

- **Tech stack**: Python 3.11+, managed via `uv` (per repo convention — `uv run`/`uv add`/`uv sync`, never bare `python`/`pip`) — matches the existing wizard codebase
- **No new backend for the dashboard**: static HTML/CSS/JS only, no build step, no server-side application — state comes entirely from MQTT retained messages
- **Container boundary**: the poller/publisher must not require filesystem access to the `checkmk` container — Livestatus-over-TCP and the REST API are the only touchpoints, consistent with existing container-mode design
- **Compatibility**: new Checkmk host tag group and folder-based VLAN derivation must not break the existing 7-phase wizard flow or its tests
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- Python 3.11+ (pinned via `.python-version` = `3.11`) — entire codebase: `src/checkmk_wizard/*.py`
- None. `docs/src/mqtt_notify.py` and `docs/src/mqtt_publisher_changes.py` are reference/example Checkmk notification scripts (Python) shipped as documentation only — not part of the installable package, not covered by `pyproject.toml` dependencies, and not imported by `src/`.
## Runtime
- CPython 3.11 (`requires-python = ">=3.11"` in `pyproject.toml`)
- Uses modern syntax requiring 3.11+: `typing.Self` (`src/checkmk_wizard/api.py:14`), `datetime.UTC` (`src/checkmk_wizard/wizard.py:15`), `from __future__ import annotations` in every module
- Linux-only for the machine that hosts a Checkmk site (`omd`, `/etc/os-release` required) — the wizard itself can also run in "container mode" from a separate Linux container without `omd`
- `uv` (Astral) — build backend is `uv_build` (`pyproject.toml` `[build-system]`)
- Lockfile: `uv.lock` present (committed)
- Per repo convention (`~/.claude/CLAUDE.md`): always invoke via `uv run`, `uv add`/`uv remove`, `uv sync`/`uv lock` — never bare `python`/`pip`
## Frameworks
- None (no web framework) — this is a CLI application. Terminal UI is built with `questionary` (interactive prompts) and `rich` (console output, progress bars, tables) — see `src/checkmk_wizard/wizard.py`
- `pytest` >=9.1.1 — `tests/test_*.py`
- `pytest-asyncio` >=1.4.0 — for the codebase's `async def` functions (most of `api.py`, `remote.py`, `scanner.py`)
- `respx` >=0.23.1 — mocks `httpx` calls in `tests/test_api.py` against the Checkmk REST client
- `uv_build` >=0.12.5,<0.13.0 (PEP 517 build backend)
- `ruff` is used for linting (`.ruff_cache/` present) but has no dedicated `ruff.toml`/`[tool.ruff]` config section — runs with default rules
- No CI configuration detected (no `.github/workflows`, no `.gitlab-ci.yml`)
## Key Dependencies
- `httpx` >=0.28.1 — async HTTP client for all Checkmk REST API calls (`src/checkmk_wizard/api.py`) and GUI-session login flow (cookie-based CSRF login for bootstrapping automation users)
- `asyncssh` >=2.24.0 — async SSH client used to remotely configure firewalls and install the Checkmk agent on Linux targets (`src/checkmk_wizard/remote.py`)
- `questionary` >=2.1.1 — interactive terminal prompts (site name, credentials, host selection) driving the wizard's phase flow (`src/checkmk_wizard/wizard.py`)
- `rich` >=15.0.0 — console rendering: tables, progress bars, colored output (`src/checkmk_wizard/wizard.py`)
- Standard library `socket` — raw TCP client for the Livestatus LQL text protocol (`src/checkmk_wizard/livestatus.py`), and for the async TCP-connect network scanner (`src/checkmk_wizard/scanner.py`, via `asyncio.open_connection`)
- Standard library `subprocess` — drives the local `omd` CLI (`create`/`start`/`config`/`status`/`restart`/`rm`) for OMD site lifecycle management (`src/checkmk_wizard/site.py`)
- Standard library `ast` — parses Checkmk's WATO `hosts.mk` config files as literal Python ASTs to extract host attributes without executing them (`src/checkmk_wizard/site.py:_parse_host_attributes`)
## Configuration
- `CMK_SITE_ID` — optional; pre-fills the site-name prompt in container mode (`src/checkmk_wizard/wizard.py:290`)
- `CMK_PASSWORD` — referenced only in comments/docs as the credential a Checkmk container's own entrypoint sets; the wizard prompts for the equivalent `cmkadmin` password interactively rather than reading this env var directly (`src/checkmk_wizard/wizard.py:273,384`)
- No `.env` file present in the repo; no dotenv loading library used
- No config files (YAML/TOML/JSON) read at runtime — all configuration is interactive (via `questionary` prompts) or read from the local OMD site filesystem (`/omd/sites/<site>/...`)
- `pyproject.toml` — project metadata, dependencies, dependency groups (`dev`), console script entry point (`checkmk-wizard = "checkmk_wizard.wizard:main"`)
- `uv.lock` — resolved dependency lockfile
## Platform Requirements
- Linux (host-native mode requires `omd`, `/etc/os-release`; no Windows/macOS support for the machine running the wizard)
- Python 3.11+, `uv` installed
- Root privileges required for host-native site creation/deletion (`omd create`/`omd rm` run as root, not via `omd su <site>`)
- Two deployment modes, auto-detected by presence of `omd` on `PATH`:
- Target Checkmk version verified against: Community Edition 2.4.0p35 (referenced throughout `src/checkmk_wizard/api.py` and `site.py` docstrings as the live-verification baseline)
- No package distribution/publishing configured — run via `uv run` from a repo checkout (comment in `src/checkmk_wizard/wizard.py:36-38` notes bundled smartmontools `.deb` assets are located relative to the repo checkout, not an installed wheel)
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Naming Patterns
- One module per pipeline concern, named after its domain, not its phase: `src/checkmk_wizard/api.py` (REST client), `src/checkmk_wizard/site.py` (OMD/site shell-outs), `src/checkmk_wizard/remote.py` (SSH/agent automation), `src/checkmk_wizard/scanner.py` (async TCP port scanner), `src/checkmk_wizard/livestatus.py` (Livestatus TCP client), `src/checkmk_wizard/wizard.py` (interactive orchestration of all phases).
- Test files mirror source files 1:1: `tests/test_api.py`, `tests/test_site.py`, `tests/test_remote.py`, `tests/test_scanner.py`, `tests/test_livestatus.py`, `tests/test_wizard.py`. No `conftest.py` exists — shared fixtures/helpers are defined per-file instead (e.g. `_mock_no_ssh_and_skip_services` in `tests/test_wizard.py:67`).
- `snake_case` throughout, no exceptions.
- Module-private helpers prefixed with a single underscore: `_request`, `_gui_login` (`src/checkmk_wizard/api.py:79,289`); `_probe_port`, `_valid_checkmk_host`, `_password_problems`, `_prompt_new_site_name` (`src/checkmk_wizard/scanner.py:32`, `src/checkmk_wizard/wizard.py:88,123`). These are still imported directly by tests (e.g. `tests/test_wizard.py:20-61` imports two dozen underscore-prefixed names) — leading underscore signals "internal to the package", not "untestable".
- Phase entry points in `wizard.py` are named `phaseN_<name>`: `phase1_site_bringup`, `phase2_folders`, `phase3_discovery`, `phase4_classification`, `phase5_onboarding`, `phase6_discovery` (`src/checkmk_wizard/wizard.py`, imported in `tests/test_wizard.py:55-60`).
- Boolean-returning functions read as predicates: `omd_installed()`, `site_exists()`, `livestatus_tcp_enabled()`, `site_running()`, `agent_status_shows_connection()` (`src/checkmk_wizard/site.py:45,54,117,128`, `src/checkmk_wizard/remote.py`).
- `snake_case` for locals and parameters; module-level constants are `UPPER_SNAKE_CASE`: `DEFAULT_PORTS`, `DEFAULT_TIMEOUT`, `DEFAULT_CONCURRENCY` (`src/checkmk_wizard/scanner.py:17-19`), `AGENT_RECEIVER_PORT` (`src/checkmk_wizard/remote.py:31`), `DEFAULT_PORT` (`src/checkmk_wizard/livestatus.py:15`).
- Compiled regexes are module-level constants named `_XXX_RE`: `_CSRF_TOKEN_RE` (`src/checkmk_wizard/api.py:286`), `_SITE_NAME_RE`, `_FOLDER_NAME_RE`, `_HOST_NAME_RE`, `_HOSTNAME_RE` (`src/checkmk_wizard/wizard.py:63,72,77,83`).
- Test constants that stand in for fixtures are hoisted to module scope in ALL_CAPS: `CONN`, `BASE`, `LOGIN_URL`, `LOGIN_PAGE_HTML` (`tests/test_api.py:18-21`).
- `PascalCase` for classes and dataclasses: `CheckmkConnection`, `CheckmkClient`, `CheckmkAPIError` (`src/checkmk_wizard/api.py`); `HostScanResult` (`src/checkmk_wizard/scanner.py:22`); `SSHCredentials`, `PortProbeResult`, `ActionResult`, `OSRelease`, `CompatibilityCheck`, `AgentStatusCheck` (`src/checkmk_wizard/remote.py`); `SiteCredentials` (`src/checkmk_wizard/site.py:26`); `ScannedHost`, `OnboardedHost` (`src/checkmk_wizard/wizard.py:139,146`).
- Enums subclass `str, Enum` so values compare/serialize as plain strings: `class Outcome(str, Enum)` (`src/checkmk_wizard/remote.py:34`).
- Custom exceptions subclass the closest built-in and end in `Error`: `CheckmkAPIError(RuntimeError)` (`src/checkmk_wizard/api.py:19`), `SiteBootstrapError(RuntimeError)` (`src/checkmk_wizard/site.py:21`).
## Code Style
- No `.prettierrc`/formatter config file found; no `black`/`ruff format` section in `pyproject.toml`. A `.ruff_cache/` directory exists (evidence `ruff` is run, likely via `uvx ruff check` per the linting default) but no `[tool.ruff]` section is committed to `pyproject.toml` — ruff runs with its own defaults (line length 88, double quotes).
- Observed style is consistent with ruff/black defaults: double-quoted strings throughout, trailing commas in multi-line calls, 4-space indentation.
- Every module starts with `from __future__ import annotations` (`src/checkmk_wizard/api.py:8`, `site.py:12`, `scanner.py:10`, `livestatus.py:11`, `remote.py:21`, `wizard.py:5`) — enables `X | None` union syntax and forward references under Python 3.11's runtime, and is required before it for classes referencing themselves (e.g. `OSRelease.parse(cls) -> OSRelease` in `src/checkmk_wizard/remote.py:73`).
- Long lines wrap function signatures one-parameter-per-line when they exceed ~100 chars; short calls stay on one line (see `create_folder`/`create_host` in `src/checkmk_wizard/api.py:125-137,168-182`).
- `.ruff_cache/0.16.4/` confirms ruff 0.16.4 is the linter in use, run with default rule set (no project-level rule overrides found).
- `python-version` pinned via `.python-version` (contents: `3.11`-family) and `requires-python = ">=3.11"` in `pyproject.toml:9`.
## Import Organization
## Error Handling
- One error type per subsystem, both wrapping enough context to act on: `CheckmkAPIError(method, url, status_code, body)` (`src/checkmk_wizard/api.py:19-27`) and `SiteBootstrapError(RuntimeError)` (`src/checkmk_wizard/site.py:21-22`), the latter carrying combined `stdout`+`stderr` text in its message rather than structured fields.
- All HTTP calls funnel through one choke point — `CheckmkClient._request()` (`src/checkmk_wizard/api.py:79-115`) — so every network failure (including raw `httpx.HTTPError`/`ConnectError`) is normalized into `CheckmkAPIError` exactly once; call sites never need their own try/except for connectivity. New `CheckmkClient` methods should be added by calling `self._request(...)`, not `self._client.request(...)` directly, to preserve this guarantee.
- Functions that shell out (`subprocess.run(..., check=False)`) always pass `check=False` explicitly and inspect `returncode` themselves, because `omd`'s exit codes are non-standard (e.g. `omd start` returns 2 on an already-running site, which is not a failure — `src/checkmk_wizard/site.py:101-114`). Raising is done by hand: `if result.returncode != 0: raise SiteBootstrapError(...)`. When a false-positive nonzero code is possible, the raise condition additionally greps the captured stdout for the literal word `"failed"` (`site.py:112,161`) rather than trusting the exit code alone.
- "Best-effort" operations that must never abort the caller's flow catch broadly and swallow: `except httpx.HTTPError: pass` around the post-bootstrap activation poll in `bootstrap_automation_user()` (`src/checkmk_wizard/api.py:458-459`) — always accompanied by a comment explaining why swallowing is safe here specifically, not applied as a blanket habit.
- Narrow except clauses elsewhere: `except (TimeoutError, OSError)` to distinguish real network conditions (`src/checkmk_wizard/scanner.py:38`, `src/checkmk_wizard/remote.py:168`), `except ValueError` when a `.json()` parse may fail and should fall back to raw text (`api.py:111-113,394-396`).
- `raise X from exc` is used whenever an exception is translated from a lower-level one, preserving the original traceback (`api.py:108,399,544,620`).
- Domain validation returns lists of human-readable problem strings instead of raising, so callers can display every issue at once: `_password_problems(pw, username) -> list[str]` (`src/checkmk_wizard/wizard.py:123-136`).
## Comments
- Every non-obvious behavior is documented with *why*, frequently citing a live-verification source: "Live-verified against a real Checkmk 2.4.0p35 CE site: ..." (`src/checkmk_wizard/api.py:204-206`) or a context7 doc citation ("verified via context7: docs.checkmk.com/..." — `src/checkmk_wizard/scanner.py:3-7`, `src/checkmk_wizard/remote.py:5-18`). New code that depends on undocumented/reverse-engineered API or CLI behavior should cite how it was verified (live test, source file read, or docs URL) the same way.
- Bug-fix commits leave a dated post-mortem comment at the fix site explaining the old broken behavior and why the new approach avoids the whole class of bug, not just the symptom: `_parse_host_attributes()`'s AST-based rewrite explicitly describes the previous greedy-regex bug it replaced (`src/checkmk_wizard/site.py:191-202`, "Bug fixed 2026-08-27").
- Regression tests get an explanatory comment naming the real bug they guard against, not just a description of the assertion: `test_delete_site_choice_value_survives_as_sentinel` (`tests/test_wizard.py:80-92`).
- Best-effort/fallback code explicitly states the fallback contract in a docstring line ("this is best-effort; the caller should treat a failure here as 'fall back to the existing manual instructions', never as fatal" — `src/checkmk_wizard/api.py:353-356`).
- Every public module has a module-level docstring stating its phase/purpose and citing verification sources (`site.py:1-10`, `scanner.py:1-8`, `livestatus.py:1-9`, `remote.py:1-19`, `wizard.py:1-3`).
- Public functions with non-trivial behavior get a docstring explaining *why* they exist and *why* the implementation looks the way it does — not just parameter descriptions (`bootstrap_automation_user()` in `api.py:324-357` is the densest example: rationale, verification method, failure contract, all in prose). Trivial one-liners (`site_home`, `site_exists`) have no docstring at all.
- No formal docstring format (no Google/NumPy/Sphinx style enforced) — plain prose paragraphs, sometimes with inline backtick-quoted identifiers.
## Function Design
## Module Design
## Dataclass Conventions
- `@dataclass` is the default modeling tool for structured data, used pervasively instead of `TypedDict`, `NamedTuple`, or Pydantic (no Pydantic dependency exists): `CheckmkConnection`, `HostScanResult`, `SSHCredentials`, `PortProbeResult`, `ActionResult`, `OSRelease`, `CompatibilityCheck`, `AgentStatusCheck`, `SiteCredentials`, `ScannedHost`, `OnboardedHost`.
- Post-init defaulting logic goes in `__post_init__`, not the field default itself, when one field's default depends on another field's value: `CheckmkConnection.__post_init__` defaults `registration_user`/`registration_secret` to `username`/`secret` when unset (`api.py:45-49`).
- Mutable-default fields use `field(default_factory=...)`: `HostScanResult.open_ports: list[int] = field(default_factory=list)` (`scanner.py:25`).
- Dataclasses may still carry computed `@property` methods for derived booleans: `HostScanResult.is_alive` (`scanner.py:27-29`).
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## System Overview
```text
```
## Component Responsibilities
| Component | Responsibility | File |
|-----------|----------------|------|
| Wizard orchestration | 7-phase interactive flow, prompts, in-memory state, snapshot export | `src/checkmk_wizard/wizard.py` |
| Checkmk REST client | Typed async wrapper over Checkmk's v1 REST API; bootstrap helpers for automation users/passwords via GUI-session login | `src/checkmk_wizard/api.py` |
| OMD site management | Local `omd` CLI subprocess wrapper (create/start/stop/delete site, read automation secrets, parse `hosts.mk`) | `src/checkmk_wizard/site.py` |
| Remote host automation | SSH-based (asyncssh) firewall fix, agent install/registration, systemd discovery, smartmontools install — Linux only; Windows produces manual instructions | `src/checkmk_wizard/remote.py` |
| Network scanner | Bounded-concurrency asyncio TCP-connect sweep across a CIDR (chunked into /24s) | `src/checkmk_wizard/scanner.py` |
| Health check client | Minimal hand-rolled Livestatus (LQL) TCP client for post-activation host-state query | `src/checkmk_wizard/livestatus.py` |
| CLI entry point | Thin `__main__` shim calling `wizard.main()` | `src/checkmk_wizard/__main__.py` |
## Pattern Overview
- Fully async (`asyncio`), using `async/await` throughout for I/O (HTTP via httpx, SSH via asyncssh, raw sockets for scanning/Livestatus).
- State is a few plain `@dataclass` objects threaded explicitly between phase functions (`CheckmkConnection`, `ScannedHost`, `OnboardedHost`, `WizardState`) — no global mutable session object, no ORM, no persistence layer beyond a final JSON snapshot file.
- Each external system boundary (OMD CLI, Checkmk REST API, SSH, TCP scanning, Livestatus) is isolated in its own single-purpose module with no cross-imports between those modules themselves — only `wizard.py` imports and composes all of them.
- Best-effort/graceful-degradation is a first-class design goal: nearly every external call site wraps failures (`except CheckmkAPIError`) and prints a warning instead of aborting, so one host's or one rule's failure doesn't halt the whole run. Contrast this with the phase-level driver (`run()`), which does not wrap phase failures — an unhandled exception in a phase aborts the whole run.
- Heavy inline documentation of *why*, not just *what* — most non-trivial functions carry paragraph-length docstrings/comments recording live-verified Checkmk REST API behavior, since this project treats Checkmk's actual server behavior (not just its docs) as the source of truth. New code should preserve this style: cite what was verified and how.
## Layers
- Purpose: prompts (`questionary`), progress bars/tables (`rich`), all user-facing text.
- Location: `src/checkmk_wizard/wizard.py` (prompt helper functions like `_prompt_new_site_name`, `_prompt_ssh_credentials`, `_prompt_threshold_levels`).
- Contains: `questionary.*` calls, `console.print`/`console.rule`, `rich.table.Table`/`rich.progress.Progress` usage.
- Depends on: the orchestration layer below it for what to prompt about.
- Used by: nothing above it — this is the outermost layer (terminal).
- Purpose: sequence the 7 phases, decide branching (container mode vs. host mode, SSH vs. manual, snmp/ping/linux/windows), build the dataclasses passed between phases.
- Location: `src/checkmk_wizard/wizard.py` (`phase1_site_bringup` ... `phase7_activation`, `run()`, `main()`).
- Contains: `async def phaseN_*` functions, private helpers prefixed `_` scoped to a phase (e.g. `_onboard_hosts`, `_create_expected_open_port_rules`).
- Depends on: `api.py`, `site.py`, `remote.py`, `scanner.py`, `livestatus.py`.
- Used by: `__main__.py` only (via `main()`).
- Purpose: talk to one external system each, translating its protocol into typed Python calls/dataclasses/exceptions.
- Location: `api.py` (Checkmk REST), `site.py` (`omd` subprocess), `remote.py` (SSH/asyncssh), `scanner.py` (raw asyncio sockets), `livestatus.py` (raw TCP/LQL).
- Contains: dataclasses for request/response shapes, `async def` (or sync for `site.py`, which shells out) functions, module-specific exception types (`CheckmkAPIError`, `SiteBootstrapError`).
- Depends on: `httpx` (api.py), `asyncssh` (remote.py), `subprocess`/`ast` (site.py), stdlib `asyncio`/`socket` (scanner.py, livestatus.py).
- Used by: `wizard.py` exclusively — these modules never import each other or `wizard.py`.
## Data Flow
### Primary Request Path (one wizard run)
### Secondary Flow: Best-Effort Bootstrap of REST Credentials
- No global session/singleton state. All cross-phase state is explicit dataclasses (`WizardState` is defined but the phases actually thread individual lists/objects directly rather than a single `WizardState` instance — `WizardState` exists as a documented shape but `run()` itself doesn't instantiate it).
- Long-lived resources (the `CheckmkClient`'s `httpx.AsyncClient`) are scoped with `async with` for the lifetime of `run()`.
- The only on-disk state the wizard itself writes is the final JSON snapshot (`config_snapshot_*.json`) — everything else is read live from Checkmk (REST/Livestatus) or the OMD filesystem (`site.py`) each run.
## Key Abstractions
- Purpose: represent one discrete stage of the setup pipeline; each is independently readable top-to-bottom and callable in tests.
- Examples: `phase1_site_bringup`, `phase2_folders`, `phase3_discovery`, `phase4_classification`, `phase5_onboarding`, `phase6_discovery`, `phase7_activation` (all in `wizard.py`).
- Pattern: `async def phaseN_name(...) -> <next-phase's input>`, printed under `console.rule("[bold]Phase N — ...")`.
- Purpose: typed, serializable-by-`__dict__` records passed between phases instead of dicts.
- Examples: `ScannedHost`, `OnboardedHost`, `WizardState` (`wizard.py:139-166`); `CheckmkConnection` (`api.py:30-49`); `SiteCredentials` (`site.py:25-29`); `SSHCredentials`, `ActionResult`, `OSRelease`, `CompatibilityCheck`, `AgentStatusCheck`, `PortProbeResult` (`remote.py`); `HostScanResult` (`scanner.py`).
- Pattern: plain `@dataclass`, no methods beyond the occasional `@property` (e.g. `CheckmkConnection.base_url`, `HostScanResult.is_alive`) or `__post_init__` default-filling (`CheckmkConnection.__post_init__`).
- Purpose: classify every SSH-automated step (firewall fix, agent install, smartmontools) into one of three uniform outcomes so `wizard.py` can render consistent status/color regardless of which step ran.
- Examples: `remote.Outcome.AUTOMATED` / `MANUAL_REQUIRED` / `FAILED_FALLBACK_MANUAL` (`remote.py:34-37`), returned inside every `ActionResult`.
- Pattern: every `remote.py` action function returns an `ActionResult(outcome, detail, manual_instructions)` regardless of success/failure, letting the caller print uniformly instead of branching on exception types.
- Purpose: every REST call funnels through one private method so error handling (turning `httpx.HTTPError`/non-2xx responses into `CheckmkAPIError`) is defined exactly once.
- Location: `api.py:79-115`.
- Pattern: public methods (`create_host`, `create_folder`, `create_rule`, etc.) are thin wrappers that just build the path/body and call `self._request(...)`.
## Entry Points
- Location: declared in `pyproject.toml` (`[project.scripts] checkmk-wizard = "checkmk_wizard.wizard:main"`), implemented at `src/checkmk_wizard/wizard.py:1778-1780`.
- Triggers: operator runs `uv run checkmk-wizard` (or the installed console script) in an interactive terminal.
- Responsibilities: starts the asyncio event loop and runs the full 7-phase pipeline (`run()`).
- Location: `src/checkmk_wizard/__main__.py`.
- Triggers: `python -m checkmk_wizard` / `uv run python -m checkmk_wizard`.
- Responsibilities: identical to the console script — imports and calls `wizard.main()`.
## Architectural Constraints
- **Threading:** Single-threaded asyncio event loop throughout (`asyncio.run(run())`); no worker threads, no multiprocessing. Concurrency within a phase is cooperative (`asyncio.gather`, `asyncio.Semaphore` in `scanner.py` to bound TCP-connect fan-out to `DEFAULT_CONCURRENCY = 256`).
- **Global state:** Module-level singletons are limited to a shared `rich.console.Console()` instance (`wizard.py:35`, `console = Console()`) and a handful of compiled regex/constant tables (`_SITE_NAME_RE`, `_HOST_NAME_RE`, `_FOLDER_NAME_RE`, `_HOSTNAME_RE`, `_DEFAULT_*_LEVELS` threshold tuples) — none of these are mutated at runtime.
- **Local filesystem/OS coupling:** `site.py` assumes it may be running directly on the Checkmk host (shells out to `omd`, reads `/omd/sites/<site>/...` directly) — the wizard branches into a distinct "container mode" (`wizard.py:274` `site.omd_installed()` check) when `omd` isn't on PATH, skipping local-only operations (site create/delete, local secret-file reads) in favor of REST-only bootstrap paths.
- **Bundled binary assets:** Linux SMART-monitoring support requires `.deb` packages checked into `docs/smart/` (read via `_SMARTMONTOOLS_DIR = Path(__file__).resolve().parents[2] / "docs" / "smart"`, `wizard.py:40`) — this only resolves correctly when running from a source checkout (`uv run`), not from an installed wheel, and is scoped to specific Ubuntu releases (`remote.py:118-122`, `_SMARTMONTOOLS_DEB_BY_UBUNTU_VERSION`).
- **No test-time network/SSH:** All external I/O in tests is mocked (`respx` for httpx, monkeypatched `asyncssh.connect`/`subprocess.run`) — there is no integration test suite that talks to a live Checkmk site or real SSH host.
## Anti-Patterns
### Cross-cutting `except CheckmkAPIError` without differentiating error classes
### Long single-file phase orchestrator
## Error Handling
- Module-specific exception types: `CheckmkAPIError` (`api.py:19-27`, carries `method`/`url`/`status_code`/`body`) and `SiteBootstrapError` (`site.py:21-22`, plain `RuntimeError` subclass wrapping `omd` stdout+stderr).
- `ActionResult`/`Outcome` in `remote.py` represents *degraded success* (falls back to manual instructions) as a normal return value, not an exception — SSH/remote failures are expected and routed to a uniform "automated / manual_required / failed_fallback_manual" tri-state rather than raised.
- Best-effort helpers (`bootstrap_automation_user`, `bootstrap_agent_registration_secret`) document explicitly in their docstrings that callers must treat failure as "fall back to manual instructions, never fatal."
- Retry loops (bounded, not infinite) are used where a transient timing issue is expected: `_DISCOVERY_RETRY_DELAYS_SECONDS = (10, 20, 30)` in Phase 6 (`wizard.py:1590`) for a freshly-registered agent's first data push.
## Cross-Cutting Concerns
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
