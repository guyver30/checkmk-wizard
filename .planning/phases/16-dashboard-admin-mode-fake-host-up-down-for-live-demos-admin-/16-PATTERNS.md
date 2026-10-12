# Phase 16: Dashboard admin mode for live demos - Pattern Map

**Mapped:** 2026-10-02
**Files analyzed:** 14 new/modified
**Analogs found:** 13 / 14 (conventions derivation skipped, see Conventions)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `scripts/mqtt_poller.py` (admin section: topics, parse/validate, cascade, command builder, send, worker, faked derivation) | service | event-driven + request-response | same file: `_reachable_roots_from`, `compute_incidents`, `_livestatus_request`, `_publish_json`, `build_mqtt_client`, `reconcile_state`; `src/checkmk_wizard/livestatus.py::send_commands`; `wizard.py::_fake_demo_hosts_up` | exact (same module) |
| `tests/test_mqtt_poller.py` (+ cascade, builder, validation, inferred-switch tests) | test | transform | same file, `test_compute_incidents_unmanaged_switch_*` (line 319), `_snapshot` (3063), `_make_message` (2949) | exact |
| `deploy/mosquitto.acl` (+ `wsadmin`) | config | request-response | same file, `user wsreader` block | exact |
| `deploy/compose.yaml` (mosquitto passwd line, mosquitto env, dashboard env) | config | batch | same file lines 108-109, 70, 464-465 | exact |
| `deploy/dashboard-nginx.conf` (+ `location = /admin-config.json`) | config | request-response | same file, `location = /config.json` | exact |
| `deploy/init-env.sh`, `deploy/.env.example` (+ `ADMIN_WS_PASSWORD`) | config | batch | same files, `WS_PASSWORD` entries | exact |
| `dashboard-react/src/lib/adminMode.ts` (detect `?admin=1`, fetch admin config, payload builders) | utility | request-response | `dashboard-react/src/lib/runtimeConfig.ts` | exact |
| `dashboard-react/src/main.tsx` (admin flag + config before mount) | config | request-response | itself (`loadRuntimeConfig().then(render)`) | exact |
| `dashboard-react/src/store/mqttClient.ts` (+ admin topics, `publishAdminCommand`) | service | pub-sub | itself | exact |
| `dashboard-react/src/store/adminStore.ts` (or slice of `useAppStore`) | store | event-driven | `dashboard-react/src/store/useAppStore.ts` (not read; zustand store) | role-match |
| `dashboard-react/src/components/AdminBar.tsx` (bar, confirm dialog, banner) | component | request-response | `TopologyToolbar.tsx`, `ConnectionIndicator.tsx` (not read) | role-match |
| `dashboard-react/src/components/TopologyMap.tsx` (ctrl+click toggle) | component | event-driven | itself, `network.on("click")` ~456 | exact |
| `dashboard-react/src/components/TreeNode.tsx` / `Tree.tsx` (ctrl+click rows, folder select) | component | event-driven | itself | exact |
| `dashboard-react/src/routes/IndexRoute.tsx` (mutual exclusion with edit mode) | route | event-driven | itself (edit mode wiring, not read) | exact |
| `dashboard-react/src/test/fakeVisNetwork.ts` (modifier info in click) | test | event-driven | itself | exact |

## Pattern Assignments

### `scripts/mqtt_poller.py` admin section (service, event-driven)

**Analog:** the same module plus `src/checkmk_wizard/livestatus.py` and `wizard.py`. The poller cannot import `src/checkmk_wizard`, so copy the idioms.

**Topic constants** (module top, near lines 113-115):
```python
TOPIC_TOPOLOGY = "lan/devices/topology"
TOPIC_EVENTS = "lan/events/recent"
TOPIC_POLLER_STATUS = "lan/poller/status"
```
Add `TOPIC_ADMIN_CMD = "admin/cmd"`, `TOPIC_ADMIN_ACK = "admin/ack"`, `TOPIC_ADMIN_FAKED = "admin/faked"` (outside `lan/`). Reuse `_HOST_ID_RE = re.compile(r"^[-0-9a-zA-Z_.]+$")` (line 162) for host-id validation.

**Cycle-guarded graph walk to copy for the cascade** (`_reachable_roots_from`, lines 812-848): build `children` from `snapshot.parents`, BFS with a `visited` set; do not expand past a node whose `unmanaged` is True (D-02):
```python
visited: set[str] = set()
frontier = [parent_id for parent_id in by_id[start_id].parents if parent_id in by_id]
while frontier:
    candidate = frontier.pop()
    if candidate in visited:
        continue
    visited.add(candidate)
    ...
    frontier.extend(parent_id for parent_id in by_id[candidate].parents if parent_id in by_id)
```

**Livestatus send-only twin** (copy rule from `livestatus.py::send_commands` lines 70-90, and transport/error idiom from `_livestatus_request` lines 1292-1314, which raises `LivestatusError` from `(TimeoutError, OSError)`):
```python
for command in commands:
    if "\n" in command or "\r" in command:
        raise ValueError(...)
for command in commands:
    payload = f"COMMAND [{int(time.time())}] {command}\n\n"
    with socket.create_connection((host, port), timeout=10) as sock:
        sock.sendall(payload.encode())
        sock.shutdown(socket.SHUT_WR)
```
One connection per command is load-bearing. Wrap OSError into `LivestatusError`.

**Command sequence and text** (`wizard.py::_fake_demo_hosts_up` lines 3101-3112; retry loop 3113-3125 over `_LIVESTATUS_RETRY_DELAYS_SECONDS`, best-effort, never fatal):
```python
output = f"OK - {h.ip} rta {random.uniform(0.2, 3.0):.3f}ms lost 0%"
commands += [
    f"DISABLE_HOST_CHECK;{h.hostname}",
    f"PROCESS_HOST_CHECK_RESULT;{h.hostname};0;{output}",
    f"DISABLE_SVC_CHECK;{h.hostname};PING",
    f"PROCESS_SERVICE_CHECK_RESULT;{h.hostname};PING;0;{output}",
]
```
Per D-04/D-05: DISABLE first, then results; DOWN host 1 / PING 2, UNREACH host 2 / PING 2, text `CRITICAL - {ip}: rta nan, lost 100%`; restore uses `ENABLE_HOST_CHECK;h` and `ENABLE_SVC_CHECK;h;PING`. Reject `;`, `'`, CR/LF in `ip` (fallback to host id from snapshot, never browser strings).

**MQTT client / subscribe seam** (`build_mqtt_client`, lines 2783-2790). Today `on_connect` only publishes birth; add `client.subscribe(TOPIC_ADMIN_CMD, qos=1)` there (a clean-session reconnect loses subscriptions) and `client.on_message`:
```python
def on_connect(client, userdata, flags, reason_code, properties=None):
    publish_device_status... / publish_poller_status(client, since=utc_now_iso(), last_poll=None, device_count=0)
client.on_connect = on_connect
client.reconnect_delay_set(min_delay=1, max_delay=120)
client.connect(config.mqtt_host, config.mqtt_port, keepalive=30)
client.loop_start()
```
`on_message` (paho thread) must only drop `msg.retain` messages, parse JSON, enqueue; a daemon worker thread does validation, cascade and Livestatus I/O. Snapshot access via a lock.

**Publish choke point** (`_publish_json`, lines 2794-2812): publish `admin/ack` (qos 1, retain False) and `admin/faked` (qos 1, retain True, on change only, like the topology signature approach `topology_signature`/`services_signature`) through this.

**Message-handler shape** (`reconcile_state` `on_message`, lines ~3270-3288): split `msg.topic.split("/")`, branch on parts, store `msg.payload`. Mirror for `admin/cmd`.

**Faked-set derivation:** add optional host/service columns via `OPTIONAL_HOST_COLUMNS` (line 258) / `OPTIONAL_SERVICE_COLUMNS` (line 300) and probe with `available_host_columns` (line 2432) / `--check-columns` before relying on them. If the live probe shows false positives, fall back to a poller-owned set re-read from retained `admin/faked`.

---

### `tests/test_mqtt_poller.py` additions (test, transform)

**Analog:** same file. Helpers `_snapshot(...)` (line 3063: `id_`, `state`, `parents`, `host_state_raw`, `unmanaged`, ...), `_make_message(topic, payload)` (2949), `_make_config(**overrides)` (2491); the module is loaded via `importlib` as `poller` (lines 11-20).

**Inferred switch pattern to copy for D-03 tests** (lines 319-334):
```python
snapshots = [
    _snapshot("um1", state="OK", host_state_raw="UP", unmanaged=True),
    _snapshot("gc1", host_state_raw="DOWN", parents=["um1"]),
    _snapshot("gc2", host_state_raw="UNREACH", parents=["um1"]),
]
incidents = poller.compute_incidents(snapshots)
assert len(incidents) == 1
assert incident["inferred"] is True
assert incident["not_observable"] == ["gc1", "gc2"]
```
Add: two DOWN children (confirm inferred card, note gc DOWN both); one child alone stays plain root (see `test_compute_incidents_lone_down_host_under_unmanaged_switch_is_its_own_incident`); managed DOWN above the switch; cascade stops at the unmanaged switch; command builder output has no `;`/`'`; unknown host ids filtered; retained message dropped; cycle in `parents` terminates. Mock Livestatus socket with `patch.object(poller, "socket")` style as used elsewhere (`patch.object(poller, "mqtt")` at line ~2954).

---

### `deploy/mosquitto.acl` (config)

**Analog:** same file lines 9-13:
```
user poller
topic readwrite #

user wsreader
topic read lan/#
```
Add block (per RESEARCH):
```
user wsadmin
topic read lan/#
topic read admin/ack
topic read admin/faked
topic write admin/cmd
```
(`read lan/#` for wsadmin is Open Question 1; confirm with the user.) Default-deny header comment already documents semantics.

### `deploy/compose.yaml` (config)

**Analog:** mosquitto entrypoint (lines 108-109):
```
mosquitto_passwd -c -b /mosquitto/config/mosquitto.passwd poller "$$MQTT_POLLER_PASSWORD";
mosquitto_passwd -b /mosquitto/config/mosquitto.passwd wsreader "$$WS_PASSWORD";
```
Add `... wsadmin "$$ADMIN_WS_PASSWORD";` and `- ADMIN_WS_PASSWORD=${ADMIN_WS_PASSWORD:?run deploy/init-env.sh}` next to line 70 (mosquitto env). Dashboard env (lines 464-465):
```
- WS_USERNAME=${WS_USERNAME:-wsreader}
- WS_PASSWORD=${WS_PASSWORD:?run deploy/init-env.sh}
```
Add `ADMIN_WS_USERNAME=${ADMIN_WS_USERNAME:-wsadmin}` and `ADMIN_WS_PASSWORD=...` (envsubst only replaces env-defined names, see nginx header).

### `deploy/dashboard-nginx.conf` (config)

**Analog:** `location = /config.json` (exact-match, no-store):
```
location = /config.json {
    default_type application/json;
    add_header Cache-Control "no-store" always;
    return 200 '{"checkmkSite":"${CMK_SITE_ID}","wsUsername":"${WS_USERNAME}","wsPassword":"${WS_PASSWORD}"}';
}
```
Copy as `location = /admin-config.json` with `wsUsername`/`wsPassword` from `ADMIN_WS_*`. Update the header comment variable list. Same character restrictions as `WS_PASSWORD` (no quotes, backslash, `$`, braces, `;`, whitespace).

### `deploy/init-env.sh` and `deploy/.env.example`

**Analog:** `init-env.sh` header comment ("Generated: ... WS_PASSWORD") and the key loop (lines ~56-60):
```bash
for key in CMK_REST_SECRET TOPOLOGY_EDITOR_SECRET ... MQTT_POLLER_PASSWORD \
    WS_PASSWORD; do
```
Append `ADMIN_WS_PASSWORD` to the loop and the "Generated:" comment. In `.env.example` add `ADMIN_WS_PASSWORD=` beside `WS_PASSWORD=` (line 68), with an optional commented `# ADMIN_WS_USERNAME=wsadmin` like line 73. Existing installs must re-run `init-env.sh` (compose uses `:?`).

---

### `dashboard-react/src/lib/adminMode.ts` (utility, request-response)

**Analog:** `dashboard-react/src/lib/runtimeConfig.ts`.

**Fetch-with-defaults pattern** (lines 62-79; never rejects, 3 s abort, non-OK or non-JSON falls back):
```ts
export async function loadRuntimeConfig(fetchFn: typeof fetch = fetch): Promise<RuntimeConfig> {
  try {
    const response = await fetchFn("/config.json", { cache: "no-store", signal: AbortSignal.timeout(3000) });
    if (!response.ok) { current = { ...DEFAULTS }; return current; }
    const body: unknown = await response.json();
    current = parseRuntimeConfig(body);
  } catch { current = { ...DEFAULTS }; }
  return current;
}
```
Mirror as `loadAdminConfig()` fetching `/admin-config.json` only when `?admin=1`; validate with a `parse...` function like `parseRuntimeConfig` (lines 31-49), plus `__set...ForTests` helper (line 90). Admin is read once at module load from `location.search`, not from the router.

### `dashboard-react/src/main.tsx`

**Analog:** itself:
```tsx
void loadRuntimeConfig().then(() => { createRoot(...).render(<StrictMode><App /></StrictMode>); });
```
Chain admin config load after `loadRuntimeConfig()` and override `wsUsername`/`wsPassword` before mount (App's effect calls `connect()`).

### `dashboard-react/src/store/mqttClient.ts`

**Analog:** itself. Header rule: only this module touches the raw client. Extend `SUBSCRIBE_TOPICS` (lines 33-42) with `admin/ack`, `admin/faked` only in admin mode; connect options (lines 85-90) take username/password from `getRuntimeConfig()`; message routing at `client.on("message", ...)` -> `useAppStore.getState().handleMessage(topic, payload)`. Add exported `publishAdminCommand(cmd)` publishing JSON on `admin/cmd` with `{ qos: 1, retain: false }` through the module's `client`. Test reset via `__resetForTests` (line 140+).

### `dashboard-react/src/components/TopologyMap.tsx` (ctrl+click)

**Analog:** itself, click handler (lines 456-475):
```tsx
network.on("click", (params: { nodes: string[]; edges?: string[] }) => {
  const nodeId = params.nodes[0];
  if (editModeRef.current) { if (nodeId) onSelectHostRef.current?.(nodeId); return; }
  ...
```
Handler is registered once; read changing props through refs (`editModeRef`, `onSelectHostRef` pattern, lines 230-247). Add `adminModeRef` and an `onToggleSelect` ref; in admin mode a ctrl/meta click toggles selection (modifier via `params.event?.srcEvent?.ctrlKey || metaKey`, assumption A2, verify), plain click keeps navigating. Extend `params` type and `fakeVisNetwork.ts` to carry the event.

### `dashboard-react/src/components/TreeNode.tsx` / `Tree.tsx`

**Analog:** itself. The group row is a `<button onClick={() => onToggle(node.key)}>` (lines 41-46); add a folder "select all hosts" control as a sibling control (not nested in that button), and ctrl+click handling on device rows (the `<Link to hostHref>` rows in the `role="group"` branch). Folder-to-hosts from device `folder` fields. Use `Badge` from `kone-design-system` for the faked marker.

### `dashboard-react/src/components/AdminBar.tsx`

**Analog:** `TopologyToolbar.tsx` (action bar) and `ConnectionIndicator.tsx` (not read; planner should read both before writing). Use `kone-design-system` components and Tailwind tokens (`text-fg-*`, `bg-bg-*`). Includes confirm dialog listing action and exact hosts (D-13) and persistent banner "ADMIN MODE - N hosts faked" (D-14).

---

## Shared Patterns

### Single choke points
**Source:** `scripts/mqtt_poller.py::_publish_json` (2794), `_livestatus_request` (1292); `dashboard-react/src/store/mqttClient.ts`.
**Apply to:** every poller publish and Livestatus call; every browser publish. Normalize failures once; never let a transient failure kill the loop.

### Input validation against known ids
**Source:** `_HOST_ID_RE` (line 162), `is_publishable_device_id` (line 710).
**Apply to:** `admin/cmd` handling. Resolve each host against the poller's own snapshots; format Livestatus text only from snapshot ids/addresses; cap hosts per command and queue length; reject `;`, `'`, CR/LF.

### Best-effort with documented fallback contract
**Source:** `wizard.py::_fake_demo_hosts_up` docstring (3083-3100) and retry loop.
**Apply to:** the command worker. Ack means "sent"; failures ack `ok: false` with a short reason; Livestatus gives no error on bad commands (Pitfall 2). Docstrings state why and cite verification, per project convention.

### envsubst-rendered secrets
**Source:** `deploy/dashboard-nginx.conf` header + `compose.yaml` env lists.
**Apply to:** `ADMIN_WS_*`: any variable referenced in the template must be defined in the dashboard service environment.

### Full restart after ACL/password change
Use full `podman compose down && up` (project memory: single-container restart breaks Checkmk egress).

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| Poller inbound command handling (subscribe + worker thread + queue) | service | event-driven | The poller only publishes today and `reconcile_state`'s `on_message` is a short-lived collector. Use the `reconcile_state` handler shape plus a stdlib `queue.Queue`/`threading.Thread` worker per RESEARCH Pattern 2. |

## Conventions

Convention derivation was not run (derivation skipped: pattern-mapper used direct file reads only). Local style observed in the touched files:

| Axis | Dominant (observed) | Status |
|---|---|---|
| File-name casing | `snake_case.py` in `scripts/`, `tests/`; `PascalCase.tsx` components, `camelCase.ts` libs in `dashboard-react/src` | per-directory |
| Identifier casing | Python `snake_case` / `UPPER_SNAKE` constants, `_private` helpers; TS `camelCase` / `PascalCase` components | per-directory |
| Export style | Python module-level functions; TS named exports (no default, except `App`) | per-directory |
| Import style | Python `from __future__ import annotations`, stdlib then third party; TS relative imports with design-system imports first | per-directory |

**Contested hotspots (author's choice):** the CJS<->SDK dual resolver (`bin/lib/**` is CJS `module.exports`/`require`; `sdk/src/**` is ESM `export`/`import`) is the prototype intentional-contested split: each half is internally consistent per-directory, contested only repo-wide. Match the directory's local style. For this phase: poller edits follow `scripts/mqtt_poller.py` style; dashboard edits follow `dashboard-react/src` style.

## Metadata

**Analog search scope:** `scripts/`, `src/checkmk_wizard/`, `tests/test_mqtt_poller.py`, `deploy/`, `dashboard-react/src/{lib,store,components}`
**Files scanned:** ~12 read (targeted ranges)
**Pattern extraction date:** 2026-10-02
