---
phase: 16-dashboard-admin-mode-fake-host-up-down-for-live-demos-admin-
reviewed: 2026-10-02T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - scripts/mqtt_poller.py
  - deploy/mosquitto.acl
  - deploy/compose.yaml
  - deploy/dashboard-nginx.conf
  - deploy/init-env.sh
  - dashboard-react/src/store/adminStore.ts
  - dashboard-react/src/store/mqttClient.ts
  - dashboard-react/src/lib/adminMode.ts
  - dashboard-react/src/lib/runtimeConfig.ts
  - dashboard-react/src/main.tsx
  - dashboard-react/src/components/AdminBar.tsx
  - dashboard-react/src/routes/IndexRoute.tsx
findings:
  critical: 0
  warning: 6
  info: 3
  total: 9
status: issues_found
---

# Phase 16: Code Review Report

**Depth:** standard. Tree, TopologyMap, TreeNode and smoke_test_broker.py were only skimmed and are not covered by the findings below.

## Summary

The Livestatus injection defence holds. Host ids are checked three times (`parse_admin_command`, the snapshot lookup, `build_admin_commands`). `_admin_guard` rejects CR, LF and `'`, and `send_livestatus_commands` rejects CR and LF again. The stale-replay guard (`retained` flag, clean paho session, seen-id deque touched only from paho's thread) is sound. The ACL grants are minimal. No blocker was found. The weaknesses are the open credential endpoint (accepted by the user but worth recording), a race on the ledger, regex `$` anchoring, and an unhandled throw in the browser.

## Warnings

### WR-01: `/admin-config.json` hands a write-capable broker credential to anyone who can reach the dashboard
**File:** `deploy/dashboard-nginx.conf:73-84` (also `deploy/mosquitto.acl:15-24`)
**Issue:** The location is deliberately open, so any LAN client can GET the `wsadmin` password and publish `admin/cmd`. That can disable host checks and inject fake results for ANY host in the snapshot, not only demo hosts. It also contradicts the CLAUDE.md constraint that "the browser holds no secret" for the topology_editor credential. The endpoint is gated only by knowing the path, and `?admin=1` adds no security. Anyone who can reach the dashboard port can read the password. If port 9001 (WS) is published, they can also use it directly. The user accepted this for a closed demo network, so it stays a WARNING. The risk is that the poller will fake real production hosts if the stack is ever pointed at a real site, because there is no demo-only restriction.
**Fix:** Add `allow <cidr>; deny all;` driven by an `ADMIN_ALLOW_CIDR` env var (default loopback or private ranges). Optionally restrict the poller to hosts carrying a demo tag or label. Document in CLAUDE.md that this is an intentional exception.

### WR-02: Ledger lost-update race between the poll thread and the admin worker
**File:** `scripts/mqtt_poller.py:1488-1510`, `1455-1463`
**Issue:** `refresh_admin_faked` runs on both the poll-loop thread (line 4509) and the worker thread (line 1658). In ledger mode it does `faked = context.faked()`, prunes, then `context.set_faked(pruned)`. If the worker's `apply_ledger` runs between the read and the write, the poll thread overwrites the ledger with a stale copy and the just-applied fake is lost. The keepalive then stops refreshing that host, and `admin/faked` is wrong. Only the fallback path (no `active_checks_enabled` column) is affected. Separately, `should_publish` decides under the lock but `publish_admin_faked` runs outside it. Two threads can therefore publish out of order and leave a stale retained `admin/faked`.
**Fix:** Make prune-and-publish one atomic operation on `AdminContext` (a `prune_ledger(known)` method done under the lock). Serialize publish with a separate publish lock, or send the whole refresh through the worker thread.

### WR-03: `$`-anchored regexes accept a trailing newline
**File:** `scripts/mqtt_poller.py:170` (`_HOST_ID_RE`), `1077`, `1081`
**Issue:** `re.match(r"^...$")` also matches `"abc\n"`. `parse_admin_command` therefore admits a host id or command id with a trailing LF. The later snapshot lookup and `_admin_guard` stop it from reaching Livestatus, so this is not exploitable today. The same flaw in `_ADMIN_SAFE_ADDRESS_RE` is reachable, though: an `address` of `"10.0.0.1\n"` passes, is interpolated into the plugin output, and `_admin_guard` then raises `ValueError`. `process_one` has no handler for it, so `_handle` reports a generic "internal error" and the whole batch is dropped, including the other hosts. The command-id regex accepts an id with a trailing newline, and that id is echoed into the ack.
**Fix:** Use `re.fullmatch` or `\Z` for all three regexes. In `build_admin_commands`, catch `ValueError` per action and report that host as skipped.

### WR-04: One bad host aborts the entire admin batch with "internal error"
**File:** `scripts/mqtt_poller.py:1631-1633`
**Issue:** `build_admin_commands` raises `ValueError` for any unsafe address or host. This is not caught per action. A single odd host out of up to 200 turns the whole command into `{"ok": false, "detail": "internal error"}`. The operator learns nothing about which host caused it.
**Fix:** Build per action inside try/except `ValueError`, append the host to `skipped`, and continue with the remaining actions.

### WR-05: `publishAdminCommand` can throw from a click handler
**File:** `dashboard-react/src/store/mqttClient.ts:143-151`, `dashboard-react/src/components/AdminBar.tsx:233`, `dashboard-react/src/lib/adminMode.ts:108-111`
**Issue:** `buildAdminCommand` throws when more than 200 hosts are selected, and "Select all" selects every visible host. On a fleet larger than 200, `confirm()` raises an uncaught exception inside the React event handler. The dialog stays open with no feedback and no waiting state. The poller enforces the same 200 cap, so the cap is not the problem, but the UI never chunks or reports it.
**Fix:** In `confirm()`, wrap the call in try/catch and show a danger feedback message. Better, disable the action buttons or warn in the dialog when the host count exceeds `ADMIN_MAX_HOSTS`, or split the command into 200-host chunks.

### WR-06: Keepalive re-injects results for hosts whose checks an operator disabled for other reasons
**File:** `scripts/mqtt_poller.py:1391-1424`, `1683-1736`
**Issue:** The docstring admits that hosts with operator-disabled checks are counted as "faked". The keepalive then writes synthetic host and PING results onto them every 30 s, masking a real DOWN. In ledger mode the opposite risk exists: a restore that fails after the ledger is updated cannot be corrected. In `process_one`, `apply_ledger` runs only after a successful send, so the ledger is not wrong here. The limitation is documented only in the docstring, not in the UI.
**Fix:** Keep a poller-owned set of the hosts it has faked, persisted in the `admin/faked` retained payload, and restrict the keepalive to that set.

## Info

### IN-01: `_admin_children_map` / `_admin_descendants` use `list.pop(0)` and a local named `queue` that shadows the imported `queue` module
**File:** `scripts/mqtt_poller.py:1157`, `1182`
**Issue:** The local variable `queue` shadows `import queue` inside those two functions. It is harmless today, but a later use of `queue.Queue` in them would break.
**Fix:** Rename the local to `pending` and use `collections.deque`.

### IN-02: Dead branch in `parse_admin_command`
**File:** `scripts/mqtt_poller.py:1127-1128`
**Issue:** `if action == "restore_all" and not hosts: hosts = []` exists only to bypass the `isinstance(hosts, list)` check. A `restore_all` with `hosts: "garbage"` is rejected as "invalid host list" even though the hosts are documented as ignored. This is inconsistent.
**Fix:** Handle `restore_all` before the hosts validation and return immediately.

### IN-03: Magic numbers and the ID generator
**File:** `dashboard-react/src/lib/adminMode.ts:79-81`, `dashboard-react/src/components/AdminBar.tsx:6000-ish (setTimeout 6000, ACK_TIMEOUT_MS 15000)`
**Issue:** `newCommandId` uses `Math.random`. That is acceptable because the id is a correlation token only, but the 6000 ms snackbar timeout is an unnamed constant. The 15 s ack timeout is shorter than the poller's worst-case latency: retries of 3+5+10 s plus the 2 s refresh delay plus queued commands. Slow but successful commands can therefore show "No answer from the poller" and then be ignored when the ack arrives late.
**Fix:** Raise `ACK_TIMEOUT_MS` to at least 30 s, or have the poller send an early "accepted" ack. Name the snackbar constant.

---

_Reviewed: 2026-10-02_
_Reviewer: Claude (bm-code-reviewer)_
_Depth: standard_
