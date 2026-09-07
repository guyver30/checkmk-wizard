# Decoupled Checkmk, Mosquitto, MinIO & Automation Worker Stack

A modular, rootless Podman deployment running stock official images across an isolated bridge network with full external LAN access. `checkmk-wizard` runs from the `worker` container in **container mode** (see [docs/WIZARD-OPERATION.md](WIZARD-OPERATION.md) and the main [README.md](../README.md#prerequisites) for how that mode differs from running the wizard directly on a Checkmk host) — it never touches the `checkmk` container's filesystem or `omd` binary, only its REST API and Livestatus-over-TCP port.

---

## 1. Prerequisites (Rootless Podman Setup)

§1.1 gets Podman onto a machine that has never had it before; §1.2 makes that installation usable rootless and persistent across reboots.

### 1.1. Install Podman

On Debian or Ubuntu, install Podman itself, `uidmap` (provides `newuidmap`/`newgidmap` — rootless Podman cannot start a container without them), and `podman-compose`:

```bash
sudo apt update
sudo apt install -y podman uidmap podman-compose
```

Debian 12+ and Ubuntu 22.04+ ship a Podman recent enough for everything this doc uses. Older releases package a Podman too old to support the `podman compose` subcommand — upgrade the distro release first if you're on something older than that.

On RHEL, Fedora, or CentOS Stream, via `dnf`:

```bash
sudo dnf install -y podman podman-compose
```

If you'd rather pull in the full toolchain than just these two packages, the `container-tools` package group (`sudo dnf install -y @container-tools`) is the RHEL/CentOS equivalent bundle.

`podman compose` is only a shim — it delegates to whichever external compose provider it finds (`docker-compose` or `podman-compose`), so one of those two has to be installed or every `podman compose` command later in this doc fails. That's the same delegation visible in the systemd failure log further down this doc (`/usr/libexec/docker/cli-plugins/docker-compose`) — installing `podman-compose` now is what makes that delegation succeed instead of erroring.

Verify the install:

```bash
podman --version
podman info --format '{{.Host.Security.Rootless}}'
# expected: true — if it prints false you are running as root, and the
# rest of this doc's rootless assumptions do not hold
podman run --rm docker.io/library/hello-world
```

**Rootless UID/GID ranges:** the distro package normally allocates these for you, so this is a check, not a step. Confirm your user has a range in both files:

```bash
grep "^$USER:" /etc/subuid /etc/subgid
# want a line in *both* files, e.g. youruser:100000:65536
```

If either file has no line for your user, add one and re-map any containers already created under the old, empty range:

```bash
sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER
podman system migrate
```

**Short-name image resolution:** the next thing a fresh install hits is §4's `podman compose up -d`, which fails for every service in this stack's `compose.yaml` that names its image without a registry — `checkmk/check-mk-raw:2.4.0-latest`, `eclipse-mosquitto:2`, and `minio/minio:latest` all fail with:

```text
Error: short-name "checkmk/check-mk-raw:2.4.0-latest" did not resolve to an alias
and no unqualified-search registries are defined in "/etc/containers/registries.conf"
```

The `worker` service (`python:3.12-slim`) is the one exception — it succeeds because Podman ships a built-in shortname alias for it in `/etc/containers/registries.conf.d/shortnames.conf`, and the other three images have no such alias.

This is Podman's deliberate anti-typosquatting default, not a broken install: a fresh machine has no `unqualified-search-registries` configured anywhere, and rootless Podman would rather refuse an unqualified short name than guess which registry it should resolve against. The verify step above passes anyway because it pulls the fully-qualified `docker.io/library/hello-world`, which is why this doesn't surface until §4.

The fix is a rootless per-user override, which takes precedence over the system-wide `/etc/containers/registries.conf` named in the error above:

```bash
mkdir -p ~/.config/containers
cat > ~/.config/containers/registries.conf <<'EOF'
unqualified-search-registries = ["docker.io"]
EOF
```

Setting `unqualified-search-registries` to `docker.io` only re-enables short-name resolution against Docker Hub — it declares the single registry a short name is allowed to mean, it does not disable Podman's protection wholesale.

No cleanup is needed: just re-run `podman compose up -d`. The three failed services never got as far as creating a container object (the failure was at the `podman run` step itself, exit code 125), so any volumes or the `cmk_net` network podman-compose already created are reused as-is on retry.

### 1.2. Enable the rootless Podman socket

Enable the Podman systemd user socket and ensure rootless background persistence:

```bash
# Enable and start user-level Podman API socket
systemctl --user enable --now podman.socket

# Keep containers running after logout
loginctl enable-linger $USER

# Configure Docker Compose provider to use Podman socket
echo 'export DOCKER_HOST="unix:///run/user/1000/podman/podman.sock"' >> ~/.bashrc
export DOCKER_HOST="unix:///run/user/1000/podman/podman.sock"

```

---

## 2. Directory Structure

The canonical `compose.yaml`, `mosquitto.conf`, `mosquitto.acl`, `mosquitto.passwd` and `gen-mosquitto-passwd.sh` live under this repo's own `deploy/` directory (see §3). Since Phase 9, `deploy/compose.yaml` also bind-mounts `../scripts` for the `poller` service (§6's MQTT topic contract), and that path resolves relative to wherever `compose.yaml` itself sits — so the repo checkout (§8.1's clone command) must exist **before** `podman compose up`, and `podman compose` must be run from the checkout's own `deploy/` directory, not from a copy of `deploy/` placed loose in `checkmk-stack/`:

```text
checkmk-stack/
└── app/
    └── checkmk-wizard/     # checkout of the checkmk-wizard repo — see §8.1
        └── deploy/         # this repo's own deploy/ directory; `podman
            ├── compose.yaml           # compose` is run from here (§4),
            ├── mosquitto.conf         # not from a separate copy
            ├── mosquitto.acl
            ├── mosquitto.passwd
            └── gen-mosquitto-passwd.sh

```

A `deploy/` copied or symlinked elsewhere (this doc's pre-Phase-9 layout) leaves the `poller` service with no `../scripts` to mount on a fresh checkout. If your layout genuinely can't follow this structure, set `POLLER_SCRIPTS_DIR` to an absolute path pointing at this repo's `scripts/` directory instead.

Create the working directory and workspace folder:

```bash
mkdir -p checkmk-stack/app
cd checkmk-stack

```

---

## 3. Configuration Files

The full 5-service stack (`checkmk`, `mosquitto`, `minio`, `worker`, `poller`) and the hardened Mosquitto configuration are checked into this repo under [`deploy/`](../deploy/) as the single source of truth — see [`deploy/compose.yaml`](../deploy/compose.yaml), [`deploy/mosquitto.conf`](../deploy/mosquitto.conf) and [`deploy/mosquitto.acl`](../deploy/mosquitto.acl). This doc no longer duplicates their contents inline, so the two can't silently drift apart; run `podman compose` from the checkout's own `deploy/` directory (see §2).

A few things worth knowing that aren't obvious just from reading those files:

- **Mosquitto's listeners bind to all container interfaces (`0.0.0.0`)** so both internal containers and external LAN devices can reach the broker — the plain-MQTT listener on 1883 stays published to the LAN for debugging, and a second listener (`protocol websockets`) is published separately for browser-based clients.
- **Podman-compatible `tmpfs` flags (`mode=1777`)** on the `checkmk` service prevent permission errors for the unprivileged Checkmk site user (`UID 1000`).
- **The `poller` runs as its own `restart: unless-stopped` service**, not inside `worker` — this keeps the always-on live Livestatus-to-MQTT bridge running independently of the `worker` container's interactive, on-demand wizard usage, so neither one can interfere with the other.

### First-time credential setup

`deploy/mosquitto.passwd` is checked in with disposable default credentials (see §6). To rotate them, re-run [`deploy/gen-mosquitto-passwd.sh`](../deploy/gen-mosquitto-passwd.sh) — optionally with `WS_PASSWORD=` / `POLLER_PASSWORD=` environment overrides — and commit (or otherwise redeploy) the resulting file. This script is the supported way to regenerate the password file; it invokes the broker's own `mosquitto_passwd` via `podman run`/`docker run`, so no local Mosquitto install is required.

**Note on `CMK_PASSWORD`:** this is the `cmkadmin` login password checkmk-wizard's container mode will ask you to re-enter at Phase 1, so it can bootstrap the site's `automation`/`agent_registration` REST users itself (see §8.3). `cmkadmin` is fine for a disposable local/test stack; change it to something you'd actually want to type before running this against anything you care about.

---

## 4. Deployment

**Migrating an already-running stack:** if a stack was already running against the old `/etc/mosquitto/mosquitto.conf` mount, `deploy/compose.yaml` corrects the mount path to `/mosquitto/config/mosquitto.conf` (the only path the `eclipse-mosquitto` image's baked-in `CMD` actually reads) and adds authentication/ACL enforcement that wasn't there before. This changes which config the broker loads, and any retained messages accumulated under the previous configuration should be backed up first if they matter — `podman volume export mosquitto_data -o mosquitto_data-backup.tar` before redeploying. This is an operator note, not a blocking step.

```bash
# Run from the repo checkout's own deploy/ directory (see §2) — this is
# what makes deploy/compose.yaml's ../scripts mount for the poller service
# resolve correctly without setting POLLER_SCRIPTS_DIR
cd app/checkmk-wizard/deploy

# Start all containers in the background
podman compose up -d

# Verify initialization
podman compose ps

```

Watch the poller's poll cycles as they happen:

```bash
podman compose logs -f poller
```

---

## 5. Enable Livestatus-over-TCP (required for checkmk-wizard)

checkmk-wizard's Phase 7 post-activation health check connects to the site's Livestatus port over **TCP**, not the local UNIX socket — that's what lets it run from the separate `worker` container instead of needing local filesystem access to `checkmk`'s `/omd/sites`. This has to be turned on once per site; it isn't on by default on a container-created site.

Run this once, right after the site first comes up (a fresh `podman compose up`, or any time you delete/recreate the site inside the `checkmk` container):

```bash
podman compose exec checkmk omd stop dmc
podman compose exec checkmk omd config dmc set LIVESTATUS_TCP on
podman compose exec checkmk omd start dmc
```

`omd config ... set` refuses to change config variables while the site is running — it errors with `Cannot change config variables while site is running.` — which is why the site is stopped first and then *started* rather than left running and restarted afterward. A site freshly brought up by §4's `podman compose up -d` is already running when you reach this step, so the stop is always needed, not situational. Stopping the site for this loses nothing: flipping `LIVESTATUS_TCP` is a config change, not a code change or a data wipe, so the site's monitoring data, hosts, and history all live in the `checkmk_data` volume and survive the stop/start untouched.

This binds Livestatus on port **6557** by default (Checkmk's own default `LIVESTATUS_TCP_PORT`) — matching what checkmk-wizard already expects, so nothing else needs configuring. No `ports:` entry is needed in `compose.yaml` for this: containers on the same `cmk_net` bridge can already reach `checkmk:6557` directly by service name, without publishing the port to the host/LAN — and it should stay that way, since Livestatus's wire protocol has no authentication of its own and relies entirely on network-level isolation.

*(There's also a documented `CMK_LIVESTATUS_TCP` boot-time environment variable for the official image that may let you skip this manual step — not verified here against this specific image/version, so the `omd stop`/`omd config`/`omd start` steps above are the confirmed way. If you try the env var, verify Phase 7 actually works end-to-end before relying on it.)*

If you skip this step, checkmk-wizard still runs fine through Phase 6 — it just prints a warning at Phase 1 ("Could not reach Livestatus on checkmk:6557") and Phase 7's host-state table will fail at the very end of the run.

---

## 6. Endpoints & Network Access

| Service | LAN / Browser URL | Internal Network DNS (Inside Containers) |
| --- | --- | --- |
| **Checkmk UI** | `http://<HOST_IP>:8080/cmk/` | `http://checkmk:5000/cmk/` |
| **Checkmk API** | `http://<HOST_IP>:8080/cmk/check_mk/api/1.0/` | `http://checkmk:5000/cmk/check_mk/api/1.0/` |
| **Checkmk Livestatus** | *N/A (not published — internal only, see §5)* | `checkmk:6557` |
| **Mosquitto** | `<HOST_IP>:1883` (requires `poller` credentials — no longer anonymous) | `mosquitto:1883` |
| **Mosquitto (WebSockets)** | `ws://<HOST_IP>:9002` | `ws://mosquitto:9001` |
| **MinIO S3** | `http://<HOST_IP>:9000` | `http://minio:9000` |
| **MinIO Console** | `http://<HOST_IP>:9001` | *N/A (Browser only)* |

Default credentials:

* **Checkmk:** `cmkadmin` / `cmkadmin`
* **MinIO:** `minioadmin` / `minioadmin`
* **Mosquitto (poller, MQTT 1883):** `poller` / `poller`
* **Mosquitto (wsreader, WebSockets 9002, read-only):** `wsreader` / `wsreader`

These Mosquitto credentials are disposable dev/local defaults, same as `cmkadmin`/`minioadmin` above — rotate them (see §3's "First-time credential setup") before exposing this stack beyond a trusted LAN.

### MQTT topic contract (poller)

The `poller` service (`scripts/mqtt_poller.py`) is the only publisher on these topics; everything else is a consumer. Browser clients read them over the WebSockets listener (§1's endpoint table) with the read-only `wsreader` credentials — only the `poller` user can publish (`deploy/mosquitto.acl`).

| Topic | Publish Trigger | QoS | Retain | Payload keys |
| --- | --- | --- | --- | --- |
| `lan/devices/{id}/status` | Every poll cycle, for every known device | 0 | true | `id`, `state` (`OK`/`WARN`/`CRIT`/`UNKNOWN`/`DOWN`), `in_downtime`, `acknowledged`, `device_type`, `folder`, `timestamp` |
| `lan/devices/topology` | Only when the id+parents+device_type+folder structure changes vs. the previous cycle | 1 | true | `devices` (list of `{id, parents, device_type, folder}`), `timestamp` |
| `lan/devices/{id}/history` | Only on an actual state transition for that device | 1 | true | Full bounded array (max `HISTORY_MAX_ENTRIES`) of `{timestamp, from, to}` |
| `lan/events/recent` | Only on any device's state transition, or a device add/remove | 1 | true | Full bounded array (max `EVENTS_MAX_ENTRIES`) of `{timestamp, device_id, event, from, to}` |
| `lan/poller/status` | Birth (on connect), heartbeat (every poll cycle), and LWT (on ungraceful disconnect) or graceful stop | 1 | true | `{status, since, last_poll, device_count}` (birth/heartbeat) or `{status: "offline"}` (LWT/graceful stop) |

A removed device is tombstoned by publishing an empty retained payload to its `status` and `history` topics.

---

## 7. Verification & Pipeline Testing

Verify end-to-end communication across the bridge network from inside the worker container. A 401 here is expected and counts as a pass at this point in the guide -- the automation REST user (and its secret, the only credential Checkmk's Bearer auth accepts) is not bootstrapped until Section 8, so a 401 or a 200 both prove the worker reached Checkmk's REST API, as opposed to a connection error, timeout, or proxy-level 404, which would indicate a genuine reachability problem:

```bash
podman compose exec worker bash -c "
  uv run --with paho-mqtt,minio,requests python3 -c '
import requests, os
from minio import Minio

# Checkmk API check
cmk = requests.get(os.environ[\"CMK_REST_API\"] + \"/version\")
print(f\"Checkmk API: {cmk.status_code}\" + (\" (reachable)\" if cmk.status_code in (200, 401) else \" (UNEXPECTED - check network/site status)\"))

# MinIO check
s3 = Minio(\"minio:9000\", access_key=\"minioadmin\", secret_key=\"minioadmin\", secure=False)
print(f\"MinIO Buckets: {s3.list_buckets()}\")
'
"

```

### Broker smoke test

[`scripts/smoke_test_broker.py`](../scripts/smoke_test_broker.py) proves the Mosquitto hardening actually holds against a live broker — configuration alone doesn't demonstrate it. From the repo checkout on the deployment host:

```bash
uv run python scripts/smoke_test_broker.py
```

From inside the `worker` container (which cannot restart its sibling `mosquitto` service, hence `--skip-restart`):

```bash
uv run python scripts/smoke_test_broker.py --host mosquitto --ws-port 9001 --skip-restart
```

What each check proves:

- `poller_publish` / `ws_subscribe` — the WebSockets listener is reachable and distinct from 1883
- `ws_publish_denied` — the `wsreader` ACL is read-only; a write attempt never reaches an independent privileged subscriber
- `persistence_across_restart` — a retained message survives a broker restart (skipped by `--skip-restart`)

### Poller smoke test

[`scripts/smoke_test_poller.py`](../scripts/smoke_test_poller.py) proves the live Livestatus column set and four of the five Phase 9 success criteria against a running stack — configuration alone doesn't demonstrate any of this. From the repo checkout on the deployment host:

```bash
uv run python scripts/smoke_test_poller.py
```

From inside the `worker` container (which cannot restart or kill its sibling `poller` service, hence `--skip-restart-checks`):

```bash
uv run python scripts/smoke_test_poller.py --host mosquitto --livestatus-host checkmk --skip-restart-checks
```

What each check proves:

- `check_livestatus_columns` — the live site's `hosts` table actually exposes the columns the poller queries (resolves RESEARCH.md Open Question 1)
- `check_device_status_retained` — Success Criterion 1 (PLR-03, PLR-08): a retained `lan/devices/{id}/status` payload matches the fixed contract
- `check_topology_retained` — the payload half of PLR-01/PLR-04
- `check_poller_liveness` — the positive half of Success Criterion 5 (PLR-07): the poller's own heartbeat
- `check_topology_quiet` — Success Criterion 3 (PLR-04): unrelated poll cycles produce no topology republish (skipped by `--skip-slow`)
- `check_ghost_tombstone` — Success Criterion 4 (PLR-06): a host that disappeared while the poller was down gets tombstoned (skipped by `--skip-restart-checks`)
- `check_lwt_offline` — the LWT half of Success Criterion 5 (PLR-07) (skipped by `--skip-restart-checks`)

`uv run python scripts/mqtt_poller.py --check-columns` is the standalone way to confirm which Livestatus `hosts` columns a given site actually exposes, without running the full smoke test.

**Manual tombstone test:** the fifth Phase 9 success criterion (a real Checkmk host deletion) needs a live Checkmk site to delete a host from, so it isn't automated. Delete a host in the Checkmk UI, activate changes, wait one poll interval, then confirm with:

```bash
mosquitto_sub -h <host> -p 1883 -u poller -P poller -t 'lan/devices/<host>/status' -v
```

that the retained payload is now empty and the host is gone from `lan/devices/topology`.

---

## 8. Installing & Running checkmk-wizard

The `worker` container has no local `omd` — checkmk-wizard auto-detects this at startup and switches to **container mode**: it can't create/delete the OMD site itself, but it can fully configure a site the `checkmk` container already created (folders, network discovery, host onboarding, agent install, activation), driving it entirely over the REST API, SSH out to target hosts, and Livestatus-over-TCP (§5).

### 8.1. Get the code onto the host

Clone (or copy) this repository into the `app/` directory you created in §2, **on the host** — it lands inside the worker container at `/app/checkmk-wizard` via the existing bind mount, so nothing needs building into the image:

```bash
cd checkmk-stack/app
git clone <this-repo-url> checkmk-wizard
# or: cp -r /path/to/your/local/checkmk-wizard .
```

### 8.2. Install dependencies (one-time, or after pulling updates)

`uv` is already installed by the worker's boot command (`pip install uv`, see §3). Sync the wizard's own dependencies into its own project-local virtualenv:

```bash
podman compose exec worker bash -c "cd /app/checkmk-wizard && uv sync"
```

### 8.3. Run the wizard

Needs a real TTY — `questionary` (the interactive-prompt library the wizard uses) won't render without one, so don't drop the `-it`:

```bash
podman compose exec -it worker bash -c "cd /app/checkmk-wizard && uv run checkmk-wizard"
```

What to expect, that's different from running it directly on a Checkmk host:

- **Phase 1 opens by announcing container mode** ("'omd' isn't on PATH — assuming this wizard is running in a separate container from Checkmk itself") and skips straight to a site-name prompt, pre-filled with `dmc` from the `CMK_SITE_ID` env var (§3) — just confirm it, or type a different name if you changed `CMK_SITE_ID` on the `checkmk` service.
- **Checkmk host/IP prompt:** pre-filled with `checkmk` (the service's hostname on `cmk_net`, which is what actually resolves to Checkmk from inside the `worker` container) — just press Enter, and only type a different host if the Checkmk service is reachable under another name.
- **Livestatus reachability check:** warns immediately if §5 wasn't done yet — fix it and re-run, or ignore and fix it before Phase 7.
- **cmkadmin password prompt:** pre-filled from the `worker` container's own `CMK_PASSWORD` (§3) — press Enter to accept it. The wizard uses it once, over the REST API, to bootstrap the `automation` and `agent_registration` REST users itself — it's never stored anywhere by the wizard. Clear it and leave it blank instead if you'd rather paste an automation secret directly (fetched via `podman compose exec checkmk cat /omd/sites/dmc/var/check_mk/web/automation/automation.secret`, for example).
- **Phase 3 network scanning / Phase 5 SSH onboarding** reach out to your actual LAN from the `worker` container over `cmk_net`'s bridge (outbound NAT) — same subnets/targets you'd scan and SSH into from any other host on that network, no extra container networking config needed.

### 8.4. Re-running later

Nothing here needs repeating on every run except §8.3 itself — dependencies (§8.2) and Livestatus TCP (§5) only need doing once (or again after `uv.lock` changes or a site recreation, respectively). checkmk-wizard also detects an already-provisioned `automation`/`agent_registration` user on re-runs and falls back to asking for its existing secret instead of failing (see the main [README.md](../README.md#prerequisites)).

---

## 9. Packaging the Worker as an Image

Once scripts are ready inside `./app`:

1. Add `./app/Dockerfile`:
```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
WORKDIR /app
COPY pyproject.toml* requirements.txt* ./
RUN if [ -f requirements.txt ]; then uv pip install --system -r requirements.txt; \
    elif [ -f pyproject.toml ]; then uv pip install --system .; fi
COPY . .
CMD ["python", "main.py"]

```


2. Build:
```bash
podman build -t my-custom-worker:1.0.0 ./app

```


3. Update `compose.yaml` to reference `image: my-custom-worker:1.0.0` under the `worker` service.


While `restart: unless-stopped` is configured in `compose.yaml`, **rootless Podman does not run a background daemon**. When the host reboots, systemd starts your user session (thanks to `loginctl enable-linger`), but it does not execute `podman compose up` on its own.

To make the stack start on system boot, create a systemd user service.

---

### Step 1: Create the systemd User Service

Create the systemd user directory if it doesn't exist:

```bash
mkdir -p ~/.config/systemd/user

```

Create `~/.config/systemd/user/checkmk-stack.service`:

```ini
[Unit]
Description=Checkmk, Mosquitto, MinIO, and Worker Podman Compose Stack
Wants=network-online.target
After=network-online.target podman.socket

[Service]
Type=oneshot
RemainAfterExit=yes
# Set working directory to your checkmk-stack folder
WorkingDirectory=%h/checkmk-stack
Environment="DOCKER_HOST=unix:///run/user/%U/podman/podman.sock"

# Start the stack on boot
ExecStart=/usr/bin/podman compose up -d

# Stop the stack cleanly on shutdown/reboot
ExecStop=/usr/bin/podman compose down

[Install]
WantedBy=default.target

```

*(Note: `%h` automatically resolves to your home directory, e.g., `/home/kone`, and `%U` to your UID `1000`).*

---

### Step 2: Enable and Start the Service

Reload the systemd user daemon and enable the service:

```bash
# Reload user unit files
systemctl --user daemon-reload

# Enable to launch on boot
systemctl --user enable checkmk-stack.service

# Start it immediately (or verify it attaches to the running stack)
systemctl --user start checkmk-stack.service

```

---

### Step 3: Verify Status

Check that systemd recognizes the active stack:

```bash
systemctl --user status checkmk-stack.service

```

*Expected output: `Active: active (exited)` with `RemainAfterExit=yes`.*

---

### Step 4: Verification Check

Ensure user lingering remains active:

```bash
loginctl show-user $USER | grep Linger
# Output: Linger=yes

```

The system will now invoke `podman compose up -d` under your user context during host boot before any user logs in, and issue a clean `podman compose down` during shutdown or reboot.

If you see error like
systemctl --user status checkmk-stack.service
× checkmk-stack.service - Checkmk, Mosquitto, MinIO, and Worker Podman Compose Stack
     Loaded: loaded (/home/kone/.config/systemd/user/checkmk-stack.service; enabled; preset: enabled)
     Active: failed (Result: exit-code) since Wed 2026-09-02 05:22:00 UTC; 21s ago
    Process: 228833 ExecStart=/usr/bin/podman compose up -d (code=exited, status=1/FAILURE)
   Main PID: 228833 (code=exited, status=1/FAILURE)
        CPU: 148ms

Sep 02 05:22:00 kone-dmc-test podman[228845]:  Volume checkmk-stack_checkmk_data Created
Sep 02 05:22:00 kone-dmc-test podman[228845]:  Volume checkmk-stack_checkmk_data Created
Sep 02 05:22:00 kone-dmc-test podman[228845]:  Container checkmk Creating
Sep 02 05:22:00 kone-dmc-test podman[228845]:  service:worker:1 Error response from daemon: container create: creating container storage: the container nam>
Sep 02 05:22:00 kone-dmc-test podman[228845]:  Volume checkmk-stack_mosquitto_data Error error during connect: Post "http://%2Frun%2Fuser%2F1000%2Fpodman%2>
Sep 02 05:22:00 kone-dmc-test podman[228845]: Error response from daemon: container create: creating container storage: the container name "automation-work>
Sep 02 05:22:00 kone-dmc-test podman[228833]: Error: executing /usr/libexec/docker/cli-plugins/docker-compose up -d: exit status 1
Sep 02 05:22:00 kone-dmc-test systemd[221094]: checkmk-stack.service: Main process exited, code=exited, status=1/FAILURE
Sep 02 05:22:00 kone-dmc-test systemd[221094]: checkmk-stack.service: Failed with result 'exit-code'.
Sep 02 05:22:00 kone-dmc-test systemd[221094]: Failed to start checkmk-stack.service - Checkmk, Mosquitto, MinIO, and Worker Podman Compose Stack.

Look at the line truncated in the log:

```text
Error response from daemon: container create: creating container storage: the container name "automation-work[er]...

```

The error is **`the container name "automation-worker" is already in use by...`** (or `checkmk` / `mosquitto`).

Because we manually ran `podman compose up -d` earlier, existing containers with those static `container_name` values already exist. When systemd executed `podman compose up -d`, it tried to recreate them and crashed due to the name collision.

---

### Step 1: Clean Up Orphaned / Existing Containers

Stop and remove any existing containers that were created manually so systemd can take full ownership:

```bash
# Move to stack directory
cd ~/checkmk-stack

# Take down any running compose units
podman compose down

# If any stray containers still linger with those names, remove them:
podman rm -f checkmk mosquitto minio automation-worker 2>/dev/null || true

```

---

### Step 2: Add `PATH` to the systemd Service

When `podman compose` delegates to `/usr/libexec/docker/cli-plugins/docker-compose`, systemd user services run with a minimal `PATH` that often lacks standard binary locations like `/usr/local/bin` and `/usr/bin`.

Update `~/.config/systemd/user/checkmk-stack.service`:

```ini
[Unit]
Description=Checkmk, Mosquitto, MinIO, and Worker Podman Compose Stack
Wants=network-online.target
After=network-online.target podman.socket

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=%h/checkmk-stack
Environment="DOCKER_HOST=unix:///run/user/%U/podman/podman.sock"
Environment="PATH=/usr/local/bin:/usr/bin:/bin"

# Commands
ExecStart=/usr/bin/podman compose up -d
ExecStop=/usr/bin/podman compose down

[Install]
WantedBy=default.target

```

---

### Step 3: Reload and Start the Service

```bash
# 1. Reload the systemd daemon
systemctl --user daemon-reload

# 2. Start the service
systemctl --user start checkmk-stack.service

# 3. Check status
systemctl --user status checkmk-stack.service

```

You should see:

```text
Active: active (exited) since ...

```

And verify the containers are up:

```bash
podman ps

```
