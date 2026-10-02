# Phase 16: Dashboard admin mode for live demos - Research

**Researched:** 2026-10-02
**Domain:** MQTT command channel (browser -> broker ACL -> poller) -> Livestatus external commands; React multi-select UI
**Confidence:** MEDIUM (codebase and mechanics HIGH; "faked" detection columns and vis-network ctrl-click are unverified live)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** DOWN on a **managed** parent auto-cascades **UNREACHABLE** to every descendant, matching real Checkmk. UP / Restore reverses the cascade.
- **D-02:** The cascade must **not** walk through an unmanaged switch (`unmanaged_switch` label): hosts behind it are DOWN, not UNREACHABLE. Descendants behind an unmanaged switch are only faked when selected explicitly.
- **D-03:** **No special action on an unmanaged switch itself.** The operator selects the switch's children and sends DOWN; the existing inferred-root rule in `compute_incidents` (unmanaged host with >= 2 non-OK children, at least one DOWN) must produce the combined switch card with children listed. Needs tests with faked DOWN children, not a new rule. (One faked child alone stays a plain root, by design.)
- **D-04:** Each fake sets host AND the host's `PING` service together: UP = host 0 / PING 0 with `OK - <ip> rta <random 0.2-3.0>ms lost 0%`; DOWN = host 1 / PING 2 with `CRITICAL - <ip>: rta nan, lost 100%`; UNREACHABLE = host 2 / PING 2 with the same CRITICAL text. The poller builds the text, never the browser. Output must not contain `;` or a single quote.
- **D-05:** Before injecting, the poller sends `DISABLE_HOST_CHECK` and `DISABLE_SVC_CHECK;<host>;PING`. Restore sends `ENABLE_HOST_CHECK` / `ENABLE_SVC_CHECK`.
- **D-06:** New broker user (`wsadmin`, password `ADMIN_WS_PASSWORD` generated into `deploy/.env` by `deploy/init-env.sh`) may publish **only** on the admin command topic and read only the admin-only topics. `wsreader` (read-only `lan/#`) unchanged.
- **D-07:** Admin login delivered by a **separate `/admin-config.json`** rendered by the dashboard's nginx, **open** (no source-network restriction). Page fetches it only when `?admin=1`. Normal `/config.json` stays read-only. Acceptable only on the closed demo network.
- **D-08:** Poller acknowledges every command on an **admin-only ack topic** (applied, or failed with short reason); admin bar shows the result.
- **D-09:** Admin topics live **outside `lan/`**, e.g. `admin/cmd`, `admin/ack`, `admin/faked`. `poller` already has `readwrite #`.
- **D-10:** "Which hosts are faked" is **derived by the poller from Livestatus** (active checks disabled with a passive result) and published retained on `admin/faked`. Non-admin dashboards never see it.
- **D-11:** A fake lasts **until restored**; no auto-expire. Admin bar offers Restore selected and Restore all.
- **D-12:** Faked hosts marked in the admin view only.
- **D-13:** Admin mode may fake **any** host. Every action goes through a **confirm dialog** listing the action and exact hosts (count and names).
- **D-14:** Persistent banner "ADMIN MODE - N hosts faked", admin view only. Banner only, no notification warning.

### Claude's Discretion
- Exact topic names, payload JSON shape, command-id/ack correlation.
- Selection UX beyond "ctrl+click toggles": folder selection control in the tree, action bar placement, shortcuts, how selection is cleared.
- How the poller maps a selected folder to hosts; cascade traversal (cycle-guarded like `compute_incidents`).
- Whether admin mode and topology edit mode are kept separate (must not conflict).
- How the poller reliably identifies "faked" in Livestatus without false positives; if no reliable signal, fall back to a poller-owned retained set while keeping the admin-only topic.

### Deferred Ideas (OUT OF SCOPE)
- Auto-expiry of fakes after N minutes.
- Source-network restriction (`ADMIN_ALLOW_CIDR`) for `/admin-config.json`.
- Notification warning in the confirm dialog.
- Criticality/dependency model rework (todo 2026-09-28).
</user_constraints>

<phase_requirements>
## Phase Requirements

No requirement IDs are mapped to this phase (TBD). The planner should derive plan-level must-haves from D-01..D-14 above; suggested handles: ADM-CMD (command channel + ACL), ADM-FAKE (poller fake/cascade/restore), ADM-DERIVE (faked set), ADM-UI (selection, bar, confirm, banner), ADM-SWITCH (inferred switch card with faked children).
</phase_requirements>

## Summary

The phase is entirely additive across four existing seams: broker (new user + ACL + `admin/*` topics), nginx (`/admin-config.json`), the standalone poller `scripts/mqtt_poller.py` (new subscribe + command handler + faked-set publisher), and the React SPA (admin mode, selection, action bar). No new service is needed. All fake mechanics are already proven by the wizard's `_fake_demo_hosts_up` and the `fakeping` runbook helper (live-verified against 2.4.0p36); the poller just needs its own copy of the one-connection-per-command sender, because it cannot import `src/checkmk_wizard`. [VERIFIED: codebase grep]

The biggest planning risks are: (1) the poller today only *publishes* from a single-threaded loop and has no inbound handler, so command handling must run off paho's network thread (queue + worker) and read the latest snapshots through a lock; (2) the admin browser also needs to *read* `lan/#`, so `wsadmin` needs `read lan/#` as well as the admin topics (or a second connection with `wsreader`); (3) the browser is untrusted input into a text protocol (Livestatus uses `;` and newlines), so the poller must validate every host id against its own known snapshot set and never interpolate browser strings; (4) the "faked" signal via `active_checks_enabled`/`check_type` columns is from Nagios-lineage knowledge and was NOT verified against a live site in this session.

**Primary recommendation:** Single admin MQTT connection as `wsadmin` (read `lan/#`, `admin/ack`, `admin/faked`; write `admin/cmd` only), non-retained QoS 1 commands `{id, action, hosts[]}` with hosts resolved client-side (folder -> host list), poller validates against known ids, applies cascade server-side from current snapshots, executes in a worker thread, acks, and republishes `admin/faked` derived from Livestatus (probe columns first; fall back to a poller-owned retained set if the probe shows false positives).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Multi-select, action bar, confirm dialog, banner, faked badge | Browser / Client | — | Pure UI state; admin view only |
| Folder -> host list resolution | Browser / Client | API/Backend (poller validates) | Browser already holds `folder` per device and the confirm dialog must list exact names (D-13) |
| Admin login delivery | CDN / Static (nginx) | — | `/admin-config.json` via envsubst, mirrors `/config.json` |
| Publish authorization | Broker (Mosquitto ACL) | — | Only `wsadmin` can write `admin/cmd` |
| Command validation, cascade, Livestatus commands | API / Backend (poller) | — | Only the poller may talk Livestatus; owns topology snapshot for cascade |
| Faked-state source of truth | Database / Storage (Checkmk core state via Livestatus) | Broker retained `admin/faked` | Survives restarts because Checkmk holds it (D-10) |
| Incident/switch card rendering with faked states | API / Backend (`compute_incidents`) | Browser | Existing engine; only tests added (D-03) |

## Standard Stack

No new packages are required. Everything uses what is already installed.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| paho-mqtt | 2.1.0 pinned in `deploy/compose.yaml` (`>=2.1.0` in pyproject) | Poller subscribe + publish | Already the poller's client [VERIFIED: codebase] |
| mqtt (mqtt.js) | ^5.16.0 | Browser publish/subscribe over WebSockets | Already `dashboard-react/package.json` [VERIFIED: codebase] |
| zustand | ^5.0.15 | Admin selection/faked store slice | Already the app store [VERIFIED: codebase] |
| vis-network | ^10.1.2 | Map multi-select | Already used by `TopologyMap.tsx` [VERIFIED: codebase] |
| stdlib `socket`, `random`, `threading`, `queue` | — | Livestatus commands, rta, worker | Poller already uses `socket`/`threading` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Single admin connection (wsadmin reads lan/#) | Second MQTT connection as wsreader | Two connections double the reconnect/backoff logic in `mqttClient.ts`; a single credential switch is simpler. D-06 says wsadmin "reads only admin-only topics"; reading `lan/#` too is an extension the planner must confirm (see Open Question 1) |
| Browser sends folder name | Browser sends resolved host list | Host list keeps the confirm dialog exact and the poller payload simple |

**Installation:** none. **Package Legitimacy Audit:** no new external packages; slopcheck not applicable.

## Architecture Patterns

### System Architecture Diagram

```
 operator browser (?admin=1)                       other browsers (normal)
   |  GET /admin-config.json  (nginx envsubst)        |  GET /config.json (wsreader)
   v                                                  v
 MQTT/WS as wsadmin ----------------------+      MQTT/WS as wsreader
   | publish admin/cmd (QoS1, retain=0)   |           | read lan/#
   | read admin/ack, admin/faked, lan/#   |           |
   v                                      v           v
 +------------------- Mosquitto (ACL default-deny) -----------------+
   |  admin/cmd -> poller                                           ^
   v                                                                |
 poller on_message (paho thread): drop if retained / bad JSON ------+ lan/devices/*/status (fresh states)
   -> queue.put(cmd)                                                |
 worker thread:                                                     |
   validate hosts in latest snapshots (lock)                        |
   expand cascade (managed descendants, stop at unmanaged_switch)   |
   build commands (DISABLE_*, PROCESS_*_CHECK_RESULT / ENABLE_*)    |
   -> Livestatus TCP :6557, one connection per command (retry)      |
   -> publish admin/ack {id, ok, detail, hosts}                     |
 poll loop (every 15 s): query hosts/services -> compute_incidents -+
   + derive faked set -> publish retained admin/faked (on change)
 Checkmk core: faked host/PING state ==> next poll shows DOWN/UNREACH => incidents (incl. inferred switch card)
```

### Recommended Project Structure
```
scripts/mqtt_poller.py            # + admin section: topics, parse/validate, cascade, command builder, worker, faked derivation
tests/test_mqtt_poller.py         # + cascade, command builder, validation, inferred-switch-with-faked-children tests
deploy/mosquitto.acl              # + user wsadmin
deploy/compose.yaml               # + mosquitto_passwd wsadmin, ADMIN_WS_* env on mosquitto + dashboard
deploy/dashboard-nginx.conf       # + location = /admin-config.json
deploy/init-env.sh, .env.example  # + ADMIN_WS_PASSWORD
dashboard-react/src/lib/adminMode.ts        # ?admin=1 detection, admin config fetch, payload builders
dashboard-react/src/store/adminStore.ts     # selection set, ack, faked set (or slice of useAppStore)
dashboard-react/src/components/AdminBar.tsx # action bar, confirm dialog, banner
```

### Pattern 1: Command payload and ack correlation
**What:** `admin/cmd` payload `{"id": "<uuid>", "action": "up"|"down"|"unreach"|"restore"|"restore_all", "hosts": ["h1", ...]}`; ack on `admin/ack` `{"id", "ok": bool, "detail": str, "applied": [..], "cascaded": [..]}` (not retained, or retained last-only; non-retained recommended so a late admin tab does not show a stale result). The browser matches by `id`.
**When:** every action. Poller ignores messages with `msg.retain` true (guards against a stale command replay) and keeps a small set of seen ids to dedupe QoS 1 redeliveries.

### Pattern 2: Command execution off the paho thread
`on_message` runs on paho's `loop_start` thread; Livestatus I/O with retries can take tens of seconds (core reloads). Enqueue and process in one daemon worker thread; serialize so two actions never interleave. Subscribe in `on_connect` (the current client only publishes the birth message there), because a reconnect with a clean session loses subscriptions. [VERIFIED: codebase, `build_mqtt_client`]

### Pattern 3: Cascade (D-01/D-02)
Build `children` from `snapshot.parents` (same as `compute_incidents`). For DOWN on managed host X: BFS over children with a `visited` set (cycle guard); each descendant gets UNREACHABLE; do not expand beyond a node whose `unmanaged` is true. Whether the unmanaged switch itself receives UNREACHABLE is not specified (Open Question 2). UP/Restore on X reverses: for descendants that were cascaded, but recompute against remaining DOWN ancestors so a descendant under two parents stays UNREACHABLE while another parent is still DOWN. Explicitly selected hosts in the same command win over cascade.

### Pattern 4: Command builder (mirror of `_fake_demo_hosts_up` and `fakeping`)
```python
# Source: src/checkmk_wizard/wizard.py::_fake_demo_hosts_up, docs/Incident demo with fake check results.md
output = f"OK - {ip} rta {random.uniform(0.2, 3.0):.3f}ms lost 0%"      # up
output = f"CRITICAL - {ip}: rta nan, lost 100%"                           # down / unreach
cmds = [
    f"DISABLE_HOST_CHECK;{host}",
    f"DISABLE_SVC_CHECK;{host};PING",
    f"PROCESS_HOST_CHECK_RESULT;{host};{hs};{output}",
    f"PROCESS_SERVICE_CHECK_RESULT;{host};PING;{ss};{output}",
]
# restore: ENABLE_HOST_CHECK;host and ENABLE_SVC_CHECK;host;PING
# send: socket.create_connection((host, 6557)); sendall(f"COMMAND [{int(time.time())}] {cmd}\n\n"); one connection per command
```
`ip` comes from the snapshot's `address` (fallback host id), then is rejected/sanitized if it contains `;`, `'`, CR or LF.

### Pattern 5: Browser side
- `?admin=1` is read once at startup (module-level, `main.tsx`), not from the router, so navigation helpers that rewrite the search string cannot drop it. Fetch `/admin-config.json` there and override `wsUsername/wsPassword` in the runtime config before `connect()`; `SUBSCRIBE_TOPICS` gains `admin/ack` and `admin/faked` only in admin mode. Add a `publishAdminCommand()` export to `src/store/mqttClient.ts` (its header rule: only that module touches the raw client).
- Map: `TopologyMap.tsx` click handler currently navigates. In admin mode, a ctrl/meta click toggles selection; plain click keeps navigating. vis-network `click` params expose the original event as `params.event` (Context7), so detect modifier via `params.event?.srcEvent?.ctrlKey || metaKey` [ASSUMED: srcEvent shape; verify with a quick manual check] or use the documented `interaction.multiselect` option. `FakeNetwork` in `src/test/fakeVisNetwork.ts` must be extended to deliver modifier info.
- Tree: `TreeNode.tsx` rows need ctrl+click toggling and a folder-level "select all hosts" control; folder -> hosts comes from device `folder` fields already in the store.
- Admin mode and topology edit mode must be mutually exclusive in `IndexRoute.tsx` (edit mode already repurposes map click for `onSelectHost`).

### Anti-Patterns to Avoid
- **Retained admin commands:** a retained `admin/cmd` replays on every poller restart. Browser publishes `retain: false`; poller drops `msg.retain` messages.
- **Trusting browser strings in LQL:** never format host names from the payload; resolve each against the poller's snapshots and use the snapshot's own id.
- **Single-service restart to apply ACL/password changes:** use full `podman compose down && up` (project memory: single restarts break Checkmk egress).
- **Putting admin topics under `lan/`:** `wsreader` has `read lan/#` and would see them.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cycle-safe graph walk | New traversal | Pattern of `_reachable_roots_from` / `children` map in `compute_incidents` | Cycles in `parents` are real and already handled |
| Livestatus transport | New protocol client | Poller's existing `socket.create_connection` idiom (`_livestatus_request`) plus a send-only twin of `livestatus.send_commands` | One-connection-per-command rule is load-bearing |
| Reconnect/backoff in browser | New retry logic | Existing `mqttClient.ts` jittered backoff | Reuse by switching credentials, not adding a client |
| Publish helper | Raw `client.publish` | `_publish_json` choke point (poller) | Normalizes broker errors |
| Random rta/ping text | New format | `_fake_demo_hosts_up` / `fakeping` text | Must look identical to demo hosts |
| Password file | Manual file | `mosquitto_passwd -b` line in compose entrypoint | Existing pattern, regenerated every start |

## Common Pitfalls

### Pitfall 1: wsadmin cannot see the dashboard data
**What goes wrong:** ACL grants only admin topics, so the admin page shows an empty map.
**How to avoid:** ACL for `wsadmin`: `topic read lan/#`, `topic read admin/ack`, `topic read admin/faked`, `topic write admin/cmd`. It still cannot write `lan/#`. [CITED: mosquitto ACL file semantics, deploy/mosquitto.acl header]

### Pitfall 2: Livestatus gives no error for bad commands
**What goes wrong:** `COMMAND` returns nothing; a nonexistent host or missing PING service silently does nothing, so "applied" is only "sent".
**How to avoid:** Ack means "sent" (failure only on socket errors after retries). Truth shows up in the next poll and in `admin/faked`. Do not claim confirmation in the ack text. Unmanaged switches may have no `PING` service; commands are best-effort per host.

### Pitfall 3: Faked-state detection false positives
**What goes wrong:** Hosts with active checks disabled by design (unmanaged nodes, user choice) appear "faked".
**How to avoid:** Add optional columns `active_checks_enabled` and `check_type` (hosts) and probe them with the existing `--check-columns` mechanism on the live site before relying on them. Candidate signal: host `active_checks_enabled == 0` AND `check_type == 1` (passive) AND the host's PING service `active_checks_enabled == 0` AND PING `check_type == 1`. These are Nagios-lineage Livestatus columns [ASSUMED]; Checkmk's docs page for the reference does not list column definitions (fetched, empty on this point). Admin-faked hosts always have both disabled by D-05, so requiring the PING service condition separates them from unmanaged hosts that never had a PING service. If the live probe shows false positives, use the fallback: poller-owned set, republished retained on `admin/faked` and rebuilt from the retained topic on restart (read it in `reconcile_state`'s subscribe barrier).

### Pitfall 4: Demo hosts and the "always UP" rule
Hosts from a `--demo` run have an "Always assume host to be up" rule; faking DOWN requires `DISABLE_HOST_CHECK` first (already D-05), and Restore on those hosts then yields UP again, not "real" state. Document in the admin UI help text.

### Pitfall 5: Passive-result translation and cascade
Faking a parent DOWN does not change children by itself (runbook note, live-verified 2026-09-26), which is why the poller must send UNREACHABLE to descendants explicitly. Unverified: whether Checkmk core translates passive host results to UNREACHABLE itself; tests against the live site are required in UAT.

### Pitfall 6: Side effects the user declined to warn about
Faked DOWN triggers real Checkmk notifications, writes ClickHouse history, feeds availability rollups/Grafana and `lan/events/recent`. D-14 declines a dialog warning; surface in the plan's docs and consider an open question about excluding faked hosts from rollups (out of scope unless the user asks). [VERIFIED: codebase, `write_history` runs every cycle]

### Pitfall 7: Credential and nginx quoting
`ADMIN_WS_PASSWORD` is pasted into an nginx string literal and JSON: same character restriction as `WS_PASSWORD` (no quotes, backslash, `$`, braces, `;`, whitespace). `init-env.sh`'s URL-safe generator satisfies it. Add the variable to the dashboard service environment or envsubst leaves `${ADMIN_WS_PASSWORD}` unsubstituted (the nginx file header documents this). `/admin-config.json` must be an exact-match `=` location, `Cache-Control: no-store`.

### Pitfall 8: Existing deployments
`init-env.sh` never overwrites set values and compose uses `${VAR:?run deploy/init-env.sh}`; existing installs must re-run `init-env.sh` before `compose up`, or the mosquitto and dashboard containers refuse to start. Call this out in docs and the runbook.

## Code Examples

### ACL addition
```
# deploy/mosquitto.acl  (default-deny; admin topics live outside lan/)
user wsadmin
topic read lan/#
topic read admin/ack
topic read admin/faked
topic write admin/cmd
```

### nginx location
```
location = /admin-config.json {
    default_type application/json;
    add_header Cache-Control "no-store" always;
    return 200 '{"wsUsername":"${ADMIN_WS_USERNAME}","wsPassword":"${ADMIN_WS_PASSWORD}"}';
}
```
(`ADMIN_WS_USERNAME` defaults to `wsadmin` in compose, like `WS_USERNAME`.)

### Poller validation sketch
```python
ACTIONS = {"up", "down", "unreach", "restore", "restore_all"}
def parse_admin_command(payload: bytes, known_ids: set[str]) -> dict | None:
    # returns None on malformed JSON / unknown action; filters hosts to known_ids only
```

## Inferred switch card with faked children (D-03)

`compute_incidents` is a pure function over `DeviceSnapshot`s; faked results arrive as ordinary Livestatus state, so no engine change is needed. Tests (in `tests/test_mqtt_poller.py`, beside `test_compute_incidents_unmanaged_switch_promoted_as_inferred_root_when_sibling_also_down`, line ~319): unmanaged switch `host_state_raw="UP"`, two children with `host_state_raw="DOWN"` -> one incident, `inferred is True`, `root` = switch, both children in `not_observable`; one child alone -> plain root (no inferred card); child DOWN plus a managed-parent DOWN above the switch (nesting); faked UNREACHABLE grandchildren. Also add a test that the cascade helper stops at the unmanaged switch. UI side: confirm the dashboard's incident/tree/map rendering shows the combined card from the inferred incident payload (existing `IncidentList`/`TopologyMap` tests already cover `inferred`; add one admin-flow level check only if cheap).

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Manual `fakeping` shell helper per host | Poller executes same sequence from MQTT command | Same commands, multi-host, cascade, no podman exec |
| GUI "Fake check results" | Disabling checks first then passive results | GUI fake is overwritten by next real check (runbook) |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Hosts/services tables expose `active_checks_enabled` and `check_type` on Checkmk 2.4 CRE | Pitfall 3 | Detection impossible; use poller-owned set fallback |
| A2 | `params.event.srcEvent.ctrlKey` is how vis-network click exposes modifiers (alternatively `interaction.multiselect`) | Pattern 5 | Ctrl-click not detected; switch to `multiselect` option or a DOM-level keydown tracker |
| A3 | Mosquitto ACL entry `topic write admin/cmd` also prevents wsadmin writing elsewhere (default-deny per header comment) | ACL | wsadmin gains extra write; verify via `scripts/smoke_test_broker.py`-style live check |
| A4 | Core does not auto-translate a passive DOWN to UNREACHABLE for children | Pitfall 5 | Cascade double-applies harmlessly; UAT must confirm |
| A5 | A single admin connection reading `lan/#` is acceptable under D-06 | Alternatives | Needs user confirmation (Open Question 1) |

## Open Questions

1. **Does `wsadmin` read `lan/#`?** D-06 says "read only the admin-only topics", but the admin page needs the normal data. Recommendation: grant `read lan/#` too (it can still never write there) and use one connection; confirm with the user. Alternative: two connections.
2. **Does DOWN on a managed parent cascade UNREACHABLE onto an unmanaged switch child itself?** D-02 says the cascade does not walk *through* it. Recommendation: the switch itself is a host Checkmk can see, so mark it UNREACHABLE but stop there; confirm.
3. **Folder semantics:** selecting a folder includes subfolders? Recommendation: all hosts whose folder path equals or is under it; resolved in the browser.
4. **Faked hosts in history/rollups:** leave as-is (indistinguishable from real failures, matching the demo goal) unless the user wants exclusion.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| podman / live stack | Live column probe, UAT | No (not on this machine in this session) | — | Run probe on the deploy host: `podman exec mqtt-poller python /scripts/mqtt_poller.py --check-columns` after adding the columns |
| node + npm | Dashboard build/tests | Yes (ctx7 under node v24.20) | v24 | — |
| uv / pytest | Poller tests | Yes (project convention) | — | — |

**Missing with no fallback:** none for planning; the live verification of A1/A4 must be a human-verify step in UAT.

## Validation Architecture

Skipped: `workflow.nyquist_validation` is `false` in `.planning/config.json`. Practical commands for plans: `uv run pytest tests/test_mqtt_poller.py -x` and, in `dashboard-react/`, `npm run test`, `npm run typecheck`, `npm run lint`.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Broker password for `wsadmin` generated by `init-env.sh`; accepted-risk open `/admin-config.json` (D-07) |
| V3 Session Management | no | Stateless MQTT credentials |
| V4 Access Control | yes | Mosquitto ACL write only on `admin/cmd`; wsreader unchanged |
| V5 Input Validation | yes | Poller validates JSON shape, action enum, host ids against known snapshots; reject `;`, `'`, CR/LF in anything interpolated |
| V6 Cryptography | no | No new crypto; broker credentials are plaintext over the closed network (existing posture) |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Livestatus command injection via host/output text | Tampering | Only snapshot-sourced ids and poller-built text; sanitize ip/output |
| Unauthorized faking by anyone reaching `/admin-config.json` | Elevation of privilege | Accepted for closed demo network (D-07); document |
| Replay of retained/duplicate commands | Tampering | `retain=false`, drop retained deliveries, dedupe ids |
| Command flood via `admin/cmd` | DoS | Cap hosts per command and queue length |
| Admin credential leaking into normal `/config.json` | Info disclosure | Separate location, exact match, only fetched with `?admin=1` |

## Sources

### Primary (HIGH)
- Codebase: `scripts/mqtt_poller.py` (compute_incidents, _reachable_roots_from, build_mqtt_client, reconcile_state, run_forever), `src/checkmk_wizard/wizard.py` (`_fake_demo_hosts_up`), `src/checkmk_wizard/livestatus.py` (`send_commands`), `deploy/{mosquitto.acl,mosquitto.conf,compose.yaml,dashboard-nginx.conf,init-env.sh}`, `dashboard-react/src/{lib/runtimeConfig.ts,store/mqttClient.ts,components/TopologyMap.tsx,TreeNode.tsx}`
- `docs/Incident demo with fake check results.md` (live-verified command sequence)
- Context7 `/visjs/vis-network` (click event exposes original `event`)

### Secondary (MEDIUM)
- docs.checkmk.com Livestatus references page: lists commands, no column definitions (does not confirm A1)

### Tertiary (LOW)
- Training knowledge for Nagios `check_type`/`active_checks_enabled` columns (A1) and vis-network `srcEvent` (A2)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH, no new dependencies
- Architecture: HIGH for MQTT/poller/nginx seams, MEDIUM for UI hooks
- Pitfalls: MEDIUM, faked detection and cascade translation unverified live

**Research date:** 2026-10-02
**Valid until:** 2026-10-30
