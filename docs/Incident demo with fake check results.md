# Incident demo with fake check results

A copy-pasteable runbook for demoing the Phase 14 root-cause incident engine to stakeholders
on the live deployed stack, using Checkmk's Livestatus external commands to force host states
without waiting for real hardware to fail. Companion to `docs/Podman setup for checkmk, minio,
mosquitto, worker.md`'s "Incident check (Phase 14)" section and `dashboard-react/README.md`'s
"5c. Incidents" section — read those first for the underlying contract; this doc is the
run-of-show script.

Live-verified against a real Checkmk 2.4.0p36.cre site on 2026-09-26 (plan 14-05, D-06 gate).

## Prerequisites

1. The stack is up (`cd deploy && podman compose up -d`, or already running).
2. The React dashboard is served by the stack's `dashboard` service: open `http://<HOST_IP>:8090/`.
   If you pulled new code, rebuild it first
   (`cd deploy && podman compose build dashboard && podman compose down && podman compose up -d`).
3. `TOPOLOGY_EDITOR_SECRET` is provisioned in `dashboard-react/src/lib/config.ts` — not required
   for this demo's fake-check-result flow, but if the site was rebuilt since the secret was last
   provisioned, every dashboard write (including this doc's cleanup verification) will 401.
   **Symptom:** the browser console/network tab shows `401` on any REST write, or provisioning
   output complains the `topology_editor` user doesn't exist. **Fix:** re-run
   `podman exec -it automation-worker bash -c "cd /app/checkmk-wizard && python3 scripts/provision_topology_editor.py"`
   and paste the freshly printed secret into `config.ts` (see the deployment doc's "Note on the
   topology editor credential" for the full procedure).
4. Pick a handful of hosts you're comfortable faking DOWN for a few minutes: one plain host with
   no children, one managed switch/host with children (parents set via the topology editor), and
   one **unmanaged** switch (Add Node, Phase 13) with at least two children. Faking a real
   production host will trigger Checkmk's own notifications if configured — use test hosts, or
   schedule a short downtime first (T-14-14).

## Why "Fake check results" isn't used, and the cmk helper instead

Checkmk's GUI has a Commands > "Fake check results" action, but its result is overwritten by the
host's own next real active check — about a minute later for a host with no real payload (e.g.
one with no IP), whose real check always comes back UP. That's fast enough to make a fake state
vanish between two 60-second poller reads, which looks like a demo bug rather than a Checkmk
quirk. The 2.4 GUI also has no "Disable active checks" command visible in the host commands menu
(checked including the "⋯ show more" toggle).

The reliable method is Livestatus external commands run from the deploy host, which first
disable the host's own active checks (so nothing overwrites the fake result), then inject the
fake state directly:

```bash
cmk() { podman exec checkmk su - dmc -c "lq 'COMMAND [$(date +%s)] $1'"; }

cmk "DISABLE_HOST_CHECK;<host>"                       # stop real checks overwriting the fake
cmk "PROCESS_HOST_CHECK_RESULT;<host>;1;faked down"   # 0=UP 1=DOWN 2=UNREACHABLE
cmk "ENABLE_HOST_CHECK;<host>"                        # undo; next real check restores truth
```

`checkmk` is the container name (`deploy/compose.yaml`), `dmc` is the default site id (see the
deployment doc's "Choosing the site name" if yours differs). Always re-run `ENABLE_HOST_CHECK`
for every host you touch — see the cleanup scenario (E) below.

Timing to expect throughout: the poller polls every 60 seconds
(`POLL_INTERVAL_SECONDS`/`DEFAULT_POLL_INTERVAL_SECONDS` in `scripts/mqtt_poller.py`); allow
about two poll cycles (up to ~2 minutes) for a card to appear, split, or clear.

## Scenario A — single host down, one card

Audience narrative: "a device just went offline."

```bash
cmk "DISABLE_HOST_CHECK;<plain_host>"
cmk "PROCESS_HOST_CHECK_RESULT;<plain_host>;1;faked down"
```

What the audience sees (within ~2 poll cycles): exactly one incident card,
`"{plain_host label} — {duration}"`, appears above the stats strip with a criticality badge. It
has no consequence line, because the root isn't counted as a consequence and there are none. No
other host changes — a plain host with no managed children never produces a second card or dims
anything else.

Recover:

```bash
cmk "PROCESS_HOST_CHECK_RESULT;<plain_host>;0;faked up"
cmk "ENABLE_HOST_CHECK;<plain_host>"
```

What the audience sees: the card disappears within ~2 more poll cycles.

## Scenario B — managed switch/host down, children UNREACH

Audience narrative: "a switch went down, and everything behind it lost its own check path."

```bash
cmk "DISABLE_HOST_CHECK;<managed_switch>"
cmk "PROCESS_HOST_CHECK_RESULT;<managed_switch>;1;faked down"
```

Checkmk itself marks each child UNREACH once its parent is DOWN and the child's own check next
fails — no separate fake command needed for the children in this scenario, since Checkmk derives
UNREACH from the parent/child relationship on its own.

What the audience sees: one card, `"{managed_switch label} — {duration}"`, description
`"{M} not observable"`, where M is the number of UNREACH children. The switch itself is the root
and isn't counted. A child that Checkmk reports as DOWN rather than UNREACH counts as confirmed
down, and the line then reads `"{N} confirmed down · {M} not observable"`. In the fleet tree and on the topology map, the UNREACH
children are dimmed with a "See incident" link; clicking a faded map node or the link routes to
`/?incident={incident_id}` and highlights the matching card with a ring. The root itself keeps
full alarm styling (no dashed border — Checkmk can see the switch itself is DOWN, unlike the
inferred case below).

Recover:

```bash
cmk "PROCESS_HOST_CHECK_RESULT;<managed_switch>;0;faked up"
cmk "ENABLE_HOST_CHECK;<managed_switch>"
```

What the audience sees: the card disappears and the dimming clears within ~2 more poll cycles
(children return to their own real states once Checkmk reschedules their checks).

## Scenario C — unmanaged switch, two children down, then split

Audience narrative: "we don't monitor this switch directly, but we can still tell something
behind it is wrong — and the system says so honestly instead of guessing."

Pick an unmanaged switch (added via the topology map's "Add Node", Phase 13 — it shows UP with
zero services in Checkmk and never turns WARN/CRIT itself) with at least two children.

```bash
cmk "DISABLE_HOST_CHECK;<child_1>"
cmk "PROCESS_HOST_CHECK_RESULT;<child_1>;1;faked down"
cmk "DISABLE_HOST_CHECK;<child_2>"
cmk "PROCESS_HOST_CHECK_RESULT;<child_2>;1;faked down"
```

What the audience sees: ONE card rooted at the unmanaged switch — `"{switch label} —
{duration}"` with an "Inferred, not confirmed" badge next to the title, description
`"2 not observable"` (never "confirmed down": Checkmk cannot see past an unchecked switch, so
every consequence of an inferred incident is reported as not observable, even though both
children are actually DOWN). Both children are dimmed in the tree with "See incident". On the
map, the unmanaged switch itself gets a distinct warning-coloured dashed border instead of
DOWN/UNREACH red (its own Checkmk state is still UP/unchecked).

**Split — restore one child:**

```bash
cmk "PROCESS_HOST_CHECK_RESULT;<child_1>;0;faked up"
cmk "ENABLE_HOST_CHECK;<child_1>"
```

What the audience sees: the switch's inferred card is replaced by a single-host incident card
rooted at the still-down `<child_2>` — `"{child_2 label} — {duration}"`, no "Inferred" badge, no
dashed border on the switch (it only appears when at least two children are non-OK with at
least one DOWN — with only one child still down, the grouping rule no longer treats the switch
as an inferred root).

**Clear:**

```bash
cmk "PROCESS_HOST_CHECK_RESULT;<child_2>;0;faked up"
cmk "ENABLE_HOST_CHECK;<child_2>"
```

What the audience sees: the remaining card disappears within ~2 poll cycles.

## Scenario D — poller restart with an incident open

Audience narrative: "the monitoring pipeline itself can restart without losing track of what's
already broken, and without inventing a duplicate."

1. Fake a host down (scenario A's two commands) and confirm its card is showing.
2. Restart the poller: `cd deploy && podman compose down && podman compose up -d`. Don't use
   `podman compose restart poller`: on rootless Podman, restarting one container can cut Checkmk
   off from the LAN and turn every host DOWN (see the deployment doc §5.1, "A third signature").

What the audience sees: after the restart, the same single card reappears (or never
disappeared, if the restart was fast) — same incident id, same duration continuing from the
original `since`, not a second card. This works because the poller rebuilds the full incident
set from Livestatus every cycle; on restart `reconcile_state()` reads only the retained incident
*topic names* (never the payload body) so the first post-restart cycle republishes the
still-open incident unchanged.

Recover with scenario A's cleanup commands.

## Scenario E — full cleanup and verification

Run this after any demo session, whichever scenarios were used, to make sure nothing was left
faked:

```bash
for h in <host_1> <host_2> <host_3> ...; do
  cmk "PROCESS_HOST_CHECK_RESULT;$h;0;demo cleanup"
  cmk "ENABLE_HOST_CHECK;$h"
done
```

Confirm every touched host has active checks back on and is reporting its real state:

```bash
podman exec checkmk su - dmc -c "lq 'GET hosts
Columns: name state active_checks_enabled'"
```

`active_checks_enabled` should read `1` for every host you touched. `state` may briefly still
show the faked value until Checkmk's next real check runs.

Confirm no incidents remain open:

```bash
mosquitto_sub -u wsreader -P wsreader -t 'lan/incidents/#' -v -C 1 -W 5
```

Expect a timeout ("Timed out", RC 27) with no message received — the same clear-vs-empty
distinction used throughout this project's poller docs, not a hang.

## STALE side effect (not a product bug)

If a host is left with active checks disabled for more than a few minutes, its Checkmk
`staleness` value grows and the dashboard marks it `STALE` (a neutral, distinct badge — see
`dashboard-react/src/lib/stateMapping.ts`), while any incident card built from its
`host_state_raw` persists independently (the poller groups incidents on `host_state_raw`
DOWN/UNREACH, not on staleness). This is expected: `ENABLE_HOST_CHECK` and a subsequent real
check clear the STALE badge on their own, no action needed beyond scenario E's cleanup.
