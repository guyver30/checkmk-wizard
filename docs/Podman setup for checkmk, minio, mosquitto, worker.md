# Decoupled Checkmk, Mosquitto, MinIO & Automation Worker Stack

A modular, rootless Podman deployment running stock official images across an isolated bridge network with full external LAN access. `checkmk-wizard` runs from the `worker` container in **container mode** (see [docs/WIZARD-OPERATION.md](WIZARD-OPERATION.md) and the main [README.md](../README.md#prerequisites) for how that mode differs from running the wizard directly on a Checkmk host) — it never touches the `checkmk` container's filesystem or `omd` binary, only its REST API and Livestatus-over-TCP port.

---

## 1. Prerequisites (Rootless Podman Setup)

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

```text
checkmk-stack/
├── compose.yaml
├── mosquitto.conf
└── app/
    └── checkmk-wizard/     # checkout of the checkmk-wizard repo — see §8

```

Create the working directory and workspace folder:

```bash
mkdir -p checkmk-stack/app
cd checkmk-stack

```

---

## 3. Configuration Files

### `mosquitto.conf`

Configures listener binding to all container interfaces (`0.0.0.0`) so both internal containers and external LAN devices can reach the broker.

```text
listener 1883 0.0.0.0
allow_anonymous true
persistence true
persistence_location /mosquitto/data/

```

### `compose.yaml`

Uses official, unmodified images. Podman-compatible `tmpfs` flags (`mode=1777`) prevent permission errors for the unprivileged Checkmk site user (`UID 1000`).

```yaml
services:
  # 1. Official Checkmk Raw
  checkmk:
    image: checkmk/check-mk-raw:2.4.0-latest
    container_name: checkmk
    restart: unless-stopped
    hostname: checkmk
    environment:
      - CMK_SITE_ID=dmc
      - CMK_PASSWORD=cmkadmin
      - TZ=Asia/Singapore
    ports:
      - "8080:5000"     # Web UI
      - "8000:8000"     # Agent TLS registration
      - "6556:6556"     # Agent pull mode
    volumes:
      - checkmk_data:/omd/sites
      - /etc/localtime:/etc/localtime:ro
    tmpfs:
      - /omd/sites/dmc/tmp:rw,size=512M,mode=1777
    networks:
      - cmk_net

  # 2. Mosquitto Broker
  mosquitto:
    image: eclipse-mosquitto:2
    container_name: mosquitto
    restart: unless-stopped
    ports:
      - "1883:1883"
    volumes:
      - ./mosquitto.conf:/etc/mosquitto/mosquitto.conf:ro,z
      - mosquitto_data:/mosquitto/data:z
      - mosquitto_log:/mosquitto/log:z
    networks:
      - cmk_net

  # 3. MinIO S3 Object Storage
  minio:
    image: minio/minio:latest
    container_name: minio
    restart: unless-stopped
    command: server /data --console-address ":9001"
    environment:
      - MINIO_ROOT_USER=minioadmin
      - MINIO_ROOT_PASSWORD=minioadmin
    ports:
      - "9000:9000"     # S3 API Endpoint
      - "9001:9001"     # Web Console
    volumes:
      - minio_data:/data:z
    networks:
      - cmk_net

  # 4. Automation Worker (Python 3.12 + uv) — runs checkmk-wizard (§8) and
  # any other scripts placed under ./app, e.g. the MQTT publisher.
  worker:
    image: python:3.12-slim
    container_name: automation-worker
    restart: unless-stopped
    working_dir: /app
    volumes:
      - ./app:/app:z
    environment:
      - CMK_REST_API=http://checkmk:5000/dmc/check_mk/api/1.0
      - CMK_SITE=dmc
      # Same name/value as the checkmk service's own CMK_SITE_ID above —
      # checkmk-wizard reads this (if present) to pre-fill its site-name
      # prompt in container mode, since it has no local 'omd' to list
      # sites with and no network-based way to discover one either.
      - CMK_SITE_ID=dmc
      - MQTT_HOST=mosquitto
      - MQTT_PORT=1883
      - S3_ENDPOINT=http://minio:9000
      - S3_ACCESS_KEY=minioadmin
      - S3_SECRET_KEY=minioadmin
    command: >
      bash -c "pip install --no-cache-dir uv &&
               tail -f /dev/null"
    networks:
      - cmk_net

volumes:
  checkmk_data:
  mosquitto_data:
  mosquitto_log:
  minio_data:

networks:
  cmk_net:
    driver: bridge

```

**Note on `CMK_PASSWORD`:** this is the `cmkadmin` login password checkmk-wizard's container mode will ask you to re-enter at Phase 1, so it can bootstrap the site's `automation`/`agent_registration` REST users itself (see §8.3). `cmkadmin` is fine for a disposable local/test stack; change it to something you'd actually want to type before running this against anything you care about.

---

## 4. Deployment

```bash
# Start all containers in the background
podman compose up -d

# Verify initialization
podman compose ps

```

---

## 5. Enable Livestatus-over-TCP (required for checkmk-wizard)

checkmk-wizard's Phase 7 post-activation health check connects to the site's Livestatus port over **TCP**, not the local UNIX socket — that's what lets it run from the separate `worker` container instead of needing local filesystem access to `checkmk`'s `/omd/sites`. This has to be turned on once per site; it isn't on by default on a container-created site.

Run this once, right after the site first comes up (a fresh `podman compose up`, or any time you delete/recreate the site inside the `checkmk` container):

```bash
podman compose exec checkmk omd config dmc set LIVESTATUS_TCP on
podman compose exec checkmk omd restart dmc
```

This binds Livestatus on port **6557** by default (Checkmk's own default `LIVESTATUS_TCP_PORT`) — matching what checkmk-wizard already expects, so nothing else needs configuring. No `ports:` entry is needed in `compose.yaml` for this: containers on the same `cmk_net` bridge can already reach `checkmk:6557` directly by service name, without publishing the port to the host/LAN — and it should stay that way, since Livestatus's wire protocol has no authentication of its own and relies entirely on network-level isolation.

*(There's also a documented `CMK_LIVESTATUS_TCP` boot-time environment variable for the official image that may let you skip this manual step — not verified here against this specific image/version, so the `omd config`/`omd restart` steps above are the confirmed way. If you try the env var, verify Phase 7 actually works end-to-end before relying on it.)*

If you skip this step, checkmk-wizard still runs fine through Phase 6 — it just prints a warning at Phase 1 ("Could not reach Livestatus on checkmk:6557") and Phase 7's host-state table will fail at the very end of the run.

---

## 6. Endpoints & Network Access

| Service | LAN / Browser URL | Internal Network DNS (Inside Containers) |
| --- | --- | --- |
| **Checkmk UI** | `http://<HOST_IP>:8080/cmk/` | `http://checkmk:5000/cmk/` |
| **Checkmk API** | `http://<HOST_IP>:8080/cmk/check_mk/api/1.0/` | `http://checkmk:5000/cmk/check_mk/api/1.0/` |
| **Checkmk Livestatus** | *N/A (not published — internal only, see §5)* | `checkmk:6557` |
| **Mosquitto** | `<HOST_IP>:1883` | `mosquitto:1883` |
| **MinIO S3** | `http://<HOST_IP>:9000` | `http://minio:9000` |
| **MinIO Console** | `http://<HOST_IP>:9001` | *N/A (Browser only)* |

Default credentials:

* **Checkmk:** `cmkadmin` / `cmkadmin`
* **MinIO:** `minioadmin` / `minioadmin`

---

## 7. Verification & Pipeline Testing

Verify end-to-end communication across the bridge network from inside the worker container:

```bash
podman compose exec worker bash -c "
  uv run --with paho-mqtt,minio,requests python3 -c '
import requests, os
from minio import Minio

# Checkmk API check
cmk = requests.get(os.environ[\"CMK_REST_API\"] + \"/domain-types/version/actions/show/invoke\")
print(f\"Checkmk API: {cmk.status_code}\")

# MinIO check
s3 = Minio(\"minio:9000\", access_key=\"minioadmin\", secret_key=\"minioadmin\", secure=False)
print(f\"MinIO Buckets: {s3.list_buckets()}\")
'
"

```

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
- **Checkmk host/IP prompt:** enter `checkmk` (the service's hostname on `cmk_net` — the default "localhost" suggestion won't resolve from inside the `worker` container).
- **Livestatus reachability check:** warns immediately if §5 wasn't done yet — fix it and re-run, or ignore and fix it before Phase 7.
- **cmkadmin password prompt:** enter whatever `CMK_PASSWORD` is set to on the `checkmk` service (§3). The wizard uses it once, over the REST API, to bootstrap the `automation` and `agent_registration` REST users itself — it's never stored anywhere by the wizard. Leave it blank instead if you'd rather paste an automation secret directly (fetched via `podman compose exec checkmk cat /omd/sites/dmc/var/check_mk/web/automation/automation.secret`, for example).
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
