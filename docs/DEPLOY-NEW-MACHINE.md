# Deploying the stack on a new machine

A step-by-step checklist for bringing up the whole containerized stack (Checkmk, Mosquitto, MinIO,
worker, poller, dashboard) on a fresh Linux machine with rootless Podman, from `git clone` to a
populated dashboard. It was followed end to end on a fresh Debian/Ubuntu host on 2026-09-30.

This is the short path. For the reasoning behind each step, troubleshooting and the full
reference, see [`Podman setup for checkmk, minio, mosquitto, worker.md`](<Podman setup for checkmk, minio, mosquitto, worker.md>)
(section numbers below, like §1.1, refer to it).

Some settings are baked in on the **first** start or at image **build** time, so do steps 1–4
before the first `podman compose up`.

## 1. Host prerequisites (one-time, needs sudo)

```bash
sudo apt update
sudo apt install -y podman uidmap podman-compose

# Rootless UID/GID ranges: expect one line in each file
grep "^$USER:" /etc/subuid /etc/subgid

# Let the Checkmk and Mosquitto images resolve by short name (§1.1)
mkdir -p ~/.config/containers
echo 'unqualified-search-registries = ["docker.io"]' > ~/.config/containers/registries.conf

# Podman API socket, and keep containers running after logout (§1.2)
systemctl --user enable --now podman.socket
loginctl enable-linger $USER
echo "export DOCKER_HOST=\"unix:///run/user/$(id -u)/podman/podman.sock\"" >> ~/.bashrc
export DOCKER_HOST="unix:///run/user/$(id -u)/podman/podman.sock"

# Let containers send ICMP; without it PING reports 100% loss on every host (§5.1)
sudo sysctl -w net.ipv4.ping_group_range="0 2147483647"
echo 'net.ipv4.ping_group_range = 0 2147483647' | sudo tee /etc/sysctl.d/99-podman-ping.conf
```

## 2. Clone into the expected layout

The worker mounts the directory **two levels above `deploy/`** as `/app`, and the wizard runs
from `/app/checkmk-wizard`. Give the checkout its own parent directory:

```bash
mkdir -p ~/checkmk-stack/app
cd ~/checkmk-stack/app
git clone <this-repo-url> checkmk-wizard
```

Do not clone straight into `~/checkmk-wizard`: the worker would then mount your whole home
directory as `/app`.

## 3. Secrets and settings to set before the first start

### `deploy/.env` (gitignored)

```bash
cd ~/checkmk-stack/app/checkmk-wizard
cp deploy/.env.example deploy/.env
uv run python -c "import secrets; print(secrets.token_urlsafe(24))"   # value for CMK_REST_SECRET
```

| Variable | Value | Why it matters |
|---|---|---|
| `CMK_REST_SECRET` | The random value generated above | Shared by the worker and the poller. The wizard's Phase 1 sets it as the `automation` user's secret. Empty means the dashboard shows no folders. |
| `CMK_PUBLIC_HOST` | This machine's LAN IP or DNS name | Agents register against `<this>:8000` (wizard Phase 5). |
| `CMK_SITE_ID` | Optional, default `dmc` | The site is created with this name on the first start. Renaming it later needs `omd mv` (§3 "Choosing the site name"). |

### `dashboard-react/src/lib/config.ts`

These values are baked into the dashboard image at build time. Edit them locally and don't
commit them.

- `CHECKMK_BASE_URL`: change `http://<HOST_IP>:8080` to this machine's address. The
  "View in Checkmk" link stays disabled until you do.
- `CHECKMK_SITE`: must match `CMK_SITE_ID`.

## 4. Default credentials in tracked files

Fine on a trusted LAN. Change them before exposing the stack beyond it.

| Credential | Where | How to change it |
|---|---|---|
| `cmkadmin` / `cmkadmin` | `deploy/compose.yaml` `CMK_PASSWORD` | Leave it. The wizard asks for it in Phase 1 and offers to change it. |
| MQTT `poller` / `poller` and `wsreader` / `wsreader` | `deploy/mosquitto.passwd` | `WS_PASSWORD=… POLLER_PASSWORD=… deploy/gen-mosquitto-passwd.sh`, then update the poller's `MQTT_PASSWORD` in `compose.yaml` and `WS_PASSWORD` in `config.ts`. |
| MinIO `minioadmin` / `minioadmin` | `deploy/compose.yaml`, in the `minio` and `worker` services | Edit both places together. |

SSH credentials for the target hosts are asked for during the wizard and are not stored.

## 5. Build and start

```bash
cd ~/checkmk-stack/app/checkmk-wizard/deploy     # always run compose from here
podman compose build dashboard
podman compose up -d
```

MinIO comes from `cgr.dev/chainguard/minio`, pinned by digest, because `minio/minio` is gone from
Docker Hub and `quay.io/minio/minio` no longer allows anonymous pulls (§3 "Note on the MinIO
image").

## 6. Checks after startup

**All six containers are up:**

```bash
podman compose ps
```

Expect `automation-worker`, `checkmk`, `dashboard`, `minio`, `mosquitto` and `mqtt-poller`,
all `Up`. The PORTS column here shows only the ports each image declares, not the host
mappings; that's how `docker-compose` displays Podman containers, so check the mappings with
the next two commands instead.

**Host ports are published and listening:**

```bash
podman ps --format '{{.Names}}  {{.Ports}}'
ss -tln | grep -E ':(8080|8000|6556|1883|9000|9001|9002|8090)\b'
```

| Port | Service |
|---|---|
| 8080 | Checkmk web UI |
| 8000 | Checkmk agent registration |
| 6556 | Checkmk agent pull |
| 1883 | Mosquitto MQTT |
| 9002 | Mosquitto WebSockets (dashboard) |
| 9000 | MinIO S3 API |
| 9001 | MinIO web console |
| 8090 | Dashboard |

The worker and poller publish no ports.

**Endpoints answer, and Livestatus is plain TCP** (use your site name instead of `dmc`):

```bash
curl -s -o /dev/null -w 'checkmk %{http_code}\n'   http://localhost:8080/dmc/check_mk/
curl -s -o /dev/null -w 'minio %{http_code}\n'     http://localhost:9000/minio/health/live
curl -s -o /dev/null -w 'dashboard %{http_code}\n' http://localhost:8090/
podman compose exec checkmk omd config dmc show LIVESTATUS_TCP_TLS
```

Expect `checkmk 302` (the redirect to the login page), `minio 200`, `dashboard 200` and `off`.
If TLS is `on`, the poller can't read Checkmk; see §5.

**The worker got the settings from `deploy/.env`:**

```bash
podman compose exec worker bash -c 'echo ${#CMK_REST_SECRET}'   # a number > 0; prints only the length
podman compose exec worker printenv CMK_PUBLIC_HOST             # this machine's LAN address
```

If either is empty, fix `deploy/.env`, then `podman compose down && podman compose up -d`.

## 7. Run the wizard

```bash
podman compose exec worker bash -c "cd /app/checkmk-wizard && uv sync"
podman exec -it automation-worker bash -c "cd /app/checkmk-wizard && uv run checkmk-wizard"
```

- **Site name** and **Checkmk host** (`checkmk:5000`) are pre-filled; press Enter.
- **cmkadmin password:** type `cmkadmin`, accept the offer to change it, and choose a new one.
  The wizard then creates the `automation` user with your `CMK_REST_SECRET`.
- **Phase 3** asks which network ranges to scan; **Phase 5** asks for SSH credentials.

See [`WIZARD-OPERATION.md`](WIZARD-OPERATION.md) for the full phase-by-phase walkthrough.

## 8. After the wizard

1. Restart the whole stack so the poller picks up the new setup:

   ```bash
   podman compose down && podman compose up -d
   ```

   Always use a full `down`/`up`. Restarting a single service (`podman compose restart poller`)
   once cut Checkmk off from the LAN and turned every host DOWN (§5.1 "A third signature").

2. Check the result:
   - Checkmk UI at `http://<this machine>:8080/<site>/`: log in with the new cmkadmin password.
   - Dashboard at `http://<this machine>:8090`: devices appear, each with its folder.

3. Optional, to enable the dashboard's map edit mode:

   ```bash
   podman exec -it automation-worker bash -c "cd /app/checkmk-wizard && python3 scripts/provision_topology_editor.py"
   ```

   It prints a secret once. Put it in `TOPOLOGY_EDITOR_SECRET` in
   `dashboard-react/src/lib/config.ts` (don't commit it), then rebuild:

   ```bash
   podman compose build dashboard && podman compose down && podman compose up -d
   ```

## 9. Start the stack automatically at boot

A systemd **user** service runs `podman compose up -d` at boot and `podman compose down` at
shutdown. Because lingering is enabled (step 1), it starts at boot without anyone logging in.

Create `~/.config/systemd/user/checkmk-stack.service`:

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/checkmk-stack.service <<'EOF'
[Unit]
Description=Checkmk monitoring stack (Podman Compose)
Wants=podman.socket
After=podman.socket

[Service]
Type=oneshot
RemainAfterExit=yes
# Must be the deploy/ directory you ran `podman compose` from by hand: compose.yaml and
# .env live there, and the directory name sets the compose project name, which prefixes
# the volume names (deploy_checkmk_data, ...). Any other directory either finds no
# compose.yaml or starts a new project with empty volumes.
WorkingDirectory=%h/checkmk-stack/app/checkmk-wizard/deploy
Environment="DOCKER_HOST=unix:///run/user/%U/podman/podman.sock"
# `podman compose` hands off to docker-compose or podman-compose, which it looks up on PATH;
# a user service's default PATH can miss them
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
ExecStart=/usr/bin/podman compose up -d
ExecStop=/usr/bin/podman compose down
TimeoutStopSec=180

[Install]
WantedBy=default.target
EOF
```

`%h` is your home directory and `%U` your numeric user ID. A oneshot unit has no start timeout,
so a slow first image pull at boot is not cut off. The unit leaves out
`network-online.target`: it only exists in the system manager, so a user unit that waits on it
waits on nothing.

Take over the running stack and enable the service:

```bash
cd ~/checkmk-stack/app/checkmk-wizard/deploy
podman compose down                    # the service starts it fresh; volumes are kept
systemctl --user daemon-reload
systemctl --user enable --now checkmk-stack.service
```

Check it:

```bash
systemctl --user status checkmk-stack.service   # expect: Active: active (exited)
loginctl show-user $USER --property=Linger      # expect: Linger=yes
podman compose ps                               # all six containers Up
```

Then reboot once and confirm the stack comes back without logging in, for example by opening
the dashboard on port 8090 from another machine.

If the service fails, read the full error with `journalctl --user -u checkmk-stack.service -e`:

- **`no configuration file provided`**: `WorkingDirectory` doesn't point at `deploy/`.
- **`the container name "…" is already in use`**: containers from a different compose project
  (typically an older layout run from another directory) still exist. Remove them with
  `podman rm -f checkmk mosquitto minio automation-worker mqtt-poller dashboard`, then
  `systemctl --user restart checkmk-stack.service`. Volumes are not removed.

After editing the unit file, run `systemctl --user daemon-reload`. Stopping and starting the
service (`systemctl --user stop` / `start checkmk-stack.service`) does the same full down/up as
running compose by hand.

## Updating later

After every `git pull`, or any `config.ts` edit:

```bash
cd ~/checkmk-stack/app/checkmk-wizard/deploy
podman compose build dashboard && podman compose down && podman compose up -d
podman compose exec worker bash -c "cd /app/checkmk-wizard && uv sync"
```
