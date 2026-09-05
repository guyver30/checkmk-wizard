# Technology Stack

**Analysis Date:** 2026-09-05

## Languages

**Primary:**
- Python 3.11+ (pinned via `.python-version` = `3.11`) — entire codebase: `src/checkmk_wizard/*.py`

**Secondary:**
- None. `docs/src/mqtt_notify.py` and `docs/src/mqtt_publisher_changes.py` are reference/example Checkmk notification scripts (Python) shipped as documentation only — not part of the installable package, not covered by `pyproject.toml` dependencies, and not imported by `src/`.

## Runtime

**Environment:**
- CPython 3.11 (`requires-python = ">=3.11"` in `pyproject.toml`)
- Uses modern syntax requiring 3.11+: `typing.Self` (`src/checkmk_wizard/api.py:14`), `datetime.UTC` (`src/checkmk_wizard/wizard.py:15`), `from __future__ import annotations` in every module
- Linux-only for the machine that hosts a Checkmk site (`omd`, `/etc/os-release` required) — the wizard itself can also run in "container mode" from a separate Linux container without `omd`

**Package Manager:**
- `uv` (Astral) — build backend is `uv_build` (`pyproject.toml` `[build-system]`)
- Lockfile: `uv.lock` present (committed)
- Per repo convention (`~/.claude/CLAUDE.md`): always invoke via `uv run`, `uv add`/`uv remove`, `uv sync`/`uv lock` — never bare `python`/`pip`

## Frameworks

**Core:**
- None (no web framework) — this is a CLI application. Terminal UI is built with `questionary` (interactive prompts) and `rich` (console output, progress bars, tables) — see `src/checkmk_wizard/wizard.py`

**Testing:**
- `pytest` >=9.1.1 — `tests/test_*.py`
- `pytest-asyncio` >=1.4.0 — for the codebase's `async def` functions (most of `api.py`, `remote.py`, `scanner.py`)
- `respx` >=0.23.1 — mocks `httpx` calls in `tests/test_api.py` against the Checkmk REST client

**Build/Dev:**
- `uv_build` >=0.12.5,<0.13.0 (PEP 517 build backend)
- `ruff` is used for linting (`.ruff_cache/` present) but has no dedicated `ruff.toml`/`[tool.ruff]` config section — runs with default rules
- No CI configuration detected (no `.github/workflows`, no `.gitlab-ci.yml`)

## Key Dependencies

**Critical:**
- `httpx` >=0.28.1 — async HTTP client for all Checkmk REST API calls (`src/checkmk_wizard/api.py`) and GUI-session login flow (cookie-based CSRF login for bootstrapping automation users)
- `asyncssh` >=2.24.0 — async SSH client used to remotely configure firewalls and install the Checkmk agent on Linux targets (`src/checkmk_wizard/remote.py`)
- `questionary` >=2.1.1 — interactive terminal prompts (site name, credentials, host selection) driving the wizard's phase flow (`src/checkmk_wizard/wizard.py`)
- `rich` >=15.0.0 — console rendering: tables, progress bars, colored output (`src/checkmk_wizard/wizard.py`)

**Infrastructure:**
- Standard library `socket` — raw TCP client for the Livestatus LQL text protocol (`src/checkmk_wizard/livestatus.py`), and for the async TCP-connect network scanner (`src/checkmk_wizard/scanner.py`, via `asyncio.open_connection`)
- Standard library `subprocess` — drives the local `omd` CLI (`create`/`start`/`config`/`status`/`restart`/`rm`) for OMD site lifecycle management (`src/checkmk_wizard/site.py`)
- Standard library `ast` — parses Checkmk's WATO `hosts.mk` config files as literal Python ASTs to extract host attributes without executing them (`src/checkmk_wizard/site.py:_parse_host_attributes`)

## Configuration

**Environment:**
- `CMK_SITE_ID` — optional; pre-fills the site-name prompt in container mode (`src/checkmk_wizard/wizard.py:290`)
- `CMK_PASSWORD` — referenced only in comments/docs as the credential a Checkmk container's own entrypoint sets; the wizard prompts for the equivalent `cmkadmin` password interactively rather than reading this env var directly (`src/checkmk_wizard/wizard.py:273,384`)
- No `.env` file present in the repo; no dotenv loading library used
- No config files (YAML/TOML/JSON) read at runtime — all configuration is interactive (via `questionary` prompts) or read from the local OMD site filesystem (`/omd/sites/<site>/...`)

**Build:**
- `pyproject.toml` — project metadata, dependencies, dependency groups (`dev`), console script entry point (`checkmk-wizard = "checkmk_wizard.wizard:main"`)
- `uv.lock` — resolved dependency lockfile

## Platform Requirements

**Development:**
- Linux (host-native mode requires `omd`, `/etc/os-release`; no Windows/macOS support for the machine running the wizard)
- Python 3.11+, `uv` installed
- Root privileges required for host-native site creation/deletion (`omd create`/`omd rm` run as root, not via `omd su <site>`)

**Production:**
- Two deployment modes, auto-detected by presence of `omd` on `PATH`:
  - **Host-native mode**: runs directly on the Checkmk site's host as root
  - **Container mode**: runs in a separate container (e.g. a "worker" container per `docs/Podman setup for checkmk, minio, mosquitto, worker.md`) alongside a containerized Checkmk instance, communicating purely over the Checkmk REST API and Livestatus-over-TCP (port 6557)
- Target Checkmk version verified against: Community Edition 2.4.0p35 (referenced throughout `src/checkmk_wizard/api.py` and `site.py` docstrings as the live-verification baseline)
- No package distribution/publishing configured — run via `uv run` from a repo checkout (comment in `src/checkmk_wizard/wizard.py:36-38` notes bundled smartmontools `.deb` assets are located relative to the repo checkout, not an installed wheel)

---

*Stack analysis: 2026-09-05*
