---
phase: quick-260907-m8w
plan: 01
subsystem: api
tags: [httpx, rest-api, checkmk, wizard-cli, container-mode]

# Dependency graph
requires: []
provides:
  - "CheckmkConnection.port and _site_base() — single netloc-assembly point for REST/GUI URLs"
  - "port= kwarg on bootstrap_automation_user, bootstrap_agent_registration_secret, change_cmkadmin_password"
  - "_split_checkmk_host_port() — one-colon host:port parsing with IPv6-safe scope"
  - "Container-mode default checkmk:5000 matching deploy/compose.yaml's real internal port"
affects: [wizard-phase1, container-deployment-docs]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single netloc-assembly helper (_site_base) shared by a dataclass property and three free functions, to prevent URL-construction drift"
    - "Strict one-colon host:port parsing to keep IPv6 literals unambiguous without bracket-syntax support"

key-files:
  created: []
  modified:
    - src/checkmk_wizard/api.py
    - src/checkmk_wizard/wizard.py
    - tests/test_api.py
    - tests/test_wizard.py
    - docs/WIZARD-OPERATION.md
    - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"

key-decisions:
  - "CheckmkConnection.host stays a bare hostname; port is a separate, strictly-additive last field — Livestatus (6557) and cmk-agent-ctl register --server (8000) call sites need zero edits"
  - "host:port is only recognized when the input has exactly one colon — IPv6 literals (zero or 2+ colons) are never misparsed; bracketed [::1]:5000 is knowingly out of scope"
  - "Container-mode default changed from checkmk to checkmk:5000 to match the check-mk-raw image's actual internal REST/GUI port (compose maps 8080:5000)"

requirements-completed: [QP-M8W-01]

# Metrics
duration: ~25min
completed: 2026-09-07
---

# Phase quick-260907-m8w: Explicit REST/GUI port support for Checkmk host prompt Summary

**Operators can now type `checkmk:5000` at the Phase 1 host prompt; the port threads into REST/GUI URLs only, while Livestatus and agent-registration keep the bare host — fixing the real `check-mk-raw` container's login failure on port 80.**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-09-07
- **Tasks:** 3/3 completed
- **Files modified:** 6

## Accomplishments
- `CheckmkConnection` gained an additive `port: int | None = None` field and a shared `_site_base()` helper used by `base_url` and all three GUI-session bootstrap helpers (`bootstrap_automation_user`, `bootstrap_agent_registration_secret`, `change_cmkadmin_password`)
- Phase 1's host prompt now accepts `host:port`, parsed by a new `_split_checkmk_host_port()` that is deliberately scoped to exactly-one-colon inputs so IPv6 literals are never misparsed
- Container-mode default changed from `checkmk` to `checkmk:5000`, matching the `check-mk-raw` image's real internal port (`deploy/compose.yaml` maps `8080:5000`)
- Livestatus (`_probe_livestatus_tcp`) and agent-receiver (`_resolve_agent_registration_server`, `livestatus.query_host_states`) call sites remain untouched and bare-host-only, each with an inline comment recording why
- Both operator docs (`WIZARD-OPERATION.md`, the Podman setup doc §8.3) updated to describe the new input format and default

## Task Commits

Each task was committed atomically:

1. **Task 1: Add optional port to CheckmkConnection and the three GUI-session bootstrap helpers** - `840d28a` (feat)
2. **Task 2: Parse an optional :port at the host prompt and thread it into the REST/GUI call sites only** - `b127458` (feat)
3. **Task 3: Update the operator docs to describe the host:port input and the new container default** - `10f3404` (docs)

_Plan metadata commit (SUMMARY.md/STATE.md) is created separately by the orchestrator, not by this executor._

## Files Created/Modified
- `src/checkmk_wizard/api.py` - Added `_site_base()` helper, `CheckmkConnection.port` field, `port=` kwarg on all three bootstrap helpers
- `src/checkmk_wizard/wizard.py` - Added `_split_checkmk_host_port()`, changed `_CONTAINER_MODE_CHECKMK_HOST` to `"checkmk:5000"`, reworked the host prompt loop, threaded `checkmk_port` through `_prompt_change_cmkadmin_password`, `_create_fresh_site`, both bootstrap call sites, and `CheckmkConnection` construction; added scope-guard comments at the three unchanged bare-host call sites
- `tests/test_api.py` - Added `PORT_BASE`/`PORT_LOGIN_URL` constants and port-aware regression tests for `base_url` and all three bootstrap helpers
- `tests/test_wizard.py` - Added parametrized tests for `_split_checkmk_host_port` (valid + malformed inputs), updated `test_default_checkmk_host_container_mode` and the CMK_PASSWORD-prefill test's default-value assertion, added an end-to-end `test_phase1_container_mode_threads_explicit_rest_port` regression test
- `docs/WIZARD-OPERATION.md` - Documented the `checkmk:5000` container default and the `host:port` input format/scope
- `docs/Podman setup for checkmk, minio, mosquitto, worker.md` - Updated §8.3's Checkmk host/IP prompt bullet to `checkmk:5000`

## Decisions Made
- Kept `CheckmkConnection.host` bare and added `port` as a wholly separate, last-positioned field — this is the reason `_resolve_agent_registration_server` and `livestatus.query_host_states` call sites needed zero code changes, only explanatory comments.
- Scoped `_split_checkmk_host_port` to the exactly-one-colon rule rather than attempting bracketed-IPv6 (`[::1]:5000`) support, per the plan's explicit design note — simpler and covers the actual deployment need (a hostname, `checkmk`, not a raw IPv6 literal).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated a pre-existing test's default-value assertion broken by the container-mode default change**
- **Found during:** Task 2 (running the full test suite after implementation)
- **Issue:** `test_phase1_container_mode_prefills_host_and_cmkadmin_from_cmk_password` asserted the recorded `questionary.text` default for the host prompt equals `"checkmk"`. Changing `_CONTAINER_MODE_CHECKMK_HOST` to `"checkmk:5000"` (an explicit, planned part of this task) made that assertion fail — it was checking the exact default value, not just answering it.
- **Fix:** Updated the assertion to expect `"checkmk:5000"`, with a short comment explaining why.
- **Files modified:** tests/test_wizard.py
- **Verification:** `uv run pytest tests/ -q` — 303 passed
- **Committed in:** `b127458` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Direct, in-scope consequence of the plan's own change to `_CONTAINER_MODE_CHECKMK_HOST`; no scope creep.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Feature is complete and self-contained; no follow-up work identified.
- A real container-mode wizard run against `deploy/compose.yaml`'s `check-mk-raw` service on port 5000 should now succeed past the previous `GET/POST http://checkmk/dmc/check_mk/login.py -> 0: All connection attempts failed` failure (fixed by code, not independently re-verified against a live container in this session — see Verification below).

## Verification

- `uv run pytest tests/ -q` — **303 passed** (ran after each task and again at the end)
- `uvx ruff check src tests` — 7 pre-existing errors, confirmed unchanged before/after this plan's diff via `git stash`/`git stash pop` comparison (all in `wizard.py:763` and pre-existing `test_site.py`/`test_wizard.py` code untouched by this plan) — no new lint errors introduced
- Manual reasoning check: `git diff` confirms no edit to the `_probe_livestatus_tcp(checkmk_host)`, `_resolve_agent_registration_server(hosts, connection.host)`, or `livestatus.query_host_states(connection.host, ...)` call-site arguments themselves (only comments added nearby)
- **Not verified in this session:** an actual live run against a real `check-mk-raw` container on port 5000 (would require a running Podman stack) — the plan's `<verification>` list this only as "manual reasoning check", not a live-container check, so this is consistent with plan scope

## Self-Check: PASSED

- FOUND: src/checkmk_wizard/api.py
- FOUND: src/checkmk_wizard/wizard.py
- FOUND: tests/test_api.py
- FOUND: tests/test_wizard.py
- FOUND: docs/WIZARD-OPERATION.md
- FOUND: docs/Podman setup for checkmk, minio, mosquitto, worker.md
- Commit 840d28a: FOUND in `git log --oneline --all`
- Commit b127458: FOUND in `git log --oneline --all`
- Commit 10f3404: FOUND in `git log --oneline --all`

---
*Phase: quick-260907-m8w*
*Completed: 2026-09-07*
