# External Integrations

**Analysis Date:** 2026-09-05

## APIs & External Services

**Checkmk REST API (v1):**
- Service: Checkmk Community Edition site's own REST API, under `<proto>://<host>/<site>/check_mk/api/v1`
  - SDK/Client: `httpx.AsyncClient`, wrapped by `CheckmkClient` (`src/checkmk_wizard/api.py`)
  - Auth: Bearer token — `Authorization: Bearer <username> <secret>` header, built from a `CheckmkConnection` dataclass (`src/checkmk_wizard/api.py:30-53`)
  - Covers: folder/host CRUD, agent binary download, service discovery, pending-changes activation, active-check rule creation (`src/checkmk_wizard/api.py:117-282`)

**Checkmk GUI session login (`login.py`):**
- Service: Checkmk's cookie-based web login flow, used only where no REST automation credential exists yet
  - SDK/Client: raw `httpx.AsyncClient` (not `CheckmkClient`) — `src/checkmk_wizard/api.py:289-621`
  - Auth: `cmkadmin` username/password + scraped CSRF token (`global_csrf_token` regex, `src/checkmk_wizard/api.py:286`), resulting in an `auth_<site>` session cookie
  - Used by: `bootstrap_automation_user()` (creates the REST `automation` user), `bootstrap_agent_registration_secret()` (resets the built-in `agent_registration` user's secret), `change_cmkadmin_password()` (changes `cmkadmin`'s own login password)
  - Not covered by Checkmk's official REST API docs — endpoints/payloads reverse-engineered from a live 2.4.0p35 CE site's own OpenAPI spec and endpoint source, per extensive docstrings in `api.py`

**Checkmk Livestatus (LQL over TCP):**
- Service: Checkmk's monitoring-core query protocol, port 6557 (`DEFAULT_PORT`)
  - SDK/Client: raw `socket` (no library) — `src/checkmk_wizard/livestatus.py`
  - Auth: none (network-level access only — must be explicitly enabled via `omd config <site> set LIVESTATUS_TCP on`)
  - Used for: post-activation host-state health checks (`query_host_states()`)

**Checkmk Agent Receiver / `cmk-agent-ctl`:**
- Service: not called over HTTP directly by this codebase; invoked as a subprocess/remote command on target hosts
  - Client: SSH command execution via `asyncssh` — `cmk-agent-ctl register --hostname --server --site --user --password` run on the remote Linux target (`src/checkmk_wizard/remote.py`)
  - Auth: dedicated `agent_registration` automation user (falls back to the general `automation` user) plus SSH credentials to the target host itself
  - Port: Agent Receiver listens on 8000 (`AGENT_RECEIVER_PORT`, `src/checkmk_wizard/remote.py:31`)
  - Windows targets: no SSH automation — the wizard prints manual `cmk-agent-ctl.exe register` instructions instead

## Data Storage

**Databases:**
- None. No SQL/NoSQL database client or ORM in dependencies.

**File Storage:**
- Local filesystem only:
  - Reads OMD site config/secrets directly from `/omd/sites/<site>/...` (host-native mode) — `src/checkmk_wizard/site.py` (`read_automation_secret()`, `list_agent_registered_hosts()` parsing `etc/check_mk/conf.d/wato/**/hosts.mk`)
  - Bundled `smartmontools` `.deb` packages under `docs/smart/` are copied to remote hosts over SSH/SFTP (`src/checkmk_wizard/remote.py`)
  - `config_snapshot_*.json` files written to the repo root at runtime (gitignored via `config_snapshot_*.json` in `.gitignore`) — appear to be wizard-run output snapshots, not fixtures

**Caching:**
- None

## Authentication & Identity

**Auth Provider:**
- Custom — entirely Checkmk's own built-in user/automation-credential system, no external identity provider (no OAuth/SAML/OIDC)
  - `cmkadmin` — Checkmk's built-in superuser, used only for GUI-session bootstrapping flows
  - `automation` — REST API user, auto-provisioned by the wizard if missing (`bootstrap_automation_user()`) or read from the local secret file (`site.get_site_credentials()`)
  - `agent_registration` — Checkmk's built-in least-privilege user for `cmk-agent-ctl register`, secret bootstrapped over REST if not locally readable (`bootstrap_agent_registration_secret()`)
  - SSH credentials (password or private key, `src/checkmk_wizard/remote.py:SSHCredentials`) — used to reach target hosts for firewall configuration and agent installation, independent of any Checkmk credential

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry/error-tracking SDK)

**Logs:**
- No structured logging framework — output is interactive terminal UI via `rich.console.Console` (`src/checkmk_wizard/wizard.py`); errors surface as `CheckmkAPIError`/`SiteBootstrapError` exceptions with the raw request/response detail embedded

## CI/CD & Deployment

**Hosting:**
- Not a hosted service — a CLI tool run either directly on a Checkmk host (host-native mode) or from a companion "worker" container (container mode) alongside a Podman-based stack (Checkmk, Mosquitto, MinIO) documented in `docs/Podman setup for checkmk, minio, mosquitto, worker.md`

**CI Pipeline:**
- None detected — no `.github/workflows`, no `.gitlab-ci.yml`, no other CI config in the repo

## Environment Configuration

**Required env vars:**
- `CMK_SITE_ID` (optional) — pre-fills the site-name prompt in container mode (`src/checkmk_wizard/wizard.py:290`)
- `CMK_PASSWORD` (referenced conceptually, not read directly by the wizard) — the Checkmk container's own `cmkadmin` bootstrap password; the wizard prompts for it interactively instead of reading the env var

**Secrets location:**
- Checkmk automation secrets: `/omd/sites/<site>/var/check_mk/web/<user>/automation.secret` (host-native mode, read directly off disk)
- In container mode, no local secret file exists — secrets are instead minted over the REST/GUI-login flow (`bootstrap_automation_user()`, `bootstrap_agent_registration_secret()`) and held only in memory for the wizard's session
- `.env`/credential files: none present in the repo (verified no `.env*`, no `credentials.*` files)

## Webhooks & Callbacks

**Incoming:**
- None — this is a CLI tool with no listening server/endpoints

**Outgoing:**
- None invoked directly by `src/checkmk_wizard/`. Note: `docs/src/mqtt_notify.py` and `docs/src/mqtt_publisher_changes.py` are example Checkmk *notification scripts* (using `paho.mqtt.client`, not a project dependency) documented as reference material for wiring Checkmk's own notification system to an MQTT broker (Mosquitto) in the Podman stack — these are deployment artifacts for the target Checkmk site, not code invoked by this wizard.

---

*Integration audit: 2026-09-05*
