# Phase 16: Dashboard admin mode for live demos - Context

**Gathered:** 2026-10-02
**Status:** Ready for planning

<domain>
## Phase Boundary

An admin mode (`?admin=1`) on the React dashboard lets an operator ctrl+click multi-select hosts in the
topology map, the device tree, or a whole folder, then send a fake UP / DOWN / UNREACHABLE ping result
(host + its PING service, realistic check_icmp-style output) so every other, non-admin dashboard shows
those states live. Purpose: live management demos of a real-looking site.

Commands travel from the browser over MQTT to the poller, which turns them into Livestatus external
commands. No new server-side application: the poller, the broker and the dashboard's nginx are the only
moving parts. An unmanaged switch whose children are faked DOWN must still render the combined inferred
switch card with its children listed below, as on a real site.

</domain>

<decisions>
## Implementation Decisions

### Fake-state semantics
- **D-01:** DOWN on a **managed** parent auto-cascades **UNREACHABLE** to every descendant, matching real
  Checkmk. UP / Restore reverses the cascade. (User chose "Auto-cascade UNREACHABLE".)
- **D-02:** The cascade must **not** walk through an unmanaged switch (`unmanaged_switch` label): Checkmk
  cannot see past it, so hosts behind it are DOWN, not UNREACHABLE. Descendants behind an unmanaged switch
  are only faked when selected explicitly. (Clarified 2026-10-02 by user: the unmanaged switch itself IS marked
  UNREACHABLE when its managed parent is faked DOWN, and the cascade stops there.)
- **D-03:** **No special action on an unmanaged switch itself.** The operator selects the switch's children
  and sends DOWN to them; the existing inferred-root rule in `compute_incidents` (an unmanaged host with
  >= 2 non-OK children, at least one DOWN) must then produce the combined switch card with the children
  listed. The user's requirement is that this keeps working with faked states; it needs tests with faked
  DOWN children, not a new rule. (One faked child alone stays a plain root, by design.)
- **D-04:** Each fake sets host AND the host's `PING` service together: UP = host 0 / PING 0 with
  `OK - <ip> rta <random 0.2-3.0>ms lost 0%`; DOWN = host 1 / PING 2 with
  `CRITICAL - <ip>: rta nan, lost 100%`; UNREACHABLE = host 2 / PING 2 with the same CRITICAL text. The
  poller builds the text (same style as the wizard's `--demo`), never the browser. Output must not contain
  `;` or a single quote.
- **D-05:** Before injecting, the poller sends `DISABLE_HOST_CHECK` and `DISABLE_SVC_CHECK;<host>;PING` so
  nothing (including the demo "Always assume host to be up" rule) overwrites the fake. Restore sends
  `ENABLE_HOST_CHECK` / `ENABLE_SVC_CHECK`.

### Broker credential and ACL
- **D-06:** A new broker user (working name `wsadmin`, password `ADMIN_WS_PASSWORD` generated into
  `deploy/.env` by `deploy/init-env.sh`, like `WS_PASSWORD`) may publish **only** on the admin command
  topic and read only the admin-only topics **plus `lan/#`** (amended 2026-10-02 by user during plan-phase:
  the admin page uses a single MQTT connection and needs the normal host data; wsadmin still cannot write
  `lan/#`). `wsreader` (read-only `lan/#`) is unchanged.
- **D-07:** The admin login is delivered by a **separate `/admin-config.json`** rendered by the dashboard's
  nginx, **open** (no source-network restriction, user's choice for a closed demo network). The page fetches
  it only when `?admin=1` is present. The normal `/config.json` stays read-only. Security note carried
  forward: anyone who can reach the dashboard and knows the path can fake hosts; acceptable only on the
  closed demo network.
- **D-08:** The poller acknowledges every command on an **admin-only ack topic** (applied, or failed with a
  short reason such as Livestatus unreachable); the admin bar shows the result.
- **D-09:** Admin topics live **outside `lan/`** (so `wsreader`'s `lan/#` never matches them), e.g.
  `admin/cmd`, `admin/ack`, `admin/faked`. The `poller` user already has `readwrite #`.

### Persistence and restore
- **D-10:** "Which hosts are faked" is **derived by the poller from Livestatus** (active checks disabled
  with a passive result) and published retained on an **admin-only topic** (`admin/faked`). Non-admin
  dashboards never see it. It survives poller and stack restarts because Checkmk itself holds the state.
- **D-11:** A fake lasts **until restored**; no auto-expire. The admin bar offers Restore selected and
  Restore all.
- **D-12:** Faked hosts are marked in the admin view only (badge or similar); non-admin dashboards are
  indistinguishable from a real failure.

### Safety
- **D-13:** Admin mode may fake **any** host. Every action goes through a **confirm dialog** that lists the
  action and the exact hosts (count and names) before anything is sent.
- **D-14:** While admin mode is active, the admin page shows a persistent banner ("ADMIN MODE - N hosts
  faked"), admin view only. **Banner only**: no notification warning in the confirm dialog (user's choice).

### Claude's Discretion
- Exact topic names, payload JSON shape, and command-id/ack correlation.
- Selection UX details beyond "ctrl+click toggles selection": folder selection control in the tree, action
  bar placement, keyboard shortcuts, how a selection is cleared.
- How the poller maps a selected folder to its hosts, and the cascade traversal (cycle-guarded, like
  `compute_incidents`).
- Whether the admin dashboard keeps topology edit mode separate from admin mode (they must not conflict).
- How the poller reliably identifies "faked" in Livestatus without false positives for hosts whose checks
  are disabled by design (e.g. unmanaged nodes): research must verify the columns; if no reliable signal
  exists, fall back to a poller-owned retained set while keeping the admin-only topic.

- **D-17:** (2026-10-02, user) Folder checkbox includes all subfolders; resolved in the browser, re-validated by the poller.
- **D-18:** (2026-10-02) Faked hosts flow into history/rollups like real failures (matches the demo goal; no exclusion).
</decisions>

<specifics>
## Specific Ideas

- "I want to be able to do a demo of a real site to our management": a second, normal dashboard must
  show what the admin dashboard sends.
- The wizard's `--demo` already fakes hosts UP with realistic ping output (random rta per host) and an
  "Always assume host to be up" rule (`_fake_demo_hosts_up`, `_create_demo_host_check_rule`); admin mode
  must be compatible with those demo hosts and reuse the same output style.
- `docs/Incident demo with fake check results.md` and its `fakeping` helper show the manual Livestatus
  command sequence that admin mode automates.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project constraints
- `CLAUDE.md` - "No new backend for the dashboard" and "Container boundary" constraints: the poller may use
  Livestatus-over-TCP and the REST API only; no filesystem access to the `checkmk` container.
- `.planning/ROADMAP.md` - Phase 16 entry.

### Incident engine and inferred switch card
- `scripts/mqtt_poller.py` - `compute_incidents` (inferred roots: unmanaged host with >= 2 non-OK children,
  at least one DOWN), `UNMANAGED_SWITCH_LABEL`, `services_signature` (output republish rule fixed 2026-10-02).
- `.planning/phases/14-fleet-intelligence/14-CONTEXT.md` - D-04 (no overclaiming "confirmed down"), D-10/D-11
  (incident grouping and inferred roots), D-15 (dependent criticality tier).
- `.planning/phases/13-wizard-parents-support-and-topology-map/13-CONTEXT.md` - unmanaged switch ("Add Node")
  and parents model.
- `.planning/todos/pending/2026-09-28-revisit-criticality-and-dependency-model.md` - related open todo
  (criticality/dependency model); reviewed, not folded.

### Faking mechanics
- `src/checkmk_wizard/wizard.py` - `_fake_demo_hosts_up`, `_create_demo_host_check_rule` (command sequence,
  random rta, `;`-free output, retry on core reload).
- `src/checkmk_wizard/livestatus.py` - `send_commands` (one connection per command, rejects CR/LF).
- `docs/Incident demo with fake check results.md` - manual runbook and `fakeping` helper.

### Broker, nginx and dashboard
- `deploy/mosquitto.conf`, `deploy/mosquitto.acl` - listeners, default-deny ACL (`poller` readwrite `#`,
  `wsreader` read `lan/#`).
- `deploy/compose.yaml` - mosquitto password provisioning from env, poller env, dashboard env.
- `deploy/dashboard-nginx.conf` - `location = /config.json` (renders `WS_USERNAME`/`WS_PASSWORD`).
- `deploy/init-env.sh` - generates secrets into `deploy/.env`.
- `dashboard-react/src/lib/runtimeConfig.ts`, `dashboard-react/src/lib/mqttClient.ts` - how the browser gets
  its login and connects.
- `dashboard-react/src/routes/IndexRoute.tsx`, `dashboard-react/src/components/TopologyMap.tsx`,
  `Tree.tsx`, `TreeNode.tsx`, `ThreePaneLayout.tsx` - map/tree selection surfaces and the layout.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `livestatus.send_commands` and the wizard's command sequence: the poller is a standalone script and cannot
  import `src/checkmk_wizard`, so it needs its own small helper with the same one-connection-per-command rule.
- `compute_incidents`, `_reachable_roots_from` (cycle-guarded parent walk): reuse the walk for the cascade.
- Existing `lan/#` MQTT topics, retained publishing helpers and startup/state handling in the poller.
- Right-column pane pattern in `ThreePaneLayout.tsx` and the topology map's existing selection state
  (`onSelectHost`, `selectedHost`).

### Established Patterns
- The browser has a read-only login from `/config.json`; secrets live in `deploy/.env` and are rendered by
  nginx (`envsubst`). Single-container restarts break Checkmk egress: use full down/up after changes.
- Best-effort Livestatus writes retried across core reloads; failures never fatal.
- Output text in the poller republish signature: only empty vs non-empty is tracked.

### Integration Points
- New: poller subscribes to `admin/cmd` (needs MQTT subscription handling in a loop that today mainly
  publishes), publishes `admin/ack` and `admin/faked`.
- New: broker ACL entry and password for the admin user; `init-env.sh`, `compose.yaml` and the nginx
  `/admin-config.json` location.
- New: dashboard admin mode (`?admin=1`): ctrl+click selection in map and tree, folder selection, action bar,
  confirm dialog, banner, faked badge; second MQTT connection (or credential switch) with the admin login.

</code_context>

<deferred>
## Deferred Ideas

- Auto-expiry of fakes after N minutes: not wanted now ("until restored").
- Source-network restriction (`ADMIN_ALLOW_CIDR`) for `/admin-config.json`: declined for this closed demo
  network; revisit if the dashboard is ever reachable from untrusted networks.
- Notification warning in the confirm dialog: declined; banner only.
- Criticality/dependency model rework (todo 2026-09-28): separate decision, not folded.

</deferred>

---

*Phase: 16-dashboard-admin-mode-for-live-demos*
*Context gathered: 2026-10-02*
