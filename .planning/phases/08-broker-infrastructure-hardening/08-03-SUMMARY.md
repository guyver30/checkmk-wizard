---
phase: 08-broker-infrastructure-hardening
plan: 03
subsystem: infra
tags: [mosquitto, mqtt, paho-mqtt, smoke-test, docs]

# Dependency graph
requires:
  - phase: 08-broker-infrastructure-hardening (plan 01)
    provides: deploy/mosquitto.conf, deploy/mosquitto.acl, deploy/mosquitto.passwd (hardened broker config this plan's smoke test verifies)
  - phase: 08-broker-infrastructure-hardening (plan 02)
    provides: deploy/compose.yaml, paho-mqtt runtime dependency
provides:
  - "scripts/smoke_test_broker.py: standalone paho-mqtt 2.x live-verification script proving BRK-01/02/03 against a running broker"
  - "docs/Podman setup for checkmk, minio, mosquitto, worker.md: repointed at deploy/ as the single source of truth, documents the WS endpoint and new default credentials"
affects: [phase-09-poller-core, phase-11-dashboard]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Independent-privileged-subscriber assertion for ACL-denial checks (never trust the publisher's own PUBACK under MQTT 3.1.1)", "Bounded threading.Event waits instead of paho's unbounded subscribe.simple()/subscribe.callback() helpers for any 'confirm nothing arrives' assertion"]

key-files:
  created: [scripts/smoke_test_broker.py]
  modified: ["docs/Podman setup for checkmk, minio, mosquitto, worker.md"]

key-decisions:
  - "check_persistence_across_restart's retry-loop connect/subscribe/wait logic was extracted into a standalone _wait_for_retained_payload() helper rather than defining the on_message closure inline inside the for loop, to satisfy ruff's B023 (function-definition-in-loop) lint rule while preserving the bounded-retry behavior"

requirements-completed: []  # Tasks 1-2 (script + doc) done and verified statically; BRK-01/02/03 live proof is pending Task 3's human checkpoint against the real deployment host

# Metrics
duration: ~45min (Tasks 1-2; Task 3 paused at checkpoint)
completed: 2026-09-06
---

# Phase 8 Plan 3: Live Broker Smoke Test + Podman Doc Repoint Summary

**Standalone paho-mqtt 2.x smoke-test script (`scripts/smoke_test_broker.py`) proving all three broker-hardening requirements against a live Mosquitto instance, plus the Podman setup doc repointed at `deploy/` as its single source of truth — live verification against the real deployment host is paused at Task 3's checkpoint.**

## Performance

- **Duration:** ~45 min (Tasks 1-2)
- **Started:** 2026-09-06
- **Completed:** Tasks 1-2 complete; Task 3 paused at checkpoint
- **Tasks:** 2 of 3 completed (Task 3 is a `checkpoint:human-verify` gate, `gate="blocking"`)
- **Files modified:** 2

## Accomplishments
- `scripts/smoke_test_broker.py` implements all four ordered checks (`check_poller_publish`, `check_ws_subscribe`, `check_ws_publish_denied`, `check_persistence_across_restart`), each printing a single `[PASS]`/`[FAIL]` line, using paho-mqtt 2.x's `CallbackAPIVersion.VERSION2` API throughout (not the legacy v1 pattern)
- `check_ws_publish_denied` is structured exactly per RESEARCH.md Pitfall 3: the assertion is made from an INDEPENDENT privileged subscriber via a bounded `threading.Event`, never from the denied publisher's own return code/PUBACK — a code comment states why, so a future reader doesn't "simplify" it back into a false positive
- The script is invisible to pytest (no `test_*` function names, not under `tests/`) and its `--help` works fully offline, confirmed by actually running it with no broker present
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` §3 no longer duplicates `mosquitto.conf`/`compose.yaml` inline — it links to `deploy/` instead; §2's directory tree, §4's migration callout, §6's endpoint table/credentials, and a new §7 subsection documenting the smoke test were all updated to match

## Task Commits

Each task was committed atomically:

1. **Task 1: Write scripts/smoke_test_broker.py** - `4a5d9de` (feat)
2. **Task 2: Repoint the Podman setup doc at deploy/ and document the new endpoint and credentials** - `520916a` (docs)

Task 3 (checkpoint:human-verify, `gate="blocking"`) is paused — see "Checkpoint" below. No commit produced by this session for Task 3; the plan's own `<action>` treats "attempt automation first, then pause" as the designed behavior when no container runtime is present, not a deviation.

## Files Created/Modified
- `scripts/smoke_test_broker.py` - Standalone, argparse-driven live-broker verification script (378 lines): four ordered checks proving BRK-01 (WS reachability), BRK-02 (persistence across restart), BRK-03 (WS read-only ACL enforcement), plus a `finally`-guarded cleanup of its own `lan/smoketest/*` retained topics
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` - §3 replaced inline config blocks with links to `deploy/`; §2 directory tree updated; §4 gained a retained-state migration callout; §6 gained a WebSockets endpoint row and `poller`/`wsreader` default credentials; §7 gained a "Broker smoke test" subsection

## Decisions Made
- Extracted the persistence check's per-attempt connect/subscribe/wait logic into `_wait_for_retained_payload()` rather than defining the `on_message` closure inline inside the retry `for` loop, after `ruff check` flagged the inline version with B023 (function definition capturing a loop variable) — functionally safe either way since the closure was only ever used within the same iteration before being redefined, but the extraction removes the lint warning and reads more clearly as a reusable helper.
- Followed RESEARCH.md/PATTERNS.md's explicit guidance not to copy `docs/src/mqtt_notify.py`'s paho v1 callback API or blanket `except Exception` pattern forward; this repo's narrow-except convention (`except (TimeoutError, OSError)`) is used throughout instead.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed the literal strings `subscribe.simple`, `subscribe.callback`, `shell=True`, and `check_call` from docstrings/comments**
- **Found during:** Task 1 verification
- **Issue:** The module's own docstrings explained *why* the script avoids `subscribe.simple()`/`subscribe.callback()` and `shell=True`/`check_call`, by name — but the plan's own `<verify>` step does a literal substring `assert 'subscribe.simple' not in s` (etc.) against the whole file, so quoting the forbidden API by name in prose caused a false-positive failure of the static gate.
- **Fix:** Reworded the affected docstring sentences to describe the avoided APIs by behavior ("the one-shot `paho.mqtt.subscribe` helpers, which have no timeout parameter", "never a raise-on-nonzero call or a shell string") instead of quoting their exact names.
- **Files modified:** `scripts/smoke_test_broker.py`
- **Verification:** Re-ran the task's `<verify>` command; it now prints `SMOKE_STATIC_OK` then `SUITE_OK`.
- **Committed in:** `4a5d9de` (fixed before the initial commit, no separate fix commit needed)

**2. [Rule 1 - Bug] Extracted a loop-scoped closure to fix a ruff B023 warning**
- **Found during:** Task 1, running `uvx ruff check` against the new script (matching this repo's documented linting convention) before committing
- **Issue:** `check_persistence_across_restart`'s retry loop defined `on_message` inline, referencing loop-scoped `payloads`/`received` — ruff's B023 rule flags this as an unsafe late-binding closure pattern, even though it was safe here in practice (the closure was only used within the same iteration).
- **Fix:** Extracted the connect/subscribe/wait logic into a standalone `_wait_for_retained_payload()` helper, called once per retry attempt, eliminating the loop-scoped closure entirely.
- **Files modified:** `scripts/smoke_test_broker.py`
- **Verification:** `uvx ruff check scripts/smoke_test_broker.py` → "All checks passed!"; re-ran the full task `<verify>` command, still `SMOKE_STATIC_OK` / `SUITE_OK`.
- **Committed in:** `4a5d9de` (fixed before the initial commit, no separate fix commit needed)

---

**Total deviations:** 2 auto-fixed (both Rule 1 bugs caught by the task's own verification/linting before commit, not carried forward)
**Impact on plan:** No scope creep — both fixes were wording/structure corrections inside the new script, made before its first commit; no functional behavior changed beyond removing the lint warning.

## Issues Encountered

None beyond the two auto-fixed issues above.

## User Setup Required

**Task 3 (live verification) requires action on the real deployment host.** See "Checkpoint" below — the deployment host is currently running the OLD, un-hardened `compose.yaml`/`mosquitto.conf` and has not yet been redeployed with this phase's `deploy/` artifacts.

## Next Phase Readiness

- Tasks 1 and 2 are complete, statically verified, and committed (`4a5d9de`, `520916a`).
- Task 3 is a `checkpoint:human-verify` gate (`gate="blocking"`) — this plan cannot be marked fully complete, and Phase 8's roadmap success criteria cannot be marked demonstrated, until the human runs the live smoke test on the deployment host and reports the result.
- No blockers for the static artifacts themselves; the only remaining work is live-infrastructure verification, which this sandbox cannot perform (no `podman`/`docker` present, confirmed again this session).

## Checkpoint

**Type:** human-verify
**Plan:** 08-03
**Progress:** 2/3 tasks complete

### Completed Tasks

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | Write scripts/smoke_test_broker.py | `4a5d9de` | `scripts/smoke_test_broker.py` |
| 2 | Repoint the Podman setup doc at deploy/ and document the new endpoint and credentials | `520916a` | `docs/Podman setup for checkmk, minio, mosquitto, worker.md` |

### Current Task

**Task 3:** Deploy the hardened stack and run the smoke test on the real host
**Status:** blocked — no container runtime in this sandbox
**Blocked by:** `command -v podman docker` returns nothing here (confirmed again this session, consistent with 08-01/08-02's findings)

### Checkpoint Details

Automation was attempted first, per the plan's own instruction: `command -v podman docker` returned nothing, and running `uv run python scripts/smoke_test_broker.py --timeout 3` against this sandbox (no broker at all, real or hardened) produced honest `[FAIL]` lines for every live check (`Connection refused`) rather than a false pass, and the persistence check's restart step raised an uncaught `FileNotFoundError` for the missing `podman` binary — confirming the script fails loudly rather than silently passing when infrastructure is absent.

**Important — the real deployment host is not yet ready for this test.** Per the known environment constraint for this session: the deployment host (running `checkmk`, `mosquitto`, `minio`, `worker` containers, verified up earlier this session) is still running the OLD, un-hardened `compose.yaml`/`mosquitto.conf` — it has **not yet been redeployed** with this phase's `deploy/` artifacts (from 08-01/08-02, already merged to `main`). Before the smoke test can pass, the operator needs to:

1. Copy `deploy/`'s five files (`compose.yaml`, `mosquitto.conf`, `mosquitto.acl`, `mosquitto.passwd`, `gen-mosquitto-passwd.sh`) into the existing `~/checkmk-stack` directory on the deployment host, **keeping that directory name** so the existing `checkmk_data` volume is preserved (not recreated under a new compose-project name).
2. From `~/checkmk-stack`: `podman compose up -d` (or `podman compose restart mosquitto` if only the broker's config changed) — expect no port-binding errors (the WS listener is now on host `9002`, not `9001`, avoiding the MinIO console collision).
3. Only then run the smoke test.

### How to Verify

On the host running the Podman stack, from this repo checkout (after the redeploy above):

1. `cd deploy && podman compose up -d` — expect all four containers to reach a running state with no "address already in use" error (that would mean the 9002 mapping regressed to 9001). If deploying into an existing `~/checkmk-stack` directory instead of a fresh `deploy/` checkout, run from there instead, per the redeploy note above.
2. `podman compose ps` — expect `mosquitto` Up, not restart-looping. If it exits immediately, run `podman compose logs mosquitto` and look for "Unable to open acl_file" / "Unable to open password file" — a file-permission problem, since the in-container broker runs as UID 1883 and the mounted files must be mode 644.
3. `podman compose exec mosquitto cat /mosquitto/config/mosquitto.conf` — expect the hardened content with both listeners, confirming the mount-path correction took effect.
4. From the repo root: `uv run python scripts/smoke_test_broker.py`
   Expect four `[PASS]` lines and exit code 0:
   - `[PASS] poller_publish` — the poller authenticated on 1883 and published a retained seed
   - `[PASS] ws_subscribe` — a WebSockets client on host 9002 connected and received that retained value (BRK-01)
   - `[PASS] ws_publish_denied` — the `wsreader` publish never reached an independent privileged subscriber (BRK-03)
   - `[PASS] persistence_across_restart` — the retained seed survived `podman compose restart mosquitto` (BRK-02)
5. Negative control: `podman compose exec mosquitto mosquitto_sub -h localhost -p 1883 -u wsreader -P wsreader -t 'lan/#' -C 1 -W 5` should subscribe fine (read allowed), while `podman compose exec mosquitto mosquitto_pub -h localhost -p 1883 -u wsreader -P wsreader -t lan/acl-probe -m x` publishes with no client-visible error yet leaves nothing readable on `lan/acl-probe`.
6. Confirm no leftovers: `podman compose exec mosquitto mosquitto_sub -h localhost -p 1883 -u poller -P poller -t 'lan/smoketest/#' -C 1 -W 3` should time out with no payload, proving the script cleaned up its retained topics.

### Awaiting

Operator to redeploy `deploy/` onto the running stack, run the smoke test, and either reply "approved" (all four `[PASS]`, `mosquitto` stays Up, `lan/smoketest/#` empty afterwards) or paste the failing `[FAIL]` line plus `podman compose logs mosquitto` output so the underlying artifact (Plan 01's config or Plan 02's compose wiring) can be fixed rather than loosening the check.

## Self-Check: PASSED

- FOUND: scripts/smoke_test_broker.py
- FOUND: docs/Podman setup for checkmk, minio, mosquitto, worker.md (modified)
- FOUND: commit 4a5d9de
- FOUND: commit 520916a

---
*Phase: 08-broker-infrastructure-hardening*
*Completed: Tasks 1-2 on 2026-09-06; Task 3 paused at checkpoint*
