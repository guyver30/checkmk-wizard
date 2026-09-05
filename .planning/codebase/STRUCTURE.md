# Codebase Structure

**Analysis Date:** 2026-09-05

## Directory Layout

```
checkmk-wizard/
├── src/
│   └── checkmk_wizard/          # Installable package (src-layout)
│       ├── __init__.py          # Empty — package marker only
│       ├── __main__.py          # `python -m checkmk_wizard` entry point
│       ├── wizard.py            # Phase 1-7 orchestration, prompts, main()
│       ├── api.py               # Checkmk REST API client + credential bootstrap
│       ├── site.py              # Local OMD site management (subprocess `omd`)
│       ├── remote.py            # SSH-based host automation (asyncssh)
│       ├── scanner.py           # Async TCP port network scanner
│       └── livestatus.py        # Minimal Livestatus (LQL) TCP client
├── tests/                       # pytest test suite, one file per src module
│   ├── test_wizard.py
│   ├── test_api.py
│   ├── test_site.py
│   ├── test_remote.py
│   ├── test_scanner.py
│   └── test_livestatus.py
├── docs/
│   ├── CHECKMK_SETUP_CONFIGURATOR_PLAN.md   # Original design/requirements doc
│   ├── PLAN-CONFORMANCE-AUDIT.md            # Audit of implementation vs. plan
│   ├── WIZARD-OPERATION.md                  # Operational/user-facing runbook
│   ├── Podman setup for checkmk, minio, mosquitto, worker.md  # Container deployment guide
│   ├── smart/                   # Bundled smartmontools .deb packages + docs (read by wizard.py at runtime)
│   └── src/                     # Standalone Checkmk notification scripts (mqtt_notify.py, mqtt_publisher_changes.py) — NOT part of the checkmk_wizard package, deployed separately to a Checkmk site's notification scripts dir
├── .planning/
│   └── codebase/                # Codebase map documents (this directory)
├── pyproject.toml               # Package metadata, deps, `[project.scripts]` entry point
├── uv.lock                      # uv-managed lockfile
├── .python-version              # Pinned Python version for uv
├── README.md
├── PROMPT_LOG.md                 # Session prompt log (per user's global CLAUDE.md instructions)
└── config_snapshot_*.json        # Output artifacts written by Phase 7 at the repo root (gitignored/transient, not source)
```

## Directory Purposes

**`src/checkmk_wizard/`:**
- Purpose: the entire installable Python package — a src-layout single-package project (no sub-packages).
- Contains: 7 flat `.py` modules, no nested directories.
- Key files: `wizard.py` (orchestrator, by far the largest at ~1780 lines), `api.py` (~620 lines, REST client), `remote.py` (~674 lines, SSH automation).

**`tests/`:**
- Purpose: pytest test suite; one test file per source module, named `test_<module>.py`.
- Contains: `pytest`/`pytest-asyncio` async test functions, `respx` mocks for HTTP, monkeypatched `asyncssh`/`subprocess` for SSH/OMD calls.
- Key files: `test_wizard.py` (largest, ~91KB — covers every phase function), `test_api.py` (~22KB — covers every REST client method plus bootstrap flows).

**`docs/`:**
- Purpose: project design docs, an operational runbook, and bundled runtime assets (not auto-generated; hand-maintained per the user's CLAUDE.md instruction to update docs after feature changes).
- Contains: Markdown design/audit/runbook docs at the top level; `smart/` (binary `.deb` packages + supporting docs, read directly by `wizard.py` at runtime — see `_SMARTMONTOOLS_DIR` in `wizard.py:40`); `src/` (two standalone MQTT notification scripts unrelated to the wizard package, intended for manual deployment onto a Checkmk site's own notification-scripts directory, not imported by `checkmk_wizard`).

**`.planning/`:**
- Purpose: GSD-style planning/codebase-map artifacts (this document's own location), plus `.pending-auth-captures.jsonl` (untracked working file, unrelated to source code).

## Key File Locations

**Entry Points:**
- `src/checkmk_wizard/wizard.py:1778-1780`: `main()` — the `checkmk-wizard` console script target (declared in `pyproject.toml`).
- `src/checkmk_wizard/__main__.py`: `python -m checkmk_wizard` entry point, delegates to `wizard.main()`.

**Configuration:**
- `pyproject.toml`: package metadata, runtime dependencies (`asyncssh`, `httpx`, `questionary`, `rich`), dev dependencies (`pytest`, `pytest-asyncio`, `respx`), `[project.scripts]` entry point, `uv_build` build backend.
- `.python-version`: pins the Python version uv provisions (`>=3.11` per `pyproject.toml`'s `requires-python`).
- `uv.lock`: uv-managed dependency lockfile (do not hand-edit).

**Core Logic:**
- `src/checkmk_wizard/wizard.py`: all phase orchestration and interactive prompting logic.
- `src/checkmk_wizard/api.py`: all Checkmk REST API interaction.
- `src/checkmk_wizard/site.py`: all local OMD (`omd` CLI) interaction.
- `src/checkmk_wizard/remote.py`: all SSH-based remote host automation.
- `src/checkmk_wizard/scanner.py`: network discovery scanning logic.
- `src/checkmk_wizard/livestatus.py`: post-activation host-state health check.

**Testing:**
- `tests/test_*.py`: mirrors `src/checkmk_wizard/*.py` one-to-one by name (no `test_wizard/` subpackage, no fixtures directory).

## Naming Conventions

**Files:**
- One module per external-system concern, named after that system/responsibility (`site.py`, `api.py`, `remote.py`, `scanner.py`, `livestatus.py`) — lowercase, no underscores-as-separators beyond the package name itself.
- Test files: `test_<module>.py`, one-to-one with `src/checkmk_wizard/<module>.py`.

**Directories:**
- `src/<package_name>/` src-layout (not a flat top-level package) — standard for a `uv`/`hatchling`-style Python package.
- No `lib/`, `utils/`, or `common/` catch-all directories — every module maps to a specific external-system responsibility; shared helpers live inline in whichever module they logically belong to (e.g. regex validation constants live in `wizard.py` next to the prompts that use them, not in a separate `validators.py`).

**Functions:**
- Phase-level orchestration functions: `phaseN_<name>` (e.g. `phase1_site_bringup`, `phase3_discovery`) — always top-level, `async def`, called directly by `run()`.
- Private, phase-scoped helpers: leading underscore, e.g. `_onboard_hosts`, `_create_expected_open_port_rules`, `_prompt_ssh_credentials` — not exported, tested directly via `from checkmk_wizard.wizard import _helper_name` in `tests/test_wizard.py`.
- Module-level constants: `UPPER_SNAKE_CASE`, private ones prefixed `_` (e.g. `_SITE_NAME_RE`, `_DEFAULT_CPU_LOAD_LEVELS`, `DEFAULT_PORTS` in `scanner.py` is public since it's referenced from `wizard.py`).

## Where to Add New Code

**New wizard phase or sub-step:**
- Primary code: add a new `async def phaseN_<name>(...)` (or extend an existing phase) directly in `src/checkmk_wizard/wizard.py`, under a new `# ── Phase N: <Title> ──` banner comment matching the existing style; wire it into `run()` (`wizard.py:1766-1775`).
- Tests: add corresponding test functions to `tests/test_wizard.py` (no new test file — this file already covers every phase).

**New external-system integration (e.g. a new Checkmk REST endpoint, a new SSH-driven remote action):**
- Checkmk REST calls: add a method to `CheckmkClient` in `src/checkmk_wizard/api.py`, grouped under the existing `# -- Phase N: <area> --` section comments by which phase uses it.
- SSH/remote host actions: add a function to `src/checkmk_wizard/remote.py`, returning an `ActionResult(outcome, detail, manual_instructions)` to match the existing tri-state (automated/manual/failed) convention.
- Tests: `tests/test_api.py` (respx-mocked HTTP) or `tests/test_remote.py` (monkeypatched `asyncssh`), respectively.

**New validation rule or prompt-side constant:**
- Add regex/constant near the top of `wizard.py`, alongside `_SITE_NAME_RE`/`_FOLDER_NAME_RE`/`_HOST_NAME_RE`/`_HOSTNAME_RE` — document the source (live Checkmk-verified pattern vs. wizard-only stricter rule) in a comment, matching existing style.

**Utilities:**
- There is no shared `utils.py`. A genuinely cross-cutting helper (used by more than one of `wizard.py`/`api.py`/`remote.py`/`site.py`) should still be placed in whichever single module most directly owns that concern (e.g. `livestatus.py` for anything Livestatus-related) — do not introduce a new catch-all module without strong justification, per this project's existing one-module-per-concern layout.

## Special Directories

**`docs/smart/`:**
- Purpose: bundled smartmontools `.deb` packages (per supported Ubuntu release) and their accompanying install/plugin docs, read directly from disk at runtime by `wizard.py` (`_SMARTMONTOOLS_DIR`).
- Generated: No — hand-curated, versioned binary packages.
- Committed: Yes — required for the SMART-monitoring feature to work when the wizard is run via `uv run` from a checkout.

**`docs/src/`:**
- Purpose: standalone Checkmk notification scripts (MQTT publisher/notifier) meant for manual deployment to a Checkmk site's own `local/share/check_mk/notifications/` (or similar), independent of the `checkmk_wizard` package and never imported by it.
- Generated: No.
- Committed: Yes (untracked in git status as of this analysis — verify before assuming committed).

**Repo-root `config_snapshot_*.json` files:**
- Purpose: Phase 7 output artifacts (`wizard.py:1751-1760`) — a point-in-time export of the site's hosts/folders after each wizard run, written to the current working directory the wizard was invoked from.
- Generated: Yes, at the end of every completed run.
- Committed: No — these are run artifacts, not source; should not be added to version control (verify `.gitignore` coverage if these begin appearing in `git status`).

---

*Structure analysis: 2026-09-05*
