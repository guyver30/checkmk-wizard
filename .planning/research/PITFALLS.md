# Pitfalls Research

**Domain:** Monitoring-to-MQTT bridge (Checkmk Livestatus poller + retained-message contract) and a static browser dashboard over MQTT-over-WebSockets, plus extending an existing Checkmk host-tag/onboarding schema
**Researched:** 2026-09-05
**Confidence:** MEDIUM-HIGH (MQTT/Mosquitto claims verified against community docs, GitHub issues, and the Mosquitto man page; Checkmk tag-group claims verified against official docs and Checkmk forum bug reports; some claims — e.g. exact behavior of `mosquitto.conf` websockets `bind_interface` support — are MEDIUM confidence and should be spot-checked against the installed Mosquitto version)

## Critical Pitfalls

### Pitfall 1: Stale retained state for decommissioned/renamed devices ("republish-only-on-change" has no tombstone)

**What goes wrong:**
The topology contract republishes `lan/devices/topology` only when topology changes, and per-device topics are keyed by host ID. If a host is deleted from Checkmk (decommissioned, renamed, or re-scanned under a different ID), nothing in the "republish only on change" design ever tells the broker "this device no longer exists." The old retained message for that device (and the old topology blob that still lists it) stays on the broker forever — every new dashboard subscriber, and every browser tab reconnecting, sees a device that hasn't existed for months as if it's still part of the network. This is the exact failure mode reported against zigbee2mqtt's own retained-availability design (Koenkk/zigbee2mqtt#30619): messages are only republished when the source device is present, so a permanently-removed device's last retained state is permanently "true."

**Why it happens:**
"Only publish on change" is attractive because it minimizes broker/network chatter, but it silently assumes the set of topics is monotonically growing. Nobody designs the "a topic should stop existing" case up front because it doesn't show up in day-one testing (you only ever add hosts during a demo).

**How to avoid:**
Every poll cycle, diff the *current* Livestatus host set against the *previously known* device-ID set (persisted across poller restarts — see Pitfall 2). For any device that disappears, publish an empty retained payload (`retain=True`, zero-length payload) to that device's `status`/`history` topics to clear them, and republish `lan/devices/topology` and `lan/events/recent` with the device removed. Treat "device removed" as a topology change, not just a status change.

**Warning signs:**
Dashboard shows devices that were deleted from Checkmk weeks ago; `mosquitto_sub -t 'lan/devices/#' -v --retained-only` lists topics for hosts no longer in `cmk-list-hosts`.

**Phase to address:**
Poller/publisher phase (the phase implementing the Livestatus-diff → MQTT publish loop) — the diff-and-tombstone logic must be part of the initial design, not a later patch, because retroactively clearing already-stale retained messages requires a one-time manual `mosquitto_pub -r -n` sweep.

---

### Pitfall 2: Poller restart loses "last known state," causing either silent desync or a full-blob republish storm

**What goes wrong:**
"Republish only on change" requires the poller to know what it last published, so it can diff against the current Livestatus snapshot. If that "last published" state lives only in the poller's process memory, a container restart (crash, `podman compose restart worker`, host reboot) wipes it. On restart the poller has two bad options if not designed for this: (a) assume nothing changed and stay silent, so if Checkmk's state *did* change during the outage window, the retained topics never catch up until the next unrelated change occurs — a form of permanent desync between Checkmk truth and MQTT retained state; or (b) treat every device as "changed" on first poll after restart and republish everything at once, producing a burst of retained publishes broker-side and a burst of merge-updates on every connected dashboard simultaneously (a self-inflicted thundering herd, distinct from the broker-reconnect herd in Pitfall 4).

**Why it happens:**
Change-detection state is easy to keep in a plain Python dict/set in the running process and easy to forget needs to survive restarts, especially since the existing wizard codebase already has a documented pattern of this exact gap (no resume/checkpoint state across phases — see `CONCERNS.md`).

**How to avoid:**
On every poll cycle, diff against Checkmk's actual current state as reported by Livestatus (not the poller's last-published memory) — this makes the poller naturally self-healing on restart, since Livestatus is always the source of truth. Only skip a publish if the *newly computed* value equals what MQTT already holds retained (query the broker's current retained value once at startup via a one-time subscribe, or persist a small local checkpoint file of last-published hashes). Either approach means restart behavior is "reconcile once, then resume only-on-change" rather than "blind full republish" or "blind silence."

**Warning signs:**
Dashboard state drifts from Checkmk's actual state after any worker-container restart; a manual full restart is needed after every deploy to force MQTT back in sync.

**Phase to address:**
Poller/publisher phase — decide the reconciliation strategy (startup diff against Livestatus, not against poller memory) before writing the "publish only on change" logic, since it changes the shape of the diffing function.

---

### Pitfall 3: Mosquitto restart silently discards all retained messages (persistence not enabled)

**What goes wrong:**
By default, Mosquitto keeps retained messages only in memory. Unless `persistence true` (and a writable `persistence_location`, ideally a mounted volume) is explicitly set in `mosquitto.conf`, a broker container restart — a Podman host reboot, an image update, an OOM kill — wipes every retained message instantly. Combined with Pitfall 1/2's "publish only on change" design, this means the dashboard shows nothing (or stale cached browser state) until every single device happens to change state again, which for stable network equipment (switches, routers) could be days.

**Why it happens:**
`persistence` defaults to off in stock `mosquitto.conf`; it's easy to stand up a working demo without it (in-memory retained messages work fine until the container restarts) and never notice the gap until a real outage.

**How to avoid:**
Set `persistence true`, an explicit `persistence_location` pointed at a named volume in `compose.yaml`, and a short `autosave_interval` (the 1800s/30-minute default means up to 30 minutes of retained-state loss on an unclean shutdown — set this to something like 60s given the low message volume expected here). Also verify container stop sends `SIGTERM` (which triggers Mosquitto's clean-exit save) rather than `SIGKILL` on `podman compose down`.

**Warning signs:**
Retained topics vanish after any `podman compose restart mosquitto`; `mosquitto.db` file doesn't exist or isn't growing under the persistence directory.

**Phase to address:**
Broker/infrastructure config phase (the `mosquitto.conf` WebSockets-listener change) — persistence should be part of the same config pass since it's a one-line settings gap that's invisible until the first real restart.

---

### Pitfall 4: Unauthenticated WebSocket listener on the LAN allows anyone to forge or clear retained state

**What goes wrong:**
The dashboard is explicitly "static HTML/CSS/JS only... no backend," meaning the browser must connect to Mosquitto's WebSocket listener directly with no server in between to hand out scoped credentials. The easy path is `allow_anonymous true` on that listener so the dashboard "just works" for any LAN device. But a WebSocket listener cannot be bound to loopback the way a Unix socket can — it is reachable by anything on the LAN's routed network — so an unauthenticated listener means *any* device on the LAN (a household IoT gadget, a compromised machine, a guest on the same Wi-Fi) can publish to the exact same topics the poller uses, including retained empty payloads that clear real device state, or garbage `status`/`history` payloads that corrupt what the dashboard renders. This is worse than a typical XSS-style read-only leak: MQTT's pub/sub model gives write access to the same topic space as read access by default.

**Why it happens:**
Authenticating a static, buildless frontend feels like it requires a backend (to avoid embedding credentials in JS served over the LAN), so teams default to `allow_anonymous true` "since it's just the LAN" and move on.

**How to avoid:**
Use Mosquitto's ACL file (`acl_file`) plus a dedicated `password_file`-based *read-only* user for the WebSocket listener, and enforce that ACL denies publish on all `lan/#` topics for that user (`topic read lan/#`, no `write`/`readwrite` entry). Yes, this means the dashboard's read-only credentials are visible in browser JS/network traffic — that's fine, since they grant no write capability. Keep the poller's publish credentials on a *separate* listener/port that is only reachable from the `cmk_net` container network (bind that listener to the container-internal interface, not the LAN-facing one), so publish credentials never need to reach a browser at all. Do not rely on "the dashboard code just doesn't publish anything" as the only safeguard — that's an application-layer assumption, not a broker-enforced one, and any other device on the LAN can trivially connect and publish once it discovers the open WS port.

**Warning signs:**
`mosquitto_pub -h <lan-ip> -p <ws-port> -t 'lan/devices/topology' -m '' -r` succeeds from an unrelated LAN device with no credentials.

**Phase to address:**
Broker/infrastructure config phase — ACLs and listener separation must exist before the dashboard phase ships, since retrofitting auth after the dashboard already assumes anonymous access means reworking both the Mosquitto config and the JS client's connect options together.

---

### Pitfall 5: Wildcard-subscription retained-message burst + synchronized reconnect storms on every dashboard load

**What goes wrong:**
Every dashboard page subscribes to wildcard topics like `lan/devices/+/status`, `lan/devices/+/history`, and `lan/events/recent`. On each subscribe, Mosquitto immediately delivers *every* matching retained message at once — for a home/small-office LAN this might be tens to a couple hundred devices, which is manageable, but if the "exponential-backoff reconnect" logic (already planned per `PROJECT.md`) doesn't add jitter, a broker restart causes every open browser tab/kiosk display to reconnect and re-subscribe at the *same* backoff intervals simultaneously, hitting the broker with synchronized wildcard-resubscribe bursts repeatedly until backoff intervals happen to desync by chance.

**Why it happens:**
"Exponential backoff" alone (without randomized jitter) produces identical retry timing across every client that failed at the same moment, which is exactly what happens when the shared broker restarts — every connected client fails at once.

**How to avoid:**
Add random jitter to the reconnect backoff (e.g. `delay = base * 2^attempt * (0.5 + random()/2)`), cap the maximum backoff, and keep the three dashboard pages' subscriptions scoped to only what each page renders (e.g. `details.html` shouldn't subscribe to `lan/devices/+/status` for every device, only the one being viewed, plus the lighter global topics) rather than every page subscribing to everything.

**Warning signs:**
Broker CPU/connection-count spikes visibly correlate with broker restarts; multiple browser tabs reconnect at visually identical moments in dev tools' network/WS inspector.

**Phase to address:**
Dashboard phase — the reconnect/backoff logic is explicitly called out in `PROJECT.md`'s active requirements; jitter must be included in that same implementation, not bolted on later.

---

### Pitfall 6: Unbounded browser-side history merge causes memory growth on long-running kiosk displays

**What goes wrong:**
`PROJECT.md` specifies the dashboard "merges incoming updates into existing UI state rather than re-rendering from scratch" — good for avoiding flicker, but if the merge logic appends every incoming `lan/devices/{id}/history` or `lan/events/recent` update to an in-memory JS array without also enforcing the same bound the *publisher* uses, a dashboard left open for days (the stated PRTG-style "at-a-glance wall display" use case) accumulates state indefinitely. Even though the MQTT payloads themselves are "bounded," each *update* to a bounded topic is still a new message; if the JS client concatenates rather than replaces, the browser tab's memory grows even though the broker's retained store does not.

**Why it happens:**
"Merge, don't rebuild" is usually implemented as "append if new, else update in place" without also implementing "and evict beyond N," because the eviction rule lives on the publisher side and is easy to assume the client doesn't need to re-enforce.

**How to avoid:**
Since each retained `history` payload is already the full bounded list (not a delta), the client should *replace* that device's history array wholesale on each message for that topic, not append — this is naturally bounded because the source topic already is. The place unbounded growth can actually sneak in is the vis-network topology graph's internal node/edge dataset and the sortable device table's row set: verify old nodes/rows are removed when a device-removal tombstone (Pitfall 1) arrives, not just added-to on device arrival.

**Warning signs:**
Browser tab memory (Chrome task manager) grows steadily over a multi-day uptime with a fixed device count; performance degrades after the dashboard has been open unattended for a week.

**Phase to address:**
Dashboard phase — verify during implementation with a soak test (leave a tab open with the poller simulating periodic changes for several hours, watch memory).

---

### Pitfall 7: QoS/retain misuse — treating high-frequency status topics like low-frequency topology topics

**What goes wrong:**
`lan/devices/{id}/status` is republished "every poll cycle" (i.e., frequently, on a timer) while `lan/devices/topology` is republished "only on topology change" (rarely). If both use the same QoS/retain settings by default (commonly QoS 0 + retain, copy-pasted across all publishes), two different problems show up: (1) for the frequent `status` topic, QoS 0 is actually fine (a dropped update is corrected next poll cycle seconds later) but many implementations reflexively bump to QoS 1 "to be safe," which for a topic published every poll cycle adds unnecessary broker-side PUBACK bookkeeping and (on a lossy Wi-Fi client, if the poller were ever on Wi-Fi) queued-but-unacked message buildup for no benefit, since retain already gives late subscribers the latest value regardless of QoS; (2) for the rare `topology`/tombstone publishes (Pitfall 1), QoS 0 is the wrong choice — a single dropped QoS-0 publish during a momentary broker hiccup means that topology change is *never* redelivered (there's no "next poll cycle" correction for topology, since it only republishes on change), so the retained value silently stays wrong indefinitely.

**Why it happens:**
QoS is usually chosen once for "the MQTT client" rather than per-topic based on how failure of that specific publish is (or isn't) self-correcting on the next cycle.

**How to avoid:**
Set QoS per topic based on self-correction: QoS 0 + retain for `status` (self-correcting every poll cycle) and `lan/events/recent` (self-correcting on next event); QoS 1 + retain for `lan/devices/topology` and any device-removal tombstone (rare, must-arrive, no future cycle will resend it if dropped).

**Warning signs:**
A topology change (e.g. a host moved to a different Checkmk folder, changing its derived VLAN) fails to show up on the dashboard until some *unrelated* topology change happens to trigger a full republish.

**Phase to address:**
Poller/publisher phase — decide per-topic QoS as part of the initial topic-contract implementation, since `PROJECT.md`'s Key Decisions table already treats the topic contract as a finalized design; QoS should be specified alongside it.

---

### Pitfall 8: New Checkmk device-type tag group silently mis-tags every host onboarded before this milestone

**What goes wrong:**
Checkmk's own host-tag behavior (per official docs) is that "the first tag in the list is the default value" and *all existing hosts automatically receive this default tag* when a new tag group is created — there is no "unset" state. Every host onboarded by earlier wizard runs, before this milestone existed, will silently be assigned whatever choice happens to be listed first in the new `device_type` tag group's definition (e.g., if "server" is listed first, every pre-existing switch/router/IoT device onboarded in prior runs now reads `tag_device_type: server` in Checkmk, even though nobody asked it to be a server). Since the dashboard uses this tag to drive per-device icon/type rendering, this isn't cosmetic — it makes prior hosts render incorrectly on the topology map with no error or warning anywhere.

**Why it happens:**
The tag-group mechanism is designed around "always has a value" as a WATO/GUI convenience (so rules never need to handle "tag absent"), which is reasonable for hosts created *after* the tag group exists, but is a trap for hosts that predate it, since retroactive backfill is not automatic or prompted.

**How to avoid:**
Either (a) make the first/default choice something explicitly neutral like `unknown`/`unclassified` rather than any real device type, so mis-tagged legacy hosts are visibly "unknown" on the dashboard rather than silently wrong as "server"; and/or (b) as part of the phase that adds this tag group, offer a one-time backfill pass (or at minimum a printed list) so the operator can retag hosts onboarded by prior wizard runs, since the wizard itself is the only tool that knows what device type those hosts actually are (from earlier classification/discovery data, if still available).

**Warning signs:**
Dashboard topology map shows switches/routers rendered with the generic "server" icon; `cmk` REST API host list shows `tag_device_type` populated on hosts that were never run through the new-tag-group-aware onboarding flow.

**Phase to address:**
Tag-group/onboarding phase (the phase adding the new Checkmk host tag group and Phase 5 prompt) — the default-choice decision must be made explicitly here, not left to whatever order feels natural when writing the tag group's choice list.

---

### Pitfall 9: Wrong REST API attribute shape for the new tag when setting it during onboarding

**What goes wrong:**
Checkmk's REST API expects host tags to be set as `attributes.tag_<group_id>` (e.g. `"tag_device_type": "switch"`), not as a bare `<group_id>` key or nested under a `tags` object — this exact confusion has generated real Checkmk-forum bug reports where developers passed custom attributes in the wrong shape and got an opaque `500 Internal Server Error` (`'NoneType' object has no attribute 'get'`) with no indication the *tag naming*, not the tag *value*, was the problem. Given this codebase already has a documented, unverified precedent for exactly this class of mistake (`CONCERNS.md` flags the SNMP `snmp_community` attribute payload shape as "not confirmed against live Checkmk REST API docs" and was never live-tested), the new `device_type` tag attribute is at real risk of shipping with an unverified payload shape too.

**Why it happens:**
The REST API's OpenAPI spec for host attributes is large and the `tag_` prefix convention isn't obvious from casual API browsing; it's easy to test against a mocked response (as `CONCERNS.md` notes is already the pattern for `bootstrap_agent_registration_secret`) that doesn't validate the real payload shape at all.

**How to avoid:**
Use `tag_<group_id>` as the attribute key when creating/updating hosts via `create_host()`/`update_host_attributes()`, and — given this project's existing pattern of shipping REST payload shapes that later turn out wrong — add at least one live-site integration test (not just a `respx`-mocked one) for the new tag-setting call before considering the onboarding-flow change done, consistent with the "Medium priority" gap already called out in `CONCERNS.md` for the SNMP payload.

**Warning signs:**
Host creation/update during Phase 5 succeeds (no exception) but the tag never actually appears against the host in the Checkmk GUI; or it fails with a generic 500 that doesn't obviously implicate the tag field.

**Phase to address:**
Tag-group/onboarding phase — verify the exact attribute shape against a live Checkmk 2.4.0p35 site (matching the project's stated verification baseline) before wiring it into the Phase 5 prompt flow.

---

### Pitfall 10: Folder-path-derived VLAN breaks silently on folder rename/restructure

**What goes wrong:**
`PROJECT.md` states VLAN is derived from "the host's Checkmk folder path — no new Checkmk configuration needed." If this derivation parses the folder path string (e.g. splitting on `/` and matching a segment against a VLAN-naming convention) rather than reading a structured folder attribute, it inherits the same fragility class already documented in `CONCERNS.md` for `_parse_host_attributes()`'s AST-walking of `hosts.mk` — a reasonable-looking string convention that silently returns nothing (or the wrong thing) the moment someone renames a folder, reorganizes the folder tree, or nests folders one level deeper than the parser expects, with no visible error.

**Why it happens:**
Folder-path parsing is convenient because "no new Checkmk configuration" was an explicit design constraint here, but string-based derivation from something as freely renameable as a folder path has no schema to validate against.

**How to avoid:**
Use the Checkmk REST API's folder-listing endpoint to get the *structured* path segments (a list, not a raw string to split) so a folder rename doesn't shift delimiter positions unexpectedly, and add an explicit fallback/warning (not silent `None`/empty) when a host's folder path doesn't match the expected VLAN-naming convention at all — mirroring the "warn if zero hosts found" self-check `CONCERNS.md` already recommends for the similar `hosts.mk` parsing fragility.

**Warning signs:**
Dashboard shows devices with a blank/`unknown` VLAN after an operator reorganizes Checkmk folders for unrelated reasons; VLAN grouping on the topology map silently stops matching the actual network layout.

**Phase to address:**
Poller/publisher phase (wherever the folder-path → VLAN derivation function is implemented) — write this against the REST API's folder object structure from the start rather than raw path-string splitting.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|-----------------|------------------|
| `allow_anonymous true` on the WS listener instead of ACL-scoped read-only user | Dashboard "just works" with zero credential wiring | Any LAN device can publish/clear retained state (Pitfall 4) | Never for a LAN reachable by untrusted/guest devices; maybe acceptable for a single-host isolated lab VLAN with no other clients, if explicitly documented as such |
| Diffing against in-memory "last published" state instead of reconciling against Livestatus on every poll | Simpler diff logic, less Livestatus load | Permanent desync after any poller restart (Pitfall 2) | Never for the primary path; acceptable only as a secondary in-process cache layered on top of the Livestatus-truth reconciliation |
| Skipping `persistence true` in `mosquitto.conf` during early development | One less config line while iterating on the topic contract | Total state loss on every container restart once "production-ish" (Pitfall 3) | Acceptable only during local dev before the dashboard/poller integration is considered real |
| First tag choice in the new `device_type` group = a real device type (e.g. "server") rather than "unknown" | Slightly nicer-looking tag-group definition | Silent mis-tagging of every pre-existing host (Pitfall 8) | Never — cost this low to avoid should not be traded for convenience |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|-----------------|-------------------|
| Checkmk REST API (host tag attribute) | Setting `device_type` as a bare attribute key or under a `tags` object | Use `tag_<group_id>` prefix convention (e.g. `tag_device_type`); verify live, not just via mocked `respx` tests |
| Mosquitto WebSockets listener | One listener/port shared by poller (needs publish) and browser (should be read-only) | Separate listeners bound to different interfaces with different ACL users — container-internal publish listener, LAN-facing read-only WS listener |
| Livestatus polling loop | Tight reconnect loop with no backoff if Livestatus TCP is briefly unreachable (e.g. during a `checkmk` container restart) | Backoff-with-jitter on Livestatus connection errors, mirroring the reconnect strategy already planned for the dashboard's MQTT client — don't leave this one unhardened while polishing the other |
| Checkmk folder → VLAN derivation | Splitting the raw folder path string on a hardcoded delimiter/position | Use the REST API's structured folder path segments; warn (don't silently blank) on unexpected shapes |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|-----------------|
| Every dashboard page subscribing to every `lan/devices/+/*` wildcard | Large retained-message burst on every page load/reconnect; unnecessary bandwidth/CPU on shared LAN | Scope each page's subscriptions to only what it renders (e.g. `details.html` subscribes to one device, not all) | Noticeable once device count reaches the low hundreds, or on constrained LAN/Wi-Fi links |
| Poller running one Livestatus query per device per poll cycle instead of one batched query | Poll cycle time grows roughly linearly with device count, delaying change detection | Use a single Livestatus query with all needed columns per poll cycle (the existing `livestatus.py` client's CSV-parsing approach should be extended, not looped per host) | Becomes visible once fleet size is large enough that per-host query overhead exceeds the desired poll interval |
| Unjittered exponential backoff across many simultaneous dashboard clients | Synchronized reconnect bursts after any broker restart | Add random jitter to backoff delays | As soon as more than one dashboard client/tab exists on the LAN |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Anonymous, unauthenticated WS listener with implicit publish rights | Any LAN device can forge device status, clear retained topology (DoS by making the dashboard show "no devices"), or inject fake events | Mosquitto ACL file restricting the WS/browser user to `read`-only on `lan/#`; publish rights reserved for the poller on a separate, non-LAN-facing listener |
| Serving the dashboard and MQTT broker over plain `ws://`/`http://` on the LAN | Credentials (even read-only ones) and all device/topology data visible to any LAN packet sniffer | Given the project's existing documented pattern of defaulting to plaintext HTTP for Checkmk's own REST/GUI traffic (`CONCERNS.md`), do not repeat that default here without at least documenting the same tradeoff explicitly; consider TLS (`wss://`) if the LAN includes untrusted segments (guest Wi-Fi, IoT VLAN) |
| Assuming "the JS client just doesn't call `publish()`" is sufficient access control | Application-layer-only restriction; trivially bypassed by any other MQTT client library pointed at the same broker/port | Enforce restrictions at the broker (ACL), never rely on client code being the only thing that ever connects to that listener |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-------------------|
| No visible distinction between "device is actually down" and "dashboard lost MQTT connection" | Operator can't tell if the network is down or just the dashboard's view of it | The planned connection-status indicator must be visually distinct from per-device down-state indicators, and per-device state should be visibly "stale" (e.g. greyed out with a last-updated timestamp) while disconnected, not silently frozen looking current |
| Topology map keeps rendering a decommissioned device indefinitely (Pitfall 1) | Operator loses trust in the map as ground truth | Tombstone removed devices explicitly (empty retained payload) so they visibly disappear rather than linger |
| Device mis-tagged as the tag group's default choice with no visual "unclassified" affordance | Operator can't tell a real "server" from an unreviewed legacy host defaulted to "server" (Pitfall 8) | Use a neutral default tag value and render it distinctly (e.g. a generic/question-mark icon) so legacy hosts are visibly flagged for review |

## "Looks Done But Isn't" Checklist

- [ ] **Republish-only-on-change topology contract:** Often missing device-removal handling — verify that deleting a host from Checkmk actually clears its retained MQTT topics, not just that adding one publishes correctly
- [ ] **MQTT reconnect logic:** Often missing jitter — verify with more than one simultaneous dashboard client that a broker restart doesn't cause synchronized reconnect bursts
- [ ] **Mosquitto WebSockets listener:** Often missing ACL scoping — verify a non-poller MQTT client (e.g. `mosquitto_pub` from another LAN host) cannot publish to `lan/#` through the WS port
- [ ] **New Checkmk tag group default value:** Often missing a neutral default — verify what tag value pre-existing (pre-milestone) hosts actually end up with, not just newly onboarded ones
- [ ] **Broker persistence:** Often missing `persistence true` — verify retained topics survive an actual `podman compose restart mosquitto`, not just a poller restart
- [ ] **Poller Livestatus reconnect:** Often missing backoff — verify the poller doesn't tight-loop against Livestatus during a `checkmk` container restart, consistent with the pre-flight-check gap already flagged for Phase 7 in `CONCERNS.md`

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|-----------------|------------------|
| Stale retained messages for removed devices already accumulated | LOW | One-time `mosquitto_pub -r -n -t '<topic>'` sweep for each known-stale topic, or clear the whole `lan/#` tree and let the poller do a full reconciliation pass on next startup (per Pitfall 2's fix) |
| Pre-existing hosts silently mis-tagged with the wrong default `device_type` | MEDIUM | Bulk-update via REST API (`update_host_attributes`) once the correct device types are known/re-derived, then trigger a full config activation so the change is live |
| Mosquitto broker was compromised/abused via the anonymous WS listener before ACLs were added | MEDIUM | Rotate any credentials that may have been observable, audit retained topics for forged content, add ACLs, then force every device's status/topology to republish to overwrite any tampered retained state |
| Browser dashboard memory growth discovered in production (kiosk tab has been open for days) | LOW | Have the JS client periodically (e.g. every few hours) force a full page reload — a pragmatic mitigation alongside fixing the underlying merge logic |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|-------------------|----------------|
| Stale retained state for removed devices (Pitfall 1) | Poller/publisher phase | Delete a test host from Checkmk, confirm its retained MQTT topics clear and topology republishes without it |
| Poller-restart desync/republish-storm (Pitfall 2) | Poller/publisher phase | Restart the poller mid-test with a pending topology change queued; confirm it reconciles correctly on the next poll, without a full-blob storm |
| Broker persistence not enabled (Pitfall 3) | Broker/infrastructure config phase | `podman compose restart mosquitto`, confirm retained topics survive |
| Unauthenticated/writable WS listener (Pitfall 4) | Broker/infrastructure config phase | Attempt to publish from an unrelated LAN client with no credentials; confirm it's rejected |
| Reconnect thundering herd (Pitfall 5) | Dashboard phase | Open multiple browser tabs, restart the broker, confirm reconnect attempts are staggered, not synchronized |
| Unbounded browser memory growth (Pitfall 6) | Dashboard phase | Multi-hour soak test with simulated periodic updates, watch tab memory in browser task manager |
| QoS/retain misuse (Pitfall 7) | Poller/publisher phase | Simulate a dropped publish during a topology change (e.g. kill the poller mid-publish); confirm QoS 1 + retain topics are not silently lost |
| Silent default mis-tagging of pre-existing hosts (Pitfall 8) | Tag-group/onboarding phase | After adding the tag group, query all pre-milestone hosts' `tag_device_type` value and confirm it's the chosen neutral default, not a real device type |
| Wrong REST API attribute shape for the new tag (Pitfall 9) | Tag-group/onboarding phase | Live-site test (not just mocked) confirming `tag_device_type` actually appears on the host in the Checkmk GUI after onboarding |
| Folder-path VLAN derivation fragility (Pitfall 10) | Poller/publisher phase | Rename/restructure a test folder and confirm VLAN derivation either still works or explicitly warns, rather than silently returning nothing |

## Sources

- [MQTT Retain Flag and Potential Problems (gist)](https://gist.github.com/machinekoder/3ba0e8a7172c0804bc3e68e25ec49bed)
- [Understanding Persistent Sessions and Clean Sessions – MQTT Essentials Part 7 (HiveMQ)](https://www.hivemq.com/blog/mqtt-essentials-part-7-persistent-session-queuing-messages/)
- [What are Retained Messages in MQTT? – MQTT Essentials Part 8 (HiveMQ)](https://www.hivemq.com/blog/mqtt-essentials-part-8-retained-messages/)
- [Battery Device Availability Messages Not Republished After MQTT Retained Message Loss — Koenkk/zigbee2mqtt#30619 (GitHub)](https://github.com/Koenkk/zigbee2mqtt/issues/30619)
- [MQTT Last Will not retaining messages — rabbitmq/rabbitmq-mqtt#74 (GitHub)](https://github.com/rabbitmq/rabbitmq-mqtt/issues/74)
- [mosquitto.conf man page (Eclipse Mosquitto)](https://mosquitto.org/man/mosquitto-conf-5.html)
- [How to set up persistent storage for Mosquitto MQTT broker (Page Fault Blog)](https://pagefault.blog/2020/02/05/how-to-set-up-persistent-storage-for-mosquitto-mqtt-broker/)
- [Keep persistent sessions after mosquitto restart — eclipse/mosquitto#769 (GitHub)](https://github.com/eclipse/mosquitto/issues/769)
- [Host tags (Checkmk official docs)](https://docs.checkmk.com/latest/en/host_tags.html)
- [\[BUG\] Create host using REST API with custom tags (Checkmk Community Forum)](https://forum.checkmk.com/t/bug-create-host-using-rest-api-with-custom-tags/28261)
- Project-internal: `.planning/PROJECT.md` (topic/payload contract, container-boundary constraints, tag-group requirement)
- Project-internal: `.planning/codebase/CONCERNS.md` (existing fragile-parsing, plaintext-HTTP-default, unverified-REST-payload-shape, and no-backoff-on-Livestatus patterns this milestone risks repeating)

---
*Pitfalls research for: Checkmk-to-MQTT bridge + live network-topology dashboard*
*Researched: 2026-09-05*
