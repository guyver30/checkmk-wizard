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

requirements-completed: [BRK-01, BRK-02, BRK-03]

# Metrics
duration: ~45min (Tasks 1-2, 2026-09-06) + live verification on deployment host (2026-09-06, after an unrelated deploy/mosquitto.conf syntax bug was fixed as quick task 260906-mm9)
completed: 2026-09-06
---

# Phase 8 Plan 3: Live Broker Smoke Test + Podman Doc Repoint Summary

**Standalone paho-mqtt 2.x smoke-test script (`scripts/smoke_test_broker.py`) proving all three broker-hardening requirements against a live Mosquitto instance, plus the Podman setup doc repointed at `deploy/` as its single source of truth — all four checks PASSED on the real deployment host, completing BRK-01/02/03.**

## Performance

- **Duration:** ~45 min (Tasks 1-2) + live verification round-trip (Task 3)
- **Started:** 2026-09-06
- **Completed:** 2026-09-06 — all 3 tasks done
- **Tasks:** 3 of 3 completed
- **Files modified:** 2 (this plan) + 1 unrelated fix (deploy/mosquitto.conf, via quick task 260906-mm9)

## Accomplishments
- `scripts/smoke_test_broker.py` implements all four ordered checks (`check_poller_publish`, `check_ws_subscribe`, `check_ws_publish_denied`, `check_persistence_across_restart`), each printing a single `[PASS]`/`[FAIL]` line, using paho-mqtt 2.x's `CallbackAPIVersion.VERSION2` API throughout (not the legacy v1 pattern)
- `check_ws_publish_denied` is structured exactly per RESEARCH.md Pitfall 3: the assertion is made from an INDEPENDENT privileged subscriber via a bounded `threading.Event`, never from the denied publisher's own return code/PUBACK — a code comment states why, so a future reader doesn't "simplify" it back into a false positive
- The script is invisible to pytest (no `test_*` function names, not under `tests/`) and its `--help` works fully offline, confirmed by actually running it with no broker present
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` §3 no longer duplicates `mosquitto.conf`/`compose.yaml` inline — it links to `deploy/` instead; §2's directory tree, §4's migration callout, §6's endpoint table/credentials, and a new §7 subsection documenting the smoke test were all updated to match

## Task Commits

Each task was committed atomically:

1. **Task 1: Write scripts/smoke_test_broker.py** - `4a5d9de` (feat)
2. **Task 2: Repoint the Podman setup doc at deploy/ and document the new endpoint and credentials** - `520916a` (docs)

3. **Task 3: Deploy the hardened stack and run the smoke test on the real host** - resolved via human-verify checkpoint, no commit (live verification only, no files modified by this task itself)

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

Resolved. The operator redeployed `deploy/`'s files onto the real Podman host and ran the smoke test twice:

1. **First attempt** surfaced a real, unrelated bug: `deploy/mosquitto.conf` crash-looped mosquitto (exit code 3, "Unknown configuration variable '#'") due to an indented comment-continuation line that mosquitto's parser tokenized as a directive. Fixed separately as quick task `260906-mm9` (commit `2eff022`) — an indented `#` line is not a valid mosquitto.conf comment; comments must start at column 0.
2. **Second attempt**, after redeploying the fixed config: mosquitto started cleanly (both listeners open, config loaded without error), and all four smoke-test checks passed.

## Next Phase Readiness

- All three tasks complete. Phase 8's roadmap success criteria (BRK-01/02/03) are now demonstrated by an automated, repeatable command (`scripts/smoke_test_broker.py`), not just static inspection.
- `deploy/` and the Podman setup doc can no longer drift apart — the doc holds no duplicated configuration.
- Phase 9 (Poller Core) can now build against a proven-working, authenticated, ACL-scoped, persistent broker.

## Checkpoint — RESOLVED

**Type:** human-verify
**Plan:** 08-03
**Progress:** 3/3 tasks complete

### Completed Tasks

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | Write scripts/smoke_test_broker.py | `4a5d9de` | `scripts/smoke_test_broker.py` |
| 2 | Repoint the Podman setup doc at deploy/ and document the new endpoint and credentials | `520916a` | `docs/Podman setup for checkmk, minio, mosquitto, worker.md` |
| 3 | Deploy the hardened stack and run the smoke test on the real host | (live verification only) | — |

### Live Verification Result

```
[PASS] poller_publish
[PASS] ws_subscribe
[PASS] ws_publish_denied
[PASS] persistence_across_restart
[SUMMARY] all checks passed
```

All four checks proved their respective requirements on the real deployment host:
- `poller_publish` — the poller's authenticated write path on 1883 works (D-05: no longer anonymous)
- `ws_subscribe` — BRK-01: the WebSockets listener (host 9002 / container 9001) is reachable and distinct from 1883
- `ws_publish_denied` — BRK-03: the `wsreader` WS user's publish never reached an independent privileged subscriber (read-only ACL enforced)
- `persistence_across_restart` — BRK-02: the retained seed survived a broker restart

### Resolution Notes

The first live run did not reach the broker at all (`Connection refused` on every check) because `deploy/mosquitto.conf` had a genuine syntax bug — an indented trailing-comment continuation line that mosquitto's parser rejects — crash-looping the container. This was outside plan 08-03's scope (it lives in Plan 01's artifact) and was fixed as a standalone quick task (`260906-mm9`) rather than folded into this plan. Once fixed and redeployed, the smoke test passed cleanly on the first subsequent attempt.

## Self-Check: PASSED

- FOUND: scripts/smoke_test_broker.py
- FOUND: docs/Podman setup for checkmk, minio, mosquitto, worker.md (modified)
- FOUND: commit 4a5d9de
- FOUND: commit 520916a
- FOUND: live verification — all four smoke-test checks PASSED on the real deployment host

---
*Phase: 08-broker-infrastructure-hardening*
*Completed: 2026-09-06 — all three tasks done, BRK-01/02/03 proven live*
