# Deploying and operating the stack

The single guide for putting the whole containerized stack (Checkmk, Mosquitto, MinIO, ClickHouse, Grafana,
worker, poller, analytics, dashboard) on a Linux machine with rootless Podman, from `git clone` to a populated
dashboard, and for running it afterwards (updating, backup, starting over, troubleshooting). It was followed
end to end on a fresh Debian/Ubuntu host on 2026-09-30.

Related documents: [`README.md`](../README.md) (what the project is, quick start),
[`WIZARD-OPERATION.md`](WIZARD-OPERATION.md) (what each wizard phase does and how to use it) and
[`../ARCHITECTURE.md`](../ARCHITECTURE.md) (container roles, ports, data flow, MQTT topic contract).

## 0. Overview

### What gets deployed

All containers share the `cmk_net` bridge and are defined in [`deploy/compose.yaml`](../deploy/compose.yaml).

| Container | Image | Job |
|---|---|---|
| `checkmk` | `checkmk/check-mk-raw` | The monitoring system; creates the site on its first start |
| `mosquitto` | `eclipse-mosquitto` | MQTT broker (live state, retained topics, optional cloud bridge) |
| `mqtt-poller` | `python:3.12-slim` | Polls Livestatus, publishes MQTT, writes history to ClickHouse |
| `analytics` | `python:3.12-slim` | Needs, forecasts, incident narration, daily availability rollup |
| `clickhouse`, `minio`, `minio-init` | stock / Chainguard | History store and object storage |
| `grafana` | stock | Analyst dashboards on the history store (login required) |
| `dashboard` | built from `deploy/dashboard.Containerfile` | nginx plus the React SPA on port 8090 |
| `automation-worker` | built from `deploy/worker.Containerfile` | Runs the wizard (container mode); idle otherwise |

### Scripts and what they are for

Run the `deploy/` scripts from anywhere; they change into `deploy/` themselves. Run `podman compose`
yourself from `deploy/`.

| Script | When | What it does |
|---|---|---|
| `deploy/init-env.sh` | Before the first start, and after any `git pull` that adds settings | Creates `deploy/.env` (mode 600), generates every secret, asks for the site name and this machine's LAN address, and writes the default `WS_USERNAME`, `ADMIN_WS_USERNAME`, `TRIAGE_WS_USERNAME` and `CLICKHOUSE_TAG` values explicitly. Never overwrites a value already set. |
| `deploy/run-wizard.sh [options]` | After the stack is up | Checks the worker got its settings, waits for the site to answer, then runs `uv sync` and the wizard inside the worker. `--demo` and `--manage` are passed through. |
| `deploy/redeploy.sh` | After every `git pull` | Rebuilds the `dashboard` and `worker` images, does a full `down`, then `up -d` (which creates every container fresh, so `poller` and `analytics` pick up new code). |
| `deploy/backup.sh` | Before risky changes, or to move to another machine | One tar bundle: Checkmk site, map drawing and a copy of `.env`. |
| `deploy/restore_backup.sh BUNDLE` | On the new machine | Restores that bundle and starts the stack. |
| `deploy/reset-site.sh` | To start over with a blank site (optionally a new name) | Wipes the site, broker and map drawing volumes and recreates the site. |
| `deploy/render-mosquitto-acl.sh`, `deploy/render-mosquitto-bridge.sh` | Run by the `mosquitto` container at every start | Render the per-site ACL and the optional cloud bridge from `.env`. Not run by hand. |
| `deploy/worker.Containerfile`, `deploy/dashboard.Containerfile` | Built by `podman compose build` | The worker image bakes in `uv` and the wizard's dependencies (offline use); the dashboard image compiles the SPA. |
| `scripts/smoke_test_broker.py`, `smoke_test_poller.py`, `smoke_test_history_proxy.py`, `smoke_test_bridge.py` | After deploying or changing the broker, poller or proxies | Prove the broker ACLs, the poller's topics, the read-only history path and the cloud bridge against a live stack (§9). |
| `scripts/provision_topology_editor.py` | Only as a manual fallback | The wizard already provisions the `topology_editor` user; this does the same without a wizard run. |
| `scripts/seed_fake_history.py` | Demos | Backfills a synthetic metric series so a forecast or trend need appears on demand. |
| `scripts/probe_*.py` | Development | One-off probes of Checkmk REST shapes; not part of a deployment. |

### The sequence for a new machine

1. **Prerequisites** (§1, needs sudo, one time) and **clone** (§2).
2. **Settings** (§3): `deploy/init-env.sh`, then the cloud-feed values if you use them. These are read on the
   **first** start or at image **build** time, so do them before the first `podman compose up`.
3. **Build and start** (§5), while the machine is online: `podman compose build dashboard worker`, then
   `podman compose up -d`. **Check** the result (§6).
4. **Run the wizard** (§7): `deploy/run-wizard.sh`. It needs the stack up and the site answering.
5. **Restart the whole stack** once (§8) so the poller sees the new setup, then look at the dashboard.
6. **Start at boot** (§10), optionally.

Day two: update with `deploy/redeploy.sh` (§11.1), back up with `deploy/backup.sh` (§11.2).

### Where commands run

The host needs only `podman`, `podman compose` and the `deploy/*.sh` scripts (plus plain `curl`, `ss` and
`systemctl`). Everything else runs **inside a container**, so every `uv`, `python` or MQTT command in this guide is
given as a `podman exec` / `podman compose exec` line. Run `podman compose ...` from `deploy/`.

| To do this | Run |
|---|---|
| The wizard, `uv`, `python`, `pytest`, the smoke scripts | `podman exec automation-worker bash -c "cd /app/checkmk-wizard && <command>"` (add `-it` when it prompts). The checkout is bind-mounted at `/app/checkmk-wizard`, so `deploy/.env` is readable there: start a command with `set -a && . deploy/.env && set +a &&` to load the secrets. |
| Read logs | `podman logs --tail 50 <container>` (add `-f` to follow), or `podman compose logs -f <service>`. Containers: `checkmk`, `mosquitto`, `mqtt-poller`, `analytics`, `clickhouse`, `minio`, `grafana`, `dashboard`, `automation-worker`. |
| MQTT (`mosquitto_sub`, `mosquitto_pub`) | `podman exec mosquitto sh -c 'mosquitto_sub -h localhost -u poller -P "$MQTT_POLLER_PASSWORD" -t "<topic>" -C 1 -W 5'`. The broker container already holds the passwords (`MQTT_POLLER_PASSWORD`, `WS_PASSWORD`, ...) in its environment; keep the single quotes so they expand inside the container. |
| Checkmk (`omd`, `lq`) | `podman compose exec checkmk omd <command> <site>` |
| ClickHouse | `podman exec clickhouse clickhouse-client --user ch_admin --password "$CH_ADMIN_PASSWORD" -q "<sql>"` after `set -a; . ./.env; set +a` in `deploy/` |
| The poller's own tools | `podman exec mqtt-poller python -u /scripts/mqtt_poller.py --check-columns` |

The wizard's `uv sync` and `uv run` work offline because the worker image carries the dependencies (§5). Nothing
needs `uv` or Python installed on the host.

Never restart a single container on its own (`podman compose restart <service>`, `podman restart ...`): on
rootless Podman it has cut Checkmk off from the LAN and turned every host DOWN (§12.3). Always use a full
`podman compose down && podman compose up -d`; volumes are kept.

## 1. Host prerequisites (one-time, needs sudo)

```bash
sudo apt update
sudo apt install -y git curl podman uidmap podman-compose

# Rootless UID/GID ranges: expect one line in each file
grep "^$USER:" /etc/subuid /etc/subgid

# Let the Checkmk and Mosquitto images resolve by short name
mkdir -p ~/.config/containers
echo 'unqualified-search-registries = ["docker.io"]' > ~/.config/containers/registries.conf

# Podman API socket, and keep containers running after logout
systemctl --user enable --now podman.socket
sudo loginctl enable-linger $USER
echo "export DOCKER_HOST=\"unix:///run/user/$(id -u)/podman/podman.sock\"" >> ~/.bashrc
export DOCKER_HOST="unix:///run/user/$(id -u)/podman/podman.sock"

# Let containers send ICMP; without it PING reports 100% loss on every host (§12.2)
sudo sysctl -w net.ipv4.ping_group_range="0 2147483647"
echo 'net.ipv4.ping_group_range = 0 2147483647' | sudo tee /etc/sysctl.d/99-podman-ping.conf
```

Notes on these steps:

- **Packages.** `git` is needed for the `git clone` in §2 and every later `git pull`; `curl` for the checks in §6 and the `curl` calls later in this guide. Debian 12+ and Ubuntu 22.04+ ship a Podman recent enough for `podman compose`; older
  releases do not. `uidmap` provides `newuidmap`/`newgidmap`, without which rootless Podman cannot start a
  container. On RHEL, Fedora or CentOS Stream use `sudo dnf install -y git curl podman podman-compose`.
  `podman compose` is only a shim: it delegates to `docker-compose` or `podman-compose`, so one of them must be
  installed.
- **Old or low-end CPU.** If `clickhouse` later exits with code 132, see §12.5 (`CLICKHOUSE_TAG`).
- **Verify the install.** `git --version`; `curl --version`; `podman --version`; `podman info --format '{{.Host.Security.Rootless}}'` must print
  `true` (if it prints `false` you are root and the rootless assumptions here do not hold);
  `podman run --rm docker.io/library/hello-world`.
- **Rootless UID/GID ranges.** The distro package normally allocates them, so the `grep` is a check. If a file
  has no line for your user, add one and re-map existing containers:
  `sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER && podman system migrate`.
- **Short names.** A fresh Podman has no `unqualified-search-registries`, so `checkmk/check-mk-raw:...` and
  `eclipse-mosquitto:2` fail with `short-name ... did not resolve to an alias`. That is Podman's
  anti-typosquatting default, not a broken install (the `hello-world` check passes because it is fully
  qualified). The per-user `registries.conf` above takes precedence over `/etc/containers/registries.conf`
  and only re-enables resolution against Docker Hub. After adding it, just re-run `podman compose up -d`:
  the failed services never created a container, so existing volumes and the network are reused.
- **`DOCKER_HOST`** points the compose provider at the rootless Podman socket. The `1000` in some older
  examples is your UID; the commands above use `$(id -u)`.
- **Which compose provider you have.** `podman compose` only forwards to an external tool, and the output
  depends on which one: with `docker-compose` you see tidy `Container x Started` lines; with `podman-compose`
  you see every raw `podman run ...` command, `exit code:` lines and a `>>>> Executing external compose
  provider ...` header. If both are installed, Podman 4.9 prefers `docker-compose`. Check with
  `podman compose version` and `which docker-compose podman-compose`; force one by setting
  `PODMAN_COMPOSE_PROVIDER=/usr/bin/podman-compose` (or `docker-compose`) in the shell, or `compose_providers`
  in `~/.config/containers/containers.conf`. **Recommended: `podman-compose` 1.0.6**, the package from step 1.
  This stack was developed and checked against it, and `deploy/compose.yaml` carries workarounds for its
  behaviour (for example no `depends_on` on `minio-init`). `docker-compose` should also work through the
  Podman socket but has not been tested here. Expected `podman-compose` noise, not errors: `exit code: 125` /
  `1` with "no such container" or "name already in use" followed by a successful `podman start`, and its
  output prints each container's environment, secrets included, so do not paste that log anywhere shared.
  Use the same provider on every machine so the behaviour described in this guide matches.

## 2. Clone into the expected layout

The worker mounts the directory **two levels above `deploy/`** as `/app`, and the wizard runs
from `/app/checkmk-wizard`. Give the checkout its own parent directory:

```bash
mkdir -p ~/checkmk-stack/app
cd ~/checkmk-stack/app
git clone <this-repo-url> checkmk-wizard
```

Do not clone straight into `~/checkmk-wizard`: the worker would then mount your whole home
directory as `/app`. Run `podman compose` from the checkout's own `deploy/` directory, not from a copy of it:
`compose.yaml` bind-mounts `../scripts` and `../analytics`, and the directory name `deploy` sets the compose
project name that prefixes the volume names (`deploy_checkmk_data`, ...). If your layout cannot follow this
structure, set `POLLER_SCRIPTS_DIR` to an absolute path to this repo's `scripts/` directory instead.

## 3. Settings to set before the first start

### 3.1 `deploy/.env` (gitignored)

```bash
~/checkmk-stack/app/checkmk-wizard/deploy/init-env.sh
```

`init-env.sh` creates `deploy/.env` from `.env.example` if it's missing and sets its mode to
600. It generates every secret below, asks for the site name (default `dmc`), and lists this
machine's IPv4 addresses so you can pick `CMK_PUBLIC_HOST`, or type an address or DNS name
yourself. It never overwrites a value that is already set, so it's safe to re-run. It never
prints the secret values, and it ends with a short note for existing installs. Then do the full `podman compose down && podman compose up -d` (§5).

| Variable | Value | Why it matters |
|---|---|---|
| `CH_ADMIN_PASSWORD`, `CH_WRITER_PASSWORD`, `CH_READER_PASSWORD`, `CH_GRAFANA_PASSWORD`, `GRAFANA_ADMIN_PASSWORD` | Generated by `init-env.sh` | Phase 14.1 history store. ClickHouse reads them only when its volume is first created, so they must be set before the first start. See `.env.example` for rotation. |
| `WS_USERNAME`, `ADMIN_WS_USERNAME`, `TRIAGE_WS_USERNAME` | Written by `init-env.sh` (`wsreader`, `wsadmin`, `wstriage`) | The broker users the dashboard's `/config.json`, `/admin-config.json` and `/triage-config.json` hand to the browser. Compose has the same defaults, but some `podman-compose` versions pass `${WS_USERNAME:-wsreader}` into the container as literal text when the variable is not in `.env`, and the `dashboard` then exits with `nginx: [emerg] the closing bracket in "WS_USERNAME" variable is missing`. `init-env.sh` writes the values so this cannot happen. If you see that error on an older `.env`, re-run `deploy/init-env.sh`, then a full `podman compose down && podman compose up -d`. |
| `CLICKHOUSE_TAG` | Written by `init-env.sh` as `26.9.4.3` | ClickHouse image tag. Set it (e.g. `25.8.33.6`) on a machine whose CPU has no AVX, such as the Intel Celeron N5105: 26.9.4.3 crashes there with exit code 132 (`Illegal instruction`). See §12.5. |
| `CMK_REST_SECRET` | Generated by `init-env.sh` | Shared by the worker and the poller. The wizard's Phase 1 sets it as the `automation` user's secret. Empty means the dashboard shows no folders. |
| `TOPOLOGY_EDITOR_SECRET` | Generated by `init-env.sh` | Amended 2026-09-30, quick 260930-hpy: read by the worker (the wizard creates/rotates the scoped `topology_editor` user to it right after Phase 1) and by the dashboard's nginx (injected server-side into the allow-listed `/checkmk-api/` calls — never sent to the browser). Empty keeps the map's "Edit topology" switch disabled. |
| `CMK_PUBLIC_HOST` | This machine's LAN IP or DNS name, picked in `init-env.sh` | Agents register against `<this>:8000` (wizard Phase 5). |
| `CMK_SITE_ID` | Asked by `init-env.sh`, default `dmc` | The site is created with this name on the first start. Renaming it later needs `omd mv` (§3.4), or `deploy/reset-site.sh`, which wipes the site and recreates it under a new name. The dashboard also picks it up at container start (quick 260930-ixs, no rebuild). It is also the MQTT namespace (`sites/<site_id>/...` on the broker) and must be globally unique across every site that feeds the same broker; nothing checks this for you, so pick distinct names. The `mosquitto` service renders its ACL from `CMK_SITE_ID` at start. |
| `MQTT_POLLER_PASSWORD` | Generated by `init-env.sh` | Added 2026-09-30, quick 260930-jj4. Required (compose refuses to start without it). Broker user `poller`, used by the `mosquitto` service (which writes its password file from it at every start) and the poller's authenticated write path. Rotate by editing `deploy/.env`, then a full `podman compose down && podman compose up -d`. |
| `WS_PASSWORD` | Generated by `init-env.sh` | Amended 2026-09-30, quick 260930-jj4 (was optional, default `wsreader`). Required (compose refuses to start without it). Broker user `wsreader`, used by `mosquitto` and served to the browser by the dashboard via `/config.json`. Same rotation as above. |
| `WS_USERNAME` (optional) | Default `wsreader` | Leave alone unless you also change the user in `deploy/mosquitto.acl.template` and the `mosquitto` service's start-up command in `compose.yaml`. The `wsreader` grant is `read sites/<site_id>/lan/#` only. |
| `ADMIN_WS_PASSWORD` | Generated by `init-env.sh` | Phase 16 admin mode. Required (compose refuses to start without it). Broker user `wsadmin`, reads `sites/<site_id>/lan/#`, `admin/ack` and `admin/faked` under the same prefix, writes only `sites/<site_id>/admin/cmd`; served by the dashboard on `/admin-config.json` for `?admin=1`. The endpoint is open: use it on the closed demo network only. Same rotation as `WS_PASSWORD`. |
| `ADMIN_WS_USERNAME` (optional) | Default `wsadmin` | Leave alone unless you also change the user in `deploy/mosquitto.acl.template` and the `mosquitto` service's start-up command in `compose.yaml`. |
| `MQTT_ANALYTICS_PASSWORD` | Generated by `init-env.sh` | Phase 14.2. Required (compose refuses to start without it). Broker user `analytics`, used by the `mosquitto` service (password file) and the `analytics` container. Reads `sites/<site_id>/lan/#` and `needs/triage/cmd`; writes only `lan/needs/#`, `lan/forecasts/#` and `lan/incidents/+/narration`. Same rotation as `MQTT_POLLER_PASSWORD`. |
| `TRIAGE_WS_PASSWORD` | Generated by `init-env.sh` | Phase 14.2. Required (compose refuses to start without it). Broker user `wstriage` (`TRIAGE_WS_USERNAME`, optional, default `wstriage`), write-only on `sites/<site_id>/needs/triage/cmd`. Served by the dashboard on `/triage-config.json`, an open endpoint, so closed network only (accepted risk: analytics validates and audits every command and it can only change a need's tier). Same rotation as `WS_PASSWORD`. |
| `CH_ANALYTICS_PASSWORD` | Generated by `init-env.sh` | Phase 14.2. ClickHouse user `analytics_writer` (SELECT/INSERT on `history.*`, S3 and `CREATE TEMPORARY TABLE`), used by the `analytics` container. On a fresh `clickhouse_data` volume initdb creates the user and the three new tables from it. On an existing volume it is **not** applied until you run the one-off migration below. |

### 3.2 Analytics settings (optional tuning)

The `analytics` service reads these from its `environment:` block in `deploy/compose.yaml`. Only the first two
are set there today; every other one uses the default from `analytics/config.py`. To change one, add it to that
block and do a full `podman compose down && podman compose up -d`.

| Variable | Default | Meaning |
|---|---|---|
| `POLL_INTERVAL_SECONDS` | `15` (set in compose) | Must equal the poller's; the availability rollup scales sample counts by it. Also the analytics failure-need tick: host-DOWN and service failure needs are evaluated at this cadence. |
| `EVAL_INTERVAL_SECONDS` | `900` (set in compose) | How often forecasts and trend/sustained needs are re-evaluated (failure needs follow `POLL_INTERVAL_SECONDS`, 15 s). |
| `TIER_IMMEDIATE_DAYS` | `3.0` | Days to critical below which a trend need is `immediate`. |
| `TIER_URGENT_DAYS` | `20.0` | Days to critical up to which a trend need is `urgent` (above it, `standard`). |
| `NEED_HORIZON_DAYS` | `90.0` | A trend crossing further out than this is not a need. |
| `FIT_R2_MIN` | `0.70` | Minimum r-squared for a trend to count; below it the series is `no_clear_trend`. |
| `FIT_R2_HIGH` | `0.90` | r-squared needed (with 60+ days of history) for `high` confidence. |
| `FIT_MIN_RISE_30D` | `1.0` | Minimum rise per 30 days (metric units, percent points) for a series to count as `trending`. |
| `CHART_METRICS` | `fs_used_percent,util,mem_used_percent` | Metrics that get a fit and a chart. Invalid names are dropped with a warning. |
| `TREND_NEED_METRICS` | `fs_used_percent,mem_used_percent` | Metrics that can raise a trend need (CPU `util` gets a fit and chart, never a need). |
| `ROLLUP_TZ`, `ROLLUP_BACKFILL_DAYS`, `ROLLUP_DELAY_MINUTES`, `AVAILABILITY_BUCKET` | `Asia/Singapore` (set in compose), `28`, `5`, `fleet-availability` | The daily availability rollup, moved from the poller. |

Live catalog facts the defaults rest on: no SMART/NVMe series exist, so disk-wear prediction is inactive until
one is monitored (analytics logs a warning at start, and its names must be added to `CHART_METRICS`,
`TREND_NEED_METRICS` and, in code, `WEAR_METRICS`); CPU `util` has no Checkmk levels, so analytics applies
fallback levels of 85 (warn) and 95 (crit) from `FALLBACK_LEVELS` in `analytics/config.py`.

### 3.3 Cloud feed (optional)

Phase 17 can forward this site's MQTT data to a shared cloud broker for the S3 archive. It is off unless
`CLOUD_BROKER_HOST` is set; with it empty the stack behaves exactly as before. The traffic is outbound only
and always TLS. Values in `deploy/.env` (all examples are placeholders):

| Variable | Where it comes from |
|---|---|
| `SITE_SEN` | Site equipment number, a positive integer without leading zeros (for example `4711`). The wizard asks for it after Phase 1 and writes it; you can also set it by hand. |
| `CLOUD_BROKER_HOST` | Address of the cloud broker, from the cloud operator. Empty means the feed is off. |
| `CLOUD_BROKER_PORT` | Defaults to `8883`. |
| `CLOUD_BROKER_PASSWORD` | From the cloud operator. Allowed characters: `A-Z a-z 0-9 _ . ~ = + -`, 1 to 256 long. The login name is the SEN. |
| `MQTT_BRIDGE_PASSWORD` | Local broker login `bridge` (read-only over this site's topics). Generated by `deploy/init-env.sh`; run it once on an existing install. |
| `CLOUD_METRICS_HEARTBEAT_S` | Seconds between status heartbeats, default `300`; `0` publishes status every cycle. |

Put the cloud broker's CA certificate at `deploy/certs/cloud-ca.pem` (the directory is gitignored). The
bridge renderer refuses to start without it, so a plaintext WAN link is not possible.

Every change to these values needs a full `podman compose down && podman compose up -d`; compose reads
`deploy/.env` only when containers are created. Data crossing the bridge is remapped from
`sites/<site_id>/` to `app/<SEN>/<site_id>/`; the contract is in [`ARCHITECTURE.md`](../ARCHITECTURE.md)
("Phase 17: cloud contract and archive feed"). During a WAN outage the broker queues up to 20000 messages or
100 MB per client and drops beyond that, so a longer outage leaves a gap in the cloud copy.

### 3.4 Choosing the site name

The site is created by the `checkmk` container's own entrypoint on its **first start** (empty `checkmk_data` volume), long before the wizard runs — and the worker has no `omd`, so the wizard cannot create or rename it. The name therefore has to be decided up front, or changed with `omd mv` afterwards.

**Option 1 — choose it before the first start (recommended).** `deploy/compose.yaml` reads one variable, `CMK_SITE_ID` (default `dmc`), and uses it everywhere the site name appears: the `checkmk` service's `CMK_SITE_ID` and its `/omd/sites/<site>/tmp` tmpfs, the `worker`'s `CMK_SITE_ID`/`CMK_SITE`/`CMK_REST_API`, and the `poller`'s `CMK_SITE_ID`. Set it once in `deploy/.env` (see `deploy/.env.example`) or inline:

```bash
echo 'CMK_SITE_ID=mysite' >> deploy/.env      # or: CMK_SITE_ID=mysite podman compose up -d
podman compose up -d
```

The site name is also the dashboard's MQTT namespace (`sites/mysite/...` on the broker) and must be globally unique across every site that feeds the same broker; there is no central registry, so neither the wizard nor `deploy/init-env.sh` can check this, they only warn. The wizard's site-name prompt is then pre-filled with `mysite`. Site names must start with a letter and be 1–16 letters/digits/underscores. The dashboard now follows `CMK_SITE_ID` automatically too (quick 260930-ixs); the one thing not driven by this variable is the `podman compose exec checkmk omd ... dmc ...` commands in this guide — substitute your name.

**Option 2 — rename an existing site.** If the stack already runs under the wrong name, rename from the host (not the wizard). Note that `omd mv` needs the site stopped:

```bash
podman compose exec checkmk omd stop dmc
podman compose exec checkmk omd mv dmc mysite
```

Then set `CMK_SITE_ID=mysite` in `deploy/.env` and recreate the containers, including the dashboard (`podman compose up -d --force-recreate checkmk worker poller dashboard`) — or a full `podman compose down && podman compose up -d`. Otherwise the checkmk entrypoint's `omd start "$CMK_SITE_ID"` targets the old name and the `tmpfs` mount stays on the old path. Because it is easy to miss one of these places, on a disposable stack it is usually simpler to run `deploy/reset-site.sh` (§11.3). It wipes the site and recreates it under a new name in one step: it asks for the new name and writes `CMK_SITE_ID` to `deploy/.env` for you. Existing agents registered against the old site keep their old URL/certs and must be re-registered after a rename. `omd mv` also moves the MQTT namespace: update `CMK_SITE_ID` in `deploy/.env` and recreate the stack so the ACL is re-rendered, and note that the old `sites/<old>/` retained subtree is left on the broker (nothing clears it automatically).

---

### 3.5 What the settings do, and gotchas

A few things that are not obvious from `compose.yaml` and `.env.example` alone.

**Compose services and the broker.** Mosquitto's listeners bind to all container interfaces so internal
containers and LAN devices can reach it: plain MQTT on 1883 (published for debugging) and a separate
WebSockets listener (published for the browser). `tmpfs` with `mode=1777` on the `checkmk` service avoids
permission errors for the unprivileged site user (UID 1000). The `poller` is its own
`restart: unless-stopped` service, not part of `worker`, so the always-on Livestatus-to-MQTT bridge runs
independently of the wizard.

**Broker passwords.** `MQTT_POLLER_PASSWORD`, `WS_PASSWORD`, `ADMIN_WS_PASSWORD` and the other broker
logins are generated into `deploy/.env` by `deploy/init-env.sh`; no credential file is tracked. `compose up`
refuses to start while a required one is empty (`${VAR:?run deploy/init-env.sh}`). The `mosquitto` entrypoint
builds `/mosquitto/config/mosquitto.passwd` from them (owned by `mosquitto`, mode `0700`, in the container's
writable layer) on every start, never on the host. To rotate one, edit it in `deploy/.env`, then do a full
down/up. If `podman logs mosquitto` shows "owner is not mosquitto" or "world readable permissions", the
`chown`/`chmod` in the `mosquitto` service `entrypoint:` did not run.

**Note on `CMK_PASSWORD`:** this sets the initial `cmkadmin` login password, and only when Checkmk first creates the site. checkmk-wizard's container mode asks for it at Phase 1 (it is not pre-filled — the prompt tells you the default is `cmkadmin` on a fresh site) so it can bootstrap the site's `automation`/`agent_registration` REST users itself (see §7), then offers to change it via the REST API. Keep `cmkadmin` here as the shipped default; there is no need to edit this file after changing the password in the wizard.

**Note on `CMK_PUBLIC_HOST`:** set this in `deploy/.env` (see `deploy/.env.example`) to the address of the machine running Podman, as your LAN hosts reach it (e.g. `192.168.1.20`) — the one publishing ports 8000 (agent registration) and 6556 (agent pull). The `worker` passes it to checkmk-wizard, whose Phase 5 shows it as the address Linux/Windows agents register against (`cmk-agent-ctl register --server <address>:8000`) instead of asking. The worker can't discover it itself: it only sees its own `10.89.x.x` bridge address, which LAN hosts can't reach. If it needs to change, edit it in `deploy/.env` and run `podman compose up -d worker`. Left empty, the wizard warns and asks for the address by hand.

**Note on the MinIO image (changed 2026-09-30):** `minio/minio` was removed from Docker Hub on 2026-09-11, and `quay.io/minio/minio` no longer allows anonymous pulls, so the `minio` service now uses `cgr.dev/chainguard/minio`, pinned by digest (Chainguard's free tier only publishes `:latest`). To update it, look up the new digest and replace the one in `compose.yaml`. The image runs MinIO as non-root UID 65532. A fresh `minio_data` volume works as is. If you're switching a stack whose `minio_data` volume was written by the old image (which ran as root), change the volume's owner once before starting:

```bash
podman compose down
podman unshare chown -R 65532:65532 "$(podman volume inspect --format '{{.Mountpoint}}' deploy_minio_data)"
podman compose up -d
```

The volume name depends on the compose project name; check it with `podman volume ls`.

The one-shot `minio-init` job (Phase 14.1, creates the `clickhouse-s3-disk` and `fleet-availability` buckets on every `up`) uses `cgr.dev/chainguard/minio-client:latest-dev`, pinned by digest — the `-dev` variant specifically, because it ships a shell and `sleep` that the plain `latest` variant's image layers lack. If Chainguard's free-tier images also stop being pullable, the fallback is the same as MinIO's own: cache the last-known-good image locally, or move the bucket store to AWS S3 (D-41), which needs no code change.

**Note on the dashboard (React, served on 8090 since 2026-09-28):** the `dashboard` service (§6)
builds `dashboard-react/` into its own nginx image (`deploy/dashboard.Containerfile`, build context
= the repo root). The image build compiles `design-system/` and the SPA inside a Node container, so
the host needs no Node install. nginx serves the static files, with an SPA fallback for
`/?host=...` (and old `/details?id=...`) bookmarks and a same-origin `/checkmk-api/` route to `checkmk:5000`
(`deploy/dashboard-nginx.conf`). There's no server-side process, and the image carries no
per-machine settings (amended 2026-09-30, quick 260930-ixs): the dashboard service's
`environment:` block passes `CMK_SITE_ID`, `WS_USERNAME`, `WS_PASSWORD`, `ADMIN_WS_USERNAME`, `ADMIN_WS_PASSWORD` (plus the existing
`CH_READER_PASSWORD`/`TOPOLOGY_EDITOR_SECRET`) from `deploy/.env`, and nginx serves the first
three as `/config.json`, which the SPA loads once before first render
(`dashboard-react/src/lib/runtimeConfig.ts`):

- `CMK_SITE_ID` — the same site name used everywhere else in this doc (`dmc` by default). Also
  what the "View in Checkmk" link and every `/checkmk-api/<site>/...` call use.
- `WS_USERNAME`/`WS_PASSWORD` (user `wsreader` by default) — read-only Mosquitto WebSockets
  credentials. `WS_PASSWORD` is generated into `deploy/.env` by `deploy/init-env.sh` and
  required (quick 260930-jj4 — see §3.5 ("Broker passwords")); rotate it by editing
  `deploy/.env`, then a full `podman compose down && podman compose up -d`. The grant behind it
  is read-only (`topic read sites/<CMK_SITE_ID>/lan/#` in the rendered `deploy/mosquitto.acl.template`), so the exposure is bounded to
  reading the device list, never writing to the broker.
- `TOPOLOGY_EDITOR_SECRET` — see the next note.

Rebuild the image only after a `git pull` (code changes only — per-machine settings come from
`deploy/.env` at container start, no rebuild needed), then restart the stack (a full down/up,
not a single-service restart; see §12.3):

```bash
cd deploy && podman compose build dashboard && podman compose down && podman compose up -d
```

The old vanilla dashboard (`dashboard/`) was deleted from the repo on 2026-09-30. For
development with hot reload, see `dashboard-react/README.md` §3.

**Note on the topology editor credential (amended 2026-09-30, quick 260930-hpy — supersedes
Phase 13's client-embedded credential):** the dashboard's map edit mode (§9 "Topology map check") writes to Checkmk's REST API through the dashboard's own nginx, which injects a
dedicated, narrowly-scoped `topology_editor` credential server-side — the browser itself never
holds this secret. Four things to know:

1. **Where it lives:** `TOPOLOGY_EDITOR_SECRET` in `deploy/.env` (gitignored). The worker
   container reads it (the wizard provisions from it) and the dashboard container reads it
   (nginx injects it as the `Authorization` header).
2. **What enforces the scope:** `deploy/dashboard-nginx.conf` allow-lists the exact
   method+path pairs the dashboard's SPA calls (host read/write, unmanaged-switch creation,
   pending-changes count, activation) and injects the credential only on those; every other
   `/checkmk-api/` request — including anything against `user_config`, `user_role`, rulesets,
   or a `DELETE` on a host — returns 403 before it ever reaches Checkmk.
3. **How it's provisioned:** the wizard creates or rotates the scoped `topology_editor`
   Checkmk role and user to `TOPOLOGY_EDITOR_SECRET`'s value right after Phase 1, best-effort
   (a failure here never aborts the wizard run). `scripts/provision_topology_editor.py` remains
   a manual fallback that reads the same env var, for provisioning without a full wizard run.
4. **How to rotate it:** edit `TOPOLOGY_EDITOR_SECRET` in `deploy/.env`, re-run the wizard (or
   `scripts/provision_topology_editor.py`), then a full `podman compose down && podman compose
   up -d`. Do not restart a single container on its own (`podman compose restart dashboard` or
   `restart worker`) — a single-service restart has been observed to break Checkmk's own egress
   (§12.3); always use the full down/up.

Blast radius: the `topology_editor` credential can edit host attributes (`parents`,
`map_position`), add new hosts, and activate pending changes. It cannot manage users, edit global
settings or rulesets. Since 2026-10-12 it also holds `wato.activateforeign`, so the dashboard's
"new hosts discovered" banner can activate the network scan's host creations (Checkmk attributes
those to the scan's user); Activate there activates every pending change, which is why the banner
asks for a second confirmation when non-host changes are pending. Edit-mode Apply still never
forces foreign changes. Existing sites pick the permission up on the next wizard run (or once in
Setup > Users > Roles & permissions > Topology editor (dashboard)). With the secret no
longer reaching the browser at all, a leaked/exfiltrated frontend has nothing to steal in the
first place.

**`CMK_REST_SECRET` (poller).** The `poller` makes an authenticated Checkmk REST call every cycle to read each
host's folder. `compose.yaml` ships `CMK_REST_USERNAME=automation` and interpolates `CMK_REST_SECRET` from
`deploy/.env`; the wizard's Phase 1 sets that exact value as the `automation` user's secret. It defaults to
empty rather than refusing to start compose, because a hard `:?` guard would also block `checkmk` and
`mosquitto` on a first-time deployment, before the wizard can create the user. A missing or wrong secret
degrades folder enrichment (empty `folder` on every device) without stopping the stack. If you leave it
empty, the wizard generates a random secret and prints it once for you to copy into `deploy/.env`.

#### History store (ClickHouse, MinIO, Parquet, Grafana)

**The five `CH_*` / `GRAFANA_*` passwords must be set in `deploy/.env` BEFORE the first `podman compose up`.** ClickHouse's `docker-entrypoint-initdb.d` scripts (`deploy/clickhouse-config/initdb/`) — which create `ch_admin` and the three read/write users — run only once, on the first start of an empty `clickhouse_data` volume. An empty `CH_*` password at that point means the corresponding user is created with an empty or broken password, and setting the variable afterwards does not fix it. If that happens, recover with:

```bash
podman compose down
podman volume rm deploy_clickhouse_data   # confirm the exact name with: podman volume ls
podman compose up -d
```

(the volume name is prefixed with the compose project name, same caveat as `deploy_checkmk_data` in §11.3). This deletes any history recorded so far — there is no in-place password reset for a ClickHouse user whose settings profile already applied, short of `ALTER USER` (see `deploy/.env.example`'s rotation note).

`grafana` refuses to start while `GRAFANA_ADMIN_PASSWORD` is empty or literally `admin` — its entrypoint guard exits before handing off to Grafana's own startup, so an empty-password deployment fails loudly (`podman compose logs grafana`) instead of coming up with a default credential.

**Note on the history store (ClickHouse, MinIO, Parquet):** `clickhouse` keeps roughly 30 days of raw poller-written rows on its local volume, downsamples aging rows to 5-minute then 1-hour aggregates in place, moves parts older than 31 days to the `clickhouse-s3-disk` bucket on `minio`, and deletes anything older than 3 years. The poller writes one INSERT batch per poll cycle and drops it if ClickHouse is unreachable at that moment — the gap simply reads as "no data" later, never as up or down (no local buffering or retry queue). Once a day, shortly after local midnight (`ROLLUP_TZ`, default `Asia/Singapore`), the `analytics` service (not the poller) computes the previous day's availability from `history.host_state` and writes it once to the `fleet-availability` bucket as both JSON (`availability/YYYY/MM/YYYY-MM-DD.json`) and Parquet (`availability_parquet/date=YYYY-MM-DD/availability.parquet`); missing days are backfilled up to `ROLLUP_BACKFILL_DAYS` (default 28) and an existing day object is never overwritten. Switching the whole store from MinIO to AWS S3 later is a configuration change only — endpoint, region and credentials in `deploy/compose.yaml` and `deploy/clickhouse-config/config.d/s3-storage.xml` — not a code change.

#### Analytics service (Phase 14.2)

The `analytics` service (`python -m analytics`, source in `analytics/`, bind-mounted read-only into a `python:3.12-slim` container like the poller) does the following:

- Fits trends to the `history.metrics` series and publishes forecasts (`sites/<site_id>/lan/forecasts/{host}`).
- Derives needs (failure, trend, sustained) with tiers `immediate`/`urgent`/`standard` and publishes them (`lan/needs/{need_id}/status`), applying validated triage commands from the dashboard.
- Narrates incidents (`lan/incidents/{incident_id}/narration`).
- Records durable `history.events`, `history.incidents` and `history.need_triage` rows in ClickHouse, reading the poller's existing `lan/events/recent` and `lan/incidents/+/status` topics.
- Runs the daily availability rollup (moved here from the poller; see the history store note above).

The topic payloads are in [`ARCHITECTURE.md`](../ARCHITECTURE.md). Every endpoint it uses (broker, ClickHouse, MinIO) is an environment variable on the compose service, so it can move off this host without code changes. It has no Livestatus access, so the Livestatus TLS caveat in §12.1 does not apply to it. Analytics degrades a cycle (and logs a warning) while ClickHouse or MinIO is down; it does not exit.

**Read cache (D-01):** `deploy/clickhouse-config/config.d/s3-storage.xml` adds a 2 GiB filesystem read cache (`s3_cache`) to the `s3` disk, stored inside the `clickhouse_data` volume, so forecast reads beyond the 31-day move to MinIO are not an S3 round trip each. It is config only, picked up on the next full down/up.

**Live limits to know about:** no SMART/NVMe series exist in the live catalog, so `WEAR_METRICS` is empty and disk-wear prediction is inactive (analytics logs a warning at start); CPU `util` has no Checkmk levels, so analytics supplies fallback levels of 85 (warn) and 95 (crit); and the default charted/forecast metrics are `fs_used_percent`, `util` and `mem_used_percent`, with trend needs only for filesystem and memory.

#### Cloud bridge, queue limits and history topics (Phase 17)

- **Bridge fragment.** `deploy/mosquitto.conf` ends with `include_dir /mosquitto/config/conf.d`. The `mosquitto`
  entrypoint creates that directory and runs `deploy/render-mosquitto-bridge.sh`, which renders
  `deploy/mosquitto.bridge.template` into `conf.d/bridge.conf` only when `CLOUD_BROKER_HOST` is set (an empty
  directory is tolerated). The template forwards `sites/<site_id>/#` to `app/<SEN>/<site_id>/` out only, over
  MQTT v5 and TLS (`bridge_cafile` from `deploy/certs/cloud-ca.pem`), with a persistent session and
  `remote_clientid bridge-<SEN>-<site_id>`. The renderer validates every value and stops the container with a
  message naming the offending variable.
- **ACL.** `deploy/mosquitto.acl.template` gains a `user bridge` block: read-only over this site's subtree.
  `MQTT_BRIDGE_PASSWORD` (generated by `deploy/init-env.sh`) is its password. A per-SEN ACL for the cloud broker
  is in `deploy/mosquitto.cloud-acl.example`.
- **Queue limits.** `max_queued_messages 20000` and `max_queued_bytes 104857600` in `deploy/mosquitto.conf`
  bound the memory used while the WAN is down. They are global per-client settings, so they apply with or
  without a bridge. Beyond them, Mosquitto drops messages.
- **Topic table addition.** `history/<table>` (`history/metrics`, `history/host_state`,
  `history/service_state`): poller writes, QoS 1, not retained, chunks of up to 500 rows. Written only when
  `SITE_SEN` is set. The `bridge` login is the only reader besides the cloud ingest.

## 4. Default credentials in tracked files

Fine on a trusted LAN. Change them before exposing the stack beyond it.

| Credential | Where | How to change it |
|---|---|---|
| `cmkadmin` / `cmkadmin` | `deploy/compose.yaml` `CMK_PASSWORD` | Leave it. The wizard asks for it in Phase 1 and offers to change it. |
| MinIO `minioadmin` / `minioadmin` | `deploy/compose.yaml`, in the `minio` and `worker` services | Edit both places together. |

SSH credentials for the target hosts are asked for during the wizard and are not stored.

No MQTT credential is tracked any more (quick 260930-jj4): `MQTT_POLLER_PASSWORD` and
`WS_PASSWORD` are generated per machine into `deploy/.env`.

## 5. Build and start

```bash
cd ~/checkmk-stack/app/checkmk-wizard/deploy     # always run compose from here
podman compose build dashboard worker
podman compose up -d
```

The `worker` image (`deploy/worker.Containerfile`) bakes in `uv`, Python 3.11 and the wizard's
dependencies, so the wizard runs on a machine **with no internet**. Build it while the machine is
online; afterwards nothing needs the network. Rebuild it (online) after a `git pull` that changes
`pyproject.toml` or `uv.lock`; offline, `uv sync` then stops with an error naming the missing
package. The image also installs `iputils-ping` (via `apt-get`, so the build itself needs internet): the wizard's network scan uses `ping` to find hosts with no open TCP ports, and falls back to TCP-only if it is missing (`podman exec automation-worker which ping` should print a path). Other images (`python:3.12-slim`, Checkmk, Mosquitto, ...) must already be present locally.

**Offline use, checklist.** Everything the wizard needs at run time is in the worker image, so the machine may be
disconnected once these hold (check while still online):

1. `podman compose build worker` finished, and `podman images` lists `localhost/checkmk-worker:latest`.
2. The other images are already pulled (`podman images`): Checkmk, Mosquitto, ClickHouse, Grafana, MinIO, the
   MinIO client and `python:3.12-slim` (used by `poller` and `analytics`). A `podman compose up -d` offline
   will not fetch a missing one.
3. `podman exec automation-worker which ping` prints a path (the network scan's ICMP probe).
4. `deploy/run-wizard.sh` gets as far as the Checkmk login prompt. Its `uv sync` runs against the baked-in
   cache (`UV_OFFLINE=1`) and fails fast, naming the package, if `uv.lock` changed since the image was built.

The wizard's SSH, REST and scan traffic stays on your LAN, so it needs no internet. The agent package is pushed to target hosts over SFTP, and the smartmontools `.deb` files ship in
`docs/smart/`, so target hosts need no internet either. Only the optional cloud feed (§3.3) needs a WAN link.

The dashboard also owns a `map_drawing_data` volume (the topology map's shared drawing layer, written through nginx's `/map-drawing.json` location). It is created on the first `up`; there is nothing to configure. `deploy/reset-site.sh` deletes it (a reset starts with an empty map). Back it up with `deploy/backup.sh` or `podman volume export deploy_map_drawing_data -o map-drawing-backup.tar` (the name is prefixed by the compose project; check `podman volume ls`). To clear the drawing, remove that volume while the stack is down.

MinIO comes from `cgr.dev/chainguard/minio`, pinned by digest, because `minio/minio` is gone from
Docker Hub and `quay.io/minio/minio` no longer allows anonymous pulls (§3.5).

**Migrating an already-running stack:** if a stack was already running against the old `/etc/mosquitto/mosquitto.conf` mount, `deploy/compose.yaml` corrects the mount path to `/mosquitto/config/mosquitto.conf` (the only path the `eclipse-mosquitto` image's baked-in `CMD` actually reads) and adds authentication/ACL enforcement that wasn't there before. This changes which config the broker loads, and any retained messages accumulated under the previous configuration should be backed up first if they matter — `podman volume export mosquitto_data -o mosquitto_data-backup.tar` before redeploying. This is an operator note, not a blocking step.

Watch the poller's poll cycles as they happen:

```bash
podman compose logs -f poller
```

## 6. Checks after startup

**All containers are up:**

```bash
podman compose ps
```

Expect `automation-worker`, `checkmk`, `clickhouse`, `dashboard`, `grafana`, `minio`,
`mosquitto`, `mqtt-poller` and `analytics`, all `Up` (`minio-init` is a one-shot and exits). The PORTS column here shows only the ports each image declares, not the host
mappings; that's how `docker-compose` displays Podman containers, so check the mappings with
the next two commands instead.

**Host ports are published and listening:**

```bash
podman ps --format '{{.Names}}  {{.Ports}}'
ss -tln | grep -E ':(8080|8000|6556|1883|9000|9001|9002|8090)\b'
```

Services, URLs and the DNS names to use between containers:

| Service | LAN / Browser URL | Internal Network DNS (Inside Containers) |
| --- | --- | --- |
| **Checkmk UI** | `http://<HOST_IP>:8080/cmk/` | `http://checkmk:5000/cmk/` |
| **Checkmk API** | `http://<HOST_IP>:8080/cmk/check_mk/api/1.0/` | `http://checkmk:5000/cmk/check_mk/api/1.0/` |
| **Checkmk Livestatus** | *N/A (not published — internal only, see §12.1)* | `checkmk:6557` |
| **Mosquitto** | `<HOST_IP>:1883` (requires `poller` credentials — no longer anonymous) | `mosquitto:1883` |
| **Mosquitto (WebSockets)** | `ws://<HOST_IP>:9002` | `ws://mosquitto:9001` |
| **MinIO S3** | `http://<HOST_IP>:9000` | `http://minio:9000` |
| **MinIO Console** | `http://<HOST_IP>:9001` | *N/A (Browser only)* |
| **Live Dashboard** (React) | `http://<HOST_IP>:8090/` | *N/A (Browser only — served by the `dashboard` nginx service)* |
| **ClickHouse HTTP** | *N/A (not published — internal only, like Livestatus above)* | `clickhouse:8123` |
| **Grafana** (Phase 14.1) | `http://<HOST_IP>:3000/` (login required, no anonymous access) | `http://grafana:3000/` |
| **Analytics** (Phase 14.2) | *N/A (publishes no port; MQTT, ClickHouse and MinIO client only)* | `analytics` (container name) |

The dashboard's browser JavaScript talks to Mosquitto's WebSockets listener (`ws://<HOST_IP>:9002`
above) directly from the LAN client, so 9002 must stay reachable from wherever the dashboard is
opened. The `dashboard` nginx service on 8090 serves the static files and forwards
`/checkmk-api/` to Checkmk's REST API (for map edit mode), and, since Phase 14.1, two more
same-origin GET-only read paths: `/ch-api/` (ClickHouse's HTTP interface, authenticated as the
read-only `dashboard_reader` user) and `/availability/` (the daily rollup JSON/Parquet objects in
the `fleet-availability` MinIO bucket). It proxies nothing else. Since Phase 14.2 (D-20) the
forecast chart is the only dashboard view that reads `/ch-api/` (the raw history behind a
need's trend); `/availability/` still has no dashboard view (D-50). Both paths are verified by the
history read-path smoke test in §9.

**Cloud feed (Phase 17).** When `CLOUD_BROKER_HOST` is set, the broker opens one outbound TLS connection to the
cloud broker (port 8883 by default). Nothing is inbound: no new port is published on this host and the cloud
cannot write to the local broker. The connection needs `deploy/certs/cloud-ca.pem`.

The worker and poller publish no ports. Cloud-feed detail: when `CLOUD_BROKER_HOST` is set, the broker opens one outbound TLS connection (port 8883 by default); nothing is inbound and no new port is published.

**Endpoints answer, and Livestatus is plain TCP** (use your site name instead of `dmc`):

```bash
curl -s -o /dev/null -w 'checkmk %{http_code}\n'   http://localhost:8080/dmc/check_mk/
curl -s -o /dev/null -w 'minio %{http_code}\n'     http://localhost:9000/minio/health/live
curl -s -o /dev/null -w 'dashboard %{http_code}\n' http://localhost:8090/
podman compose exec checkmk omd config dmc show LIVESTATUS_TCP_TLS
```

Expect `checkmk 302` (the redirect to the login page), `minio 200`, `dashboard 200` and `off`.
If TLS is `on`, the poller can't read Checkmk; see §12.1.

**The worker got the settings from `deploy/.env`:**

```bash
podman compose exec worker bash -c 'echo ${#CMK_REST_SECRET}'   # a number > 0; prints only the length
podman compose exec worker printenv CMK_PUBLIC_HOST             # this machine's LAN address
```

If either is empty, fix `deploy/.env`, then `podman compose down && podman compose up -d`.

**The worker got the settings from `deploy/.env`:**

```bash
podman compose exec worker bash -c 'echo ${#CMK_REST_SECRET}'   # a number > 0; prints only the length
podman compose exec worker printenv CMK_PUBLIC_HOST             # this machine's LAN address
```

If either is empty, fix `deploy/.env`, then `podman compose down && podman compose up -d`.

**Cloud bridge connected (only when `CLOUD_BROKER_HOST` is set):**

```bash
podman compose logs mosquitto | grep -i bridge
```

With the feed off, the log says the cloud bridge is disabled and shows no error. With it on, look for the
`cloud-<SEN>-<site_id>` connection being established. A validation error from the bridge renderer (missing
`SITE_SEN`, a password with a disallowed character, no `deploy/certs/cloud-ca.pem`) stops the mosquitto
container with a message naming the variable; fix it and run a full down/up. `podman compose logs poller |
grep "SEN="` shows the feed identity line the poller logs at start.

## 7. Run the wizard

```bash
~/checkmk-stack/app/checkmk-wizard/deploy/run-wizard.sh
```

The script checks that `automation-worker` is running and that it received
`CMK_REST_SECRET`. It then waits up to 3 minutes for the `CMK_SITE_ID` site to answer
on `checkmk:5000`, because a new site takes a minute or two to create after `up -d`. If
Checkmk answers but has no site by that name, the script stops and lists the sites it
does have. Finally it runs `uv sync` and the wizard inside the worker. If you start the
wizard by hand while Checkmk is still unreachable, it now stops with a "not reachable"
message instead of asking for an automation secret. By hand, the same is:

```bash
podman compose exec worker bash -c "cd /app/checkmk-wizard && uv sync"
podman exec -it automation-worker bash -c "cd /app/checkmk-wizard && uv run checkmk-wizard"
```

The worker keeps its virtualenv in the container (`UV_PROJECT_ENVIRONMENT=/opt/checkmk-wizard-venv`),
not in the checkout, and nothing in this guide runs `uv` on the host. If an old `.venv` from an earlier worker
or a host `uv` run sits in the checkout and `uv` fails with
`failed to canonicalize path .../.venv/bin/python3: Permission denied`, delete it
(`rm -rf ~/checkmk-stack/app/checkmk-wizard/.venv`), then do a full `podman compose down && podman compose up -d`
so the worker picks up the variable.

To start over later with a blank site, run `deploy/reset-site.sh`; it also lets
you pick a new site name, and wipes the existing site
(§11.3).

The worker has no local `omd`, so the wizard switches to **container mode** automatically: it cannot create or delete the OMD site, but it fully configures a site the `checkmk` container already created, over the REST API, SSH out to target hosts and Livestatus-over-TCP. It needs a real TTY (`questionary` will not render without one), so keep `-it` if you start it by hand. What to expect, compared with running it directly on a Checkmk host:

- **Phase 1 opens by announcing container mode** ("'omd' isn't on PATH — assuming this wizard is running in a separate container from Checkmk itself") and skips straight to a site-name prompt, pre-filled with `dmc` from the `CMK_SITE_ID` env var (§3.1) — just confirm it. The default follows `CMK_SITE_ID` from `deploy/.env` (see §3.4); the name has to match the site the `checkmk` container actually created — the wizard cannot rename it.
- **Checkmk host/IP prompt:** pre-filled with `checkmk:5000` (`checkmk` is the service's hostname on `cmk_net`, which is what actually resolves to Checkmk from inside the `worker` container; `:5000` because the `checkmk` service serves its site on container port 5000 internally — see the `ports: "8080:5000"` mapping in `compose.yaml`, and the `worker` service's own `CMK_REST_API=http://checkmk:5000/...`) — just press Enter to accept it. The `:5000` is the web/REST port only; the Livestatus check on `checkmk:6557` (§12.1) is unaffected, so the following bullet still reads correctly. Only type a different host (with or without its own `:port`) if the Checkmk service is reachable under another name.
- **Livestatus reachability check:** warns immediately if Livestatus over TCP is not working (§12.1), and also when port 6557 accepts connections but answers only TLS (`LIVESTATUS_TCP_TLS` on) — fix it and re-run, or ignore and fix it before Phase 7.
- **cmkadmin password prompt:** not pre-filled. The prompt reminds you that on a freshly created site whose password was never changed, it is the compose default `cmkadmin` (§4); if you already changed it on an earlier run, type the new one. The wizard then offers (default yes) to change it to one you choose via the REST API. `compose.yaml` keeps `CMK_PASSWORD=cmkadmin` and needs no update, since Checkmk only reads it when the site is first created. The wizard uses the resulting password once, over the REST API, to bootstrap the `automation` and `agent_registration` REST users itself — it's never stored anywhere by the wizard. The `automation` user is provisioned with the `CMK_REST_SECRET` from `deploy/.env` automatically (updated if it already exists) and that value is not printed. Clear it and leave it blank instead if you'd rather paste an automation secret directly (fetched via `podman compose exec checkmk cat /omd/sites/dmc/var/check_mk/web/automation/automation.secret`, for example).
- **Phase 3 network scanning / Phase 5 SSH onboarding** reach out to your actual LAN from the `worker` container over `cmk_net`'s bridge (outbound NAT) — same subnets/targets you'd scan and SSH into from any other host on that network, no extra container networking config needed.

Re-running later needs nothing extra: dependencies are baked into the worker image (§5), and the wizard detects an already-provisioned `automation`/`agent_registration` user and falls back to asking for its secret instead of failing.

See [`WIZARD-OPERATION.md`](WIZARD-OPERATION.md) for the full phase-by-phase walkthrough.

## 8. After the wizard

1. Restart the whole stack so the poller picks up the new setup:

   ```bash
   podman compose down && podman compose up -d
   ```

   Always use a full `down`/`up`. Restarting a single service (`podman compose restart poller`)
   once cut Checkmk off from the LAN and turned every host DOWN (§12.3).

2. Check the result:
   - Checkmk UI at `http://<this machine>:8080/<site>/`: log in with the new cmkadmin password.
   - Dashboard at `http://<this machine>:8090`: devices appear, each with its folder.

3. Nothing to do. If `TOPOLOGY_EDITOR_SECRET` is set in `deploy/.env` (§3.1), the wizard
   provisions the scoped `topology_editor` Checkmk user to that value right after Phase 1,
   and the dashboard's map "Edit topology" switch is already enabled after step 1's restart.
   `scripts/provision_topology_editor.py` remains a manual fallback (it reads the same env
   var) if you need to (re)provision it without running the whole wizard.

4. Gauge refresh and the heartbeat: since Phase 17 the poller publishes a device's status on a state change,
   a gauge ok/warn/crit band crossing, or every `CLOUD_METRICS_HEARTBEAT_S` seconds (default 300). That same
   value therefore sets how often the on-prem dashboard's CPU, RAM and disk gauges refresh. Set it to `0` to
   refresh on every poll cycle. A state change still shows within about 15 s.

## 9. Verification and smoke tests

Verify end-to-end communication across the bridge network from inside the worker container. A 401 here is expected and counts as a pass at this point in the guide -- the automation REST user (and its secret, the only credential Checkmk's Bearer auth accepts) is not bootstrapped until the wizard has run (§7), so a 401 or a 200 both prove the worker reached Checkmk's REST API, as opposed to a connection error, timeout, or proxy-level 404, which would indicate a genuine reachability problem:

```bash
# Checkmk REST API: prints 200 or 401 when reachable
podman exec automation-worker python3 -c 'import os, urllib.request, urllib.error
try:
    print("Checkmk API:", urllib.request.urlopen(os.environ["CMK_REST_API"] + "/version", timeout=5).status)
except urllib.error.HTTPError as e:
    print("Checkmk API:", e.code)'

# MinIO: lists the buckets (boto3 is part of the worker's baked-in environment)
podman exec automation-worker bash -c 'cd /app/checkmk-wizard && uv run python -c "
import boto3
s3 = boto3.client(\"s3\", endpoint_url=\"http://minio:9000\", aws_access_key_id=\"minioadmin\", aws_secret_access_key=\"minioadmin\", region_name=\"us-east-1\")
print([b[\"Name\"] for b in s3.list_buckets()[\"Buckets\"]])"'
```

### Broker smoke test

[`scripts/smoke_test_broker.py`](../scripts/smoke_test_broker.py) proves the Mosquitto hardening actually holds against a live broker — configuration alone doesn't demonstrate it. Its `--poller-password`/`--ws-password` default from the `MQTT_POLLER_PASSWORD`/`WS_PASSWORD` environment variables, and `--site-id` defaults to `CMK_SITE_ID`, so the command loads `deploy/.env` first. It runs in the worker, which reaches the broker by its service name (`mosquitto`, WebSockets on container port 9001):

```bash
podman exec automation-worker bash -c 'cd /app/checkmk-wizard && set -a && . deploy/.env && set +a && uv run python scripts/smoke_test_broker.py --host mosquitto --ws-port 9001'
```

The script never restarts the broker unless `--with-restart` is passed. What each check proves (the analytics and triage checks take `--analytics-password` / `--triage-ws-password`, which default from `MQTT_ANALYTICS_PASSWORD` / `TRIAGE_WS_PASSWORD`; the broker restart check is off by default and opt-in via `--with-restart`, because restarting a single container breaks Checkmk egress on the deploy host, so never pass it there; `--skip-restart` is still accepted as a no-op; the last line reports `N checks passed, M skipped`, so groups skipped for lack of a password are visible):

- `analytics_writes_allowed` / `analytics_incident_status_denied` — the `analytics` login may publish under `lan/needs/` and `lan/incidents/<id>/narration` but not on `lan/incidents/<id>/status`
- `wstriage_publish_cmd` / `wstriage_publish_lan_denied` — the `wstriage` login can publish `needs/triage/cmd` (analytics receives it) and nothing under `lan/`
- `poller_publish` / `ws_subscribe` — the WebSockets listener is reachable and distinct from 1883
- `ws_publish_denied` — the `wsreader` ACL is read-only; a write attempt never reaches an independent privileged subscriber
- `persistence_across_restart` — a retained message survives a broker restart (runs only with `--with-restart`)

The broker config caps every publish at 2 MB (`message_size_limit 2097152` in `deploy/mosquitto.conf`), above the 1 MB events payload analytics accepts; mosquitto silently drops anything larger. Applying a change to `mosquitto.conf` needs a full `podman compose down && podman compose up -d`, never a single-service restart.

### Poller smoke test

[`scripts/smoke_test_poller.py`](../scripts/smoke_test_poller.py) proves the live Livestatus column set and four of the five Phase 9 success criteria against a running stack — configuration alone doesn't demonstrate any of this. It runs in the worker, which cannot restart or kill its sibling `poller` container, hence `--skip-restart-checks`:

```bash
podman exec automation-worker bash -c 'cd /app/checkmk-wizard && set -a && . deploy/.env && set +a && uv run python scripts/smoke_test_poller.py --host mosquitto --livestatus-host checkmk --skip-restart-checks'
```

What each check proves:

- `check_livestatus_columns` — the live site's `hosts` table actually exposes the columns the poller queries (resolves RESEARCH.md Open Question 1)
- `check_device_status_retained` — Success Criterion 1 (PLR-03, PLR-08): a retained `sites/<site_id>/lan/devices/{id}/status` payload matches the fixed contract
- `check_topology_retained` — the payload half of PLR-01/PLR-04
- `check_device_enrichment` — TAG-03: plan 10-03's `alias`/`folder` enrichment actually reached retained device payloads. An all-empty `folder` result points straight at the `CMK_REST_SECRET` step in §3.1 — that's the cause when this check fails
- `check_poller_liveness` — the positive half of Success Criterion 5 (PLR-07): the poller's own heartbeat
- `check_topology_quiet` — Success Criterion 3 (PLR-04): unrelated poll cycles produce no topology republish (skipped by `--skip-slow`)
- `check_ghost_tombstone` — Success Criterion 4 (PLR-06): a host that disappeared while the poller was down gets tombstoned (skipped by `--skip-restart-checks`)
- `check_lwt_offline` — the LWT half of Success Criterion 5 (PLR-07) (skipped by `--skip-restart-checks`)

To confirm which Livestatus `hosts` columns a given site actually exposes, without running
the full smoke test:

```bash
podman exec mqtt-poller python -u /scripts/mqtt_poller.py --check-columns
```

Run it against the `mqtt-poller` container, not from a shell on the deployment host. Livestatus
TCP (6557) is deliberately never published to the host — the `checkmk` service publishes only
8080/8000/6556 — so it is reachable only from inside `cmk_net`. The poller container already has
`LIVESTATUS_HOST=checkmk` in its `environment:`, already has `paho-mqtt` installed, and already
mounts the script at `/scripts/mqtt_poller.py`, so the command needs no further setup.

**Manual tombstone test:** the fifth Phase 9 success criterion (a real Checkmk host deletion) needs a live Checkmk site to delete a host from, so it isn't automated. Delete a host in the Checkmk UI, activate changes, wait one poll interval, then confirm with:

```bash
podman exec mosquitto sh -c 'mosquitto_sub -h localhost -u poller -P "$MQTT_POLLER_PASSWORD" -t "sites/<site_id>/lan/devices/<host>/status" -v -C 1 -W 5'
```

Live-verified 2026-09-08 (deleting `192.168.0.215`): a zero-length retained publish is a *clear*, not a delivered empty message, so `mosquitto_sub` without `-C`/`-W` would simply hang with no output. `-C 1 -W 5` makes that observable: the subscribe times out ("Timed out", RC 27) with no message received, which is what confirms the retained status was cleared. Also confirm the host is gone from `sites/<site_id>/lan/devices/topology` and that a `removed` event appears in `sites/<site_id>/lan/events/recent`.

### History read-path smoke test (Phase 14.1)

[`scripts/smoke_test_history_proxy.py`](../scripts/smoke_test_history_proxy.py) proves the read-only ClickHouse/rollup HTTP path (HIST-08/HIST-09/HIST-10): that `/ch-api/` and `/availability/` answer GET reads as the read-only `dashboard_reader` identity, that every write/admin/system-table/credential-override path through them is refused, and that Grafana requires login. It uses only the standard library and talks to the published ports (dashboard 8090, Grafana 3000, MinIO 9000), so it needs this machine's LAN address, which the worker already has as `CMK_PUBLIC_HOST`:

```bash
podman exec automation-worker bash -c 'cd /app/checkmk-wizard && set -a && . deploy/.env && set +a && uv run python scripts/smoke_test_history_proxy.py --host "$CMK_PUBLIC_HOST" --grafana-password "$GRAFANA_ADMIN_PASSWORD"'
```

If the connection from inside the container to the host's own LAN address is refused (some rootless network setups do not route it), run the same script from any other machine with Python 3.9+ and `--host <this machine's address>`.

The rollup-object checks need at least one day's availability rollup to already exist in `fleet-availability` — the analytics service (formerly the poller) backfills on startup once it has a previous local day's data in ClickHouse, so run this after the stack has been up across at least one local midnight (Asia/Singapore), or after confirming a rollup object exists by hand (`mc ls local/fleet-availability/availability/` from inside a MinIO client, or an `/availability/...` GET once you know a date). As with the broker and poller smoke tests, if you change poller code or need to re-apply a compose change, restart the whole stack (`podman compose down && podman compose up -d`) rather than a single service — see §12.3.

### Dashboard check (Phase 11)

With the stack up (§5) and at least one poll cycle elapsed, open `http://<HOST_IP>:8090/` from any
LAN browser. Confirm:

- The connection indicator (top-right of the top bar) reads "Connected", not "Connecting…" or
  "Disconnected — retrying".
- The device list populates from the broker's own retained messages — this should happen without
  restarting the `poller` service, since every topic in the MQTT topic contract in [`ARCHITECTURE.md`](../ARCHITECTURE.md) is published with
  `retain: true` specifically so a freshly-opened browser tab gets the current fleet state
  immediately, not just future updates.

If the indicator never leaves "Connecting…", check that `WS_USERNAME`/`WS_PASSWORD` in
`deploy/.env` (visible via `curl http://HOST:8090/config.json`) are the values the `mosquitto`
container's own entrypoint used to build its password file (`podman logs mosquitto` shows no
password-file errors — see §3.5, "Broker passwords"), and that
port 9002 is reachable from the browser's own network, not just from the deployment host.

### Topology map check (Phase 13)

With `TOPOLOGY_EDITOR_SECRET` provisioned (§3.1) and the stack up, condensed from the full live
UAT checklist:

1. Confirm the poller's `sites/<site_id>/lan/devices/topology` payload carries `map_position`/`unmanaged` keys
   on each device node (`podman exec mosquitto sh -c 'mosquitto_sub -h localhost -u wsreader -P "$WS_PASSWORD" -t "sites/<site_id>/lan/devices/topology" -C 1 -W 5'`).
2. Open the dashboard — the topology map (vis-network) replaces the old placeholder, coloured by
   live state, with parent→child arrows and click-to-detail navigation.
3. Turn on "Edit topology", draw an edge, drag a node, and press "Apply changes" — confirm it
   goes live in a second browser within about two poll cycles, and in Checkmk's own UI
   (Setup > Hosts > the child host > Parents).
4. Add an unmanaged switch (Add Node); confirm it appears in Checkmk as UP with zero services
   (no PING) and never turns WARN/CRIT.
5. With another operator's change pending in Checkmk, confirm Apply shows "Saved, but not live
   yet" instead of force-activating it.

See `dashboard-react/README.md`'s "Topology map and editing" section for the full behaviour.

### Incident check (Phase 14)

With the stack up, verify the root-cause incident engine end to end:

1. `podman exec mqtt-poller python -u /scripts/mqtt_poller.py --check-columns` should list
   `present: last_state_change (optional)`. If it instead reports `missing`, every incident's
   `since` will be `null` and the dashboard's duration string will read "duration unknown" —
   not a bug, a documented degradation (see the incident topic paragraph in [`ARCHITECTURE.md`](../ARCHITECTURE.md)).
2. `podman exec mosquitto sh -c 'mosquitto_sub -h localhost -u wsreader -P "$WS_PASSWORD" -t "sites/<site_id>/lan/incidents/#" -v -C 1 -W 5'` shows any currently
   open incidents (one retained message per open incident); with none open it times out
   ("Timed out", RC 27) with no message received, the same clear-vs-empty distinction as the
   manual tombstone test above.
3. To provoke one safely: **do not use Checkmk's GUI "Fake check results"** — live-verified
   2026-09-26 (plan 14-05), its result is overwritten by the host's own next real active check
   (~1 minute for a host with no IP, whose real check always returns UP), so a fake can vanish
   within about a minute, often before it's clearly visible. Use Livestatus external commands
   instead (`DISABLE_HOST_CHECK` first, then `PROCESS_HOST_CHECK_RESULT`, then
   `ENABLE_HOST_CHECK` to reverse) — see the "Incident demo with fake check results" appendix in [`WIZARD-OPERATION.md`](WIZARD-OPERATION.md) for the
   exact commands, scenario scripts (single host, managed switch, unmanaged/inferred switch,
   poller restart), and cleanup/verification steps.
4. Expected dashboard result: within about two poll cycles, one incident card appears in the Incidents
   pane at the top of the right-hand column (`"{host} — {duration}"`, worst-criticality colour), the affected hosts dim in
   the fleet tree and on the topology map with a "See incident" link, and restoring the faked
   state clears the card and the dimming within about two more poll cycles.

See `dashboard-react/README.md`'s "5c. Incidents" section for the full card/dimming behaviour.

---

## 10. Start the stack automatically at boot

A systemd **user** service runs `podman compose up -d` at boot and `podman compose down` at
shutdown. Because lingering is enabled (§1), it starts at boot without anyone logging in.

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
# `systemctl --user reload checkmk-stack.service` does a full down/up (same as restart)
ExecReload=/bin/sh -c '/usr/bin/podman compose down && /usr/bin/podman compose up -d'
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
systemctl --user enable checkmk-stack.service
systemctl --user restart checkmk-stack.service
```

Use `restart`, not `enable --now`: the unit is `oneshot` with `RemainAfterExit=yes`, so once it has run
it stays `active (exited)` and `--now` does nothing. If the unit is already active (a re-run of this
step, or a stack that came up from the service at boot), the `podman compose down` above removes the
containers and `enable --now` never starts them again. `restart` always does a full down/up.

Check it:

```bash
systemctl --user status checkmk-stack.service   # expect: Active: active (exited)
loginctl show-user $USER --property=Linger      # expect: Linger=yes
podman compose ps                               # all containers Up (see §6)
```

Then reboot once and confirm the stack comes back without logging in, for example by opening
the dashboard on port 8090 from another machine.

If the service fails, read the full error with `journalctl --user -u checkmk-stack.service -e`:

- **`podman ps` shows no stack containers, but the service is `active (exited)`**: the stack was
  taken down by hand (`podman compose down`) while the unit was already active, so nothing started
  it again. Run `systemctl --user restart checkmk-stack.service`.
- **After a reboot the dashboard never reconnects; `podman logs mosquitto` repeats `Unable to open file
  /mosquitto/config/mosquitto.passwd for writing. File exists.`**: an older `compose.yaml` whose
  mosquitto entrypoint did not remove the previous password file first, so a plain container restart
  (not a recreate) crash-looped the broker. `git pull` (the entrypoint now runs `rm -f` first), then
  `podman compose down && podman compose up -d`.
- **`no configuration file provided`**: `WorkingDirectory` doesn't point at `deploy/`.
- **`the container name "…" is already in use`**: containers from a different compose project
  (typically an older layout run from another directory) still exist. Remove them with
  `podman rm -f checkmk mosquitto minio automation-worker mqtt-poller dashboard`, then
  `systemctl --user restart checkmk-stack.service`. Volumes are not removed.

After editing the unit file, run `systemctl --user daemon-reload`, then `systemctl --user restart
checkmk-stack.service` so the change takes effect. Stopping and starting the service
(`systemctl --user stop` / `start checkmk-stack.service`) does the same full down/up as running
compose by hand.

The unit also has an `ExecReload`, so `systemctl --user reload checkmk-stack.service` does a full
`podman compose down && up -d` without leaving the unit stopped in between. It is equivalent to
`restart`. It is not a lightweight reload: every container is recreated. If you added the unit
before `ExecReload` existed, add the line to your copy and run `daemon-reload`; `reload` fails with
"Job type reload is not applicable" until you do.

Why the unit looks like this (corrected 2026-09-30; an earlier version had three problems):

- **`WorkingDirectory`** used to be `%h/checkmk-stack`, from the layout before Phase 9 moved `compose.yaml` into the repo's `deploy/` directory (§2). From there, `podman compose` finds no `compose.yaml`. And a directory that *does* hold one but has a different name starts a separate compose project with its own, empty volumes.
- **`network-online.target` is gone.** It exists only in the system manager, so a user unit that waits on it waits on nothing.
- **`Wants=podman.socket` is added.** `After=` alone only orders the unit after the socket; it doesn't start the socket.

`ExecReload` makes `systemctl --user reload checkmk-stack.service` a full `compose down && up -d` (equivalent to `restart`; every container is recreated). `TimeoutStopSec=180` gives `compose down` more than the default 90 seconds at shutdown. No start timeout is needed: systemd disables it for `Type=oneshot` (`man systemd.service`, `TimeoutStartSec=`), so a slow first image pull at boot is not cut off. The unit file was checked with `systemd-analyze --user verify` (systemd 257).

If a stray project's empty volumes were created (like `checkmk-stack_checkmk_data` above), list them with `podman volume ls` and remove only those with `podman volume rm`. Keep the `deploy_*` ones: they hold your site.

## 11. Operating the stack

### 11.1 Updating later

After every `git pull`, while the machine is online:

```bash
~/checkmk-stack/app/checkmk-wizard/deploy/redeploy.sh
```

`redeploy.sh` builds `dashboard` and `worker` (unchanged layers come from cache and need no network;
`poller` and `analytics` have no build section; `down` removes their containers and `up -d` creates them
fresh with the new code), runs `podman compose down`, then `up -d`. By hand the same is
`podman compose build dashboard worker && podman compose down && podman compose up -d`. You do not need a
separate `uv sync`: `run-wizard.sh` runs it on every wizard start, and it works offline because the worker image
carries the wizard's dependencies.

The worker image is the reason to rebuild while online: if a `git pull` changed `pyproject.toml` or `uv.lock`,
the new packages are downloaded during `build worker`. Skip that rebuild and run the wizard offline, and
`uv sync` stops with an error naming the missing package.

The map drawing layer needs the rebuilt dashboard image (new nginx location and volume), so run `podman compose build dashboard` and then a full `podman compose down && podman compose up -d`, not a single-container restart (that has cut Checkmk's egress before).

### 11.2 Backup and restore (move the site and map to another machine)

`deploy/backup.sh` writes one tar bundle containing the Checkmk site, the topology map drawing
(`map_drawing_data`) and a copy of `deploy/.env` (the site id and the secrets the restored site was
created with). The bundle holds secrets, so it is written mode 600.

```bash
cd ~/checkmk-stack/app/checkmk-wizard/deploy
./backup.sh                  # with history: exports the checkmk_data volume (full down/up, brief downtime)
./backup.sh --no-history     # config only: omd backup --no-rrds --no-past, no downtime
./backup.sh --out ~/backups  # where to write the bundle (default: current directory)
```

On the new machine do §1–§2 (prerequisites, clone), skip §3 (the bundle brings `.env`), then:

```bash
cd ~/checkmk-stack/app/checkmk-wizard/deploy
podman compose build dashboard
./restore_backup.sh /path/to/checkmk-backup-dmc-<stamp>-full.tar --public-host <this machine's address>
```

- `--public-host` rewrites `CMK_PUBLIC_HOST`; agents registered against the old address need
  re-registering if it changed. `--yes` skips the confirmation. An existing `.env` is kept as
  `.env.bak-<stamp>`.
- A `full` bundle replaces the `checkmk_data` volume (history included). The script extracts it with `tar` inside the Checkmk image, not `podman volume import`: the import fails with `Error: invalid symlink .../<site>/version -> ../../versions/<ver>.cre` because the site's own symlink points outside the volume (fixed 2026-10-21). If you hit that error on an older checkout, `git pull` and run the script again; it recreates the half-filled volume. A `nohistory` bundle starts a
  blank site and restores the archive into it with `omd restore --reuse`, then does a full down/up.
- Do not run the wizard afterwards; the site already has its configuration.
- The Checkmk image on the new machine must be the same version as at backup time (the bundle's
  `manifest.txt` records it).
- ClickHouse and MinIO history (`clickhouse_data`, `minio_data`) is not in the bundle; export those
  volumes with `podman volume export` if you want it.

### 11.3 Starting over with a blank site

`deploy/reset-site.sh` automates this whole section: it detects the site in the `checkmk_data` volume, asks you to confirm its name, asks for a new site name (Enter keeps it; Esc or Ctrl+C aborts with nothing changed), writes it to `CMK_SITE_ID` in `deploy/.env` and does the full down/up. `--yes --site NAME` does it non-interactively. The by-hand steps follow.

To run the wizard against a genuinely fresh Checkmk site, remove the Checkmk volume **and** the Mosquitto volume (the second is recommended, see below):

- `checkmk_data` holds the site itself (hosts, folders, rules, tag groups, users, monitoring history). Removing it makes the container's entrypoint create a brand-new `dmc` site on the next start.
- `mosquitto_data` holds the broker's **retained** messages, which is all the dashboard reads (`sites/<site_id>/lan/devices/{id}/...`, `sites/<site_id>/lan/devices/topology`). On startup the poller reads every retained `sites/<site_id>/lan/devices/{id}/*` topic and clears the ones whose host is not on the site. This happens on its first cycle that has a confirmed host list: either Livestatus returned hosts, or Livestatus returned none and the REST API confirmed zero configured hosts (which needs `CMK_REST_SECRET`). So old hosts disappear from the dashboard without touching the broker volume. The sweep does not rewrite the global `sites/<site_id>/lan/events/recent` feed, though, and after a poller restart the old hosts' `removed` events carry no previous state (`from`/`to` both empty), so the dashboard's history lists them as "unknown → unknown". Remove `mosquitto_data` together with `checkmk_data` so the old site's event history goes with it.
- `map_drawing_data` (the dashboard's topology map drawing) is removed by `deploy/reset-site.sh` too, so the reset starts with an empty map. Back it up first (`deploy/backup.sh`) if you want to keep it.

Run from `deploy/` (compose prefixes volume names with its project name — `deploy_` here; confirm with `podman volume ls` and, if unsure, `podman inspect checkmk --format '{{range .Mounts}}{{.Name}} -> {{.Destination}}{{"\n"}}{{end}}'`):

```bash
podman compose down
podman volume rm deploy_checkmk_data deploy_mosquitto_data deploy_map_drawing_data
podman compose up -d
```

If you only want to clear the events feed and keep everything else in the broker, publish an empty retained message instead (the poller rebuilds the feed from empty):

```bash
set -a; . deploy/.env; set +a
podman exec mosquitto mosquitto_pub -h localhost -u poller -P "$MQTT_POLLER_PASSWORD" -t sites/<site_id>/lan/events/recent -r -n
```

If you rebuilt Checkmk **without** a full `podman compose down`, the poller kept running. The sweep runs only at poller startup, so restart the stack afterwards with `podman compose down && podman compose up -d`. Don't use `podman compose restart poller`: restarting a single container can cut Checkmk off from the LAN (see §12.3).

Leave `deploy_mosquitto_log` and `deploy_minio_data` alone. The broker's ACL is rendered at every start from the bind-mounted `mosquitto.acl.template`; its users are regenerated from `deploy/.env` at every start (quick 260930-jj4) — both survive the volume wipe.

Then, on the fresh site:

1. Make sure `deploy/.env` holds a `CMK_REST_SECRET` (any long random value, e.g. `openssl rand -base64 24`) **before** running the wizard. The wizard creates the `automation` user with that secret, so the worker and poller need no hand-copying afterwards. Restart the poller if it started before you set the value.
2. Livestatus-over-TCP comes up on its own, in plain text (`CMK_LIVESTATUS_TCP=on` plus the pre-start hook in `compose.yaml`, see §12.1); check with `podman compose exec checkmk omd config dmc show LIVESTATUS_TCP` (expect `on`) and `podman compose exec checkmk omd config dmc show LIVESTATUS_TCP_TLS` (expect `off`).
3. Run the wizard (§7).
4. Nothing to do for the topology editor if you use the editable topology map: the `topology_editor` role and user lived in the deleted site, but the wizard re-provisions them from `TOPOLOGY_EDITOR_SECRET` as part of step 3's run (amended 2026-09-30, quick 260930-hpy — previously required a manual re-run of `scripts/provision_topology_editor.py` here).
5. Hard-refresh the dashboard (Ctrl+Shift+R).

Everything on the old site is gone after this, including the monitoring history (RRD data) — there is no undo.

---

### 11.4 Upgrade notes by release

These apply to an **existing** install being brought forward; a fresh install needs none of them. In every case: `git pull`, `deploy/init-env.sh` (adds new secrets, keeps every other value), `podman compose build dashboard`, then a **full** `podman compose down && podman compose up -d`. Never restart a single container.

#### Phase 17 (cloud feed, status throttle)

New optional settings (§3.3) and a new `MQTT_BRIDGE_PASSWORD` that `deploy/init-env.sh` generates. The wizard asks for `SITE_SEN` after Phase 1. The poller now throttles device status (§8 shows the effect on gauges).

#### Phase 16 (admin mode)

Admin mode needs the new `ADMIN_WS_PASSWORD`; compose refuses to start without it.

```bash
git pull
deploy/init-env.sh                       # adds ADMIN_WS_PASSWORD, keeps every other value
cd deploy
podman compose build dashboard
podman compose down && podman compose up -d   # full down/up, never a single-service restart
```

Never restart a single service: a lone container restart breaks Checkmk's egress and turns hosts
DOWN. Then check against the live stack:

```bash
podman exec automation-worker bash -c 'cd /app/checkmk-wizard && set -a && . deploy/.env && set +a && uv run python scripts/smoke_test_broker.py --host mosquitto --ws-port 9001'
podman exec mqtt-poller python /scripts/mqtt_poller.py --check-columns
```

`--check-columns` should list `active_checks_enabled` (admin, optional). When it is missing, the
poller falls back to its in-memory ledger for the faked signal and logs that at startup.

#### Phase 14.3 (per-site MQTT namespace)

Every MQTT topic moved under `sites/<site_id>/`, so the poller, broker ACL and dashboard must change together.

The poller's one-time cleanup of the pre-14.3 topics and its temporary broker grants (`readwrite lan/#`, `readwrite admin/#`) were removed on 2026-10-04 (quick 261004-lyz), after they had run on the only deployment. A stack still on pre-14.3 topics keeps its old retained `lan/*` and `admin/faked` data and must either upgrade through a commit before 261004-lyz first, or clear that data by hand: list the topics with `mosquitto_sub -u poller -P "$MQTT_POLLER_PASSWORD" -t 'lan/#' -t 'admin/faked' --retained-only -W 3 -v`, then publish an empty retained payload to each with `mosquitto_pub -r -n -t <topic>` as a user that is granted that topic (temporarily add `topic readwrite lan/#` and `topic readwrite admin/#` to the poller block of `deploy/mosquitto.acl.template`), or clear the mosquitto volume.

Procedure:

1. In the admin view (`?admin=1`), run **Restore All** first. Fakes held in the old un-namespaced `admin/faked` topic do not carry over, so clearing them up front is the only way to avoid a stale fake.
2. Pull the new code and rebuild the dashboard image: `podman compose build dashboard`.
3. Restart the **whole** stack: `podman compose down && podman compose up -d`. Never restart or stop a single container on dmc-server; doing so breaks Checkmk egress and turns every real host DOWN.

What to expect afterwards:

- An old dashboard image shows nothing after the upgrade, because it subscribes to the un-namespaced topics.
- The first poller start waits the full reconcile timeout once.
- Topology, events, history and incidents rebuild from Checkmk within the first cycles.

#### Phase 14.2 (analytics service)

```bash
cd ~/checkmk-stack/app/checkmk-wizard
git pull
deploy/init-env.sh                       # adds the three new secrets, keeps every other value
cd deploy
podman compose build dashboard
podman compose down && podman compose up -d   # full down/up, never a single-service restart
# then the ClickHouse migration below, once
```

The one-off ClickHouse migration (initdb never re-runs on an existing volume; safe to re-run, and `podman exec` is not a restart):

```bash
cd ~/checkmk-stack/app/checkmk-wizard/deploy
set -a; . ./.env; set +a
sed "s/@CH_ANALYTICS_PASSWORD@/$CH_ANALYTICS_PASSWORD/" clickhouse-config/migrations/14.2-analytics.sql | podman exec -i clickhouse clickhouse-client --user ch_admin --password "$CH_ADMIN_PASSWORD" --multiquery
```

Until it has run, analytics logs a warning with the migration hint on each cycle and skips its history writes; it does not crash.

Then verify:


```bash
# the read cache is active (0 rows means the cache config did not load)
podman exec clickhouse clickhouse-client --user ch_admin --password "$CH_ADMIN_PASSWORD" -q \
  "SELECT cache_name, path, max_size, current_size FROM system.filesystem_cache_settings"
# analytics started cleanly
podman logs analytics 2>&1 | tail -30
```

Expect in the analytics log: `Analytics service running (...)` (with passwords shown as `***`), one `Chart metric <name> matched <N> series` line per charted metric (a `matched 0 series` warning means the metric name is wrong), `Restored <N> need(s) from retained topics`, and a startup warning that no SMART/NVMe wear metric is configured (expected today). Failure needs under `lan/needs/#` appear within about 15 s (`POLL_INTERVAL_SECONDS`); retained `sites/<site_id>/lan/forecasts/#` and trend needs appear within the first slow evaluation cycle (up to `EVAL_INTERVAL_SECONDS`, 15 minutes by default):

```bash
podman exec mosquitto sh -c 'mosquitto_sub -h localhost -u poller -P "$MQTT_POLLER_PASSWORD" -t "sites/<site_id>/lan/needs/#" -t "sites/<site_id>/lan/forecasts/#" -v -W 5'
```

Then run the broker smoke test (§9), which now also checks the `analytics` and `wstriage` grants, and confirm a rollup object appears in the `fleet-availability` bucket after the next local midnight (the analytics service now owns it).

A rollback is the same full down/up on the previous commit; the new ClickHouse tables are left in place and are ignored by older code.

---

A rollback is the same full down/up on the previous commit; the new ClickHouse tables are left in place and ignored by older code.

#### Quick 260930-jj4 (broker passwords moved to `.env`)

If your `deploy/.env` predates quick 260930-jj4, it has no `MQTT_POLLER_PASSWORD` or
`WS_PASSWORD`:

```bash
git pull
deploy/init-env.sh                              # fills in the two new values; every
                                                  # other value in .env is kept as is
podman compose down && podman compose up -d      # full down/up, never a single-service restart
```

Retained messages in the `mosquitto_data` volume are unaffected by a password change. If
your `.env` already has `WS_PASSWORD=wsreader` uncommented, `init-env.sh` keeps that value
(it never overwrites a value that's already set) — blank it out first and re-run the script
if you want a freshly generated one instead. Until you re-run `init-env.sh`, `podman compose
up` refuses to start with an error naming `deploy/init-env.sh`.

## 12. Troubleshooting and host quirks

### 12.1 Livestatus over TCP, in plain text

checkmk-wizard's Phase 7 post-activation health check connects to the site's Livestatus port over **TCP**, not the local UNIX socket — that's what lets it run from the separate `worker` container instead of needing local filesystem access to `checkmk`'s `/omd/sites`. It isn't on by default on a container-created site, but `deploy/compose.yaml` sets the documented `CMK_LIVESTATUS_TCP=on` environment variable on the `checkmk` service (docs.checkmk.com/latest/en/introduction_docker.html, "Additional environment variables"), so the container's entrypoint enables it when it creates the site — including after you wipe and recreate the `checkmk_data` volume.

`CMK_LIVESTATUS_TCP=on` only turns TCP on; it does not touch TLS. A fresh Checkmk 2.4 site defaults to `LIVESTATUS_TCP_TLS=on`, and xinetd then sends port 6557 to `live-tls`, which plain-LQL clients (the poller and the wizard) cannot speak: they see "Connection reset by peer", the poller exits with "Malformed columns response", and the dashboard shows "connected" but stays empty. The shipped `compose.yaml` therefore also mounts a pre-start entrypoint hook (`deploy/checkmk-hooks/pre-start/10-livestatus-tcp-plaintext.sh`) that sets `LIVESTATUS_TCP_TLS off` before every site start, so it also repairs an existing site on the next container restart. This is not a documented environment variable; it was verified from the image's entrypoint source (`docker_image/docker-entrypoint.sh`, `exec_hook pre-start`). The hook must keep its executable bit, or the entrypoint skips it; keep that in mind if you copy the file elsewhere. **The shipped `compose.yaml` sets both automatically, so no manual step is needed.** Check it with:

```bash
podman compose exec checkmk omd config dmc show LIVESTATUS_TCP       # expect: on
podman compose exec checkmk omd config dmc show LIVESTATUS_TCP_TLS   # expect: off
podman compose exec checkmk ls -l /omd/sites/dmc/tmp/run/live-tcp     # should point at `live`, not `live-tls`
```

The manual steps below are only for a site that was created without that variable (an older `compose.yaml`, a site created by hand with `omd create`, or a non-compose setup). Run them once:

```bash
podman compose exec checkmk omd stop dmc
podman compose exec checkmk omd config dmc set LIVESTATUS_TCP on
podman compose exec checkmk omd config dmc set LIVESTATUS_TCP_TLS off
podman compose down && podman compose up -d    # full down/up: starts the site and reconnects the poller
```

`omd config ... set` refuses to change config variables while the site is running — it errors with `Cannot change config variables while site is running.` — which is why the site is stopped first; the full down/up at the end then starts it again (the `checkmk` entrypoint runs `omd start`) and makes the poller reconnect, without a single-container restart. A site freshly brought up by `podman compose up -d` (§5) is already running when you reach this step, so the stop is always needed, not situational. Stopping the site for this loses nothing: flipping `LIVESTATUS_TCP` is a config change, not a code change or a data wipe, so the site's monitoring data, hosts, and history all live in the `checkmk_data` volume and survive the stop and the down/up untouched.

This binds Livestatus on port **6557** by default (Checkmk's own default `LIVESTATUS_TCP_PORT`) — matching what checkmk-wizard already expects, so nothing else needs configuring. No `ports:` entry is needed in `compose.yaml` for this: containers on the same `cmk_net` bridge can already reach `checkmk:6557` directly by service name, without publishing the port to the host/LAN — and it should stay that way, since Livestatus's wire protocol has no authentication of its own and relies entirely on network-level isolation.


If you skip this step, checkmk-wizard still runs fine through Phase 6 — it just prints a warning at Phase 1 ("Could not reach Livestatus on checkmk:6557", or, when the port is open but answers only TLS, "accepts connections but gives no plain-text reply" with the exact `omd config ... LIVESTATUS_TCP_TLS off` fix) and Phase 7's host-state table will fail at the very end of the run.

---

### 12.2 ICMP/PING checks (Checkmk's PING service)

Checkmk's PING service runs the `check_icmp` plugin, which needs a raw ICMP socket. Under rootless Podman that requires two unrelated things to be true at once — a container capability and a host kernel setting — and each fails with a different, misleading symptom. Both are required together; fixing only one still leaves PING broken.

**Container capability (already done — informational only).** `check_icmp` ships with the file capability `cap_net_raw=ep`, but rootless Podman's default container capability set excludes `CAP_NET_RAW`, so the kernel refuses to grant it at exec time. `deploy/compose.yaml` already adds `cap_add: [NET_RAW]` to the `checkmk` service — you don't need to add it yourself. The symptom this fixes: Checkmk reports `Return code of 126 is out of bounds - plugin may not be executable` on the PING service of every host. This is an exec-level error, not a reachability failure — a genuine network problem surfaces as a normal `check_icmp` CRIT such as "100% packet loss", so RC 126 is never a NAT/VMware-networking symptom even though it superficially looks like one.

**Picking the capability up on an already-running stack.** This is the general procedure for any `deploy/compose.yaml` change that requires a container to be *recreated* (not merely restarted) to take effect — capabilities, mounts, ports. `podman-compose` 1.0.6 has no `rm` subcommand, and its recreate-on-`up` logic can silently fall back to restarting the *old* container in place when another container is registered as a dependent (here, `mqtt-poller` depends on `checkmk`), so `podman compose up -d` alone can appear to succeed while changing nothing. The working order is: stop and remove the dependent container(s) first, then the target container, then bring each back up in turn:

```bash
podman stop mqtt-poller && podman rm mqtt-poller
podman stop checkmk && podman rm checkmk
podman compose up -d checkmk
podman compose up -d poller
```

Removing these containers loses no data — Checkmk's site lives in the `checkmk_data` volume and the poller is stateless. This step is only needed on an already-running stack; a first-ever `podman compose up -d` from §5 creates the container with the capability already applied.

**Host sysctl (the part you must do yourself).** Rootless Podman's netavark/pasta networking relays container ICMP through the host's unprivileged "ping socket" mechanism rather than a true host-level raw socket, and that mechanism is gated by the `net.ipv4.ping_group_range` sysctl. Its default value `1 0` is an empty range — it permits no group at all to open a ping socket — so all relayed ICMP is dropped silently, with no error logged on either the container or the host side. Confirm you're in this situation with:

```bash
podman info --format '{{.Host.NetworkBackend}}'   # expect: netavark
sysctl net.ipv4.ping_group_range                  # expect: net.ipv4.ping_group_range = 1  0
```

Then apply the fix — immediately, and persisted across reboots:

```bash
sudo sysctl -w net.ipv4.ping_group_range="0 2147483647"
echo 'net.ipv4.ping_group_range = 0 2147483647' | sudo tee /etc/sysctl.d/99-podman-ping.conf
```

This is a host-level setting with no representation in `deploy/compose.yaml` or any other repo file — it's a property of the Podman host, which is why it's the one part of this fix a fresh deployment must perform by hand. The `sysctl -w` takes effect immediately with no container restart needed; the `/etc/sysctl.d/` file is what survives a reboot. Both are wanted.

**Confirming it works.** Run `check_icmp` directly against a host you know is reachable, such as your LAN gateway:

```bash
podman compose exec checkmk /omd/sites/dmc/lib/nagios/plugins/check_icmp -H 192.168.0.1
```

Expected output: `OK - 192.168.0.1 rta 1.072ms lost 0%` (substitute your own LAN gateway).

If you skip this step, there are two distinct failure signatures depending on which half is missing: without the capability, every PING service reports `Return code of 126 is out of bounds - plugin may not be executable`. With the capability but without the sysctl, `check_icmp` runs cleanly but reports 100% packet loss to every target — including the LAN gateway that the host itself can ping successfully — which is indistinguishable from a genuine network fault unless you check this sysctl specifically.

### 12.3 Every host goes DOWN right after restarting a single container

**The third signature.** Seen on 2026-09-28 (rootless Podman 4.9.3, netavark, slirp4netns). Running `podman compose restart poller` removed and re-created the poller's link on the `cmk_net` bridge. Seven seconds later, every host except the always-UP unmanaged switch went DOWN, with `rta nan, lost 100%`. Checkmk had lost *all* traffic to the LAN, not only ICMP. A TCP test from inside the container failed too, while the host itself could still ping the gateway. Traffic between the containers kept working, so the poller and dashboard kept updating, just with the wrong states. The sysctl and the NAT rules were both still in place. What fixed it was a full `podman compose down && podman compose up -d`, which rebuilds the shared rootless network namespace. To tell this apart from the sysctl case above: TCP out of the container fails too, and the sysctl is already set.

```bash
podman exec checkmk bash -c 'timeout 3 bash -c "</dev/tcp/192.168.0.1/80" && echo tcp-ok || echo tcp-fail'
```

This was seen once and not re-run to confirm. Until it's shown to be safe, apply new poller code with a full `podman compose down && podman compose up -d`, not `podman compose restart <service>`. Volumes are kept, so this loses no data.

---

### 12.4 ClickHouse and Grafana on an existing host

**Grafana panels show `SETTING_CONSTRAINT_VIOLATION ... max_execution_time shouldn't be greater than 60`:**
the read-only ClickHouse profile used to cap `max_execution_time` at 60 s, and Grafana's client sends a
higher value (fixed for new installs in quick 261002-nm2). `02-users.sh` only runs when the
`clickhouse_data` volume is first created, so an existing host needs the cap raised once:

```bash
cd ~/checkmk-stack/app/checkmk-wizard/deploy && set -a && . ./.env && set +a
podman exec clickhouse clickhouse-client --user ch_admin --password "$CH_ADMIN_PASSWORD" -q \
  "ALTER SETTINGS PROFILE history_reader_profile SETTINGS readonly = 1, max_execution_time = 30 MAX 120 CHANGEABLE_IN_READONLY"
```
Then reload the Grafana dashboard. No container restart is needed. (On this host, never restart or
stop a single container: it cuts Checkmk off from the LAN, §12.3.)

**(Before Phase 14.2 only; the rollup now runs in `analytics` as `analytics_writer`, which has this grant from
initdb or the 14.2 migration, so check `podman logs analytics` instead.) Poller log repeats `Availability rollup for ... failed ... poller_writer: Not enough privileges ...
CREATE TEMPORARY TABLE ON *.*`:** the Parquet export (`INSERT INTO FUNCTION s3`) needs that grant, and
`poller_writer` lacked it (fixed for new installs in quick 261003-le3). An existing host needs it once;
the poller retries every 5 minutes, so no restart is needed:

```bash
cd ~/checkmk-stack/app/checkmk-wizard/deploy && set -a && . ./.env && set +a
podman exec clickhouse clickhouse-client --user ch_admin --password "$CH_ADMIN_PASSWORD" -q \
  "GRANT CREATE TEMPORARY TABLE ON *.* TO poller_writer"
```

### 12.5 `clickhouse` exits with code 132 (Illegal instruction)

`podman ps -a` shows `clickhouse` as `Exited (132)`, `grafana` stuck at `Created` and `dashboard` exited, and
`podman logs clickhouse` shows `Illegal instruction  clickhouse extract-from-config ...`. Exit code 132 is
SIGILL: the ClickHouse 26.9.4.3 binary uses an instruction the CPU does not have. Seen on an Intel Celeron
N5105 (SSE4.2, no AVX); the older 25.8.33.6 and 24.8.14.39 images run there. Setting the Proxmox VM's CPU
type to `host` is still right, but it cannot add instructions the physical CPU lacks.

Test a tag without touching the stack: `podman run --rm docker.io/clickhouse/clickhouse-server:25.8.33.6 clickhouse --version`
(it prints a version when the CPU is fine). Then pin it for this machine and recreate everything:

```bash
cd ~/checkmk-stack/app/checkmk-wizard/deploy
echo 'CLICKHOUSE_TAG=25.8.33.6' >> .env
podman compose down && podman compose up -d
```

The default stays 26.9.4.3, which the schema and storage config were written against; check
`podman logs clickhouse` after the first start on an older tag. The init scripts run only on an empty
`clickhouse_data` volume, so if an earlier start crashed before they ran, use the recovery under "History store" in §3.5.
