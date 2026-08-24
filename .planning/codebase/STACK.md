# Technology Stack

**Analysis Date:** 2026-08-24

## Languages

**Primary:**
- Python 3.11+ - Core application language; single-platform CLI tool for Checkmk site automation

## Runtime

**Environment:**
- Python 3.11 (specified in `.python-version`)
- Unix/Linux only (OMD sites are Linux-based; SFTP and UNIX socket access required)

**Package Manager:**
- uv - Modern Python package manager with fast resolution and lockfile support
- Lockfile: `uv.lock` (committed; comprehensive dependency pinning for reproducibility)

## Frameworks

**Core:**
- asyncio (stdlib) - Asynchronous concurrency for HTTP, SSH, TCP scanning, and SFTP operations

**CLI/UI:**
- questionary 2.1.1+ - Interactive terminal prompts and user input (confirmation dialogs, text input, multiple choice, password input)
- rich 15.0.0+ - Terminal output formatting, progress bars, styled tables, and colored console output

**HTTP:**
- httpx 0.28.1+ - Async HTTP client for Checkmk REST API v1 communication

**SSH/Remote:**
- asyncssh 2.24.0+ - Async SSH client for remote Linux host automation (firewall configuration, agent installation, OS detection)

**Testing:**
- pytest 9.1.1+ - Test runner and assertion framework
- pytest-asyncio 1.4.0+ - Async test support (fixtures and markers)
- respx 0.23.1+ - HTTP mock library for mocking httpx requests in tests

## Key Dependencies

**Critical:**
- asyncssh 2.24.0+ - Provides async SSH/SFTP for Phase 5 host automation; no alternative SSH library in use
- httpx 0.28.1+ - Sole HTTP client for Checkmk REST API communication; async-first design required by the application's async/await architecture
- questionary 2.1.1+ - Enables interactive wizard UI; replacing it would require rewriting the entire CLI interaction flow
- rich 15.0.0+ - Provides styled terminal output (progress bars, tables) for wizard feedback

**Infrastructure:**
- asyncio (stdlib) - No third-party async runtime (no Twisted, no gevent); pure asyncio architecture
- subprocess (stdlib) - Invokes local `omd` CLI commands for site bootstrap (Phase 1)
- socket (stdlib) - Raw UNIX socket client for Livestatus queries (Phase 7 health checks)
- ipaddress (stdlib) - IPv4 CIDR parsing and subnet manipulation for network scanning (Phase 3)

## Configuration

**Environment:**
- Application reads from local filesystem only (no env vars required for runtime)
- Phase 1 reads site secrets from: `/omd/sites/{site}/var/check_mk/web/automation/automation.secret`
- Phase 7 queries Livestatus socket at: `/omd/sites/{site}/tmp/run/live`

**Build:**
- `pyproject.toml` - Single Python project manifest (dependencies, scripts, version, author)
- Build backend: `uv_build` (specified in `[build-system]` as exclusive backend)
- Entry point: `checkmk-wizard = "checkmk_wizard.wizard:main"` (CLI script installed via `uv sync`)

## Platform Requirements

**Development:**
- Python 3.11+ installed
- `uv` package manager
- Local Checkmk Community Edition instance (optional; tests mock APIs)

**Production:**
- Python 3.11+ runtime
- Linux/Unix OS (OMD sites are Linux-only; SFTP and UNIX sockets required)
- Local filesystem access to `/omd/sites/` and local `omd` CLI binary
- SSH connectivity to target hosts (for Phase 5 automation)
- Network access to Checkmk host's REST API endpoint

---

*Stack analysis: 2026-08-24*
