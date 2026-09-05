<!-- refreshed: 2026-09-05 -->
# Architecture

**Analysis Date:** 2026-09-05

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────┐
│                     Interactive Terminal Wizard                      │
│                  `src/checkmk_wizard/wizard.py`                      │
│   Phase 1..7 orchestration, questionary prompts, rich console I/O    │
└───────┬───────────┬────────────┬────────────┬────────────┬──────────┘
        │            │            │            │            │
        ▼            ▼            ▼            ▼            ▼
┌───────────┐ ┌─────────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐
│  site.py  │ │   api.py    │ │remote.py │ │scanner.py│ │livestatus. │
│ omd CLI   │ │ Checkmk     │ │ SSH host │ │ async TCP│ │py — TCP    │
│ subprocess│ │ REST client │ │ automation│ │ port scan│ │ LQL client │
└─────┬─────┘ └──────┬──────┘ └────┬─────┘ └────┬─────┘ └─────┬──────┘
      │              │              │            │             │
      ▼              ▼              ▼            ▼             ▼
┌──────────┐  ┌──────────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐
│  omd CLI │  │ Checkmk REST │ │ SSH/     │ │ raw TCP  │ │ Livestatus  │
│  (local  │  │ API (httpx)  │ │ asyncssh │ │ connect  │ │ TCP socket  │
│  host)   │  │ over HTTP    │ │ to target│ │ sweep    │ │ (site:6557) │
│          │  │ site         │ │ hosts    │ │          │ │             │
└──────────┘  └──────────────┘ └──────────┘ └──────────┘ └─────────────┘
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

**Overall:** Single-process **scripted pipeline / procedural phase orchestrator** — not a layered web app. There is no persistent server, database, or HTTP API of its own; the tool is a stateful CLI script that drives an *external* system (a Checkmk OMD site) to a desired configuration end-state through a sequence of named phases (Phase 1 through Phase 7), each an `async def phaseN_xxx(...)` function in `wizard.py`.

**Key Characteristics:**
- Fully async (`asyncio`), using `async/await` throughout for I/O (HTTP via httpx, SSH via asyncssh, raw sockets for scanning/Livestatus).
- State is a few plain `@dataclass` objects threaded explicitly between phase functions (`CheckmkConnection`, `ScannedHost`, `OnboardedHost`, `WizardState`) — no global mutable session object, no ORM, no persistence layer beyond a final JSON snapshot file.
- Each external system boundary (OMD CLI, Checkmk REST API, SSH, TCP scanning, Livestatus) is isolated in its own single-purpose module with no cross-imports between those modules themselves — only `wizard.py` imports and composes all of them.
- Best-effort/graceful-degradation is a first-class design goal: nearly every external call site wraps failures (`except CheckmkAPIError`) and prints a warning instead of aborting, so one host's or one rule's failure doesn't halt the whole run. Contrast this with the phase-level driver (`run()`), which does not wrap phase failures — an unhandled exception in a phase aborts the whole run.
- Heavy inline documentation of *why*, not just *what* — most non-trivial functions carry paragraph-length docstrings/comments recording live-verified Checkmk REST API behavior, since this project treats Checkmk's actual server behavior (not just its docs) as the source of truth. New code should preserve this style: cite what was verified and how.

## Layers

**Presentation / interaction layer:**
- Purpose: prompts (`questionary`), progress bars/tables (`rich`), all user-facing text.
- Location: `src/checkmk_wizard/wizard.py` (prompt helper functions like `_prompt_new_site_name`, `_prompt_ssh_credentials`, `_prompt_threshold_levels`).
- Contains: `questionary.*` calls, `console.print`/`console.rule`, `rich.table.Table`/`rich.progress.Progress` usage.
- Depends on: the orchestration layer below it for what to prompt about.
- Used by: nothing above it — this is the outermost layer (terminal).

**Orchestration layer (phases):**
- Purpose: sequence the 7 phases, decide branching (container mode vs. host mode, SSH vs. manual, snmp/ping/linux/windows), build the dataclasses passed between phases.
- Location: `src/checkmk_wizard/wizard.py` (`phase1_site_bringup` ... `phase7_activation`, `run()`, `main()`).
- Contains: `async def phaseN_*` functions, private helpers prefixed `_` scoped to a phase (e.g. `_onboard_hosts`, `_create_expected_open_port_rules`).
- Depends on: `api.py`, `site.py`, `remote.py`, `scanner.py`, `livestatus.py`.
- Used by: `__main__.py` only (via `main()`).

**External-system client layer:**
- Purpose: talk to one external system each, translating its protocol into typed Python calls/dataclasses/exceptions.
- Location: `api.py` (Checkmk REST), `site.py` (`omd` subprocess), `remote.py` (SSH/asyncssh), `scanner.py` (raw asyncio sockets), `livestatus.py` (raw TCP/LQL).
- Contains: dataclasses for request/response shapes, `async def` (or sync for `site.py`, which shells out) functions, module-specific exception types (`CheckmkAPIError`, `SiteBootstrapError`).
- Depends on: `httpx` (api.py), `asyncssh` (remote.py), `subprocess`/`ast` (site.py), stdlib `asyncio`/`socket` (scanner.py, livestatus.py).
- Used by: `wizard.py` exclusively — these modules never import each other or `wizard.py`.

## Data Flow

### Primary Request Path (one wizard run)

1. Entry: `checkmk-wizard` console script → `checkmk_wizard.wizard:main` (`pyproject.toml` `[project.scripts]`) → `main()` → `asyncio.run(run())` (`src/checkmk_wizard/wizard.py:1778-1780`).
2. `run()` (`wizard.py:1766-1775`) calls each phase in order, holding results in local variables (`connection`, `folder_subnets`, `scan_results`, `onboarded`) — no shared mutable state object survives across phases except what's explicitly passed as arguments/return values.
3. Phase 1 (`phase1_site_bringup`, `wizard.py:265-493`): detects container vs. host mode via `site.omd_installed()`; creates/reuses an OMD site via `site.py`; bootstraps REST credentials via `api.bootstrap_automation_user`/`bootstrap_agent_registration_secret`; returns a `CheckmkConnection`.
4. `async with CheckmkClient(connection) as client:` opens the REST client for the rest of the run (`wizard.py:1768`).
5. Phase 2 (`phase2_folders`): optional folder creation + per-folder Checkmk-native network scan config via `client.create_folder`/`update_folder_attributes`.
6. Phase 3 (`phase3_discovery`): runs `scanner.scan_network()` per folder subnet, stages every found IP as an inert host via `client.create_host` (tags `no-agent`/`no-snmp`), returns `list[ScannedHost]`.
7. Phase 4 (`phase4_classification`): purely interactive promotion of scanned IPs to named `OnboardedHost` records (no network calls).
8. Phase 5 (`phase5_onboarding` → `_onboard_hosts`): per-host branch by `os_family` (snmp/ping/linux/windows) — creates/updates the real host object, and for Linux with SSH creds, drives `remote.py` functions (firewall fix, OS compatibility check, agent download via `client.download_agent` + install, registration, smartmontools). Also creates shared rules (`active_checks:tcp`, `active_checks:icmp`, discovery-selection rulesets, optional threshold rulesets) via `client.create_rule`.
9. Phase 6 (`phase6_discovery`): activates pending changes (`client.activate_changes`), then runs `client.start_service_discovery(mode="fix_all")` per host with bounded retries, verifying expected services actually became monitored.
10. Phase 7 (`phase7_activation`): re-activates pending changes, queries host state via `livestatus.query_host_states`, pulls `client.list_hosts`/`client.list_folders` and writes a `config_snapshot_<timestamp>.json` file to the working directory (`wizard.py:1751-1760`).

### Secondary Flow: Best-Effort Bootstrap of REST Credentials

1. `api.bootstrap_automation_user()` (`api.py:316-461`) logs into Checkmk's GUI session (`_gui_login`, CSRF-token scrape + POST to `login.py`) using `cmkadmin`, since no REST automation secret exists yet on a fresh site.
2. Creates the `automation` user via REST with `store_automation_secret: true`.
3. Immediately self-activates that one pending change (still authenticated as `cmkadmin`) to avoid a later "foreign changes" 401 once the wizard switches to the new automation user for all further calls — polls the activation's `is_running` flag rather than trusting the redirect-based "wait for completion" link.
4. Failure anywhere in this flow raises `CheckmkAPIError`, treated as best-effort by every caller in `wizard.py` (falls back to prompting the operator for a manually created automation secret).

**State Management:**
- No global session/singleton state. All cross-phase state is explicit dataclasses (`WizardState` is defined but the phases actually thread individual lists/objects directly rather than a single `WizardState` instance — `WizardState` exists as a documented shape but `run()` itself doesn't instantiate it).
- Long-lived resources (the `CheckmkClient`'s `httpx.AsyncClient`) are scoped with `async with` for the lifetime of `run()`.
- The only on-disk state the wizard itself writes is the final JSON snapshot (`config_snapshot_*.json`) — everything else is read live from Checkmk (REST/Livestatus) or the OMD filesystem (`site.py`) each run.

## Key Abstractions

**Phase functions (`phaseN_*`):**
- Purpose: represent one discrete stage of the setup pipeline; each is independently readable top-to-bottom and callable in tests.
- Examples: `phase1_site_bringup`, `phase2_folders`, `phase3_discovery`, `phase4_classification`, `phase5_onboarding`, `phase6_discovery`, `phase7_activation` (all in `wizard.py`).
- Pattern: `async def phaseN_name(...) -> <next-phase's input>`, printed under `console.rule("[bold]Phase N — ...")`.

**Result/state dataclasses:**
- Purpose: typed, serializable-by-`__dict__` records passed between phases instead of dicts.
- Examples: `ScannedHost`, `OnboardedHost`, `WizardState` (`wizard.py:139-166`); `CheckmkConnection` (`api.py:30-49`); `SiteCredentials` (`site.py:25-29`); `SSHCredentials`, `ActionResult`, `OSRelease`, `CompatibilityCheck`, `AgentStatusCheck`, `PortProbeResult` (`remote.py`); `HostScanResult` (`scanner.py`).
- Pattern: plain `@dataclass`, no methods beyond the occasional `@property` (e.g. `CheckmkConnection.base_url`, `HostScanResult.is_alive`) or `__post_init__` default-filling (`CheckmkConnection.__post_init__`).

**Outcome enum for remote actions:**
- Purpose: classify every SSH-automated step (firewall fix, agent install, smartmontools) into one of three uniform outcomes so `wizard.py` can render consistent status/color regardless of which step ran.
- Examples: `remote.Outcome.AUTOMATED` / `MANUAL_REQUIRED` / `FAILED_FALLBACK_MANUAL` (`remote.py:34-37`), returned inside every `ActionResult`.
- Pattern: every `remote.py` action function returns an `ActionResult(outcome, detail, manual_instructions)` regardless of success/failure, letting the caller print uniformly instead of branching on exception types.

**Single HTTP choke point (`CheckmkClient._request`):**
- Purpose: every REST call funnels through one private method so error handling (turning `httpx.HTTPError`/non-2xx responses into `CheckmkAPIError`) is defined exactly once.
- Location: `api.py:79-115`.
- Pattern: public methods (`create_host`, `create_folder`, `create_rule`, etc.) are thin wrappers that just build the path/body and call `self._request(...)`.

## Entry Points

**Console script `checkmk-wizard`:**
- Location: declared in `pyproject.toml` (`[project.scripts] checkmk-wizard = "checkmk_wizard.wizard:main"`), implemented at `src/checkmk_wizard/wizard.py:1778-1780`.
- Triggers: operator runs `uv run checkmk-wizard` (or the installed console script) in an interactive terminal.
- Responsibilities: starts the asyncio event loop and runs the full 7-phase pipeline (`run()`).

**Module execution (`python -m checkmk_wizard`):**
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

**What happens:** Nearly every phase-level call site (`wizard.py`) catches the single broad `CheckmkAPIError` and prints a yellow/red warning, whether the underlying cause was a validation error (400), a conflict (409, e.g. duplicate rule), or a network failure (status_code=0, per `api.py:79-115`'s own comment).
**Why it's wrong:** A genuine network outage (Checkmk unreachable) and "host already exists" are handled identically — the operator sees a generic warning either way and has to read the interpolated exception text to tell them apart.
**Do this instead:** This is an accepted, intentional tradeoff documented directly in `api.py`'s `_request` docstring (status_code=0 for network failures, "no call site needs to change") — when adding new call sites, follow the same pattern rather than introducing per-status-code branching, unless a specific status code needs different recovery behavior (as `_create_or_update_host` does for the create-then-fall-back-to-update case, `wizard.py:804-827`).

### Long single-file phase orchestrator

**What happens:** `wizard.py` is 1779 lines and contains all seven phases, their private helpers, and top-level validation regexes/constants in one file.
**Why it's wrong:** Locating a specific phase's logic requires searching within one large file; there is no per-phase module boundary.
**Do this instead:** This is a deliberate, documented tradeoff (see `_onboard_hosts` docstring noting it was "split out... so expected-open-port rule creation... still runs even when hosts is empty") — the project favors one file with clear `# ── Phase N ── ...` section-comment banners over splitting into `phases/phase1.py` etc. New phase-level code should follow the same section-banner convention and stay in `wizard.py` rather than introducing a new phases package, unless the user explicitly requests that refactor.

## Error Handling

**Strategy:** Two-tier — exceptions are used for genuine failures, but the *orchestration* layer converts nearly all of them into a printed warning and a fallback path (manual instructions, skip, or default) rather than aborting the run. Only unrecoverable Phase 1 failures (`SystemExit(1)` when the initial REST version check fails, `wizard.py:489-491`) actually stop the wizard.

**Patterns:**
- Module-specific exception types: `CheckmkAPIError` (`api.py:19-27`, carries `method`/`url`/`status_code`/`body`) and `SiteBootstrapError` (`site.py:21-22`, plain `RuntimeError` subclass wrapping `omd` stdout+stderr).
- `ActionResult`/`Outcome` in `remote.py` represents *degraded success* (falls back to manual instructions) as a normal return value, not an exception — SSH/remote failures are expected and routed to a uniform "automated / manual_required / failed_fallback_manual" tri-state rather than raised.
- Best-effort helpers (`bootstrap_automation_user`, `bootstrap_agent_registration_secret`) document explicitly in their docstrings that callers must treat failure as "fall back to manual instructions, never fatal."
- Retry loops (bounded, not infinite) are used where a transient timing issue is expected: `_DISCOVERY_RETRY_DELAYS_SECONDS = (10, 20, 30)` in Phase 6 (`wizard.py:1590`) for a freshly-registered agent's first data push.

## Cross-Cutting Concerns

**Logging:** No logging framework — all user-facing output goes through the shared `rich.console.Console` (`console.print`/`console.rule`/`Table`/`Progress`), color-coded by severity (green=success, yellow=warning/degraded, red=failure). There is no separate log file or structured log output.

**Validation:** Input validation is inline, per-prompt, in `wizard.py` using compiled regexes matched directly against Checkmk's own live-verified REST field patterns (`_SITE_NAME_RE`, `_FOLDER_NAME_RE`, `_HOST_NAME_RE`, `_HOSTNAME_RE`) plus small helper functions (`_valid_checkmk_host`, `_password_problems`). Server-side validation (Checkmk's REST API itself) is always still the final authority — client-side checks exist to fail fast with a clearer message, not to replace server validation.

**Authentication:** Two credential types flow through `CheckmkConnection` (`api.py:30-49`): the general `username`/`secret` (REST Bearer auth, used for all `CheckmkClient` calls) and an optional narrower `registration_user`/`registration_secret` (used only for `cmk-agent-ctl register` commands), defaulting to the general credential when no dedicated `agent_registration` user secret is available. GUI-session (cookie-based) auth is a separate, one-off mechanism (`api.py`'s `_gui_login`) used only for the initial `cmkadmin`-authenticated bootstrap calls, never for ordinary REST operations.

---

*Architecture analysis: 2026-09-05*
