# Phase 8: Broker Infrastructure Hardening - Pattern Map

**Mapped:** 2026-09-05
**Files analyzed:** 7 (new/modified)
**Analogs found:** 5 / 7 (2 have no in-repo code analog — config artifacts with no prior pattern; RESEARCH.md supplies the pattern instead)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|-----------------|----------------|
| `deploy/compose.yaml` | config (infra/deployment) | batch (declarative container wiring) | `docs/Podman setup for checkmk, minio, mosquitto, worker.md` §3 (embedded `compose.yaml` block, lines 61-158) | exact — this file IS the promotion of that embedded block to a real, checked-in file (D-02) |
| `deploy/mosquitto.conf` | config (infra) | batch (declarative broker config) | `docs/Podman setup for checkmk, minio, mosquitto, worker.md` §3 (embedded `mosquitto.conf` block, lines 49-59) | exact — same relationship; must be corrected/hardened per RESEARCH.md Patterns 1-3 |
| `deploy/mosquitto.acl` | config (infra) | request-response (per-connection ACL check) | none in-repo (no ACL file exists anywhere in this codebase today) | no analog — use RESEARCH.md Pattern 1 verbatim |
| `deploy/mosquitto.passwd` | config (generated artifact) | n/a | none in-repo; precedent is the *convention* of disposable default creds (`cmkadmin`/`cmkadmin`, `minioadmin`/`minioadmin`) in the same doc, lines 74-75, 110-111, 209-210 | no code analog — file is CLI-generated, not hand-authored (see Code Examples below) |
| `docs/Podman setup for checkmk, minio, mosquitto, worker.md` | doc | n/a | itself (existing doc, being edited in place per D-03) | exact |
| `scripts/smoke_test_broker.py` | test (standalone live-infra script, deliberately outside the mocked pytest suite) | pub-sub (MQTT connect/subscribe/publish) | `src/checkmk_wizard/livestatus.py` (style analog: hand-rolled typed client used for a live post-activation health check) + `docs/src/mqtt_notify.py` (existing paho-mqtt usage in this repo — API-shape analog only, **not** a style/version analog, see warning below) | role-match |
| `pyproject.toml` | config (dependency manifest) | n/a | itself — existing `dependencies = [...]` list, lines 9-14 | exact |

## Pattern Assignments

### `deploy/compose.yaml` (config, infra/deployment)

**Analog:** `docs/Podman setup for checkmk, minio, mosquitto, worker.md` lines 65-158 (embedded 4-service `compose.yaml`)

**Core pattern — copy the whole block as the starting point**, then apply exactly two structural fixes required by RESEARCH.md (the doc's current content has both bugs baked in):

```yaml
# from docs, lines 89-101 — mosquitto service, AS-IS (has both known bugs)
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
```

Required fixes (per RESEARCH.md Pattern 3 / Pitfalls 1-2), applied on top of the copied block:
1. Mount path: `/etc/mosquitto/mosquitto.conf` → `/mosquitto/config/mosquitto.conf` (image's baked-in `CMD` only reads this path — see RESEARCH.md Pitfall 1).
2. Add two new bind mounts alongside it: `./mosquitto.acl:/mosquitto/config/mosquitto.acl:ro,z` and `./mosquitto.passwd:/mosquitto/config/mosquitto.passwd:ro,z`.
3. Add a second published port for the new WS listener: `"9002:9001"` — **not** `"9001:9001"`, which collides with the `minio` service's existing published console port at line 114 of the same file (RESEARCH.md Pitfall 2).
4. Keep `"1883:1883"` published exactly as-is (D-04 — deliberate, not a bug).

**Everything else in the file** (checkmk service lines 68-88, minio service lines 104-118, worker service lines 122-146, volumes/networks blocks lines 148-157) copies over unchanged — D-02 only asks for wiring the mosquitto service correctly, not touching the others.

**Convention to preserve:** inline `#`-prefixed section-number comments per service (`# 1. Official Checkmk Raw`, `# 2. Mosquitto Broker`, etc. — doc lines 67, 89, 103, 120) and the trailing prose comment style under the block explaining non-obvious choices (see the `CMK_PASSWORD` note at doc lines 160, and the Livestatus/networking rationale at doc lines 188).

---

### `deploy/mosquitto.conf` (config, infra)

**Analog:** `docs/Podman setup for checkmk, minio, mosquitto, worker.md` lines 49-59 (embedded `mosquitto.conf`)

**Baseline (current, insecure) content being replaced:**
```text
listener 1883 0.0.0.0
allow_anonymous true
persistence true
persistence_location /mosquitto/data/
```

**Target pattern — RESEARCH.md Pattern 2 (global settings before any `listener` line)**, which is the authoritative replacement content (already vetted against the official `mosquitto.conf(5)` man page and this repo's specific port-collision constraint):
```text
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

**Note:** container-internal port stays `9001` for the WS listener — only the host-side publish mapping changes to `9002` in `compose.yaml` (see above). Do not confuse the two numbers when writing this file.

---

### `deploy/mosquitto.acl` (config, no in-repo analog)

**Analog:** none in this codebase. RESEARCH.md Pattern 1 is the primary source, sourced from `mosquitto.org/documentation/plugins/acl-file/`.

```text
# Authenticated users not listed below get NO access at all (default-deny) —
# confirmed: "topic" lines outside a "user" block apply only to anonymous
# clients, and allow_anonymous is false in this phase's config.

user poller
topic readwrite #

user wsreader
topic read lan/#
```

**Naming convention to follow (Claude's discretion per CONTEXT.md):** `wsreader` for the WS read-only user, `poller` for the 1883 full-access user — these names are also what `deploy/mosquitto.passwd` and `scripts/smoke_test_broker.py` must use consistently.

---

### `deploy/mosquitto.passwd` (config, generated artifact — not hand-authored)

**No code analog** — this file is never hand-written; it's produced by running `mosquitto_passwd` once per user via the broker's own container image (RESEARCH.md "Code Examples" section), matching this project's existing precedent of checking in disposable, plainly-documented default credentials (`cmkadmin`/`cmkadmin`, `minioadmin`/`minioadmin` — doc lines 209-210).

**Generation commands to run once, then commit the resulting file:**
```bash
podman run --rm -v "$(pwd)/deploy:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd -b -c /mosquitto/config/mosquitto.passwd wsreader '<disposable-default-password>'
podman run --rm -v "$(pwd)/deploy:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd -b /mosquitto/config/mosquitto.passwd poller '<disposable-default-password>'
# -c on the FIRST invocation only — omit on the second or it wipes the first user.
```

**Pitfall to carry into the plan (RESEARCH.md Pitfall 4):** keep default/world-readable host file permissions on this file and on `mosquitto.acl` (matching the existing `mosquitto.conf:ro,z` mount) — the image's Mosquitto process runs as non-root UID/GID `1883`, and an overly-locked-down `chmod 600` on a bind-mounted "password-looking" file is the most likely way for a well-meaning fix to silently break broker startup.

---

### `docs/Podman setup for checkmk, minio, mosquitto, worker.md` (doc)

**Analog:** itself — edited in place per D-03.

**Pattern:** replace the embedded `mosquitto.conf`/`compose.yaml` code blocks (lines 49-158) with a short pointer to the new canonical files, following this doc's own existing cross-reference style (it already links to other repo docs this way, e.g. line 3: `see [docs/WIZARD-OPERATION.md](WIZARD-OPERATION.md)`):
```markdown
See [`deploy/compose.yaml`](../deploy/compose.yaml) and [`deploy/mosquitto.conf`](../deploy/mosquitto.conf) for the current, canonical configuration — this doc no longer duplicates their contents inline so the two can't drift apart.
```
Also update:
- §6 "Endpoints & Network Access" table (lines 196-205): add a row for the new WS listener (`<HOST_IP>:9002` / `mosquitto:9001` internal), and note that `1883`/WS now require the `poller`/`wsreader` credentials respectively (no longer anonymous).
- The "Default credentials" list (lines 207-210): add the new mosquitto `wsreader`/`poller` entries, using the exact same one-line disposable-default disclosure phrasing already used for `cmkadmin`/`minioadmin` there.

---

### `scripts/smoke_test_broker.py` (test/utility script, pub-sub)

**Analog:** `src/checkmk_wizard/livestatus.py` (style/structure) — this project's established "hand-rolled, typed, single-purpose live-verification client" pattern, explicitly called out in CONTEXT.md's Reusable Assets as the stylistic reference for this script (typed functions, explicit exception handling, no silent broad excepts, no dataclass unless there's real structured state to carry).

**Module docstring pattern** (`livestatus.py` lines 1-9):
```python
"""Minimal Livestatus client for the Phase 7 post-activation health check.

Connects to the site's Livestatus port over TCP — not the local UNIX
socket — so the wizard can run from a different container/host than the
Checkmk site itself. `site.enable_livestatus_tcp()` turns this on for
every site the wizard creates or reuses. Uses the standard LQL text
protocol: a query terminated by a blank line, response requested as CSV
via OutputFormat/ColumnHeaders headers.
"""

from __future__ import annotations

import socket
```
Apply the same shape to the new script: module docstring stating *why* this script exists and what it proves (BRK-01/02/03), `from __future__ import annotations` first, then imports — matching every module in `src/checkmk_wizard/` (`api.py:8`, `site.py:12`, `scanner.py:10`).

**Do NOT copy the API shape from `docs/src/mqtt_notify.py`** (lines 10, 110-111) — it uses paho-mqtt's **v1** callback API (`mqtt.Client(client_id=...)`, no `CallbackAPIVersion`), which is explicitly flagged in RESEARCH.md's "State of the Art" table as the outdated pattern to leave behind. Use `mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="websockets")` per RESEARCH.md Code Examples instead.

**Core pub-sub pattern** — copy directly from RESEARCH.md's Code Examples section (already vetted against `paho-mqtt` 2.1.0's actual API and this phase's specific MQTT-3.1.1-ack-semantics pitfall):

1. WS connect + subscribe (success path, `subscribe.simple()` is safe here since a message/SUBACK is actually expected):
```python
import paho.mqtt.subscribe as subscribe

msg = subscribe.simple(
    "lan/#",
    hostname="mosquitto",
    port=9001,  # internal container port; use 9002 if run from outside cmk_net
    transport="websockets",
    auth={"username": "wsreader", "password": "<disposable-default-password>"},
    msg_count=1,
    retained=True,
)
```

2. WS publish-denied (negative path — **must** use a bounded `threading.Event`, never `subscribe.simple()`/`subscribe.callback()`, which have no timeout and will hang forever on a correctly-enforced denial — RESEARCH.md Pitfall 3):
```python
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

publish.single(
    "lan/smoketest/deny-check", "should-never-arrive",
    hostname="mosquitto", port=9001, transport="websockets",
    auth={"username": "wsreader", "password": "<disposable-default-password>"},
    retain=True,
)

arrived = received.wait(timeout=5)
privileged.loop_stop()
privileged.disconnect()
assert not arrived, "ACL FAILED: wsreader was able to publish"
```

**Error handling pattern:** follow this repo's narrow-except convention (`except (TimeoutError, OSError)` in `scanner.py:38`, `remote.py:168`) rather than a blanket `except Exception` — contrast with `docs/src/mqtt_notify.py:151` (`except Exception as e:`), which is exactly the pattern this repo's own CLAUDE.md-documented convention avoids. If a distinct exception type is warranted for a hard-failure case (e.g. broker unreachable at all), follow `site.py`'s `SiteBootstrapError(RuntimeError)` naming convention (`ends in Error`, subclasses the closest built-in) rather than inventing a bespoke hierarchy for a one-shot script — but a plain `assert` (as shown above) is likely sufficient here since this is a pass/fail smoke test, not a library.

**Persistence-across-restart verification** — this part is a shell/CLI sequence, not Python (per RESEARCH.md Code Examples "Verifying persistence across a restart" and Open Question 1's note that `podman`/`podman compose` aren't available in any sandboxed execution environment — this step runs on the real deployment host):
```bash
podman compose exec mosquitto mosquitto_pub -h localhost -p 1883 \
  -u poller -P '<disposable-default-password>' \
  -t lan/smoketest/persist -m 'still-here' -r
podman compose restart mosquitto
podman compose exec mosquitto mosquitto_sub -h localhost -p 1883 \
  -u poller -P '<disposable-default-password>' \
  -t lan/smoketest/persist -C 1 -W 5
```
Whether to shell out to this from within `scripts/smoke_test_broker.py` (via `subprocess.run(..., check=False)`, matching `site.py`'s established shell-out convention — explicit `check=False` + manual `returncode` inspection) or leave it as a documented manual step is Claude's discretion at plan time; either way, if it's automated in Python, follow `site.py:79-87`'s `subprocess.run(capture_output=True, text=True, check=False)` + explicit `if result.returncode != 0: raise ...` shape, not a bare `subprocess.check_call`.

---

### `pyproject.toml` (config, dependency manifest)

**Analog:** itself, lines 9-14 (existing `dependencies` list)

**Pattern — single alphabetically-adjacent addition, not a rewrite:**
```toml
dependencies = [
    "asyncssh>=2.24.0",
    "httpx>=0.28.1",
    "paho-mqtt>=2.1.0",
    "questionary>=2.1.1",
    "rich>=15.0.0",
]
```
Apply via `uv add paho-mqtt` (per D-08) rather than hand-editing — `uv` will also update `uv.lock` correctly, which a manual edit would not.

---

## Shared Patterns

### Disposable default-credential disclosure
**Source:** `docs/Podman setup for checkmk, minio, mosquitto, worker.md` lines 160, 207-210 (`cmkadmin`/`cmkadmin`, `minioadmin`/`minioadmin`)
**Apply to:** `deploy/mosquitto.passwd` generation + the doc's updated "Default credentials" section — state the new `wsreader`/`poller` defaults in the same plain, undisguised, one-line style, with the same "disposable dev/local default, rotate before wider exposure" caveat.

### Narrow exception handling, no silent broad excepts
**Source:** `src/checkmk_wizard/scanner.py:38` (`except (TimeoutError, OSError):`), `src/checkmk_wizard/site.py:85-86` (explicit `if result.returncode != 0: raise SiteBootstrapError(...)`)
**Apply to:** `scripts/smoke_test_broker.py` — every failure path should be a targeted except/assert, not a blanket `except Exception` (the anti-pattern present in the legacy `docs/src/mqtt_notify.py:151`, which must not be copied forward).

### Module docstring + `from __future__ import annotations` first
**Source:** every module under `src/checkmk_wizard/` (`api.py:8`, `site.py:1-12`, `scanner.py:1-10`, `livestatus.py:1-13`, `remote.py:1-21`, `wizard.py:1-5`)
**Apply to:** `scripts/smoke_test_broker.py` — even though it lives outside `src/`, it should read as consistent with the rest of the codebase's documentation-of-*why* convention (cite what was verified: BRK-01/02/03, and how — live smoke test against a running broker).

### CLI-generated, not hand-authored, credential/config artifacts
**Source:** RESEARCH.md "Don't Hand-Roll" table — `mosquitto_passwd` for password hashing
**Apply to:** `deploy/mosquitto.passwd` — the plan should include the exact `podman run ... mosquitto_passwd -b ...` invocation as a documented, reproducible step (see file section above), not ask an agent to hand-write argon2id hashes.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `deploy/mosquitto.acl` | config | request-response (per-connect ACL check) | No ACL file of any kind exists anywhere in this repo today — first one. Use RESEARCH.md Pattern 1 (official `mosquitto.org` ACL-file plugin syntax) directly. |
| `deploy/mosquitto.passwd` | config (generated artifact) | n/a | Never hand-authored in this repo or elsewhere — generated via the `mosquitto_passwd` CLI shipped inside the `eclipse-mosquitto` image. Use the exact `podman run` invocations under "Code Examples" in RESEARCH.md / above. |

## Metadata

**Analog search scope:** `docs/Podman setup for checkmk, minio, mosquitto, worker.md`, `docs/src/*.py`, `src/checkmk_wizard/*.py`, `tests/test_*.py`, `pyproject.toml` — the entire repo, since Phase 8 introduces the project's first `deploy/` directory and there is no prior infra-as-code to search within.
**Files scanned:** 12 (all `src/checkmk_wizard/*.py`, both `docs/src/*.py` prototypes, `docs/Podman setup...md`, `pyproject.toml`, `tests/test_livestatus.py`, `tests/test_wizard.py` names-only via grep)
**Pattern extraction date:** 2026-09-05
**Convention derivation:** skipped (no-readable-files — the shared `gsd-tools verify conventions --derive` module targets JS/TS file conventions; this is a pure-Python codebase with no `.ts`/`.tsx`/`.js` files for it to analyze, so no `## Conventions` axis table applies here). Naming/style conventions for this phase's Python code are instead documented directly above (module docstring order, narrow-except pattern, dataclass/CLI-generated-artifact distinctions) and are already codified in this repo's own `CLAUDE.md`.
