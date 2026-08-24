# External Integrations

**Analysis Date:** 2026-08-24

## APIs & External Services

**Checkmk REST API v1:**
- Service: Checkmk monitoring platform (v2.4.0+)
- What it's used for: Host configuration, folder management, service discovery, configuration activation
- SDK/Client: Custom async wrapper in `src/checkmk_wizard/api.py` (CheckmkClient using httpx)
- Auth: Bearer token authentication with two credentials: username (e.g., "automation") and secret (automation API key)
- Endpoint Base: `http://{host}/{site}/check_mk/api/v1`
- Protocol: HTTP/HTTPS (configurable via `proto` parameter in CheckmkConnection)
- Phases using it:
  - Phase 1: `GET /version` (connectivity verification)
  - Phase 2: `POST /domain-types/folder_config/collections/all` (folder creation)
  - Phase 3-5: `POST /domain-types/host_config/collections/all`, `PUT /objects/host_config/{hostname}` (host creation and updates)
  - Phase 5: `GET /domain-types/agent/actions/download/invoke` (Linux agent package download)
  - Phase 6: `POST /domain-types/service_discovery_run/actions/start/invoke` (service discovery)
  - Phase 7: `GET /domain-types/activation_run/collections/pending_changes`, `POST /domain-types/activation_run/actions/activate-changes/invoke` (activation)

## Data Storage

**Databases:**
- Not used - Checkmk manages its own database; this tool is a client-side configurator

**File Storage:**
- Local filesystem only
  - Reads: `/omd/sites/{site}/var/check_mk/web/automation/{user}/automation.secret` (Phase 1 credential bootstrap)
  - Writes: `config_snapshot_{timestamp}.json` in current working directory (Phase 7 output)

**Caching:**
- None - Stateless tool; all configuration persisted directly to Checkmk

## Authentication & Identity

**Auth Provider:**
- Checkmk native automation user (built-in to every site)
- Implementation: Bearer token sent as `Authorization: Bearer {username} {secret}` header
- User creation: Manual via web UI (Setup > Users) with authentication mode "Automation secret for machine accounts"
- Secret storage: Filesystem (`/omd/sites/{site}/var/check_mk/web/automation/{user}/automation.secret`)
- No external identity provider (LDAP, OAuth, etc.)

## Monitoring & Observability

**Error Tracking:**
- Not integrated - All errors bubble up as exceptions to caller

**Logs:**
- Console-based via `rich` library (styled terminal output)
- Log levels: Info, Warning, Yellow/Red error messages (semantic, not structured)
- No persistent logging to file or external service

## CI/CD & Deployment

**Hosting:**
- On-premises: Must run on the Checkmk host itself (requires local filesystem and `omd` CLI access)
- Not suitable for cloud or remote deployment

**CI Pipeline:**
- Not configured - Project tests mock all external services (respx for httpx, no live Checkmk required)
- Tests run with: `uv run pytest`

## Environment Configuration

**Required env vars:**
- None - Application is stateless and driven by interactive user input

**Secrets location:**
- `/omd/sites/{site}/var/check_mk/web/automation/{user}/automation.secret` (local filesystem; requires Phase 1 user setup in web UI)
- Credentials provided interactively if file doesn't exist

## Webhooks & Callbacks

**Incoming:**
- None - Tool is pull-based only

**Outgoing:**
- None - Tool makes only synchronous REST API calls to Checkmk

## Livestatus Integration

**Service:** Checkmk Livestatus (local monitoring query engine)
- What it's used for: Post-activation health check (Phase 7) to query host state
- Protocol: UNIX socket + LQL (Livestatus Query Language) text protocol
- Socket path: `/omd/sites/{site}/tmp/run/live`
- Client: Custom minimal sync socket client in `src/checkmk_wizard/livestatus.py` (no external library)
- Query format: Plain text LQL terminated by blank line, response as CSV
- Example query:
  ```
  GET hosts
  Columns: name state
  OutputFormat: csv
  ColumnHeaders: off
  ```
- Return states: 0 (UP), 1 (DOWN), 2 (UNREACHABLE), or omitted if host not yet known

## SSH & Remote Execution

**Service:** Target Linux hosts (via SSH for Phase 5 automation)
- What it's used for: Firewall configuration, agent installation, OS compatibility checks
- SDK/Client: asyncssh 2.24.0+ (async SSH/SFTP client)
- Auth modes: Password or private key file path (configurable per session)
- Port: 22 (standard SSH)
- Operations:
  - Firewall detection and rule addition (ufw, firewall-cmd, or nft)
  - OS release detection via `/etc/os-release` (used for agent package compatibility check)
  - Agent package upload via SFTP
  - Agent package installation (dpkg or rpm)
  - Agent registration via `cmk-agent-ctl register` command
- Fallback: If SSH automation fails, wizard provides manual step-by-step instructions

## Network Scanning

**Service:** Target network (via TCP connect probes)
- What it's used for: Phase 3 network discovery to identify responsive hosts
- Protocol: Custom async TCP connect scanner (asyncio-based, no external library)
- Port scanning: Configurable default ports (22, 80, 443); user can specify custom ports
- Scan strategy: Bounded concurrency (default 256 concurrent connections) with /24 subnet chunking for large networks
- Result: List of responsive hosts with open ports
- No fingerprinting applied (manual host classification in Phase 4)

## Agent Installation

**Service:** Checkmk Agent (Phase 5.2)
- Download protocol: REST API (binary download endpoint `/domain-types/agent/actions/download/invoke`)
- Supported formats: `.deb` (Debian/Ubuntu), `.rpm` (RedHat/CentOS/SUSE)
- Installation: Pushed to target over SFTP, installed locally with dpkg/rpm
- Registration: `cmk-agent-ctl register` command (must run on target host; cannot be invoked remotely)
- Receiver port: 8000 (Agent Receiver listens here for incoming registrations)

## OMD Site Management

**Service:** Local OMD (Open Monitoring Distribution) site bootstrap
- What it's used for: Phase 1 site creation and startup
- Interface: Local subprocess calls to `omd` CLI
- Operations:
  - `omd create --admin-password {pwd} {site}` (creates site with known cmkadmin password)
  - `omd start {site}` (starts site services; no-op if already running)
- Execution context: Must run as user with OMD access (typically `root` or OMD site user)
- Credential bootstrap: Reads automation secret file post-creation

---

*Integration audit: 2026-08-24*
