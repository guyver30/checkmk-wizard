# Phase 8: Broker Infrastructure Hardening - Research

**Researched:** 2026-09-05
**Domain:** Eclipse Mosquitto 2.x multi-listener/ACL configuration inside an existing rootless-Podman-Compose stack; `paho-mqtt` for a live smoke test
**Confidence:** HIGH (Mosquitto config syntax, ACL semantics, official Docker image internals — verified against official docs/source) / MEDIUM (exact interaction of some edge cases with the specific `eclipse-mosquitto:2` tag currently pinned in this repo's baseline doc — recommend a live spot-check during implementation)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Check real config files into this repo under a new `deploy/` directory (`deploy/compose.yaml`, `deploy/mosquitto.conf`, `deploy/mosquitto.acl`, `deploy/mosquitto.passwd`) as the canonical source of truth — this repo currently has zero infra-as-code files; today it's only markdown snippets in `docs/Podman setup for checkmk, minio, mosquitto, worker.md`.
- **D-02:** `deploy/compose.yaml` is the **full 4-service stack** (`checkmk`, `mosquitto`, `minio`, `worker`) — not just a mosquitto fragment — replacing the copy currently only embedded in the doc. Phase 11's `dashboard` nginx service extends this same file later; one canonical file going forward.
- **D-03:** `docs/Podman setup for checkmk, minio, mosquitto, worker.md` is updated to reference `deploy/compose.yaml` / `deploy/mosquitto.conf` (e.g. "see deploy/compose.yaml") instead of duplicating the full block inline, so the doc and the real config can't silently drift apart.
- **D-04:** The existing `1883` TCP listener **stays published to the LAN** in `deploy/compose.yaml` (`ports: "1883:1883"`) in this phase — user explicitly wants it reachable for debugging for now, even though PITFALLS.md flags an unauthenticated LAN-reachable publish port as undermining the point of ACL-hardening the WS listener.
- **D-05:** 1883 gains **username/password authentication** for the poller via the same `acl_file`/`password_file` mechanism as the WS listener — no longer purely `allow_anonymous true`. No topic-level ACL restriction is required on 1883 beyond requiring valid credentials to connect (full read/write for the authenticated poller user is fine).
- **D-07:** A standalone **automated smoke-test script** is checked into the repo — not part of the existing mocked pytest suite (this project's tests never touch live infrastructure, by established convention) — that verifies: a WS client can connect and subscribe, a WS publish attempt is rejected by the ACL, and retained messages survive a broker restart.
- **D-08:** `paho-mqtt` is added as a project dependency now via `uv add paho-mqtt` to back the smoke-test script, since Phase 9's poller needs it anyway (v2.1.0, `CallbackAPIVersion.VERSION2` — per `.planning/research/SUMMARY.md`). One well-tested client shared between the smoke test and the future poller instead of shelling out to CLI tools.
- **D-09:** `deploy/mosquitto.passwd` is checked into the repo **pre-hashed with fixed default credentials** (a read-only WS user, a poller user for 1883), documented in the Podman setup doc as disposable dev/local defaults to rotate before exposing beyond a trusted LAN — matching this project's existing convention for default credentials (`cmkadmin`/`cmkadmin`, `minioadmin`/`minioadmin`).

### Claude's Discretion

- Exact ACL file syntax/topic patterns (e.g. `lan/#` read-only for the WS user)
- Exact username naming (e.g. `wsreader`, `poller`)
- Mosquitto password-hash generation method for the checked-in file (`mosquitto_passwd` invocation), documented so it's reproducible
- Smoke-test script's exact location/structure (e.g. `scripts/smoke_test_broker.py` vs. a `tests/smoke/` dir — kept clearly separate from the mocked pytest suite either way)
- Exact internal layout of `deploy/`

### Deferred Ideas (OUT OF SCOPE)

- Restricting the 1883 TCP listener to container-internal-only network reachability (dropping its LAN port publish, or `bind_interface` scoping) — explicitly deferred by the user to a later hardening pass, not part of Phase 8.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-------------------|
| BRK-01 | Mosquitto gains a WebSockets listener for browser clients, separate from the existing internal TCP listener the poller uses to publish | Pattern 2/3 (listener block ordering + correct mount path), Pitfall 1 (mount path) and Pitfall 2 (port collision) directly govern whether this listener is actually reachable as intended |
| BRK-02 | Mosquitto has `persistence true` against a mounted volume, so retained state survives a broker restart | Pattern 2 (global settings placement, tightened `autosave_interval`), Code Examples "Verifying persistence across a restart"; note under Summary that the *existing* baseline doc already specifies `persistence true` — the gap this phase closes is making it a real, checked-in, verified artifact (and fixing the mount-path bug that would otherwise make it a no-op) |
| BRK-03 | The WebSocket listener is ACL-scoped to read-only for browser clients; only the poller (via the internal listener) can publish | Pattern 1 (global acl_file/password_file with per-user scoping), Pitfall 3 (MQTT 3.1.1 ack semantics — critical for how the smoke test must verify this requirement), Code Examples "Smoke test — WS publish-denied" |
</phase_requirements>

## Summary

Phase 8 turns a markdown-only Mosquitto sketch (`docs/Podman setup for checkmk, minio, mosquitto, worker.md`) into real, checked-in, access-controlled, durable broker configuration under `deploy/`. The technical core is well-trodden: Mosquitto 2.x supports multiple `listener` blocks natively (one plain-TCP for the poller, one `protocol websockets` for browsers), a single global `acl_file`/`password_file` pair (no `per_listener_settings` needed, since ACL enforcement is per-*user*, not per-*listener*, and both listeners can share one file with different users granted different rights), and `persistence true` against a mounted volume for retained-message durability. All of this is HIGH-confidence, official-docs-verified territory — the STACK.md/ARCHITECTURE.md/PITFALLS.md research already produced for this milestone gives the right shape.

This research surfaced three concrete, actionable problems that were **not** visible in the milestone-level research and must be corrected in this phase's plan, not carried forward as latent bugs:

1. **The baseline doc's config mount path is almost certainly wrong.** The official `eclipse-mosquitto` image's baked-in `CMD` is `mosquitto -c /mosquitto/config/mosquitto.conf` — there is no fallback to, or symlink from, `/etc/mosquitto/mosquitto.conf` (confirmed against the image's own Dockerfile/entrypoint source). The current doc mounts the custom conf to `/etc/mosquitto/mosquitto.conf`, which the running process never reads. This must move to `/mosquitto/config/mosquitto.conf` (and the new ACL/password files alongside it) as part of this phase's `deploy/compose.yaml`, or the whole hardening effort silently has no effect.
2. **The proposed WebSockets host port (9001) collides with MinIO's already-published console port** (`9001:9001` in the existing 4-service `compose.yaml`). Since D-02 makes `deploy/compose.yaml` the *full* 4-service stack, this collision is real, not hypothetical, and must be resolved by publishing the WS listener on a different host port (container-side port 9001 is fine internally; recommend host `9002:9001`).
3. **MQTT 3.1.1 (the default protocol both `paho-mqtt` and Mosquitto negotiate unless told otherwise) gives no reliable error signal when a publish is ACL-denied.** Mosquitto still sends a normal PUBACK to the denying client for QoS 1/2 publishes — the message is silently dropped, not rejected with an error the client can see. The smoke test required by D-07 (verify "a WS publish attempt is rejected") **cannot** check a return code; it must functionally verify the message never arrives (subscribe as a privileged client, assert nothing shows up within a bounded window), because the publisher-side call will appear to succeed either way.

**Primary recommendation:** Build `deploy/mosquitto.conf` with global auth/persistence settings declared before any `listener` line, mount all three Mosquitto config artifacts under `/mosquitto/config/` (not `/etc/mosquitto/`), publish the new WS listener on host port 9002, and write the smoke test around `paho.mqtt.publish.single()` / a raw `Client` with a bounded `event.wait()` — never `paho.mqtt.subscribe.simple()` for the "assert nothing arrives" case, since it has no timeout and will hang forever if the ACL correctly denies the write.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| MQTT message broker / retained-state store | Database / Storage (broker-as-datastore) | — | Mosquitto's retained-message store IS the persistence layer for this milestone; no separate DB |
| WebSockets transport for browser clients | API / Backend (broker boundary) | Browser / Client (consumer) | Mosquitto's own listener terminates the WS connection directly — no reverse proxy tier in this phase |
| Access control (who may publish/subscribe) | API / Backend (broker boundary) | — | Enforced entirely at the broker via `acl_file`/`password_file`; no application-layer auth exists or is needed |
| Container/network wiring (`compose.yaml`) | Infra / Deployment | — | Not a request-serving tier; governs how the other tiers reach each other and the LAN |
| Smoke-test verification script | Dev tooling (out-of-band) | — | Not part of the running system; a one-shot verification client, stylistically consistent with `livestatus.py` |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `eclipse-mosquitto` (Docker image) | `2` tag currently resolves to the 2.1.x line; **2.1.2** confirmed current stable at research time `[CITED: mosquitto.org/download]` | MQTT broker with native multi-listener + WebSockets support | Already the project's chosen broker; no change needed, only configuration |
| `paho-mqtt` | **2.1.0** `[VERIFIED: PyPI JSON API — https://pypi.org/pypi/paho-mqtt/json, confirmed live 2026-09-05]` | Backs the new smoke-test script (and, per `.planning/research/SUMMARY.md`, Phase 9's poller) | Eclipse Foundation's reference Python MQTT client; already the milestone's chosen library; `paho.mqtt.publish`/`paho.mqtt.subscribe` one-shot helpers are purpose-built for exactly this phase's smoke-test shape |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `mosquitto_passwd` (CLI, ships inside the `eclipse-mosquitto` image) | bundled with image | Generates the argon2id-hashed `deploy/mosquitto.passwd` file | Run once via `podman run --rm -v ./deploy:/mosquitto/config eclipse-mosquitto:2 mosquitto_passwd -b -c /mosquitto/config/mosquitto.passwd <user> <pass>` — no local mosquitto install needed on the dev machine |
| Python stdlib `threading.Event` | stdlib | Bounded wait for the "publish was rejected" smoke-test assertion | `paho.mqtt.subscribe.simple()`/`callback()` have no timeout parameter (confirmed against source) and will hang forever if nothing arrives — needed only for that one negative-assertion test case |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Mosquitto's native `protocol websockets` listener | nginx reverse-proxy WS→TCP bridge in front of a TCP-only Mosquitto | More moving parts, no benefit at this milestone's scale; already rejected by milestone-level ARCHITECTURE.md research — do not revisit in this phase |
| Single global `acl_file`/`password_file` (per_listener_settings=false, default) | `per_listener_settings true` with separate ACL/password files per listener | Only worth it if the two listeners ever need genuinely different user namespaces; D-05 explicitly wants the *same* mechanism reused for both, so the simpler global-file approach matches the locked decision |
| `mosquitto_passwd`'s default `argon2id` hash | `-H sha512-pbkdf2` or `-H sha512` | No reason to deviate; argon2id is the current default and strongest option shipped |

**Installation:**
```bash
uv add paho-mqtt
```

**Version verification:**
```bash
# Confirmed 2026-09-05 via PyPI JSON API (see Package Legitimacy Audit below)
curl -s https://pypi.org/pypi/paho-mqtt/json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['info']['version'])"
# -> 2.1.0
```
No `npm view`/`pip index versions` tool was available in the research sandbox (no `pip` binary present); version was confirmed directly against the PyPI JSON API instead, which is an equally authoritative source for this ecosystem.

## Package Legitimacy Audit

Only one new external package is introduced by this phase: `paho-mqtt` (the Docker images — `eclipse-mosquitto`, and already-present `checkmk`/`minio`/`python` base images — are unchanged, pre-existing dependencies, not newly introduced here).

`slopcheck` was installed and run successfully via `uvx slopcheck` (no `pip` binary was available in this sandbox, but `uvx` resolved and ran it without issue).

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `paho-mqtt` | PyPI | First release 0.4.90 (long-established; Eclipse Foundation project) | Millions/month (de facto standard Python MQTT client; not independently re-measured this session) | github.com/eclipse-paho/paho.mqtt.python | `OK` (`uvx slopcheck scan paho-mqtt --pkg pypi --json` → `"status": "OK", "flags": []`) | Approved |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

Package name provenance note: `paho-mqtt` was already known from this project's own `docs/src/mqtt_publisher_changes.py`/`mqtt_notify.py` prototypes and from the milestone-level `.planning/research/STACK.md` (itself sourced from Eclipse's official migration guide and the PyPI JSON API) — this qualifies as `[VERIFIED: PyPI registry]` per the provenance rule (official-docs-sourced name, registry-confirmed, slopcheck-clean), not `[ASSUMED]`.

## Architecture Patterns

### System Architecture Diagram

```
                         ┌─────────────────────────────────────────┐
                         │        Podman bridge network: cmk_net    │
                         │                                          │
  (not built yet,        │   ┌───────────────────────────────┐      │
   Phase 9)               │   │        mosquitto container     │     │
  worker/mqtt_poller  ───▶│   │  listener 1883 0.0.0.0          │     │  internal + LAN-published,
  (publishes, QoS1/0,      │   │    user "poller": readwrite     │     │  now requires poller
   retain=True)            │   │                                 │     │  credentials (was anonymous)
                         │   │  listener 9001 0.0.0.0          │     │
                         │   │    protocol websockets           │     │
                         │   │    user "wsreader": read-only    │     │
                         │   │                                 │     │
                         │   │  acl_file  /mosquitto/config/... │     │  ← global, both listeners
                         │   │  password_file /mosquitto/config/│     │  ← global, both listeners
                         │   │  persistence true                │     │
                         │   │  persistence_location /mosquitto/│     │
                         │   │    data/  (named volume)          │     │
                         │   └───────┬─────────────────┬─────────┘     │
                         │           │ published        │ published    │
                         │           │ host:1883         │ host:9002    │  ← NOT 9001 (MinIO
                         └───────────┼───────────────────┼──────────────┘     console conflict)
                                     ▼                   ▼
                         (poller,              LAN browser / mosquitto_sub -L
                          Phase 9,               ws://<host>:9002 (subscribe-only)
                          uses "poller"
                          credentials)
```

Data flow for this phase's own verification (no poller/dashboard exist yet):
```
[smoke_test.py --role wsreader]
    → connect ws://mosquitto:9002 (or LAN host:9002) as "wsreader"
    → subscribe "#"                                    → expect: succeeds, any retained msgs deliverable
    → publish "lan/smoketest" (as wsreader)             → expect: PUBACK returned (misleading!) but message
                                                            never actually retained/delivered — verify via
                                                            a SECOND, "poller"-credentialed subscriber instead
                                                            of trusting the publish() return value
[podman compose restart mosquitto]
    → re-subscribe as "poller" to a topic published+retained before the restart
    → expect: retained value still present (persistence proved)
```

### Recommended Project Structure
```
deploy/
├── compose.yaml          # full 4-service stack (checkmk, mosquitto, minio, worker) — D-02
├── mosquitto.conf         # two listeners, global acl_file/password_file, persistence true
├── mosquitto.acl          # "user poller" readwrite, "user wsreader" read-only lan/#
└── mosquitto.passwd       # pre-hashed (argon2id) disposable default creds — D-09

scripts/                   # (Claude's discretion location per CONTEXT.md)
└── smoke_test_broker.py   # paho-mqtt-based: WS connect+subscribe, WS publish-denied,
                            # persistence-survives-restart — NOT part of pytest suite
```

### Pattern 1: Global `acl_file`/`password_file` shared across both listeners

**What:** With `per_listener_settings` left at its default (`false`), one `acl_file` and one `password_file` apply to *every* listener. Access is scoped by matching the connecting client's *username* against `user <name>` blocks in the ACL file — not by which port/listener it connected on.
**When to use:** Exactly this phase's shape — two listeners, two distinct users (`poller` full access, `wsreader` read-only), no need for per-listener file scoping since the ACL is already granular per-user.
**Example:**
```text
# deploy/mosquitto.acl
# Source: mosquitto.org/documentation/plugins/acl-file/ (fetched 2026-09-05)

# Authenticated users not listed below get NO access at all (default-deny) —
# confirmed: "topic" lines outside a "user" block apply only to anonymous
# clients, and allow_anonymous is false in this phase's config.

user poller
topic readwrite #

user wsreader
topic read lan/#
```
**Note (Claude's discretion, exercised here):** `wsreader` is scoped to `lan/#` per CONTEXT.md's discretion note ("e.g. `lan/#` read-only for the WS user"), not the full `#` tree — this matches the milestone's actual topic namespace (`lan/devices/...`, `lan/poller/status`) and avoids also exposing Mosquitto's internal `$SYS/#` tree to browser clients unless explicitly desired.

### Pattern 2: Global settings declared before any `listener` line

**What:** Although `per_listener_settings=false` makes `allow_anonymous`/`acl_file`/`password_file`/`persistence` apply globally regardless of where they appear in the file, Mosquitto's own config parsing is otherwise position-sensitive for listener-scoped directives (anything after a `listener` line up to the next `listener` line is scoped to that listener). To avoid ambiguity for a future reader (or a future `per_listener_settings true` migration), declare every global directive **before** the first `listener` line.
**When to use:** Always, for this file — it's a documentation/maintainability improvement over the milestone-level ARCHITECTURE.md draft (which interleaved `allow_anonymous`/`persistence` between listener blocks), not a functional requirement.
**Example:**
```text
# deploy/mosquitto.conf
# Source: mosquitto.org/man/mosquitto-conf-5.html (fetched 2026-09-05)

# --- global settings (apply to all listeners; per_listener_settings left
#     at its default `false`) ---
allow_anonymous false
password_file /mosquitto/config/mosquitto.passwd
acl_file /mosquitto/config/mosquitto.acl

persistence true
persistence_location /mosquitto/data/
autosave_interval 60   # default is 1800s (30 min) — tightened per PITFALLS.md
                         # Pitfall 3, given expected low message volume

# --- listeners ---
listener 1883 0.0.0.0
# no "protocol" line -> defaults to plain MQTT

listener 9001 0.0.0.0
protocol websockets
```

### Pattern 3: Mount config artifacts under the image's actual default path

**What:** The official `eclipse-mosquitto` image's baked-in `CMD` is `["/usr/sbin/mosquitto", "-c", "/mosquitto/config/mosquitto.conf"]` (confirmed directly against the `docker/2.1-alpine/Dockerfile` on the `eclipse-mosquitto/mosquitto` GitHub repo). There is no documented fallback to `/etc/mosquitto/mosquitto.conf`, and no symlink between the two paths ships in the image.
**When to use:** Always, for this image. This phase's `deploy/compose.yaml` must mount all three new/changed files under `/mosquitto/config/`, correcting the existing baseline doc's `/etc/mosquitto/mosquitto.conf` mount (which the running process very likely never reads today).
**Example:**
```yaml
# deploy/compose.yaml (mosquitto service excerpt)
mosquitto:
  image: eclipse-mosquitto:2
  ports:
    - "1883:1883"
    - "9002:9001"     # NEW — host 9002 avoids clashing with MinIO's
                        # existing published "9001:9001" console port
  volumes:
    - ./mosquitto.conf:/mosquitto/config/mosquitto.conf:ro,z     # was /etc/mosquitto/...
    - ./mosquitto.acl:/mosquitto/config/mosquitto.acl:ro,z        # NEW
    - ./mosquitto.passwd:/mosquitto/config/mosquitto.passwd:ro,z  # NEW
    - mosquitto_data:/mosquitto/data:z
    - mosquitto_log:/mosquitto/log:z
```

### Anti-Patterns to Avoid
- **Trusting a successful `publish()` call/PUBACK as proof of ACL enforcement:** under MQTT 3.1.1 (the default both Mosquitto and `paho-mqtt` negotiate unless configured otherwise), a PUBACK is sent to the publishing client even when the broker silently drops the message due to an ACL denial. Verify by checking, from a *different, privileged* subscriber, that the message never actually arrived/retained — not by inspecting the publisher's own return value.
- **Publishing the WS listener on host port 9001:** collides with the existing `minio` service's already-published `9001:9001` console port in the same `compose.yaml`. Podman/Docker Compose will fail to bind the second service to the same host port.
- **Mounting config to `/etc/mosquitto/mosquitto.conf`:** the running `mosquitto` process inside this image never looks there; it always loads `/mosquitto/config/mosquitto.conf` per the image's own `CMD`.
- **Using `subscribe.simple()`/`subscribe.callback()` for a "confirm nothing arrives" test:** neither has a timeout parameter (confirmed against source) — the process will hang forever if the ACL is correctly denying the publish, which is exactly the success case being tested.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Topic-level read/write access control | A custom auth plugin, or application-layer topic filtering in a future dashboard | Mosquitto's built-in `acl_file` plugin | Native, zero extra dependencies, exactly matches the read-only-WS/full-access-poller requirement |
| Password hashing for broker credentials | Hand-rolled hashing/salting | `mosquitto_passwd` (ships in the image, defaults to argon2id) | Purpose-built, already the correct current-best-practice hash for this exact file format |
| One-shot MQTT publish/subscribe for the smoke test | A hand-rolled raw-socket MQTT client (mirroring `livestatus.py`'s pattern) | `paho.mqtt.publish.single()` / a `paho.mqtt.client.Client` with `loop_start()` | MQTT's wire protocol (unlike Livestatus's simple text LQL) has real complexity (CONNACK, keepalive pings, QoS handshakes) that `paho-mqtt` already handles correctly; hand-rolling here would be reinventing a mature client for no benefit |

**Key insight:** Every piece of this phase's actual hardening work (auth, ACL, persistence, WS transport) is a *configuration* problem solvable entirely inside `mosquitto.conf`/`mosquitto.acl`/`mosquitto.passwd` — there is no code to write for the broker itself, only for the verification script.

## Common Pitfalls

### Pitfall 1: Config mount path silently ignored (`/etc/mosquitto/` vs `/mosquitto/config/`)
**What goes wrong:** The custom `mosquitto.conf` (and, if placed there, the new ACL/password files) never actually get loaded by the running `mosquitto` process — the container instead runs whatever config is baked into the image at `/mosquitto/config/mosquitto.conf`.
**Why it happens:** The project's own baseline doc mounts to `/etc/mosquitto/mosquitto.conf`, which is a reasonable guess (matches Debian package conventions) but doesn't match this specific Docker image's `CMD`.
**How to avoid:** Mount all three files under `/mosquitto/config/` (see Pattern 3). Verify post-deploy with `podman compose exec mosquitto cat /mosquitto/config/mosquitto.conf` to confirm the container sees the intended content.
**Warning signs:** `allow_anonymous true` still appears to work even after setting `allow_anonymous false` in the mounted file; `podman compose logs mosquitto` shows Mosquitto starting with defaults instead of the custom listeners.

### Pitfall 2: WS host-port collision with MinIO's console port
**What goes wrong:** `podman compose up` fails outright (port already bound) or, worse under some compose implementations, silently binds only one of the two services to the conflicting host port.
**Why it happens:** The milestone-level ARCHITECTURE.md research picked `9001` for Mosquitto's WS listener as a common MQTT-over-WS convention, without cross-checking it against this specific project's existing `minio` service, which already publishes host `9001` for its web console.
**How to avoid:** Publish Mosquitto's WS listener on a different host port (`9002:9001` recommended — container-internal port stays the conventional `9001`, only the host-side mapping changes) and update `docs/Podman setup...md`'s endpoint table accordingly.
**Warning signs:** `podman compose up` errors with "address already in use" or one of `minio`/`mosquitto` fails to start.

### Pitfall 3: MQTT 3.1.1 gives no error on ACL-denied publish
**What goes wrong:** A smoke test that checks `publish()`'s return code (or waits for a PUBACK) will report "success" for a publish that the broker actually dropped — producing a false-positive pass for the exact security property (BRK-03 / success criterion 3) this phase exists to prove.
**Why it happens:** MQTT 3.1.1's PUBACK packet has no reason-code field at all (that's an MQTT 5 addition); Mosquitto acknowledges receipt of the PUBLISH packet from the client's TCP connection regardless of whether the ACL check later drops it server-side.
**How to avoid:** Structure the smoke test as: (1) connect as `wsreader`, publish a uniquely-named test topic with `retain=True`; (2) *separately*, connect as `poller` (or any user with read access to that topic) and subscribe, with a bounded wait (`threading.Event().wait(timeout=5)` pattern, not `subscribe.simple()`); (3) assert the message never arrives. Optionally corroborate via `podman compose logs mosquitto | grep "Denied PUBLISH"` if `log_type all` (or at least a verbose level covering ACL denials) is enabled — treat this as a supplementary check, not the primary one, since it depends on log verbosity configuration.
**Warning signs:** A smoke test that "passes" by checking only the publisher's own success/failure, with no independent verification that the message was actually withheld.

### Pitfall 4: Bind-mounted credential files unreadable by the container's non-root user
**What goes wrong:** The `eclipse-mosquitto` image runs the broker as a non-root `mosquitto` user/group with UID/GID **1883** (confirmed against the image's documented user setup). If the checked-in `mosquitto.passwd`/`mosquitto.acl` files are bind-mounted read-only with host permissions that UID 1883 can't read (e.g., `0600` owned by a different host UID with no world-read bit, common under rootless Podman's UID-mapping), Mosquitto fails to start or silently falls back to no-ACL/no-auth behavior.
**Why it happens:** Easy to overlook when the existing `mosquitto.conf:ro,z` mount already "just works" — a plain-text conf file is usually world-readable by default, but developers sometimes lock down permissions specifically on files that look like "password files," which is exactly the file most likely to need broad read access here for the container's non-root user to load it at all.
**How to avoid:** Keep default host file permissions (or explicitly `chmod 644`) on `deploy/mosquitto.passwd`/`deploy/mosquitto.acl`, matching the existing `mosquitto.conf`'s permissions; verify with `podman compose logs mosquitto` for permission-denied errors on startup.
**Warning signs:** Mosquitto container exits immediately after `podman compose up`; logs show "Unable to open acl_file" or "Unable to open password file."

## Code Examples

### Generating the password file (reproducible, no local mosquitto install needed)
```bash
# Source: mosquitto_passwd(1) man page (mosquitto.org/man/mosquitto_passwd-1.html,
# fetched 2026-09-05) — run via the image itself so no host install is required.
podman run --rm -v "$(pwd)/deploy:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd -b -c /mosquitto/config/mosquitto.passwd wsreader '<disposable-default-password>'
podman run --rm -v "$(pwd)/deploy:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd -b /mosquitto/config/mosquitto.passwd poller '<disposable-default-password>'
# -b = batch mode (password on the command line — acceptable here since these
#      are documented disposable dev defaults, not real secrets, per D-09).
# -c on the FIRST invocation only (creates/overwrites the file); omit -c on
#      subsequent invocations or it will wipe the previously added user.
```

### Smoke test — WS connect + subscribe (success path)
```python
# Source: paho-mqtt helpers docs (eclipse.dev/paho/files/paho.mqtt.python/html/helpers.html,
# fetched 2026-09-05) — subscribe.simple() is fine here since we DO expect a message
# (or just a clean SUBACK) and can bound msg_count.
import paho.mqtt.subscribe as subscribe

msg = subscribe.simple(
    "lan/#",
    hostname="mosquitto",  # or LAN host IP if run from outside cmk_net
    port=9002 if external else 9001,
    transport="websockets",
    auth={"username": "wsreader", "password": "<disposable-default-password>"},
    msg_count=1,
    retained=True,
)
```

### Smoke test — WS publish-denied (negative path, bounded wait required)
```python
# Source: paho.mqtt.client (eclipse-paho/paho.mqtt.python) — CallbackAPIVersion.VERSION2
# per this milestone's STACK.md guidance. subscribe.simple()/callback() have NO timeout
# parameter (confirmed against source) so a raw Client + threading.Event is used instead.
import threading
import paho.mqtt.client as mqtt
import paho.mqtt.publish as publish

received = threading.Event()

def on_message(client, userdata, msg):
    received.set()

privileged = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="websockets")
privileged.username_pw_set("poller", "<disposable-default-password>")
privileged.on_message = on_message
privileged.connect("mosquitto", 9001)
privileged.subscribe("lan/smoketest/deny-check")
privileged.loop_start()

# Attempt the disallowed publish AS the read-only user — PUBACK will likely
# still report "success" under MQTT 3.1.1; that return value is NOT checked.
publish.single(
    "lan/smoketest/deny-check",
    "should-never-arrive",
    hostname="mosquitto",
    port=9001,
    transport="websockets",
    auth={"username": "wsreader", "password": "<disposable-default-password>"},
    retain=True,
)

arrived = received.wait(timeout=5)  # bounded — subscribe.simple() cannot do this
privileged.loop_stop()
privileged.disconnect()
assert not arrived, "ACL FAILED: wsreader was able to publish"
```

### Verifying persistence across a restart
```bash
# Publish + retain a known value, restart the broker, confirm it survives.
podman compose exec mosquitto mosquitto_pub -h localhost -p 1883 \
  -u poller -P '<disposable-default-password>' \
  -t lan/smoketest/persist -m 'still-here' -r
podman compose restart mosquitto
podman compose exec mosquitto mosquitto_sub -h localhost -p 1883 \
  -u poller -P '<disposable-default-password>' \
  -t lan/smoketest/persist -C 1 -W 5
# Expect: prints 'still-here' — proves persistence true + the mounted
# volume actually round-tripped the retained message across a restart.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `allow_anonymous true`, single TCP listener, no persistence (current baseline doc) | Two listeners, global `acl_file`/`password_file`, `allow_anonymous false`, `persistence true` with tightened `autosave_interval` | This phase | Anonymous LAN clients can no longer publish/clear broker state at all; retained state survives restarts |
| paho-mqtt v1 callback API (`Client()` with no `CallbackAPIVersion`, 4-arg `on_connect`) — the pattern in `docs/src/mqtt_notify.py`/`mqtt_publisher_changes.py` | `Client(mqtt.CallbackAPIVersion.VERSION2)`, 5-arg callbacks with `ReasonCode` objects | paho-mqtt 2.0 (2024) | The smoke-test script must use VERSION2 from the start — do not copy the prototype scripts' v1 pattern forward |

**Deprecated/outdated:**
- The existing doc's `/etc/mosquitto/mosquitto.conf` mount path: not deprecated exactly, but appears to have never matched this specific Docker image's actual config-loading path — see Pitfall 1.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The `eclipse-mosquitto:2` tag currently resolves to the 2.1.x line (confirmed 2.1.2 as of the milestone-level STACK.md research pass, not independently re-pulled this session since Docker Hub tag listings weren't re-queried) | Standard Stack | If the pinned `2` tag has since moved to a materially different minor version, some option availability (e.g. argon2id default) could differ — low risk, argon2id has been the default since early 2.x |
| A2 | Downloads/week figure for `paho-mqtt` ("millions/month") is asserted from general knowledge, not re-measured via pypistats this session (pypistats.org rate-limited the request) | Package Legitimacy Audit | Cosmetic only — package legitimacy is otherwise established via slopcheck + long release history (first release 0.4.90) + Eclipse Foundation ownership, none of which depend on the exact download figure |
| A3 | No official symlink or fallback exists from `/etc/mosquitto/mosquitto.conf` to `/mosquitto/config/mosquitto.conf` in the `eclipse-mosquitto:2.1-alpine` image — based on reading the image's Dockerfile/entrypoint source directly (HIGH confidence) plus absence of any documented mention of such a symlink across multiple community sources, but not verified by actually running the container | Pitfall 1 / Pattern 3 | If a symlink turns out to exist after all, the existing baseline doc's mount path would have been working correctly all along, and Pitfall 1's fix would be unnecessary (harmless either way — moving to the documented default path is correct regardless) |

## Open Questions

1. **Does the currently-running (if any) mosquitto container on the user's actual deployment host already have this mount-path problem, and if so, is there already-accumulated retained state to migrate/lose?**
   - What we know: The doc describes the intended setup; whether it's actually deployed and running right now with the `/etc/mosquitto/` mount is unknown from this repo alone.
   - What's unclear: Whether Phase 8's implementation needs a "before you deploy this, note any existing retained state will not carry over" callout for the user.
   - Recommendation: Planner should add a note (not a blocking task) in the plan's deploy instructions: back up `mosquitto_data` volume contents before applying, if a live stack already exists.

2. **Exact behavior of Mosquitto's `log_type` verbosity needed to see "Denied PUBLISH" lines, for the optional supplementary smoke-test log check.**
   - What we know: The message format and that it's an ACL-denial log line (confirmed via GitHub issue discussion, MEDIUM confidence — not the official man page).
   - What's unclear: The exact minimum `log_type` value needed (`all` vs `notice` vs `warning`) to guarantee it appears without also being buried in unrelated debug noise.
   - Recommendation: Treat the functional (subscribe-and-wait) check as the required verification; the log-grep check is optional polish, not a blocking requirement — don't spend planning time nailing the exact log_type value.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `podman` / `podman compose` | Actually running/testing the compose stack and smoke test | ✗ (not present in this research sandbox) | — | None for live verification — this must run on the user's actual deployment host, not in an agent sandbox; the plan should treat "run the smoke test" as a step for the human/execution environment, not assume CI can do it |
| `uv` | `uv add paho-mqtt`, running the smoke test script | ✓ | 0.12.5 | — |
| `mosquitto_passwd` CLI (host-installed) | Generating `deploy/mosquitto.passwd` | ✗ (not present in this research sandbox) | — | Generate via `podman run --rm ... eclipse-mosquitto:2 mosquitto_passwd ...` (see Code Examples) — no host install needed, this fallback is actually the recommended approach regardless of local availability |
| `mosquitto_sub`/`mosquitto_pub` CLI (host-installed) | Manual verification, persistence smoke-test step | ✗ (not present in this research sandbox) | — | Run via `podman compose exec mosquitto mosquitto_sub/mosquitto_pub ...` (already ships inside the broker's own container) — same reasoning as above |
| Network access to PyPI/GitHub/mosquitto.org | Verifying package legitimacy and doc claims during this research pass | ✓ | — | — |

**Missing dependencies with no fallback:**
- `podman`/`podman compose` for actually executing and observing the smoke test — this is expected to run on the user's real deployment host during phase execution, not in whatever sandbox executes the plan's automation.

**Missing dependencies with fallback:**
- `mosquitto_passwd`, `mosquitto_sub`, `mosquitto_pub` CLIs — all three ship inside the `eclipse-mosquitto` container image itself and can be invoked via `podman run`/`podman compose exec` with zero host installation.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | Yes | Mosquitto `password_file` (argon2id-hashed) — this phase's core deliverable; replaces the current `allow_anonymous true` |
| V3 Session Management | No | MQTT has no session/cookie concept comparable to HTTP; connection-level auth via CONNECT packet is the only relevant mechanism, already covered under V2 |
| V4 Access Control | Yes | Mosquitto `acl_file` — per-user topic-level read/write scoping (`wsreader` read-only, `poller` full access) |
| V5 Input Validation | No | This phase carries no application-layer payload parsing — that's Phase 9's poller/Phase 11's dashboard concern |
| V6 Cryptography | Partial | `mosquitto_passwd`'s argon2id hashing is the only cryptographic control in scope; TLS (`wss://`)/`mosquitto_tls` is explicitly out of scope for this phase per the milestone's LAN-only trust model (STACK.md flags TLS as a "worth flagging, not required" future item) |

### Known Threat Patterns for Mosquitto/MQTT

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| Anonymous LAN client forges/clears retained state via unauthenticated publish | Tampering | `acl_file` + `password_file`, default-deny for any user/topic combination not explicitly granted (this phase's core mitigation, per PITFALLS.md Pitfall 4) |
| LAN device sniffs plaintext `ws://`/`mqtt://` traffic (credentials + payloads both readable) | Information Disclosure | Explicitly accepted risk for this phase, consistent with the project's existing plaintext-HTTP-for-Checkmk precedent (`.planning/research/PITFALLS.md` "Security Mistakes" table) — documented, not silently ignored; `wss://`/TLS deferred |
| Application-code-only "the dashboard just doesn't call publish()" assumption mistaken for real access control | Elevation of Privilege | Broker-level ACL enforcement (this phase), independent of what any specific client chooses to do — any other MQTT client library pointed at the same port/credentials is equally constrained |
| Disposable default credentials (`wsreader`/`poller` with documented default passwords) reused unchanged in a less-trusted network | Spoofing | Documented explicitly in the Podman setup doc as disposable dev/local defaults to rotate before exposing beyond a trusted LAN (D-09) — same precedent as `cmkadmin`/`minioadmin` |

## Sources

### Primary (HIGH confidence)
- [mosquitto.conf(5) man page](https://mosquitto.org/man/mosquitto-conf-5.html) — `listener`, `protocol websockets`, `allow_anonymous`, `per_listener_settings`, `acl_file`, `password_file`, `persistence`/`persistence_location`/`autosave_interval` syntax and defaults (fetched 2026-09-05)
- [ACL file Plugin — official docs](https://mosquitto.org/documentation/plugins/acl-file/) — `user`/`topic`/`pattern` ACL file syntax, default-deny behavior for authenticated users without an explicit `user` block (fetched 2026-09-05)
- [mosquitto_passwd(1) man page](https://mosquitto.org/man/mosquitto_passwd-1.html) — `-c`/`-b`/`-D`/`-H` flags, argon2id default hash (fetched 2026-09-05)
- `eclipse-mosquitto/mosquitto` GitHub repo, `docker/2.1-alpine/Dockerfile` and `docker-entrypoint.sh` — confirmed baked-in `CMD ["mosquitto", "-c", "/mosquitto/config/mosquitto.conf"]`, UID/GID 1883 non-root user, no `/etc/mosquitto/` fallback (fetched 2026-09-05)
- [paho-mqtt helpers docs](https://eclipse.dev/paho/files/paho.mqtt.python/html/helpers.html) — `publish.single()`/`subscribe.simple()` full signatures including `transport`/`auth` params (fetched 2026-09-05)
- PyPI JSON API (`pypi.org/pypi/paho-mqtt/json`) — confirmed current version 2.1.0, `requires-python >=3.7` (queried live, 2026-09-05)
- `uvx slopcheck scan paho-mqtt --pkg pypi --json` — confirmed `"status": "OK"` (run live, 2026-09-05)

### Secondary (MEDIUM confidence)
- [eclipse-mosquitto/mosquitto issue #547 — "Publish Denied still sends PUBACK to client"](https://github.com/eclipse/mosquitto/issues/547) and [issue #2042 — MQTT5 reason codes](https://github.com/eclipse/mosquitto/issues/2042) — corroborate MQTT 3.1.1's lack of publish-denial feedback vs. MQTT5's reason code 135
- Community/GitHub-derived summary of "Denied PUBLISH" log line format (exact minimum `log_type` verbosity not independently pinned down)
- `.planning/research/{STACK,ARCHITECTURE,PITFALLS,SUMMARY}.md` (this project's own milestone-level research, produced 2026-09-05) — provided the baseline architecture/pitfall shape this phase-level research refined and corrected

### Tertiary (LOW confidence)
- General knowledge of `paho-mqtt`'s download volume (not re-verified via pypistats this session due to rate limiting)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every version/API claim traced to an official doc, source repo, or a live registry/tool query performed this session
- Architecture: HIGH (core Mosquitto config patterns) / MEDIUM (exact `eclipse-mosquitto:2` tag's minor version and untested assumption about the `/etc/mosquitto/` mount's actual runtime effect — reasoned from source, not observed by running the container)
- Pitfalls: HIGH — the three phase-specific pitfalls (mount path, port collision, MQTT 3.1.1 ack semantics) were each independently confirmed against primary sources (image Dockerfile, this repo's own existing compose ports, GitHub issue discussion) during this research pass, not inherited unverified from milestone-level research

**Research date:** 2026-09-05
**Valid until:** 30 days (stable, official-docs-grounded domain; re-verify only if the `eclipse-mosquitto:2` tag or `paho-mqtt` major version changes)
