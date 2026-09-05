---
phase: 08-broker-infrastructure-hardening
plan: 02
subsystem: infra
tags: [podman-compose, mosquitto, mqtt, paho-mqtt, deploy]

# Dependency graph
requires:
  - phase: 08-broker-infrastructure-hardening (plan 01, sibling wave)
    provides: deploy/mosquitto.conf, deploy/mosquitto.acl, deploy/mosquitto.passwd (hardened broker config this plan's compose.yaml mounts)
provides:
  - "deploy/compose.yaml: canonical 4-service Podman Compose stack (checkmk, mosquitto, minio, worker) with hardened mosquitto wiring"
  - "paho-mqtt >=2.1.0 as a locked runtime dependency exposing CallbackAPIVersion.VERSION2"
affects: [08-03-smoke-test, phase-09-poller-core, phase-11-dashboard]

# Tech tracking
tech-stack:
  added: [paho-mqtt 2.1.0]
  patterns: []

key-files:
  created: [deploy/compose.yaml]
  modified: [pyproject.toml, uv.lock]

key-decisions:
  - "Mounted all three mosquitto config artifacts under /mosquitto/config/ (not /etc/mosquitto/), the only path the eclipse-mosquitto image's baked-in CMD reads"
  - "Published the new WebSockets listener on host 9002 (container 9001) to avoid colliding with minio's existing published 9001:9001 console port"

patterns-established: []

requirements-completed: [BRK-01, BRK-02]

# Metrics
duration: 5min
completed: 2026-09-05
---

# Phase 8 Plan 2: Compose Stack Promotion + paho-mqtt Dependency Summary

**Promoted the markdown-embedded 4-service compose block to a real `deploy/compose.yaml` with the mosquitto service wired to the image's actual config path and a collision-free WebSockets port, and added `paho-mqtt` 2.1.0 as a locked runtime dependency.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-09-05T18:21:00+08:00
- **Completed:** 2026-09-05T18:22:00+08:00
- **Tasks:** 2 completed
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments
- `deploy/compose.yaml` is now the canonical 4-service stack (checkmk, mosquitto, minio, worker), checked into the repo rather than only existing as an embedded markdown snippet
- Mosquitto's config/ACL/password mounts corrected to `/mosquitto/config/`, making Plan 01's hardened config actually loadable by the running broker (previously the doc's `/etc/mosquitto/` path would have silently no-op'd every auth/ACL control)
- New WebSockets listener published on host 9002, verified collision-free against minio's existing 9001:9001 console port
- `paho-mqtt` 2.1.0 added as a runtime dependency, ready for Plan 03's smoke test and Phase 9's poller

## Task Commits

Each task was committed atomically:

1. **Task 1: Create deploy/compose.yaml as the canonical 4-service stack** - `04399f1` (feat)
2. **Task 2: Add paho-mqtt as a runtime dependency** - `62db29f` (feat)

**Plan metadata:** committed alongside this summary

## Files Created/Modified
- `deploy/compose.yaml` - Canonical 4-service Podman Compose stack; mosquitto service mounts config/ACL/password under `/mosquitto/config/`, publishes `9002:9001` (WS) and `1883:1883` (plain MQTT), backs `/mosquitto/data` with the `mosquitto_data` named volume
- `pyproject.toml` - Added `paho-mqtt>=2.1.0` to `[project].dependencies` (inserted alphabetically between `httpx` and `questionary`)
- `uv.lock` - Resolved and locked `paho-mqtt` 2.1.0 and its transitive state; no other package changed

## Decisions Made
- Used `uv add paho-mqtt` rather than hand-editing `pyproject.toml`, per D-08 and this repo's uv-only tooling convention, so `uv.lock` stayed consistent
- No architectural decisions required beyond what the plan and its interfaces block already specified

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Reworded a compose.yaml comment that broke the port-collision verify check**
- **Found during:** Task 1 verification
- **Issue:** The WHY-comment on the new `"9002:9001"` port line quoted the literal string `"9001:9001"` to explain the minio-console collision it avoids. The plan's own `<verify>` command greps the file for `"[0-9]+:[0-9]+"` patterns to detect duplicate published host ports, and it can't distinguish a quoted port pair inside a comment from a real `ports:` entry — so the comment text itself was being counted as a second `9001:9001` mapping, producing a false-positive duplicate-port failure.
- **Fix:** Reworded the comment to describe the collision in prose ("avoids colliding with minio's own published console port (host 9001) below") without repeating the exact quoted `"9001:9001"` token.
- **Files modified:** `deploy/compose.yaml`
- **Verification:** Re-ran the task's `<verify>` command; it now prints `COMPOSE_OK` with no duplicate-port match.
- **Committed in:** `04399f1` (part of Task 1 commit — comment was fixed before the initial commit, no separate fix commit needed)

---

**Total deviations:** 1 auto-fixed (1 bug in an in-progress edit, caught by the task's own verify step before commit)
**Impact on plan:** No scope creep; the fix only reworded prose inside a comment, no functional change to the compose file's actual service definitions.

## Issues Encountered
None beyond the auto-fixed comment-wording issue above.

## User Setup Required
None - no external service configuration required. Note: this plan only creates/wires the compose file and dependency; nobody has run `podman compose up` against it yet (that's expected to happen on the user's actual deployment host per RESEARCH.md's "Environment Availability" section — `podman`/`podman compose` were not available in this execution environment either).

## Next Phase Readiness
- `deploy/compose.yaml` is ready for Plan 01's `deploy/mosquitto.conf`/`.acl`/`.passwd` files to be bind-mounted once that sibling plan lands (same wave, separate worktree, no file overlap)
- `paho-mqtt` is importable via `uv run` with `CallbackAPIVersion.VERSION2` available, ready for Plan 03's `scripts/smoke_test_broker.py`
- Existing pytest suite unaffected: `uv run pytest -q` still passes all 222 tests
- No blockers for Plan 03 or Phase 9

---
*Phase: 08-broker-infrastructure-hardening*
*Completed: 2026-09-05*
