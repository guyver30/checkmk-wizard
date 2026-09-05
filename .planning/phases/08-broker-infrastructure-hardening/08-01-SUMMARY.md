---
phase: 08-broker-infrastructure-hardening
plan: 01
subsystem: infra
tags: [mosquitto, mqtt, acl, argon2id, podman]

# Dependency graph
requires: []
provides:
  - "deploy/mosquitto.conf: two-listener (1883 plain MQTT, 9001 WebSockets) authenticated, ACL-scoped, persistent broker config"
  - "deploy/mosquitto.acl: per-user topic ACL (poller readwrite #, wsreader read-only lan/#)"
  - "deploy/gen-mosquitto-passwd.sh: reproducible argon2id password-file generator (podman/docker/host mosquitto_passwd)"
affects: [08-02-broker-compose, 08-03-broker-smoke-test]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Mosquitto global-directives-before-listeners config ordering", "runtime-agnostic container CLI invocation via podman/docker/host fallback chain"]

key-files:
  created: [deploy/mosquitto.conf, deploy/mosquitto.acl, deploy/gen-mosquitto-passwd.sh]
  modified: []

key-decisions:
  - "wsreader ACL scoped to lan/# (not #) to keep $SYS/# broker internals hidden from browser clients"
  - "gen-mosquitto-passwd.sh dispatches through a single RUNTIME_PREFIX array so both mosquitto_passwd invocations are written literally once, avoiding duplicated -c create-flag call sites across the podman/docker/host branches"

patterns-established:
  - "Config artifacts under deploy/ use documented-why # comments citing the specific Mosquitto behavior verified (global-before-listener parsing, non-root UID 1883 file permission requirement)"

requirements-completed: []  # BRK-01/02/03 satisfied by conf+acl content, but deploy/mosquitto.passwd (Task 3) is still pending human action — do not mark complete until Task 3 resolves

# Metrics
duration: 25min
completed: 2026-09-05
---

# Phase 8 Plan 1: Broker Configuration Artifacts Summary

**Two-listener (plain MQTT 1883 + WebSockets 9001) authenticated, ACL-scoped, persistent Mosquitto config plus a reproducible argon2id password-file generator; password file generation itself is paused at a human-action checkpoint pending a container runtime.**

## Performance

- **Duration:** 25 min (in progress — paused at Task 3 checkpoint)
- **Started:** 2026-09-05T09:57:00Z
- **Completed:** N/A — plan paused, not finished
- **Tasks:** 2 of 3 completed
- **Files modified:** 3

## Accomplishments
- `deploy/mosquitto.conf` declares all global auth/persistence directives before either `listener` line, per Mosquitto's position-sensitive config parsing, with WebSockets correctly bound to container-side port 9001 (not the host-side 9002 used later by compose)
- `deploy/mosquitto.acl` grants `poller` full readwrite and scopes `wsreader` to read-only `lan/#`, with no bare `topic` line outside a `user` block (which would otherwise be dead config since `allow_anonymous false` already blocks anonymous clients)
- `deploy/gen-mosquitto-passwd.sh` is an executable, syntax-valid, runtime-agnostic (podman → docker → host `mosquitto_passwd`) generator that fails loudly with exit 1 when none of the three are available — confirmed by actually running it in this environment (see Issues Encountered)

## Task Commits

Each task was committed atomically:

1. **Task 1: Write deploy/mosquitto.conf and deploy/mosquitto.acl** - `0cc7a7a` (feat)
2. **Task 2: Write deploy/gen-mosquitto-passwd.sh** - `66686b7` (feat)
3. **Task 3: Generate and commit deploy/mosquitto.passwd** - PAUSED (checkpoint:human-action, gate="blocking") — not yet committed

## Files Created/Modified
- `deploy/mosquitto.conf` - Two-listener Mosquitto config: globals (auth, ACL, persistence) declared before both `listener` blocks
- `deploy/mosquitto.acl` - Per-user topic ACL: `poller` readwrite `#`, `wsreader` read-only `lan/#`
- `deploy/gen-mosquitto-passwd.sh` - Executable generator for `deploy/mosquitto.passwd`, dispatching to podman/docker/host `mosquitto_passwd`

## Decisions Made
- Followed RESEARCH.md Pattern 2 exactly: globals-before-listeners ordering in `mosquitto.conf`, with an explanatory comment for future readers.
- Refactored the password generator's runtime dispatch into a single `RUNTIME_PREFIX` array (rather than duplicating the `mosquitto_passwd -b -c ...` call inside three separate per-runtime branches) so the create-flag invocation appears exactly once in the script text — matches the plan's acceptance criterion that `-c` never risks being duplicated across a code path, and keeps the two-call generation sequence (`-b -c` then `-b`) unambiguous regardless of which runtime executes it.

## Deviations from Plan

None - plan executed exactly as written for Tasks 1 and 2. Task 3 is proceeding via the plan's own documented "automation first, then pause" path (not a deviation — this is the checkpoint's designed behavior when no runtime is available).

## Issues Encountered

**Task 3 checkpoint confirmed necessary, not skipped speculatively.** Before pausing, per the plan's `<action>` instruction to attempt automation first: ran `command -v podman docker mosquitto_passwd` (all three returned nothing) and then actually executed `./deploy/gen-mosquitto-passwd.sh`, which printed:
```
ERROR: no way to run mosquitto_passwd — none of podman, docker, or a host-installed mosquitto_passwd binary were found on PATH.
Install one of: podman, docker, or the mosquitto-clients package (provides mosquitto_passwd).
```
and exited 1, matching RESEARCH.md's "Environment Availability" finding that no container runtime exists in this sandbox. This confirms the checkpoint is genuine, not avoidable by this agent, and `deploy/mosquitto.passwd` cannot be hand-written (Mosquitto 2.x refuses plaintext password files; hand-rolling argon2id hashes is explicitly rejected by RESEARCH.md's "Don't Hand-Roll" table).

## User Setup Required

None beyond the checkpoint itself - no external service configuration required. See CHECKPOINT REACHED section returned to the orchestrator for the exact one-command manual step.

## Next Phase Readiness

- `deploy/mosquitto.conf` and `deploy/mosquitto.acl` are complete, verified, and committed — Plan 02 (`deploy/compose.yaml`) and Plan 03 (`scripts/smoke_test_broker.py`) can reference their fixed container-side paths and usernames now.
- `deploy/gen-mosquitto-passwd.sh` is complete and committed, but `deploy/mosquitto.passwd` itself does not yet exist — Plan 02/03 work that depends on a running, authenticated broker cannot be smoke-tested end-to-end until Task 3 resolves on a host with podman, docker, or mosquitto_passwd available.
- Blocker: this plan cannot self-resolve Task 3 in the current sandboxed environment; requires a human to run `./deploy/gen-mosquitto-passwd.sh` on the actual Podman deployment host.

---
*Phase: 08-broker-infrastructure-hardening*
*Completed: paused — see Task 3 checkpoint*
