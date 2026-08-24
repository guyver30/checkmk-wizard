<!-- refreshed: 2026-08-24 -->
# Architecture

**Analysis Date:** 2026-08-24

## System Overview

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                    Interactive Terminal UI Layer                         │
│          questionary prompts + rich console output formatting             │
│                         wizard.py (phases 1-7)                           │
└────┬────────────────────┬──────────────────────┬───────────────┬─────────┘
     │                    │                      │               │
     │                    │                      │               │
┌────▼──────┐  ┌──────────▼────────┐  ┌─────────▼──────┐  ┌─────▼────────┐
│  Site      │  │  Network Scanner  │  │  API Client    │  │   Remote SSH │
│ Bootstrap  │  │   (Async TCP)     │  │  (HTTP/REST)   │  │  & Firewall  │
│  site.py   │  │  scanner.py       │  │  api.py        │  │  remote.py   │
└────┬──────┘  └──────────┬─────────┘  └────────┬───────┘  └──────┬────────┘
     │                    │                      │                │
     └────────────────────┼──────────────────────┼────────────────┘
                          │                      │
                 ┌────────▼──────────────────────▼─────────┐
                 │      Livestatus Socket Query            │
                 │         livestatus.py                   │
                 │   (Phase 7 health check only)           │
                 └────────┬──────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
    ┌───▼───┐        ┌────▼────┐      ┌────▼──────┐
    │  OMD   │        │Checkmk  │      │ Local SSH │
    │ Site   │        │REST API │      │ Targets   │
    │ (/omd) │        │(Remote) │      │ (Linux)   │
    └────────┘        └─────────┘      └───────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| **Interactive Wizard** | Phases 1-7 orchestration, user prompts, progress display | `src/checkmk_wizard/wizard.py` |
| **REST API Client** | Checkmk v1 API calls (folders, hosts, discovery, activation) | `src/checkmk_wizard/api.py` |
| **Site Bootstrap** | OMD site creation/startup, automation credential discovery | `src/checkmk_wizard/site.py` |
| **Network Scanner** | Async TCP port sweep with bounded concurrency | `src/checkmk_wizard/scanner.py` |
| **Remote SSH Ops** | Firewall detection/fix, OS compatibility check, agent install | `src/checkmk_wizard/remote.py` |
| **Livestatus Query** | Host state lookup from site socket (post-activation) | `src/checkmk_wizard/livestatus.py` |

## Pattern Overview

**Overall:** Layered async pipeline with orchestrated phases

**Key Characteristics:**
- **Sequential phase execution:** Each phase runs to completion before the next; phases share state via `WizardState` or parameters
- **Async throughout:** All I/O operations (HTTP, SSH, network scanning) are async using `asyncio`
- **Fail-safe degradation:** Firewall and agent install have manual fallback instructions; no single failure blocks the entire flow
- **Interactive during discovery:** User makes decisions (folder structure, host classification, SSH credentials) at specific decision points
- **Local execution:** Runs on the Checkmk host itself; accesses OMD site files and drives `omd` commands locally

## Layers

**Presentation (UI):**
- Purpose: Capture user input and display progress/results
- Location: `src/checkmk_wizard/wizard.py` (phase functions)
- Contains: `questionary` prompts, `rich` console formatting, phase-level orchestration logic
- Depends on: All service layers; `questionary`, `rich`
- Used by: Entry point `main()` in `wizard.py`

**Orchestration (Phases):**
- Purpose: Sequence operations and manage control flow between phases
- Location: `src/checkmk_wizard/wizard.py` (phase1-7 functions, `run()`, `main()`)
- Contains: Phase logic, state sharing via function parameters and `WizardState`
- Depends on: Service layers (API client, site bootstrap, scanner, remote, livestatus)
- Used by: `main()` entry point

**Service/Domain (Business Logic):**
- Purpose: Implement domain-specific operations
- Location: `src/checkmk_wizard/{api,site,scanner,remote,livestatus}.py`
- Contains: 
  - `api.py`: Checkmk REST client with per-phase endpoint groupings
  - `site.py`: OMD subprocess operations, credential file reading
  - `scanner.py`: Async TCP connection probes with semaphore concurrency control
  - `remote.py`: SSH firewall/compatibility checks, agent installation
  - `livestatus.py`: Livestatus socket protocol query
- Depends on: External libraries (`httpx`, `asyncssh`, `asyncio`)
- Used by: Phase functions in `wizard.py`

**External Integration:**
- Checkmk REST API (v1) — all host/folder/activation operations
- OMD command-line (`omd create`, `omd start`)
- SSH (asyncssh) — firewall/OS/agent operations on Linux targets
- Livestatus socket — post-activation host state queries
- Local filesystem — automation secret, agent packages

## Data Flow

### Primary Request Path (Full Wizard Run)

1. **Phase 1 — Site Bring-up** (`phase1_site_bringup()` in `wizard.py:44-89`)
   - Prompt for site name and Checkmk host
   - Check if site exists via `site.site_exists()` (`site.py:34-35`)
   - Create site if needed via `site.create_site()` (`site.py:38-47`)
   - Start site via `site.start_site()` (`site.py:50-53`)
   - Retrieve automation credentials via `site.get_site_credentials()` (`site.py:69-73`)
   - Prompt for secret if not found
   - Validate via `CheckmkClient.get_version()` (`api.py:89-91`)
   - Returns: `CheckmkConnection` object with auth details

2. **Phase 2 — Folder Structure** (`phase2_folders()` in `wizard.py:95-111`)
   - User decides if folders are needed
   - For each folder name, call `CheckmkClient.create_folder()` (`api.py:95-107`)
   - API: `POST /domain-types/folder_config/collections/all`
   - No state persisted; phase can be skipped entirely

3. **Phase 3 — Network Discovery** (`phase3_discovery()` in `wizard.py:116-146`)
   - Prompt for CIDR and ports
   - Call `scan_network()` (`scanner.py:63-85`) with progress callback
   - Async TCP probes via `scan_host()` → `_probe_port()` (`scanner.py:48-53, 32-45`)
   - Stage scan results into Checkmk via `CheckmkClient.create_host()` for each IP (`api.py:111-125`)
   - API: `POST /domain-types/host_config/collections/all`
   - Returns: `list[HostScanResult]` (IPs + open ports)

4. **Phase 4 — Host Classification** (`phase4_classification()` in `wizard.py:152-171`)
   - User selects which IPs to promote to named hosts
   - For each selected IP, prompt for hostname, folder, OS family
   - Returns: `list[OnboardedHost]` (hostname, folder, OS, IP)
   - No API calls; purely interactive

5. **Phase 5 — Host Onboarding** (`phase5_onboarding()` in `wizard.py:177-258`)
   - Phase 5.1 (Firewall):
     - For each Linux host, probe port 8000 via `remote.probe_port()` (`remote.py:81-101`)
     - SSH to target via `remote.check_ssh_reachable()` → `_connect()` (`remote.py:113-119, 104-110`)
     - Detect firewall backend (ufw/firewall-cmd/nft) via SSH command tests
     - Apply allow rule via `remote.fix_firewall_linux()` (`remote.py:129-164`)
     - Return: `ActionResult` (automated, manual_required, or failed_fallback_manual)
   - Phase 5.2 (Agent Install):
     - Prompt for SSH credentials (password or key path)
     - Check OS compatibility via `remote.check_os_compatibility()` (`remote.py:167-194`)
     - Download agent via `CheckmkClient.download_agent()` (`api.py:143-150`)
     - API: `GET /domain-types/agent/actions/download/invoke`
     - Push package via SFTP, install (dpkg/rpm), register via `remote.install_agent_linux()` (`remote.py:220-272`)
   - Windows targets: print manual instructions only
   - Update host in Checkmk via `CheckmkClient.create_host()` with `tag_agent` attribute

6. **Phase 6 — Discovery & Baseline** (`phase6_discovery()` in `wizard.py:271-278`)
   - For each onboarded host, call `CheckmkClient.start_service_discovery()` (`api.py:154-160`)
   - API: `POST /domain-types/service_discovery_run/actions/start/invoke`

7. **Phase 7 — Activation & Validation** (`phase7_activation()` in `wizard.py:284-312`)
   - Get pending changes ETag via `CheckmkClient.get_pending_changes_etag()` (`api.py:164-169`)
   - Activate via `CheckmkClient.activate_changes()` (`api.py:171-187`)
   - API: `POST /domain-types/activation_run/actions/activate-changes/invoke`
   - Query host states via `livestatus.query_host_states()` (`livestatus.py:18-57`)
     - Connects to `/omd/sites/{site}/tmp/run/live` socket
     - Sends LQL query: `GET hosts\nColumns: name state\n`
     - Parses CSV response into `{hostname: state_int}` map
   - Write snapshot JSON to disk with onboarded hosts and timestamp
   - Print final status table

**State Management:**
- `CheckmkConnection` — Connection details (host, site, username, secret); created in Phase 1, passed to API client
- `OnboardedHost` list — Built in Phase 4, used in Phases 5-7
- `HostScanResult` list — Built in Phase 3, used in Phase 4
- Local variables in each phase function — No global state except the async context

## Key Abstractions

**CheckmkConnection:**
- Purpose: Encapsulates Checkmk REST API authentication details
- Examples: `src/checkmk_wizard/api.py:27-37`, `src/checkmk_wizard/wizard.py:75-80`
- Pattern: Dataclass with computed `base_url` property; passed to `CheckmkClient`

**CheckmkClient:**
- Purpose: Thin async wrapper around Checkmk v1 REST API
- Examples: `src/checkmk_wizard/api.py:40-187`
- Pattern: Context manager (async with support); methods grouped by phase; raises `CheckmkAPIError` on failure

**ActionResult:**
- Purpose: Represents outcome of remote operations (firewall/install); can degrade gracefully
- Examples: `src/checkmk_wizard/remote.py:45-49`, `src/checkmk_wizard/wizard.py:218-227`
- Pattern: Dataclass with `outcome` (enum), `detail` (string), `manual_instructions` (optional)

**OnboardedHost:**
- Purpose: Represents a host promoted from scan results to named entity
- Examples: `src/checkmk_wizard/wizard.py:26-31`, Phase 4 return
- Pattern: Dataclass with IP, hostname, folder, OS family

**HostScanResult:**
- Purpose: Represents a discovered host + its open ports
- Examples: `src/checkmk_wizard/scanner.py:22-29`, Phase 3 return
- Pattern: Dataclass with IP and open_ports list; computed `is_alive` property

## Entry Points

**CLI Entrypoint:**
- Location: `src/checkmk_wizard/__main__.py:1-4`
- Triggers: `python -m checkmk_wizard` or `uv run checkmk-wizard` (from `pyproject.toml` script)
- Responsibilities: Import `main()` from `wizard.py` and call it

**Async Entry:**
- Location: `src/checkmk_wizard/wizard.py:318-331`
- `main()` → calls `asyncio.run(run())`
- `run()` → orchestrates all 7 phases sequentially

## Architectural Constraints

- **Threading:** Single-threaded async event loop (`asyncio.run()` at top level). Network I/O uses asyncio; SSH uses `asyncssh` (async); port scanner uses bounded semaphore for concurrency control (~256 concurrent connections, tunable).
- **Global state:** None. All state is local to function scopes or passed as parameters.
- **Circular imports:** None detected. Module hierarchy is linear: `wizard` → `{api,site,scanner,remote,livestatus}`.
- **Subprocess execution:** Only in `site.py` via `subprocess.run()` for OMD commands; blocks the event loop (acceptable because OMD operations are infrequent and critical path).
- **Filesystem access:** Read-only for automation secret and `/etc/os-release`; write-only for snapshot JSON and agent package temp files.
- **Socket access:** Livestatus queries via Unix socket; fails gracefully if socket is unavailable.
- **Concurrency model:** Semaphore-bounded TCP probes during scan; otherwise sequential; no shared mutable state across tasks.

## Anti-Patterns

### Subprocess in Async Context

**What happens:** `site.py:38-47` and `site.py:50-53` use `subprocess.run()` (blocking) in what is otherwise an async codebase.

**Why it's wrong:** Blocks the event loop during OMD operations. On large scale or with slow OMD commands, the wizard UI becomes unresponsive.

**Do this instead:** Migrate to `asyncio.create_subprocess_exec()` or `subprocess.run()` in a thread pool executor (`loop.run_in_executor()`) to avoid blocking. However, this is acceptable for v0.1 given that OMD operations are rare (Phase 1 only) and non-interactive waits are brief.

### Hard-Coded Paths and Constants

**What happens:** Hardcoded paths like `/omd/sites/{site}/var/check_mk/web/...` and port constants (`AGENT_RECEIVER_PORT = 8000`) are scattered across modules.

**Why it's wrong:** Reduces portability; changes to Checkmk site layout or custom ports require code edits.

**Do this instead:** Centralize path and port constants in a `config.py` module, or query them from the Checkmk site at runtime (e.g., `omd config show`). For v0.1, hard-coded constants are acceptable given the limited scope.

### Manual Fallback Instructions as Strings

**What happens:** Firewall and agent install instructions are embedded in strings within `remote.py` functions, duplicated across error paths.

**Why it's wrong:** Difficult to maintain; risk of inconsistency between automated and manual paths; poor localization support.

**Do this instead:** Move instructions to a dedicated template engine or documentation file, and reference them via keys. For v0.1, inline strings are acceptable.

## Error Handling

**Strategy:** Fail-safe degradation with manual instructions.

**Patterns:**
- REST API errors (`CheckmkAPIError`) are caught in phase functions and logged; the wizard prints the error and either continues (if not critical) or raises `SystemExit(1)` (Phase 1 connectivity check).
- SSH/firewall errors return `ActionResult` with `outcome=FAILED_FALLBACK_MANUAL` and a fallback instruction string; the wizard prints this and continues.
- Network scan timeouts are handled per-host; a timeout on one host doesn't stop scanning others.
- Site bootstrap errors raise `SiteBootstrapError` with stderr output; the wizard does not catch this (fatal).
- Livestatus socket errors are unhandled (fatal); if the site is up, the socket should be available.

**No exceptions are silenced.** Errors either fail fast or degrade gracefully with clear user messaging.

## Cross-Cutting Concerns

**Logging:** None. Output is via `rich.console.Console()` for user-facing messages. Debugging requires reading phase function logic or adding print statements.

**Validation:**
- CIDR validation: `ipaddress.ip_network()` in `scanner.py:71` raises `ValueError` if malformed.
- Port validation: User input is split and `int()` is called; invalid ports raise `ValueError`.
- Hostname/folder/site names: No validation; passed directly to Checkmk API.

**Authentication:**
- Checkmk REST API: Bearer token in `Authorization` header (username + secret).
- SSH: Password or private key via `asyncssh.connect()`.
- Local OMD access: No auth required; assumes wizard runs on the Checkmk host.

**Rate Limiting:** None. TCP scanner is bounded by semaphore concurrency, not rate limits. REST API calls are sequential per phase.

---

*Architecture analysis: 2026-08-24*
