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

**Short-name image resolution:** the next thing a fresh install hits is §4's `podman compose up -d`, which fails for every service in this stack's `compose.yaml` that names its image without a registry — `checkmk/check-mk-raw:2.4.0-latest` and `eclipse-mosquitto:2` both fail with:

```text
Error: short-name "checkmk/check-mk-raw:2.4.0-latest" did not resolve to an alias
and no unqualified-search registries are defined in "/etc/containers/registries.conf"
```

The `worker` service (`python:3.12-slim`) is the one exception — it succeeds because Podman ships a built-in shortname alias for it in `/etc/containers/registries.conf.d/shortnames.conf`, and the other two images have no such alias (the `minio` image is fully qualified, see §3).

This is Podman's deliberate anti-typosquatting default, not a broken install: a fresh machine has no `unqualified-search-registries` configured anywhere, and rootless Podman would rather refuse an unqualified short name than guess which registry it should resolve against. The verify step above passes anyway because it pulls the fully-qualified `docker.io/library/hello-world`, which is why this doesn't surface until §4.

The fix is a rootless per-user override, which takes precedence over the system-wide `/etc/containers/registries.conf` named in the error above:

```bash
mkdir -p ~/.config/containers
cat > ~/.config/containers/registries.conf <<'EOF'
unqualified-search-registries = ["docker.io"]
EOF
```

Setting `unqualified-search-registries` to `docker.io` only re-enables short-name resolution against Docker Hub — it declares the single registry a short name is allowed to mean, it does not disable Podman's protection wholesale.

No cleanup is needed: just re-run `podman compose up -d`. The two failed services never got as far as creating a container object (the failure was at the `podman run` step itself, exit code 125), so any volumes or the `cmk_net` network podman-compose already created are reused as-is on retry.

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

The canonical `compose.yaml`, `mosquitto.conf` and `mosquitto.acl.template` live under this repo's own `deploy/` directory (see §3). Since quick 260930-jj4, the broker's password file is no longer a tracked file — it is generated at container start from `deploy/.env` (see §3's "First-time credential setup"). Since Phase 9, `deploy/compose.yaml` also bind-mounts `../scripts` for the `poller` service (§6's MQTT topic contract), and that path resolves relative to wherever `compose.yaml` itself sits — so the repo checkout (§8.1's clone command) must exist **before** `podman compose up`, and `podman compose` must be run from the checkout's own `deploy/` directory, not from a copy of `deploy/` placed loose in `checkmk-stack/`:

```text
checkmk-stack/
└── app/
    └── checkmk-wizard/     # checkout of the checkmk-wizard repo — see §8.1
        ├── deploy/         # this repo's own deploy/ directory; `podman
        │   ├── compose.yaml           # compose` is run from here (§4),
        │   ├── mosquitto.conf         # not from a separate copy
        │   ├── mosquitto.acl.template # rendered to mosquitto.acl at broker start
        │   └── render-mosquitto-acl.sh # (mosquitto.passwd is generated in the
        │                              #  container from deploy/.env, not tracked)
        └── dashboard/      # Phase 11 — static live dashboard, bind-mounted
            ├── index.html          # read-only into the `dashboard` service
            ├── devices.html        # (§4/§6); see dashboard/README.md for
            ├── details.html        # the module list and vendored-asset
            ├── css/                # provenance
            ├── js/
            │   └── vendor/         # third-party scripts, vendored verbatim
            ├── fonts/
            ├── icons/
            └── images/

```

A `deploy/` copied or symlinked elsewhere (this doc's pre-Phase-9 layout) leaves the `poller` service with no `../scripts` to mount on a fresh checkout. If your layout genuinely can't follow this structure, set `POLLER_SCRIPTS_DIR` to an absolute path pointing at this repo's `scripts/` directory instead.

Create the working directory and workspace folder:

```bash
mkdir -p checkmk-stack/app
cd checkmk-stack

```

---

## 3. Configuration Files

The full 5-service stack (`checkmk`, `mosquitto`, `minio`, `worker`, `poller`) and the hardened Mosquitto configuration are checked into this repo under [`deploy/`](../deploy/) as the single source of truth — see [`deploy/compose.yaml`](../deploy/compose.yaml), [`deploy/mosquitto.conf`](../deploy/mosquitto.conf) and [`deploy/mosquitto.acl.template`](../deploy/mosquitto.acl.template) (rendered per deployment at broker start by [`deploy/render-mosquitto-acl.sh`](../deploy/render-mosquitto-acl.sh), see the MQTT topic contract section). This doc no longer duplicates their contents inline, so the two can't silently drift apart; run `podman compose` from the checkout's own `deploy/` directory (see §2).

A few things worth knowing that aren't obvious just from reading those files:

- **Mosquitto's listeners bind to all container interfaces (`0.0.0.0`)** so both internal containers and external LAN devices can reach the broker — the plain-MQTT listener on 1883 stays published to the LAN for debugging, and a second listener (`protocol websockets`) is published separately for browser-based clients.
- **Podman-compatible `tmpfs` flags (`mode=1777`)** on the `checkmk` service prevent permission errors for the unprivileged Checkmk site user (`UID 1000`).
- **The `poller` runs as its own `restart: unless-stopped` service**, not inside `worker` — this keeps the always-on live Livestatus-to-MQTT bridge running independently of the `worker` container's interactive, on-demand wizard usage, so neither one can interfere with the other.

### First-time credential setup

The three Mosquitto broker passwords, `MQTT_POLLER_PASSWORD` (user `poller`), `WS_PASSWORD` (user `wsreader`) and `ADMIN_WS_PASSWORD` (user `wsadmin`, admin demo login), are generated into `deploy/.env` by `deploy/init-env.sh` (quick 260930-jj4 — no tracked credential file any more). `compose up` refuses to start without all three set (`${VAR:?run deploy/init-env.sh}` on the `mosquitto`, `poller` and `dashboard` services). The `mosquitto` service's own entrypoint (see `deploy/compose.yaml`) builds `/mosquitto/config/mosquitto.passwd` from these two values, owned by `mosquitto` (uid 1883) and mode `0700`, in the container's writable layer, on every start — never on the host. To rotate any of these passwords: edit it in `deploy/.env`, then `podman compose down && podman compose up -d` (a full down/up, never a single-service restart).

**Troubleshooting the generated password file:** if `podman logs mosquitto` shows "owner is not mosquitto" or "world readable permissions", the start-up command's `chown`/`chmod` did not run — check `deploy/compose.yaml`'s `mosquitto` service `entrypoint:`.

**Note on `CMK_PASSWORD`:** this sets the initial `cmkadmin` login password, and only when Checkmk first creates the site. checkmk-wizard's container mode asks for it at Phase 1 (it is not pre-filled — the prompt tells you the default is `cmkadmin` on a fresh site) so it can bootstrap the site's `automation`/`agent_registration` REST users itself (see §8.3), then offers to change it via the REST API. Keep `cmkadmin` here as the shipped default; there is no need to edit this file after changing the password in the wizard.

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
  required (quick 260930-jj4 — see §3's "First-time credential setup"); rotate it by editing
  `deploy/.env`, then a full `podman compose down && podman compose up -d`. The grant behind it
  is read-only (`topic read sites/<CMK_SITE_ID>/lan/#` in the rendered `deploy/mosquitto.acl.template`), so the exposure is bounded to
  reading the device list, never writing to the broker.
- `TOPOLOGY_EDITOR_SECRET` — see the next note.

Rebuild the image only after a `git pull` (code changes only — per-machine settings come from
`deploy/.env` at container start, no rebuild needed), then restart the stack (a full down/up,
not a single-service restart; see §5.1 "A third signature"):

```bash
cd deploy && podman compose build dashboard && podman compose down && podman compose up -d
```

The old vanilla dashboard (`dashboard/`) was deleted from the repo on 2026-09-30. For
development with hot reload, see `dashboard-react/README.md` §3.

**Note on the topology editor credential (amended 2026-09-30, quick 260930-hpy — supersedes
Phase 13's client-embedded credential):** the dashboard's map edit mode (§7's "Topology map
check") writes to Checkmk's REST API through the dashboard's own nginx, which injects a
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
   (§5.1 "A third signature"); always use the full down/up.

Blast radius: the `topology_editor` credential can edit host attributes (`parents`,
`map_position`), add new hosts, and activate its own pending changes. It cannot manage users,
edit global settings or rulesets, and — critically — cannot activate another operator's
pending changes (`wato.activateforeign` is deliberately not granted), so a topology edit can
never accidentally push someone else's unreviewed configuration change live. With the secret no
longer reaching the browser at all, a leaked/exfiltrated frontend has nothing to steal in the
first place.

**Note on `CMK_REST_SECRET` (poller):** the `poller` service now makes an authenticated Checkmk REST call every poll cycle to read each host's folder, alongside its unauthenticated Livestatus query. `deploy/compose.yaml` ships `CMK_REST_USERNAME=automation` and interpolates `CMK_REST_SECRET` from `deploy/.env`, which is gitignored so the real secret never lands in a tracked file. You choose the secret yourself, up front: copy `deploy/.env.example` to `deploy/.env`, set `CMK_REST_SECRET` to a long random value (`uv run python -c "import secrets; print(secrets.token_urlsafe(24))"`) before `podman compose up`, and the wizard's Phase 1 (see §8.3) pushes that exact value into Checkmk as the `automation` user's secret — creating the user, or updating the secret of an existing one on a re-run. Both `worker` and `poller` read the same value from `deploy/.env`; run `podman compose up -d poller` after changing it. If you leave it empty, the wizard falls back to generating a random secret and printing it once, which you then copy into `deploy/.env` by hand. `CMK_REST_SECRET` defaults to empty rather than refusing to start compose: a forgotten or missing secret leaves folder enrichment degraded (empty `folder` on every device) rather than blocking the stack, because a hard `:?` guard would also block `checkmk` and `mosquitto` from starting on a first-time deployment — before the automation secret this variable demands can even exist. A *wrong* secret degrades the same way (empty `folder` on every device) — see §7. Like `CMK_PASSWORD` above, rotate it before exposing this stack beyond a trusted LAN.

### History store secrets (Phase 14.1)

Five new secrets in `deploy/.env` back the ClickHouse history store and Grafana added in Phase 14.1 — `deploy/.env.example` documents all five inline:

| Variable | Read by | Purpose |
| --- | --- | --- |
| `CH_ADMIN_PASSWORD` | `clickhouse` (init scripts, operator CLI) | `ch_admin`, ClickHouse's own admin user |
| `CH_WRITER_PASSWORD` | `poller` | `poller_writer`, INSERT/SELECT on `history.*` plus the S3 export privilege and `CREATE TEMPORARY TABLE` (required by `INSERT INTO FUNCTION s3`) |
| `CH_READER_PASSWORD` | `dashboard` (nginx, `/ch-api/`) | `dashboard_reader`, SELECT-only, never reaches the browser |
| `CH_GRAFANA_PASSWORD` | `grafana` | `grafana_reader`, SELECT-only, used by the provisioned ClickHouse datasource |
| `GRAFANA_ADMIN_PASSWORD` | `grafana` | Grafana's own admin login |

Generate each the same way as `CMK_REST_SECRET` above:

```bash
uv run python -c "import secrets; print(secrets.token_urlsafe(24))"
```

**All five must be set in `deploy/.env` BEFORE the first `podman compose up`.** ClickHouse's `docker-entrypoint-initdb.d` scripts (`deploy/clickhouse-config/initdb/`) — which create `ch_admin` and the three read/write users — run only once, on the first start of an empty `clickhouse_data` volume. An empty `CH_*` password at that point means the corresponding user is created with an empty or broken password, and setting the variable afterwards does not fix it. If that happens, recover with:

```bash
podman compose down
podman volume rm deploy_clickhouse_data   # confirm the exact name with: podman volume ls
podman compose up -d
```

(the volume name is prefixed with the compose project name, same caveat as `deploy_checkmk_data` in §8.5). This deletes any history recorded so far — there is no in-place password reset for a ClickHouse user whose settings profile already applied, short of `ALTER USER` (see `deploy/.env.example`'s rotation note).

`grafana` refuses to start while `GRAFANA_ADMIN_PASSWORD` is empty or literally `admin` — its entrypoint guard exits before handing off to Grafana's own startup, so an empty-password deployment fails loudly (`podman compose logs grafana`) instead of coming up with a default credential.

**Note on the history store (ClickHouse, MinIO, Parquet):** `clickhouse` keeps roughly 30 days of raw poller-written rows on its local volume, downsamples aging rows to 5-minute then 1-hour aggregates in place, moves parts older than 31 days to the `clickhouse-s3-disk` bucket on `minio`, and deletes anything older than 3 years. The poller writes one INSERT batch per poll cycle and drops it if ClickHouse is unreachable at that moment — the gap simply reads as "no data" later, never as up or down (no local buffering or retry queue). Once a day, shortly after local midnight (`ROLLUP_TZ`, default `Asia/Singapore`), the poller computes the previous day's availability from `history.host_state` and writes it once to the `fleet-availability` bucket as both JSON (`availability/YYYY/MM/YYYY-MM-DD.json`) and Parquet (`availability_parquet/date=YYYY-MM-DD/availability.parquet`); missing days are backfilled up to `ROLLUP_BACKFILL_DAYS` (default 28) and an existing day object is never overwritten. Switching the whole store from MinIO to AWS S3 later is a configuration change only — endpoint, region and credentials in `deploy/compose.yaml` and `deploy/clickhouse-config/config.d/s3-storage.xml` — not a code change.

### Choosing the site name

The site is created by the `checkmk` container's own entrypoint on its **first start** (empty `checkmk_data` volume), long before the wizard runs — and the worker has no `omd`, so the wizard cannot create or rename it. The name therefore has to be decided up front, or changed with `omd mv` afterwards.

**Option 1 — choose it before the first start (recommended).** `deploy/compose.yaml` reads one variable, `CMK_SITE_ID` (default `dmc`), and uses it everywhere the site name appears: the `checkmk` service's `CMK_SITE_ID` and its `/omd/sites/<site>/tmp` tmpfs, the `worker`'s `CMK_SITE_ID`/`CMK_SITE`/`CMK_REST_API`, and the `poller`'s `CMK_SITE_ID`. Set it once in `deploy/.env` (see `deploy/.env.example`) or inline:

```bash
echo 'CMK_SITE_ID=mysite' >> deploy/.env      # or: CMK_SITE_ID=mysite podman compose up -d
podman compose up -d
```

The site name is also the dashboard's MQTT namespace (`sites/mysite/...` on the broker) and must be globally unique across every site that feeds the same broker; there is no central registry, so neither the wizard nor `deploy/init-env.sh` can check this, they only warn. The wizard's site-name prompt is then pre-filled with `mysite`. Site names must start with a letter and be 1–16 letters/digits/underscores. The dashboard now follows `CMK_SITE_ID` automatically too (quick 260930-ixs); the one thing not driven by this variable is the `podman compose exec checkmk omd ... dmc ...` commands in this doc — substitute your name.

**Option 2 — rename an existing site.** If the stack already runs under the wrong name, rename from the host (not the wizard). Note that `omd mv` needs the site stopped:

```bash
podman compose exec checkmk omd stop dmc
podman compose exec checkmk omd mv dmc mysite
```

Then set `CMK_SITE_ID=mysite` in `deploy/.env` and recreate the containers, including the dashboard (`podman compose up -d --force-recreate checkmk worker poller dashboard`) — or a full `podman compose down && podman compose up -d`. Otherwise the checkmk entrypoint's `omd start "$CMK_SITE_ID"` targets the old name and the `tmpfs` mount stays on the old path. Because it is easy to miss one of these places, on a disposable stack it is usually simpler to run `deploy/reset-site.sh` (§8.5). It wipes the site and recreates it under a new name in one step: it asks for the new name and writes `CMK_SITE_ID` to `deploy/.env` for you. Existing agents registered against the old site keep their old URL/certs and must be re-registered after a rename. `omd mv` also moves the MQTT namespace: update `CMK_SITE_ID` in `deploy/.env` and recreate the stack so the ACL is re-rendered, and note that the old `sites/<old>/` retained subtree is left on the broker (the Phase 14.3 sweep only clears the pre-14.3 un-namespaced topics).

---

## 4. Deployment

**Migrating an already-running stack:** if a stack was already running against the old `/etc/mosquitto/mosquitto.conf` mount, `deploy/compose.yaml` corrects the mount path to `/mosquitto/config/mosquitto.conf` (the only path the `eclipse-mosquitto` image's baked-in `CMD` actually reads) and adds authentication/ACL enforcement that wasn't there before. This changes which config the broker loads, and any retained messages accumulated under the previous configuration should be backed up first if they matter — `podman volume export mosquitto_data -o mosquitto_data-backup.tar` before redeploying. This is an operator note, not a blocking step.

```bash
# Run from the repo checkout's own deploy/ directory (see §2) — this is
# what makes deploy/compose.yaml's ../scripts mount for the poller service
# resolve correctly without setting POLLER_SCRIPTS_DIR
cd app/checkmk-wizard/deploy

# Build the dashboard image (first time, and after every git pull;
# see the dashboard note in §3)
podman compose build dashboard

# Start all containers in the background
podman compose up -d

# Verify initialization
podman compose ps

```

Watch the poller's poll cycles as they happen:

```bash
podman compose logs -f poller
```

### Upgrading to the per-site namespace (Phase 14.3)

Every MQTT topic moved under `sites/<site_id>/`, so the poller, broker ACL and dashboard must change together. Procedure:

1. In the admin view (`?admin=1`), run **Restore All** first. This is belt and braces: the poller also seeds `admin/faked` from the legacy retained topic, but clearing fakes up front leaves nothing to carry over.
2. Pull the new code and rebuild the dashboard image: `podman compose build dashboard`.
3. Restart the **whole** stack: `podman compose down && podman compose up -d`. Never restart or stop a single container on dmc-server; doing so breaks Checkmk egress and turns every real host DOWN.

What to expect afterwards:

- An old dashboard image shows nothing after the upgrade, because it subscribes to the un-namespaced topics.
- The first poller start waits the full reconcile timeout once.
- Topology, events, history and incidents rebuild from Checkmk within the first cycles.
- The old retained `lan/*` topics and the legacy `admin/faked` are cleared on the first cycle that has a confirmed host list.

Verify the sweep. This prints nothing once the legacy topics are gone:

```bash
podman exec mosquitto mosquitto_sub -u poller -P "$MQTT_POLLER_PASSWORD" -t 'lan/#' -t 'admin/faked' --retained-only -W 3 -v
```

---

## 5. Enable Livestatus-over-TCP (required for checkmk-wizard)

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
podman compose exec checkmk omd start dmc
podman restart mqtt-poller
```

`omd config ... set` refuses to change config variables while the site is running — it errors with `Cannot change config variables while site is running.` — which is why the site is stopped first and then *started* rather than left running and restarted afterward. A site freshly brought up by §4's `podman compose up -d` is already running when you reach this step, so the stop is always needed, not situational. Stopping the site for this loses nothing: flipping `LIVESTATUS_TCP` is a config change, not a code change or a data wipe, so the site's monitoring data, hosts, and history all live in the `checkmk_data` volume and survive the stop/start untouched.

This binds Livestatus on port **6557** by default (Checkmk's own default `LIVESTATUS_TCP_PORT`) — matching what checkmk-wizard already expects, so nothing else needs configuring. No `ports:` entry is needed in `compose.yaml` for this: containers on the same `cmk_net` bridge can already reach `checkmk:6557` directly by service name, without publishing the port to the host/LAN — and it should stay that way, since Livestatus's wire protocol has no authentication of its own and relies entirely on network-level isolation.


If you skip this step, checkmk-wizard still runs fine through Phase 6 — it just prints a warning at Phase 1 ("Could not reach Livestatus on checkmk:6557", or, when the port is open but answers only TLS, "accepts connections but gives no plain-text reply" with the exact `omd config ... LIVESTATUS_TCP_TLS off` fix) and Phase 7's host-state table will fail at the very end of the run.

---

## 5.1. Enable ICMP/PING checks (required for Checkmk's PING service)

Checkmk's PING service runs the `check_icmp` plugin, which needs a raw ICMP socket. Under rootless Podman that requires two unrelated things to be true at once — a container capability and a host kernel setting — and each fails with a different, misleading symptom. Both are required together; fixing only one still leaves PING broken.

**Container capability (already done — informational only).** `check_icmp` ships with the file capability `cap_net_raw=ep`, but rootless Podman's default container capability set excludes `CAP_NET_RAW`, so the kernel refuses to grant it at exec time. `deploy/compose.yaml` already adds `cap_add: [NET_RAW]` to the `checkmk` service — you don't need to add it yourself. The symptom this fixes: Checkmk reports `Return code of 126 is out of bounds - plugin may not be executable` on the PING service of every host. This is an exec-level error, not a reachability failure — a genuine network problem surfaces as a normal `check_icmp` CRIT such as "100% packet loss", so RC 126 is never a NAT/VMware-networking symptom even though it superficially looks like one.

**Picking the capability up on an already-running stack.** This is the general procedure for any `deploy/compose.yaml` change that requires a container to be *recreated* (not merely restarted) to take effect — capabilities, mounts, ports. `podman-compose` 1.0.6 has no `rm` subcommand, and its recreate-on-`up` logic can silently fall back to restarting the *old* container in place when another container is registered as a dependent (here, `mqtt-poller` depends on `checkmk`), so `podman compose up -d` alone can appear to succeed while changing nothing. The working order is: stop and remove the dependent container(s) first, then the target container, then bring each back up in turn:

```bash
podman stop mqtt-poller && podman rm mqtt-poller
podman stop checkmk && podman rm checkmk
podman compose up -d checkmk
podman compose up -d poller
```

Removing these containers loses no data — Checkmk's site lives in the `checkmk_data` volume and the poller is stateless. This step is only needed on an already-running stack; a first-ever `podman compose up -d` from §4 creates the container with the capability already applied.

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

**A third signature: every host goes DOWN right after restarting a single container.** Seen on 2026-09-28 (rootless Podman 4.9.3, netavark, slirp4netns). Running `podman compose restart poller` removed and re-created the poller's link on the `cmk_net` bridge. Seven seconds later, every host except the always-UP unmanaged switch went DOWN, with `rta nan, lost 100%`. Checkmk had lost *all* traffic to the LAN, not only ICMP. A TCP test from inside the container failed too, while the host itself could still ping the gateway. Traffic between the containers kept working, so the poller and dashboard kept updating, just with the wrong states. The sysctl and the NAT rules were both still in place. What fixed it was a full `podman compose down && podman compose up -d`, which rebuilds the shared rootless network namespace. To tell this apart from the sysctl case above: TCP out of the container fails too, and the sysctl is already set.

```bash
podman exec checkmk bash -c 'timeout 3 bash -c "</dev/tcp/192.168.0.1/80" && echo tcp-ok || echo tcp-fail'
```

This was seen once and not re-run to confirm. Until it's shown to be safe, apply new poller code with a full `podman compose down && podman compose up -d`, not `podman compose restart <service>`. Volumes are kept, so this loses no data.

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
| **Live Dashboard** (React) | `http://<HOST_IP>:8090/` | *N/A (Browser only — served by the `dashboard` nginx service)* |
| **ClickHouse HTTP** | *N/A (not published — internal only, like Livestatus above)* | `clickhouse:8123` |
| **Grafana** (Phase 14.1) | `http://<HOST_IP>:3000/` (login required, no anonymous access) | `http://grafana:3000/` |

The dashboard's browser JavaScript talks to Mosquitto's WebSockets listener (`ws://<HOST_IP>:9002`
above) directly from the LAN client, so 9002 must stay reachable from wherever the dashboard is
opened. The `dashboard` nginx service on 8090 serves the static files and forwards
`/checkmk-api/` to Checkmk's REST API (for map edit mode), and, since Phase 14.1, two more
same-origin GET-only read paths: `/ch-api/` (ClickHouse's HTTP interface, authenticated as the
read-only `dashboard_reader` user) and `/availability/` (the daily rollup JSON/Parquet objects in
the `fleet-availability` MinIO bucket). It proxies nothing else, and no dashboard views read
these two paths yet (D-50) — they exist only to prove the read path works, verified by the
history read-path smoke test in §7.

Default credentials:

* **Checkmk:** `cmkadmin` / `cmkadmin`
* **MinIO:** `minioadmin` / `minioadmin`
* **Mosquitto (poller, MQTT 1883):** user `poller`, password generated by `deploy/init-env.sh` into `MQTT_POLLER_PASSWORD` in `deploy/.env`
* **Mosquitto (wsreader, WebSockets 9002, read-only):** user `wsreader`, password generated by `deploy/init-env.sh` into `WS_PASSWORD` in `deploy/.env`
* **Mosquitto (wsadmin, WebSockets 9002, admin demo login):** user `wsadmin`, password generated by `deploy/init-env.sh` into `ADMIN_WS_PASSWORD` in `deploy/.env`; ACL: read `sites/<site_id>/lan/#`, `sites/<site_id>/admin/ack`, `sites/<site_id>/admin/faked`, write `sites/<site_id>/admin/cmd` only. Served open on `/admin-config.json` for `?admin=1`, so closed demo network only.

`cmkadmin`/`minioadmin` above are disposable dev/local defaults — rotate them before exposing this stack beyond a trusted LAN. The three Mosquitto passwords have no default at all (quick 260930-jj4): `compose up` refuses to start until `deploy/init-env.sh` has generated them (see §3's "First-time credential setup").

### MQTT topic contract (poller)

The `poller` service (`scripts/mqtt_poller.py`) is the only publisher on these topics; everything else is a consumer. Browser clients read them over the WebSockets listener (§1's endpoint table) with the read-only `wsreader` credentials — only the `poller` user can publish.

**Per-site namespace (Phase 14.3).** Every topic below lives under `sites/<site_id>/`, where `site_id` is `CMK_SITE_ID`, the Checkmk site id. The rows keep the full prefixed form; the dashboard strips the prefix once at its MQTT edge (`dashboard-react/src/lib/topics.ts`), so its stores see the relative `lan/...` form.

**Broker ACL.** `deploy/mosquitto.acl` is no longer a tracked file. The `mosquitto` container renders it at start from `deploy/mosquitto.acl.template` by running `deploy/render-mosquitto-acl.sh`, which substitutes a validated `CMK_SITE_ID` for `@SITE_ID@`. Mosquitto ACL files have no environment expansion, so rendering is how the grants get scoped to one site subtree. Per-user grants:

| User | Grants |
| --- | --- |
| `poller` | `readwrite sites/<site_id>/#`, plus the temporary `readwrite lan/#` and `readwrite admin/#` |
| `wsreader` | `read sites/<site_id>/lan/#` |
| `wsadmin` | `read sites/<site_id>/lan/#`, `read sites/<site_id>/admin/ack`, `read sites/<site_id>/admin/faked`, `write sites/<site_id>/admin/cmd` |

The temporary poller `lan/#` and `admin/#` grants exist only so the poller can tombstone the old un-namespaced retained topics once; Mosquitto silently drops an unauthorized publish, so narrowing them earlier would orphan the legacy retained data. They are to be removed once every deployment has run the sweep.

| Topic | Publish Trigger | QoS | Retain | Payload keys |
| --- | --- | --- | --- | --- |
| `sites/<site_id>/lan/devices/{id}/status` | Every poll cycle, for every known device | 0 | true | `id`, `state` (`OK`/`WARN`/`CRIT`/`UNKNOWN`/`DOWN`), `in_downtime`, `acknowledged`, `device_type`, `folder`, `alias`, `address`, `staleness`, `host_state_raw`, `timestamp`, `cpu_percent`, `cpu_warn`, `cpu_crit`, `ram_percent`, `ram_warn`, `ram_crit`, `disk_percent`, `disk_warn`, `disk_crit`, `disk_other_worst_percent`, `disk_other_worst_warn`, `disk_other_worst_crit`, `disk_other_worst_mount`, `smart_total`, `smart_failing` |
| `sites/<site_id>/lan/devices/topology` | Only when the id+parents+device_type+folder structure changes vs. the previous cycle, or a label changes (`map_position`, `unmanaged`, `criticality`, `service_criticality`, `depends_on`) | 1 | true | `devices` (list of `{id, parents, device_type, folder, alias, map_position, unmanaged, criticality, service_criticality, depends_on}`), `timestamp` |
| `sites/<site_id>/lan/devices/{id}/services` | Only when a service's state changes or the service set changes (never on `plugin_output` alone) | 1 | true | JSON array of `{description, state, plugin_output}` — every monitored service except the CPU/RAM/Filesystem/SMART gauge-backing services |
| `sites/<site_id>/lan/events/recent` | Only on any device's state transition, or a device add/remove | 1 | true | Full bounded array (max `EVENTS_MAX_ENTRIES`, default 1000, about 160 KB when full) of `{timestamp, device_id, event, from, to}` |
| `sites/<site_id>/lan/poller/status` | Birth (on connect), heartbeat (every poll cycle), and LWT (on ungraceful disconnect) or graceful stop | 1 | true | `{status, since, last_poll, device_count}` (birth/heartbeat) or `{status: "offline"}` (LWT/graceful stop) |
| `sites/<site_id>/lan/incidents/{incident_id}/status` | Only when an incident opens, closes, or its root, consequence set, dependents or worst criticality change | 1 | true | `id`, `root`, `root_state`, `inferred`, `confirmed_down`, `not_observable`, `dependents`, `worst_criticality`, `since`, `timestamp` |

A removed device is tombstoned by publishing an empty retained payload to its `status` and `services` topics (and, for one release, the retired `history` and `service_history` topics, which the poller no longer publishes; transition history lives in ClickHouse). On startup the poller also tombstones, the same way, any retained per-device topic whose host is absent from the site, and clears any retained `history`/`service_history` topic once; this is gated so that a failed or unconfirmed-empty Livestatus query never clears anything, and it adds no `removed` event.

`folder` is a generic location/group label derived from the host's Checkmk folder — whatever grouping the operator chose in the wizard's Phase 2 (a VLAN, a physical location, a site, etc.). It is read from Checkmk's REST folder association (`fetch_host_folders()` in `scripts/mqtt_poller.py`), not parsed from a filesystem path — see §3's "First-time credential setup" for the credential this requires. `alias` is Checkmk's native host alias, set optionally through the wizard's Phase 4 prompt; it is empty for any host without one. `address` is the host's configured IP, read from Livestatus's `hosts.address` column; it is empty for a host with no configured address (e.g. an unmanaged switch), and absent entirely from payloads written by a poller older than quick task 260928-m6f.

`state` on an agent host (one with a `Check_MK Agent` service) is the worst of the services the dashboard shows — the wizard-chosen `Systemd Service <unit>` / `Service <name>` entries, `TCP Port N` checks, CPU, memory, filesystem and SMART services, `Check_MK` and `Uptime` — not Livestatus's `worst_service_state`, so a service the dashboard hides (for example `Systemd Timesyncd Time` or `Systemd Service Summary`) cannot turn the host CRIT (quick 261003-lnr). Hosts without an agent, and any host whose host state is DOWN/UNREACHABLE, are unchanged. On a cycle whose services query failed the host-column state is published as before.

`staleness` (Phase 11, D-17) is Checkmk's own authoritative Livestatus `staleness` value (a float), additive to the payload above. It is `null` when the live site's `hosts` table does not expose the column — a graceful degradation, not an error; a consumer should then fall back to a timestamp-age check against `timestamp` above. `host_state_raw` (Phase 11, D-17) is also additive: one of `UP`/`DOWN`/`UNREACH`, derived from Checkmk's raw host-state integer. **`state` never contains `"UNREACH"`** — it keeps its collapsed `OK`/`WARN`/`CRIT`/`UNKNOWN`/`DOWN` meaning, folding both DOWN and UNREACHABLE raw states into `"DOWN"`; a consumer that needs to tell them apart must read `host_state_raw` instead. Both fields are additive — a subscriber written before Phase 11 sees a payload it already understands, just without these two keys.

The fifteen gauge keys above (Phase 12, D-12) — `cpu_percent`/`cpu_warn`/`cpu_crit`, `ram_percent`/`ram_warn`/`ram_crit`, `disk_percent`/`disk_warn`/`disk_crit`, `disk_other_worst_percent`/`disk_other_worst_warn`/`disk_other_worst_crit`/`disk_other_worst_mount`, `smart_total`/`smart_failing` — are additive to `status` and follow the same null-when-absent convention as `staleness`: each is `null` when its backing Checkmk service does not exist, never an omitted key. `sites/<site_id>/lan/devices/{id}/services` is a new topic, not an additive payload, so no pre-Phase-12 subscriber is affected by its existence — it is simply absent from a subscriber that has not added the new subscription.

**`sites/<site_id>/lan/incidents/{incident_id}/status` (Phase 14, PLR-14/PLR-15/PLR-16):** the incident id is `incident-{root host id}`; a closed incident is cleared with an empty retained payload, the same tombstone contract as every other topic above. The poller rebuilds the full incident set from Livestatus every cycle — there is no poller-side incident file — and, after a restart, `reconcile_state()` reads only the retained incident *topic names* (never the payload body) so the first post-restart cycle republishes a still-open incident unchanged or tombstones one that closed while the poller was down. Grouping rules, one sentence each:

- A DOWN host whose parent is not an unmanaged switch is a root.
- UNREACH hosts, and DOWN hosts reachable through a contiguous chain of non-OK hosts, join the topmost root.
- An unmanaged switch becomes an *inferred* root when at least two of its children are non-OK and at least one of those is DOWN, and every consequence of an inferred incident is reported as `not_observable`, never `confirmed_down` (Checkmk cannot see past an unchecked switch).
- A lone DOWN host under an unmanaged switch is its own incident, not folded into the switch.

`since` comes from Livestatus's `last_state_change` and is `null` if the column is absent (or every candidate value is non-positive). `worst_criticality` counts the root, every consequence, and every host that transitively depends on them (host-level criticality only — per-service criticality does not feed this in Phase 14) and defaults to `low` until an operator sets criticality labels. Known v1 limitation: an unrelated host that happens to be DOWN at the same time, inside the same non-OK chain, is folded into the incident as a consequence — Livestatus's `parents`/`host_state_raw` alone cannot disambiguate "down because of the incident" from "coincidentally also down".

**Criticality and dependency labels (Phase 14, PLR-16/DASH-16):** three Checkmk host labels drive
the incident engine's severity and dependency fan-out above. All three are written by the
dashboard's "Edit topology" mode (the `CriticalityEditor` panel, plan 14-08) using the same
`topology_editor` credential Phase 13's map edits already use — no new Checkmk permission is
needed — and go live only once **Apply changes** is pressed, identical to every other topology
edit. They can equally be hand-edited directly in Checkmk (Setup > Hosts > *host* > Labels); the
poller reads whichever value Checkmk actually stores, dashboard or not.

- `criticality`: one of `low`/`medium`/`high`/`critical`, set on the host itself. Absent, or any
  other value, degrades to `low`.
- `service_criticality`: `<name>=<tier>;<name>=<tier>;...`, a per-service override on the host. A
  service name may not contain `:` (reserved by Checkmk's own service naming), `;` or `=` (this
  label's own separators). Stored and republished on every topology node, but does **not** feed
  `worst_criticality` in Phase 14 — only host-level `criticality` does.
- `depends_on`: `<host>,<host>,...`, set on the *dependent* host, listing the hosts it depends on.
  This is what lets `worst_criticality` count a still-UP dependent one tier below a critical host
  it depends on that is currently down (D-15).

The poller's label parsers never raise: an out-of-vocabulary tier, a malformed entry (missing
`=`, empty name, a name containing a reserved character), or an invalid host id is silently
dropped rather than rejected or crashing the poll cycle. Both multi-value labels are capped
against a runaway label value — `service_criticality` at 200 entries, `depends_on` at 50 ids —
counting only the entries that parsed successfully, not raw comma/semicolon-split segments.

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

[`scripts/smoke_test_broker.py`](../scripts/smoke_test_broker.py) proves the Mosquitto hardening actually holds against a live broker — configuration alone doesn't demonstrate it. Its `--poller-password`/`--ws-password` default from the `MQTT_POLLER_PASSWORD`/`WS_PASSWORD` environment variables, and `--site-id` defaults to `CMK_SITE_ID`, so source `deploy/.env` first. From the repo checkout on the deployment host:

```bash
set -a; . deploy/.env; set +a
uv run python scripts/smoke_test_broker.py
```

From inside the `worker` container (which cannot restart its sibling `mosquitto` service, hence `--skip-restart`): the worker container does not carry `MQTT_POLLER_PASSWORD`/`WS_PASSWORD` in its own environment, so pass them explicitly:

```bash
uv run python scripts/smoke_test_broker.py --host mosquitto --ws-port 9001 --skip-restart \
  --poller-password "$MQTT_POLLER_PASSWORD" --ws-password "$WS_PASSWORD" \
  --site-id "$CMK_SITE_ID"
```

What each check proves:

- `poller_publish` / `ws_subscribe` — the WebSockets listener is reachable and distinct from 1883
- `ws_publish_denied` — the `wsreader` ACL is read-only; a write attempt never reaches an independent privileged subscriber
- `check_wsreader_cannot_read_legacy` — `wsreader` cannot read the old un-namespaced `lan/#` topics
- `check_poller_legacy_write` — the poller still holds the temporary legacy grant it needs for the one-time sweep
- `persistence_across_restart` — a retained message survives a broker restart (skipped by `--skip-restart`)

### Poller smoke test

[`scripts/smoke_test_poller.py`](../scripts/smoke_test_poller.py) proves the live Livestatus column set and four of the five Phase 9 success criteria against a running stack — configuration alone doesn't demonstrate any of this. From the repo checkout on the deployment host:

```bash
uv run python scripts/smoke_test_poller.py   # --site-id defaults to CMK_SITE_ID
```

From inside the `worker` container (which cannot restart or kill its sibling `poller` service, hence `--skip-restart-checks`):

```bash
uv run python scripts/smoke_test_poller.py --host mosquitto --livestatus-host checkmk --skip-restart-checks --site-id "$CMK_SITE_ID"
```

What each check proves:

- `check_livestatus_columns` — the live site's `hosts` table actually exposes the columns the poller queries (resolves RESEARCH.md Open Question 1)
- `check_device_status_retained` — Success Criterion 1 (PLR-03, PLR-08): a retained `sites/<site_id>/lan/devices/{id}/status` payload matches the fixed contract
- `check_topology_retained` — the payload half of PLR-01/PLR-04
- `check_device_enrichment` — TAG-03: plan 10-03's `alias`/`folder` enrichment actually reached retained device payloads. An all-empty `folder` result points straight at the `CMK_REST_SECRET` step in §3 — that's the cause when this check fails
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

Corrected 2026-09-16: this line previously read `uv run python scripts/mqtt_poller.py
--check-columns`, which is an `automation-worker` command (that container installs `uv`; the
poller container does not) written as if it were a host command. Run from a host shell it fails
on DNS or connect, which reads like a site problem rather than a wrong-command problem. Every
bare `uv run` elsewhere in this section is likewise a command for inside `automation-worker` at
`/app/checkmk-wizard`, never for the deployment host itself.

**Manual tombstone test:** the fifth Phase 9 success criterion (a real Checkmk host deletion) needs a live Checkmk site to delete a host from, so it isn't automated. Delete a host in the Checkmk UI, activate changes, wait one poll interval, then confirm with:

```bash
set -a; . deploy/.env; set +a
mosquitto_sub -h <host> -p 1883 -u poller -P "$MQTT_POLLER_PASSWORD" -t 'sites/<site_id>/lan/devices/<host>/status' -v -C 1 -W 5
```

Live-verified 2026-09-08 (deleting `192.168.0.215`): a zero-length retained publish is a *clear*, not a delivered empty message, so `mosquitto_sub` without `-C`/`-W` would simply hang with no output. `-C 1 -W 5` makes that observable: the subscribe times out ("Timed out", RC 27) with no message received, which is what confirms the retained status was cleared. Also confirm the host is gone from `sites/<site_id>/lan/devices/topology` and that a `removed` event appears in `sites/<site_id>/lan/events/recent`.

### History read-path smoke test (Phase 14.1)

[`scripts/smoke_test_history_proxy.py`](../scripts/smoke_test_history_proxy.py) proves the read-only ClickHouse/rollup HTTP path (HIST-08/HIST-09/HIST-10): that `/ch-api/` and `/availability/` answer GET reads as the read-only `dashboard_reader` identity, that every write/admin/system-table/credential-override path through them is refused, and that Grafana requires login. From the repo checkout on the deployment host:

```bash
uv run python scripts/smoke_test_history_proxy.py --host <podman-host> --grafana-password "$GRAFANA_ADMIN_PASSWORD"
```

The rollup-object checks need at least one day's availability rollup to already exist in `fleet-availability` — the poller backfills on startup once it has a previous local day's data in ClickHouse, so run this after the stack has been up across at least one local midnight (Asia/Singapore), or after confirming a rollup object exists by hand (`mc ls local/fleet-availability/availability/` from inside a MinIO client, or an `/availability/...` GET once you know a date). As with the broker and poller smoke tests, if you change poller code or need to re-apply a compose change, restart the whole stack (`podman compose down && podman compose up -d`) rather than a single service — see §5.1.

### Dashboard check (Phase 11)

With the stack up (§4) and at least one poll cycle elapsed, open `http://<HOST_IP>:8090/` from any
LAN browser. Confirm:

- The connection indicator (top-right of the top bar) reads "Connected", not "Connecting…" or
  "Disconnected — retrying".
- The device list populates from the broker's own retained messages — this should happen without
  restarting the `poller` service, since every topic in §6's MQTT topic contract is published with
  `retain: true` specifically so a freshly-opened browser tab gets the current fleet state
  immediately, not just future updates.

If the indicator never leaves "Connecting…", check that `WS_USERNAME`/`WS_PASSWORD` in
`deploy/.env` (visible via `curl http://HOST:8090/config.json`) are the values the `mosquitto`
container's own entrypoint used to build its password file (`podman logs mosquitto` shows no
password-file errors — see §3's "First-time credential setup" troubleshooting note), and that
port 9002 is reachable from the browser's own network, not just from the deployment host.

### Topology map check (Phase 13)

With `TOPOLOGY_EDITOR_SECRET` provisioned (§3) and the stack up, condensed from the full live
UAT checklist:

1. Confirm the poller's `sites/<site_id>/lan/devices/topology` payload carries `map_position`/`unmanaged` keys
   on each device node (`mosquitto_sub -u wsreader -P wsreader -t sites/<site_id>/lan/devices/topology -C 1 -W 5`).
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
   not a bug, a documented degradation (see §6's incident topic paragraph).
2. `mosquitto_sub -u wsreader -P wsreader -t 'sites/<site_id>/lan/incidents/#' -v -C 1 -W 5` shows any currently
   open incidents (one retained message per open incident); with none open it times out
   ("Timed out", RC 27) with no message received, the same clear-vs-empty distinction as the
   manual tombstone test above.
3. To provoke one safely: **do not use Checkmk's GUI "Fake check results"** — live-verified
   2026-09-26 (plan 14-05), its result is overwritten by the host's own next real active check
   (~1 minute for a host with no IP, whose real check always returns UP), so a fake can vanish
   within about a minute, often before it's clearly visible. Use Livestatus external commands
   instead (`DISABLE_HOST_CHECK` first, then `PROCESS_HOST_CHECK_RESULT`, then
   `ENABLE_HOST_CHECK` to reverse) — see `docs/Incident demo with fake check results.md` for the
   exact commands, scenario scripts (single host, managed switch, unmanaged/inferred switch,
   poller restart), and cleanup/verification steps.
4. Expected dashboard result: within about two poll cycles, one incident card appears in the Incidents
   pane at the top of the right-hand column (`"{host} — {duration}"`, worst-criticality colour), the affected hosts dim in
   the fleet tree and on the topology map with a "See incident" link, and restoring the faked
   state clears the card and the dimming within about two more poll cycles.

See `dashboard-react/README.md`'s "5c. Incidents" section for the full card/dimming behaviour.

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
podman exec --interactive --tty automation-worker bash -c "cd /app/checkmk-wizard && uv run checkmk-wizard"
```

What to expect, that's different from running it directly on a Checkmk host:

- **Phase 1 opens by announcing container mode** ("'omd' isn't on PATH — assuming this wizard is running in a separate container from Checkmk itself") and skips straight to a site-name prompt, pre-filled with `dmc` from the `CMK_SITE_ID` env var (§3) — just confirm it. The default follows `CMK_SITE_ID` from `deploy/.env` (see §3 "Choosing the site name"); the name has to match the site the `checkmk` container actually created — the wizard cannot rename it.
- **Checkmk host/IP prompt:** pre-filled with `checkmk:5000` (`checkmk` is the service's hostname on `cmk_net`, which is what actually resolves to Checkmk from inside the `worker` container; `:5000` because the `checkmk` service serves its site on container port 5000 internally — see §3's compose file `ports: "8080:5000"` mapping, and the `worker` service's own `CMK_REST_API=http://checkmk:5000/...`) — just press Enter to accept it. The `:5000` is the web/REST port only; the Livestatus check on `checkmk:6557` (§5) is unaffected, so the following bullet still reads correctly. Only type a different host (with or without its own `:port`) if the Checkmk service is reachable under another name.
- **Livestatus reachability check:** warns immediately if §5 wasn't done yet, and also when port 6557 accepts connections but answers only TLS (`LIVESTATUS_TCP_TLS` on) — fix it and re-run, or ignore and fix it before Phase 7.
- **cmkadmin password prompt:** not pre-filled. The prompt reminds you that on a freshly created site whose password was never changed, it is the compose default `cmkadmin` (§3); if you already changed it on an earlier run, type the new one. The wizard then offers (default yes) to change it to one you choose via the REST API. `compose.yaml` keeps `CMK_PASSWORD=cmkadmin` and needs no update, since Checkmk only reads it when the site is first created. The wizard uses the resulting password once, over the REST API, to bootstrap the `automation` and `agent_registration` REST users itself — it's never stored anywhere by the wizard. The `automation` user is provisioned with the `CMK_REST_SECRET` from `deploy/.env` automatically (updated if it already exists) and that value is not printed. Clear it and leave it blank instead if you'd rather paste an automation secret directly (fetched via `podman compose exec checkmk cat /omd/sites/dmc/var/check_mk/web/automation/automation.secret`, for example).
- **Phase 3 network scanning / Phase 5 SSH onboarding** reach out to your actual LAN from the `worker` container over `cmk_net`'s bridge (outbound NAT) — same subnets/targets you'd scan and SSH into from any other host on that network, no extra container networking config needed.

### 8.4. Re-running later

Nothing here needs repeating on every run except §8.3 itself — dependencies (§8.2) and Livestatus TCP (§5) only need doing once (or again after `uv.lock` changes or a site recreation, respectively). checkmk-wizard also detects an already-provisioned `automation`/`agent_registration` user on re-runs and falls back to asking for its existing secret instead of failing (see the main [README.md](../README.md#prerequisites)).

### 8.5. Starting over with a blank site

`deploy/reset-site.sh` automates this whole section: it detects the site in the `checkmk_data` volume, asks you to confirm its name, asks for a new site name (Enter keeps it; Esc or Ctrl+C aborts with nothing changed), writes it to `CMK_SITE_ID` in `deploy/.env` and does the full down/up. `--yes --site NAME` does it non-interactively. The by-hand steps follow.

To run the wizard against a genuinely fresh Checkmk site, remove the Checkmk volume **and** the Mosquitto volume (the second is recommended, see below):

- `checkmk_data` holds the site itself (hosts, folders, rules, tag groups, users, monitoring history). Removing it makes the container's entrypoint create a brand-new `dmc` site on the next start.
- `mosquitto_data` holds the broker's **retained** messages, which is all the dashboard reads (`sites/<site_id>/lan/devices/{id}/...`, `sites/<site_id>/lan/devices/topology`). On startup the poller reads every retained `sites/<site_id>/lan/devices/{id}/*` topic and clears the ones whose host is not on the site. This happens on its first cycle that has a confirmed host list: either Livestatus returned hosts, or Livestatus returned none and the REST API confirmed zero configured hosts (which needs `CMK_REST_SECRET`). So old hosts disappear from the dashboard without touching the broker volume. The sweep does not rewrite the global `sites/<site_id>/lan/events/recent` feed, though, and after a poller restart the old hosts' `removed` events carry no previous state (`from`/`to` both empty), so the dashboard's history lists them as "unknown → unknown". Remove `mosquitto_data` together with `checkmk_data` so the old site's event history goes with it.

Run from `deploy/` (compose prefixes volume names with its project name — `deploy_` here; confirm with `podman volume ls` and, if unsure, `podman inspect checkmk --format '{{range .Mounts}}{{.Name}} -> {{.Destination}}{{"\n"}}{{end}}'`):

```bash
podman compose down
podman volume rm deploy_checkmk_data deploy_mosquitto_data
podman compose up -d
```

If you only want to clear the events feed and keep everything else in the broker, publish an empty retained message instead (the poller rebuilds the feed from empty):

```bash
set -a; . deploy/.env; set +a
podman exec mosquitto mosquitto_pub -h localhost -u poller -P "$MQTT_POLLER_PASSWORD" -t sites/<site_id>/lan/events/recent -r -n
```

If you rebuilt Checkmk **without** a full `podman compose down`, the poller kept running. The sweep runs only at poller startup, so restart the stack afterwards with `podman compose down && podman compose up -d`. Don't use `podman compose restart poller`: restarting a single container can cut Checkmk off from the LAN (see §5.1, "A third signature").

Leave `deploy_mosquitto_log` and `deploy_minio_data` alone. The broker's ACL is rendered at every start from the bind-mounted `mosquitto.acl.template`; its users are regenerated from `deploy/.env` at every start (quick 260930-jj4) — both survive the volume wipe.

Then, on the fresh site:

1. Make sure `deploy/.env` holds a `CMK_REST_SECRET` (any long random value, e.g. `openssl rand -base64 24`) **before** running the wizard. The wizard creates the `automation` user with that secret, so the worker and poller need no hand-copying afterwards. Restart the poller if it started before you set the value.
2. Livestatus-over-TCP comes up on its own, in plain text (`CMK_LIVESTATUS_TCP=on` plus the pre-start hook in `compose.yaml`, see §5); check with `podman compose exec checkmk omd config dmc show LIVESTATUS_TCP` (expect `on`) and `podman compose exec checkmk omd config dmc show LIVESTATUS_TCP_TLS` (expect `off`).
3. Run the wizard (§8.3).
4. Nothing to do for the topology editor if you use the editable topology map: the `topology_editor` role and user lived in the deleted site, but the wizard re-provisions them from `TOPOLOGY_EDITOR_SECRET` as part of step 3's run (amended 2026-09-30, quick 260930-hpy — previously required a manual re-run of `scripts/provision_topology_editor.py` here).
5. Hard-refresh the dashboard (Ctrl+Shift+R).

Everything on the old site is gone after this, including the monitoring history (RRD data) — there is no undo.

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

---

## 10. Starting the Stack at Boot (systemd User Service)

While `restart: unless-stopped` is configured in `compose.yaml`, **rootless Podman does not run a background daemon**. When the host reboots, systemd starts your user session (thanks to `loginctl enable-linger`), but it does not execute `podman compose up` on its own.

To make the stack start on system boot, create a systemd user service. The same steps, in short form, are in [`DEPLOY-NEW-MACHINE.md`](DEPLOY-NEW-MACHINE.md) step 9.

---

### Step 1: Create the systemd User Service

Create the systemd user directory if it doesn't exist:

```bash
mkdir -p ~/.config/systemd/user
```

Create `~/.config/systemd/user/checkmk-stack.service`:

```ini
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
```

*(Note: `%h` resolves to your home directory, e.g. `/home/kone`, and `%U` to your numeric UID, e.g. `1000`.)*

Why it looks like this (corrected 2026-09-30; the earlier version of this unit had three problems):

- **`WorkingDirectory`** used to be `%h/checkmk-stack`, from the layout before Phase 9 moved `compose.yaml` into the repo's `deploy/` directory (§2). From there, `podman compose` finds no `compose.yaml`. And a directory that *does* hold one but has a different name starts a separate compose project with its own, empty volumes.
- **`network-online.target` is gone.** It exists only in the system manager, so a user unit that waits on it waits on nothing.
- **`Wants=podman.socket` is added.** `After=` alone only orders the unit after the socket; it doesn't start the socket.

`TimeoutStopSec=180` gives `compose down` more than the default 90 seconds at shutdown. No start timeout is needed: systemd disables it for `Type=oneshot` (`man systemd.service`, `TimeoutStartSec=`), so a slow first image pull at boot is not cut off. The unit file was checked with `systemd-analyze --user verify` (systemd 257).

---

### Step 2: Take Over the Running Stack and Enable the Service

If you started the stack by hand before, take it down first so the service starts it fresh. Volumes are kept.

```bash
cd ~/checkmk-stack/app/checkmk-wizard/deploy
podman compose down

systemctl --user daemon-reload
systemctl --user enable --now checkmk-stack.service
```

---

### Step 3: Verify Status

```bash
systemctl --user status checkmk-stack.service   # expect: Active: active (exited)
loginctl show-user $USER --property=Linger      # expect: Linger=yes
podman compose ps                               # all six containers Up
```

The system will now run `podman compose up -d` under your user during boot, before anyone logs in, and a clean `podman compose down` at shutdown or reboot. Reboot once and confirm the stack comes back without logging in, e.g. by opening the dashboard on port 8090 from another machine.

After editing the unit file, run `systemctl --user daemon-reload`. `systemctl --user stop` / `start checkmk-stack.service` does the same full down/up as running compose by hand (see §5.1 on why a full down/up rather than a single-service restart).

---

### Troubleshooting

Read the full error with `journalctl --user -u checkmk-stack.service -e`; `systemctl status` truncates long lines.

**`no configuration file provided: not found`**: `WorkingDirectory` doesn't point at the repo's `deploy/` directory.

**`the container name "…" is already in use`**: an example seen on 2026-09-02 with the old unit:

```text
× checkmk-stack.service - Checkmk, Mosquitto, MinIO, and Worker Podman Compose Stack
     Active: failed (Result: exit-code) since Wed 2026-09-02 05:22:00 UTC; 21s ago
Sep 02 05:22:00 kone-dmc-test podman[228845]:  Volume checkmk-stack_checkmk_data Created
Sep 02 05:22:00 kone-dmc-test podman[228845]:  Container checkmk Creating
Sep 02 05:22:00 kone-dmc-test podman[228845]: Error response from daemon: container create: creating container storage: the container name "automation-work>
Sep 02 05:22:00 kone-dmc-test podman[228833]: Error: executing /usr/libexec/docker/cli-plugins/docker-compose up -d: exit status 1
```

`Volume checkmk-stack_checkmk_data Created` is the tell: the service ran compose from a different directory than the manual `podman compose up -d`, so compose saw a new project (`checkmk-stack`), created new empty volumes, and then collided with the existing containers' fixed `container_name`s. Fix `WorkingDirectory` first. Then remove the old containers (volumes are not touched) and restart the service:

```bash
podman rm -f checkmk mosquitto minio automation-worker mqtt-poller dashboard 2>/dev/null || true
systemctl --user restart checkmk-stack.service
```

If a stray project's empty volumes were created (like `checkmk-stack_checkmk_data` above), list them with `podman volume ls` and remove only those with `podman volume rm`. Keep the `deploy_*` ones: they hold your site.
