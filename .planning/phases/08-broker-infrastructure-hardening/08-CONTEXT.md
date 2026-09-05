# Phase 8: Broker Infrastructure Hardening - Context

**Gathered:** 2026-09-05
**Status:** Ready for planning

<domain>
## Phase Boundary

The MQTT broker (Mosquitto) becomes durable and access-controlled — ready to serve both the future poller (Phase 9) and browser clients (Phase 11) — before either is built against it. Scope is broker/infra configuration only: a new ACL-scoped WebSockets listener, `persistence true` against a mounted volume, and the compose wiring to expose it. No poller code, no Checkmk tagging, no dashboard code in this phase.

</domain>

<decisions>
## Implementation Decisions

### Config Artifact Location
- **D-01:** Check real config files into this repo under a new `deploy/` directory (`deploy/compose.yaml`, `deploy/mosquitto.conf`, `deploy/mosquitto.acl`, `deploy/mosquitto.passwd`) as the canonical source of truth — this repo currently has zero infra-as-code files; today it's only markdown snippets in `docs/Podman setup for checkmk, minio, mosquitto, worker.md`.
- **D-02:** `deploy/compose.yaml` is the **full 4-service stack** (`checkmk`, `mosquitto`, `minio`, `worker`) — not just a mosquitto fragment — replacing the copy currently only embedded in the doc. Phase 11's `dashboard` nginx service extends this same file later; one canonical file going forward.
- **D-03:** `docs/Podman setup for checkmk, minio, mosquitto, worker.md` is updated to reference `deploy/compose.yaml` / `deploy/mosquitto.conf` (e.g. "see deploy/compose.yaml") instead of duplicating the full block inline, so the doc and the real config can't silently drift apart.

### 1883 TCP Listener Exposure
- **D-04:** The existing `1883` TCP listener **stays published to the LAN** in `deploy/compose.yaml` (`ports: "1883:1883"`) in this phase — user explicitly wants it reachable for debugging for now, even though PITFALLS.md flags an unauthenticated LAN-reachable publish port as undermining the point of ACL-hardening the WS listener.
- **D-05:** 1883 gains **username/password authentication** for the poller via the same `acl_file`/`password_file` mechanism as the WS listener — no longer purely `allow_anonymous true`. No topic-level ACL restriction is required on 1883 beyond requiring valid credentials to connect (full read/write for the authenticated poller user is fine).

### Verification Approach
- **D-07:** A standalone **automated smoke-test script** is checked into the repo — not part of the existing mocked pytest suite (this project's tests never touch live infrastructure, by established convention) — that verifies: a WS client can connect and subscribe, a WS publish attempt is rejected by the ACL, and retained messages survive a broker restart.
- **D-08:** `paho-mqtt` is added as a project dependency now via `uv add paho-mqtt` to back the smoke-test script, since Phase 9's poller needs it anyway (v2.1.0, `CallbackAPIVersion.VERSION2` — per `.planning/research/SUMMARY.md`). One well-tested client shared between the smoke test and the future poller instead of shelling out to CLI tools.

### ACL Credential Handling
- **D-09:** `deploy/mosquitto.passwd` is checked into the repo **pre-hashed with fixed default credentials** (a read-only WS user, a poller user for 1883), documented in the Podman setup doc as disposable dev/local defaults to rotate before exposing beyond a trusted LAN — matching this project's existing convention for default credentials (`cmkadmin`/`cmkadmin`, `minioadmin`/`minioadmin`).

### Claude's Discretion
- Exact ACL file syntax/topic patterns (e.g. `lan/#` read-only for the WS user)
- Exact username naming (e.g. `wsreader`, `poller`)
- Mosquitto password-hash generation method for the checked-in file (`mosquitto_passwd` invocation), documented so it's reproducible
- Smoke-test script's exact location/structure (e.g. `scripts/smoke_test_broker.py` vs. a `tests/smoke/` dir — kept clearly separate from the mocked pytest suite either way)
- Exact internal layout of `deploy/`

</decisions>

<specifics>
## Specific Ideas

- User's own framing on 1883: "I still want to have 1883 exposed to the outside for debugging, but later on I want to keep it only internal" — the LAN exposure is a deliberate, temporary choice, not an oversight.
- Default-credential precedent to follow: the doc's existing `cmkadmin`/`cmkadmin` and `minioadmin`/`minioadmin` disposable-default pattern, called out explicitly as the model for the new mosquitto password file.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Broker/MQTT hardening
- `.planning/research/ARCHITECTURE.md` — "Compose/config wiring specifics" section (mosquitto.conf listener blocks, compose.yaml wiring pattern for the WS port + dashboard service) and "Build Order Implications" §1
- `.planning/research/PITFALLS.md` — the unauthenticated-WS-listener pitfall (why ACL is required, the `acl_file`/`password_file` mechanism, reasoning on why a LAN-reachable anonymous publish port undermines ACL hardening) and its risk-tradeoff tables
- `.planning/research/STACK.md` — Mosquitto 2.1.2 version/feature baseline (native WebSockets listener, no reverse proxy needed)
- `.planning/research/SUMMARY.md` — "Phase A: Broker infrastructure hardening" section (phase rationale, what it delivers/avoids)
- `.planning/ROADMAP.md` — Phase 8 section (locked success criteria BRK-01/02/03/04)
- `.planning/REQUIREMENTS.md` — Broker section (BRK-01, BRK-02, BRK-03 requirement text)
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` — current/baseline `mosquitto.conf` + `compose.yaml` this phase modifies and the doc this phase updates to reference `deploy/`

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/checkmk_wizard/livestatus.py` — this project's established "hand-rolled raw TCP client" convention; not reused directly by Phase 8, but the smoke-test script and Phase 9's poller should stay stylistically consistent with it (typed dataclasses, explicit exception handling, no silent broad excepts).

### Established Patterns
- Project convention of documenting default/disposable credentials plainly in-doc rather than hiding them (`cmkadmin`/`cmkadmin`, `minioadmin`/`minioadmin`) — extended here to the new `deploy/mosquitto.passwd` entries.
- This project's tests are 100% mocked against live infrastructure (`respx` for HTTP, monkeypatched `asyncssh`/`subprocess`) — the new smoke-test script is a deliberate, documented exception to that pattern (it needs a live broker), not a new precedent for the main pytest suite.

### Integration Points
- `deploy/compose.yaml` becomes the file Phase 11 extends with the new `dashboard` nginx service.
- `deploy/mosquitto.conf`'s two-listener + ACL shape is what Phase 9's poller must authenticate against on port 1883 (credentials from `deploy/mosquitto.passwd`).

</code_context>

<deferred>
## Deferred Ideas

- Restricting the 1883 TCP listener to container-internal-only network reachability (dropping its LAN port publish, or `bind_interface` scoping) — explicitly deferred by the user to a later hardening pass, not part of Phase 8.

</deferred>

---

*Phase: 08-broker-infrastructure-hardening*
*Context gathered: 2026-09-05*
