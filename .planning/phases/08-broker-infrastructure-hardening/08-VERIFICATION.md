---
phase: 08-broker-infrastructure-hardening
verified: 2026-10-12T00:00:00Z
status: human_needed
score: 4/4 roadmap success criteria verified in current code; 3 of 4 also re-confirmed live after Phase 14.3, 1 (persistence) last confirmed live 2026-09-06
has_blocking_gaps: false
overrides_applied: 0
gaps: []
deferred: []
human_verification:
  - test: "On the deployment host run `scripts/smoke_test_broker.py --with-restart --compose-dir deploy` (restart is opt-in since quick 261008-b5a; every post-14.3 live run used --skip-restart)"
    expected: "[PASS] persistence_across_restart in addition to the ACL/WS checks, proving the retained seed survives a broker restart against the CURRENT mosquitto.conf and volume wiring"
    why_human: "Needs live podman/mosquitto access. The only live persistence proof is 08-03 (2026-09-06); the config was edited afterwards (message_size_limit, ACL template, entrypoint-generated passwd) so the original evidence predates the current state, although the persistence directives and volume mount are unchanged in code."
---

# Phase 8: Broker Infrastructure Hardening Verification Report

**Phase Goal:** The MQTT broker is durable and access-controlled, ready to serve both the poller and browser clients before either is built against it
**Verified:** 2026-10-12
**Status:** human_needed (all requirements satisfied in code; one live re-confirmation outstanding, low risk)
**Re-verification:** No - initial verification (no prior 08-VERIFICATION.md existed). Judged against the CURRENT code, which Phase 14.3 (and quick 260930-jj4, 261004-lyz, Phases 14.2/16) re-shaped.

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A browser MQTT client can connect over a WebSockets listener distinct from the poller's internal TCP listener | VERIFIED | `deploy/mosquitto.conf`: `listener 1883 0.0.0.0` (plain MQTT) and a separate `listener 9001 0.0.0.0` + `protocol websockets`. Live: `[PASS] ws_subscribe` in 08-03 (2026-09-06); wsreader WS subscribe re-confirmed in the post-14.3 run (14.3-06-SUMMARY, 2026-10-04: 9 checks PASS) and 14.2-19 (2026-10-05: 11 checks PASS). |
| 2 | Restarting the mosquitto container preserves retained messages (`persistence true` on a mounted volume) | VERIFIED (code) / live evidence dated | `mosquitto.conf`: `persistence true`, `persistence_location /mosquitto/data/`, `autosave_interval 60`. `deploy/compose.yaml`: `mosquitto_data:/mosquitto/data:z` plus top-level `mosquitto_data:` volume declared. Live: `[PASS] persistence_across_restart` in 08-03 (2026-09-06). Not re-run live since: 14.3-06 and 14.2-19 both ran `--skip-restart` (persistence SKIPPED by design). See human_verification. Indirect live evidence: Phase 9 restart checks and the 14.3 retained-topic sweep rely on retained data surviving, but they are not a direct test of this criterion. |
| 3 | WS listener enforces read-only ACL: WS client can subscribe, publish rejected; only the poller's internal connection publishes | VERIFIED, wording superseded (see below) | `deploy/mosquitto.acl.template`: `user wsreader` has only `topic read sites/@SITE_ID@/lan/#` (no write grant anywhere); `allow_anonymous false`; default-deny for users without a block. `tests/test_mosquitto_acl.py::test_rendered_grants_are_exact` and `test_no_grant_on_bare_wildcard` pin the exact grant set. Live: `[PASS] ws_publish_denied` (08-03, 2026-09-06) and again after 14.3 (2026-10-04, 9 checks PASS) via an independent privileged subscriber (not the denied publisher's PUBACK). |
| 4 | `compose.yaml` exposes the WS port to the LAN alongside 1883 | VERIFIED | `deploy/compose.yaml` mosquitto service: `"1883:1883"` and `"9002:9001"` (host 9002 avoids minio's 9001 console). Config mounted at `/mosquitto/config/mosquitto.conf` (the only path the image CMD reads). |

**Score:** 4/4 verified in code; live evidence per row above.

### Where Phase 14.3 (and later changes) superseded the original wording

The original criteria were written for a flat `lan/#` namespace with two users (poller, wsreader). The current state differs, and the judgments above are made against it:

- **Topic scope:** wsreader no longer reads "any topic" or `lan/#`; it reads `sites/<CMK_SITE_ID>/lan/#` only. The ACL is a template rendered per deployment by `deploy/render-mosquitto-acl.sh` at container start (validates the site id before it reaches sed; fails the container start on an invalid id). This is a tightening, consistent with the intent of SC3.
- **"Only the poller can publish" is no longer literally true.** Additional narrowly scoped writers exist by later design decisions: `wsadmin` (write `sites/<id>/admin/cmd` only; Phase 16), `wstriage` (write `sites/<id>/needs/triage/cmd` only; Phase 14.2 D-21), `analytics` (writes its own `lan/needs/#`, `lan/forecasts/#`, `lan/incidents/+/narration`; Phase 14.2). None can write the poller's topics, and the baseline browser login (wsreader) remains strictly read-only. BRK-03's intent (browser read-only login cannot publish to the data topics) holds; the "only poller" clause is amended by Phases 14.2/16 (documented in CLAUDE.md constraints). wsadmin/wstriage credentials are served openly on the closed demo network by design.
- **Auth is per-user, not per-listener** (`per_listener_settings` default false): "WS listener is read-only" is realised as "the WS-facing login (wsreader) is read-only", not that the listener itself blocks writes. A client holding the poller credentials could publish over WS. This matches the original 08-01 design and is not a new gap.
- **Phase 8's original artifacts were replaced:** `deploy/mosquitto.acl`, `deploy/mosquitto.passwd` and `deploy/gen-mosquitto-passwd.sh` no longer exist. The password file is generated by the compose entrypoint from `deploy/.env` at every start (quick 260930-jj4); the ACL is rendered from `mosquitto.acl.template`. Wiring verified in `deploy/compose.yaml` (entrypoint, mounts) and `tests/test_mosquitto_acl.py::test_compose_wires_the_renderer` / `test_compose_creates_new_broker_users`.
- **Smoke test** now uses `sites/<id>/...` topics (`--site-id`), covers the later users, and the persistence check is opt-in (`--with-restart`, `--skip-restart` wins).

### Required Artifacts (current state)

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `deploy/mosquitto.conf` | two listeners, auth, persistence | VERIFIED | Globals before listeners; `allow_anonymous false`, `password_file`, `acl_file`, `persistence true`, `message_size_limit 2097152` (test-pinned above the analytics events cap). |
| `deploy/mosquitto.acl.template` + `deploy/render-mosquitto-acl.sh` | per-user default-deny ACL | VERIFIED | wsreader read-only; 23 tests in `tests/test_mosquitto_acl.py` + `tests/test_smoke_test_broker.py` pass (run during this verification). |
| `deploy/compose.yaml` mosquitto service | WS port published, volumes, creds from env | VERIFIED | `9002:9001`, `mosquitto_data`/`mosquitto_log` volumes, `${VAR:?}` guards on broker passwords. |
| `scripts/smoke_test_broker.py` | live proof of BRK-01/02/03 | VERIFIED | 781 lines, `--help` runs offline; paho-mqtt `>=2.1.0` in `pyproject.toml`. Denial checks assert via an independent subscriber. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `mosquitto.conf` | `/mosquitto/config/mosquitto.passwd` | entrypoint `mosquitto_passwd` for poller/wsreader/wsadmin/analytics/wstriage | WIRED | compose.yaml entrypoint; file chowned `mosquitto`, mode 0700 |
| `mosquitto.conf` | `/mosquitto/config/mosquitto.acl` | renderer run in entrypoint before `exec` | WIRED | live-confirmed rendered file in 14.3-06 (owner mosquitto, 0700, no ACL warnings in log) |
| `compose.yaml` | volume `mosquitto_data` | `/mosquitto/data` mount, matches `persistence_location` | WIRED | |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| ACL render/grants/compose wiring + smoke script logic | `uv run pytest tests/test_mosquitto_acl.py tests/test_smoke_test_broker.py -q` | 23 passed | PASS |
| Smoke script CLI loads offline | `uv run python scripts/smoke_test_broker.py --help` | usage printed | PASS |
| Live broker behavior | requires running mosquitto (none on this machine) | not run here | SKIP (see Probe/Live evidence) |

### Live evidence (not re-executed by this verification)

| Run | Date | Result | Source |
|-----|------|--------|--------|
| Original 4 checks incl. persistence | 2026-09-06 | all PASS (after quick 260906-mm9 fixed a mosquitto.conf indented-comment crash loop) | 08-03-SUMMARY |
| Post-14.3 cutover, `--skip-restart` | 2026-10-04 | 9 checks PASS, persistence SKIPPED | 14.3-06-SUMMARY |
| Post-14.2, `--skip-restart` | 2026-10-05 | 11 checks PASS, persistence SKIPPED | 14.2-19-SUMMARY |

These are recorded user-reported runs on the deployment host; this verification could not repeat them.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| BRK-01 | 08-01, 08-02, 08-03 | WebSockets listener for browser clients, separate from the internal TCP listener | SATISFIED | Two listeners in `mosquitto.conf`; `9002:9001` published; `ws_subscribe` verified live 2026-09-06 and re-confirmed 2026-10-04/05. |
| BRK-02 | 08-01, 08-02, 08-03 | `persistence true` against a mounted volume | SATISFIED (code); live re-run pending | `persistence true` + `mosquitto_data` volume in current code; `persistence_across_restart` PASS 2026-09-06 only. Flagged as the single human_verification item. |
| BRK-03 | 08-01, 08-03 | WS listener ACL-scoped read-only for browser clients; only poller can publish | SATISFIED, wording amended | wsreader read-only, exact-grant tests; `ws_publish_denied` PASS live 2026-09-06 and post-14.3. "Only the poller" now has narrow, documented exceptions (wsadmin, wstriage, analytics) from Phases 14.2/16. |

No orphaned requirements: REQUIREMENTS.md maps only BRK-01..03 to Phase 8, all claimed by plans.

### Anti-Patterns Found

None. No TBD/FIXME/XXX in `deploy/mosquitto.conf`, `deploy/mosquitto.acl.template`, `deploy/render-mosquitto-acl.sh`, `scripts/smoke_test_broker.py`.

### Documentation drift (informational, not a gap)

- `.planning/REQUIREMENTS.md` still lists BRK-01/02/03 as `[ ]` / "Pending" (lines 29-31, 114-116) although ROADMAP marks Phase 8 `[x]`; it should be ticked off. Not edited here.
- `mosquitto.conf` comment still says "scoped per-username rather than per-listener", which is accurate; the ROADMAP SC3 wording ("any topic", "only the poller") is the stale text.

### Human Verification Required

#### 1. Persistence across restart on the current stack

**Test:** `uv run scripts/smoke_test_broker.py --with-restart --compose-dir deploy` (with `.env` credentials and `--site-id` = deployment's `CMK_SITE_ID`) on the deployment host.
**Expected:** `[PASS] persistence_across_restart`.
**Why human:** needs live podman access; the only live proof predates the current config and every later live run skipped it.

### Gaps Summary

No gaps. The broker config, ACL, compose wiring and smoke test exist, are substantive, wired, and unit-tested; live ACL/WS behavior was re-confirmed after the per-site namespace change. The only open item is a routine live re-confirmation of retained-state persistence against today's config.

---

_Verified: 2026-10-12_
_Verifier: Claude (bm-verifier)_
