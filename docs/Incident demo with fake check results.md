# Incident demo with fake check results

A copy-pasteable runbook for demoing the Phase 14 root-cause incident engine to stakeholders
on the live deployed stack, using Checkmk's Livestatus external commands to force host states
without waiting for real hardware to fail. Companion to `docs/Podman setup for checkmk, minio,
mosquitto, worker.md`'s "Incident check (Phase 14)" section and `dashboard-react/README.md`'s
"5c. Incidents" section — read those first for the underlying contract; this doc is the
run-of-show script.

Since 2026-10-02 the preferred way to run it is the dashboard's admin mode (see "Admin mode (dashboard, Phase 16)" below); the `fakeping` helper stays as the manual fallback.

Live-verified against a real Checkmk 2.4.0p36.cre site on 2026-09-26 (plan 14-05, D-06 gate).

## Prerequisites

1. The stack is up (`cd deploy && podman compose up -d`, or already running).
2. The React dashboard is served by the stack's `dashboard` service: open `http://<HOST_IP>:8090/`.
   If you pulled new code, rebuild it first
   (`cd deploy && podman compose build dashboard && podman compose down && podman compose up -d`).
3. `TOPOLOGY_EDITOR_SECRET` is set in `deploy/.env` and provisioned into Checkmk — not required
   for this demo's fake-check-result flow, but if the Checkmk site was rebuilt since the secret
   was last provisioned, every dashboard write (including this doc's cleanup verification) will
   401. **Symptom:** the browser console/network tab shows `401` on any REST write, or
   provisioning output complains the `topology_editor` user doesn't exist. **Fix:** re-run
   `podman exec -it automation-worker bash -c "cd /app/checkmk-wizard && python3 scripts/provision_topology_editor.py"`
   (or re-run the wizard) with the value already in `deploy/.env`, then
   `cd deploy && podman compose down && podman compose up -d` (see the deployment doc's "Note on
   the topology editor credential" for the full procedure).
4. Pick a handful of hosts you're comfortable faking DOWN for a few minutes: one plain host with
   no children, one managed switch/host with children (parents set via the topology editor), and
   one **unmanaged** switch (Add Node, Phase 13) with at least two children. Faking a real
   production host will trigger Checkmk's own notifications if configured — use test hosts, or
   schedule a short downtime first (T-14-14).

## Admin mode (dashboard, Phase 16)

Since 2026-10-02 the preferred way to run this demo is the dashboard's admin mode; the `fakeping`
helper below stays as the manual fallback. Open `http://<host>:8090/?admin=1` on the presenter's
machine and the normal `http://<host>:8090/` on the audience screen. For the technical contract
(topics, payloads, modules) see `dashboard-react/README.md` section "5e. Admin mode (live demos)".

What you see in admin mode:

- A persistent banner, "ADMIN MODE - N hosts faked" (or "no hosts"). If it says "Admin login
  unavailable" the dashboard container has no admin password configured and every action is
  disabled (see `docs/DEPLOY-NEW-MACHINE.md`).
- A FAKED badge on every faked host in the tree, and a FAKED caption under it on the map.
- A bottom action bar with Set UP, Set DOWN, Set UNREACHABLE, Restore selected, Restore all, Select
  all and Clear selection. Every action opens a confirm dialog listing the exact host names (and, for Set DOWN, the cascade preview).
- "Sent" in the result message means the command was sent to Livestatus. The truth shows up on
  the next 15 s poll.

Selecting hosts: a plain click on a map node or tree row selects that host (replacing the current
selection), ctrl/cmd+click adds or removes a host, or tick a host's or folder's checkbox (in folder
grouping this includes its subfolders). "Select all" selects every listed host; Escape, "Clear
selection" or a plain click on empty map canvas clears the selection. Admin mode shows no host details pane.

Per host the poller sends the same Livestatus sequence as `fakeping`: disable the host check and
the `PING` service check first, then inject the host and `PING` results.

Restore returns a host to the demo baseline (decision "Always demo baseline", 2026-10-02): it sends
`ENABLE_HOST_CHECK`, then injects host UP and `PING` OK with the Set UP text, and leaves the `PING`
check disabled. That is exactly the state the wizard's `--demo` leaves a host in. Restore selected,
Restore all and the reverse cascade after Set UP on a managed parent all use this rule. A restored
host leaves the faked set because its host check is enabled again. For a real (non-demo) host, run
`cmk "ENABLE_SVC_CHECK;<host>;PING"` manually if you want the real `PING` check back; it is not
re-enabled on purpose, because on demo hosts it pings a non-existent IP and goes CRITICAL.

Keeping fakes fresh: the poller re-injects each faked host's current host and `PING` result every
`ADMIN_FAKE_KEEPALIVE_INTERVAL_SECONDS` (30 s) from the admin worker thread, without re-sending
DISABLE commands, and only for hosts in the faked set. Admin-mode fakes therefore no longer turn
STALE after about 3 minutes (live UAT 2026-10-02 measured staleness 2.9 to 11.2 on faked hosts
before the fix).

Known limitation (code review WR-06, kept open by decision 2026-10-02): the faked set is derived from
Livestatus (host check disabled and `PING` disabled or absent), so a host someone disabled by hand for another
reason looks faked and gets the keepalive results too, which can hide a real outage on it. Fine on a pure
demo site. On a site with real hosts, do not disable a host's checks by hand while admin mode is deployed.
The fix would be a poller-owned faked set persisted in the retained `sites/<site_id>/admin/faked` message
(`.planning/phases/16-*/16-REVIEW-FIX.md`).

Cascade rules:

- Set DOWN on a managed parent sets its managed descendants to UNREACHABLE.
- The walk stops at an unmanaged switch: the switch itself becomes UNREACHABLE, but the hosts
  behind it only change when you select them.
- Set UP and Restore reverse the cascade.
- Fakes last until restored. Use "Restore selected" for some hosts or "Restore all" for every
  faked host.

### Presenter cheat sheet (read this before a demo)

**The baseline.** A demo host's normal state is the *baseline*: host check **enabled** (the "Always
assume host to be up" rule keeps it UP), `PING` check **disabled** and showing OK. `wizard --demo`
leaves every host there, and **Restore** puts a host back there. A baseline host is *not* in the
faked set, so the 30 s keepalive does nothing for it.

**The faked set** is every host whose host check is disabled. Any Set UP, Set DOWN or Set UNREACHABLE
disables the host check and the `PING` check, injects the result, and so adds the host to the faked
set. The keepalive then re-injects its result every 30 s until you Restore it.

| Button | Host check afterwards | `PING` check | Result shown | Cascade |
|---|---|---|---|---|
| Set UP | disabled (faked) | disabled | host UP, `PING` OK | Reverses UNREACH on managed descendants |
| Set DOWN | disabled (faked) | disabled | host DOWN, `PING` CRIT | Managed descendants become UNREACHABLE (stops at an unmanaged switch, which itself goes UNREACHABLE) |
| Set UNREACHABLE | disabled (faked) | disabled | host UNREACH, `PING` CRIT | None |
| Restore selected | **enabled** (baseline) | disabled | host UP, `PING` OK | Reverses UNREACH on managed descendants |
| Restore all | **enabled** (baseline) | disabled | every faked host back to baseline | Hosts already at baseline are left alone |

**Rules of thumb**

1. **Start clean:** press **Restore all** before the demo. Every host is then at baseline, the banner
   says "no hosts" faked, and no host carries a FAKED badge.
2. **Break things with Set DOWN** on the thing you want to fail (a switch, a server). Its managed
   children go UNREACHABLE by themselves and the incident card roots at the DOWN host.
3. **Put things back with Restore**, not Set UP. Set UP looks identical on screen but leaves the host
   faked (check disabled, keepalive running), so it is not a clean baseline and Restore all will still
   count it. Set UP is only for forcing a host green while its real state is bad, for example a real
   host that is genuinely down.
4. **Set UNREACHABLE is for fine-tuning**, not for normal use. It marks one host as a consequence
   without cascading. In real Checkmk a host is only UNREACHABLE when a parent is DOWN, so a lone
   UNREACH host has no root cause and looks odd on an incident card. Use it on a child of a host you
   have already set DOWN.
5. **Restore a parent to reverse its cascade.** A child that still shows UNREACH afterwards is covered
   by another faked-DOWN managed ancestor: restore that one too (or Restore all).
6. **Same red on screen:** DOWN and UNREACH both show red and `state` is `DOWN` for both; the real
   state is in `host_state_raw`, and the tree/details badge is solid for DOWN and outline for UNREACH.
7. **"Sent" is not "applied".** The result message only means Livestatus got the command; confirm on
   the next 15 s poll before you move on.
8. **Real hosts (for example a real Linux box) behave differently:** Set DOWN works on them, but
   Restore re-enables the host check and leaves their `PING` check **disabled**. Re-enable it by hand
   with `cmk "ENABLE_SVC_CHECK;<host>;PING"`. And never disable a real host's checks by hand while admin
   mode is deployed, or it counts as faked and the keepalive can hide a real outage (WR-06).

**Reading a host's state at a glance**

| What you see | What it is |
|---|---|
| UP, check enabled | Baseline (restored or never touched) |
| UP, check disabled | Faked UP (Set UP). Not a clean baseline; Restore it |
| DOWN, check disabled | Faked DOWN |
| UNREACH, check disabled | Faked UNREACH (by Set UNREACHABLE, or by a parent's Set DOWN cascade) |
| FAKED badge in the tree, FAKED caption on the map | In the faked set |

### What the small orange dot means (for the audience)

When you fake a host DOWN, a small orange marker appears at the top-right of its icon on the map
and next to it in the tree, and a row appears in the **Needs** tab of the "Incidents & needs"
pane. The marker is the host's *service need tier*, derived from its criticality: a filled dot is
**Immediate** (critical host), a ring is **Urgent** (high), and medium or low criticality shows no
marker (the need is still listed in the Needs tab as Standard). It appears within about 30 s and
clears about 30 s after you restore the host. To show all three tiers, fake DOWN three hosts that
have different criticality. **Triage** on a need row (downgrade, upgrade to immediate, cancel) works in
admin mode too. Full legend: `dashboard-react/README.md`, section 5c.

### Scenario A, B and C with admin mode

Scenario A (single host down):

1. Click the plain host, press Set DOWN, confirm.
2. Within about two poll cycles one incident card appears. Press Restore selected, confirm.

Scenario B (managed switch or host down, children UNREACH):

1. Select the managed parent, press Set DOWN, confirm. The dialog lists its managed children,
   which become UNREACHABLE automatically.
2. Expect one card rooted at the parent. Restore selected on the parent (the cascade reverses),
   or Restore all.

Scenario C (unmanaged switch, two children down, then split):

1. Select the two children of the unmanaged switch, press Set DOWN, confirm. You get one
   combined inferred card rooted at the switch.
2. Restore one child: the card becomes a plain single-host card for the other child. One child
   alone stays its own card, by design (D-03).
3. Restore the second child (or Restore all) and the card clears.

### Side effects

A faked state is a real Checkmk state change. It triggers real Checkmk notifications if any are
configured, lands in ClickHouse history and the availability rollups (so Grafana shows it), and
appears in the event feed. Nothing marks it as fake outside the admin view, by design (D-12). Use
test hosts or a short downtime.

### Demo hosts

Hosts created by the wizard's `--demo` keep their "Always assume host to be up" rule. Restore puts
them back to the demo baseline (host UP, `PING` OK, `PING` check disabled); the rule keeps the
re-enabled host check UP. They are not counted as faked because their host check is enabled.

### Security

`/admin-config.json` serves the `wsadmin` login to anyone who can reach the dashboard (D-07). That
is acceptable only on the closed demo network; a CIDR restriction is deferred. The broker limits
that login to writing `sites/<site_id>/admin/cmd`; it cannot write anywhere under `sites/<site_id>/lan/`.

## Why "Fake check results" isn't used, and the cmk helper instead

Checkmk's GUI has a Commands > "Fake check results" action, but its result is overwritten by the
host's own next real active check — about a minute later for a host with no real payload (e.g.
one with no IP), whose real check always comes back UP. That's fast enough to make a fake state
vanish within about a minute, often after at most a few poller reads, which looks like a demo
bug rather than a Checkmk quirk. The 2.4 GUI also has no "Disable active checks" command visible in the host commands menu
(checked including the "⋯ show more" toggle).

The reliable method is Livestatus external commands run from the deploy host, which first
disable the host's own active checks (so nothing overwrites the fake result), then inject the
fake state directly:

```bash
cmk() { podman exec checkmk su - dmc -c "lq 'COMMAND [$(date +%s)] $1'"; }

cmk "DISABLE_HOST_CHECK;<host>"                       # stop real checks overwriting the fake
cmk "PROCESS_HOST_CHECK_RESULT;<host>;1;CRITICAL - <ip>: rta nan, lost 100%"   # 0=UP 1=DOWN 2=UNREACHABLE
cmk "ENABLE_HOST_CHECK;<host>"                        # undo; next real check restores truth
```

`checkmk` is the container name (`deploy/compose.yaml`), `dmc` is the default site id (see the
deployment doc's "Choosing the site name" if yours differs). Always re-run `ENABLE_HOST_CHECK`
for every host you touch — see the cleanup scenario (E) below.

### `fakeping` helper: host and PING together

Typing four commands per host gets old. This helper sets a host's state and its `PING` service in
one call, with realistic `check_icmp`-style output (a random round-trip time on UP, like the
wizard's `--demo` mode), so host details on the dashboard never shows anything that looks faked.
It also disables the real host and PING checks first, so nothing overwrites the fake. Paste it
once per shell, after `cmk()` above:

```bash
SITE=${SITE:-dmc}   # your site id, e.g. SITE=dmc_test
cmk() { podman exec checkmk su - "$SITE" -c "lq 'COMMAND [$(date +%s)] $1'"; }

# fakeping <host> up|down|unreach|restore [ip]   (restore = demo baseline; ip defaults to the host name, used in the output text)
fakeping() {
  local h=$1 mode=$2 ip=${3:-$1} rta hs ss out
  rta=$(awk -v s="$RANDOM" 'BEGIN { srand(s); printf "%.3f", 0.2 + rand() * 2.8 }')
  case $mode in
    restore)
      out="OK - $ip rta ${rta}ms lost 0%"
      cmk "ENABLE_HOST_CHECK;$h"
      cmk "PROCESS_HOST_CHECK_RESULT;$h;0;$out"
      cmk "PROCESS_SERVICE_CHECK_RESULT;$h;PING;0;$out"
      return ;;
    up)       hs=0 ss=0 out="OK - $ip rta ${rta}ms lost 0%" ;;
    down)     hs=1 ss=2 out="CRITICAL - $ip: rta nan, lost 100%" ;;
    unreach)  hs=2 ss=2 out="CRITICAL - $ip: rta nan, lost 100%" ;;
    *) echo "usage: fakeping <host> up|down|unreach|restore [ip]" >&2; return 1 ;;
  esac
  cmk "DISABLE_HOST_CHECK;$h"
  cmk "DISABLE_SVC_CHECK;$h;PING"
  cmk "PROCESS_HOST_CHECK_RESULT;$h;$hs;$out"
  cmk "PROCESS_SERVICE_CHECK_RESULT;$h;PING;$ss;$out"
}

fakeping 198.51.100.3 down        # host DOWN, PING CRIT
fakeping 198.51.100.1 unreach     # a child behind it: UNREACHABLE
fakeping 198.51.100.3 up          # bring it back (random rta)
fakeping 198.51.100.3 restore     # back to the demo baseline (UP, PING OK, PING check stays disabled)
```

Notes:

- `unreach` is for the children of a DOWN parent. Checkmk only works out UNREACHABLE from its own
  host checks, so a faked DOWN on a parent does not change its children by itself — send them
  `unreach` too.
- Hosts from a `--demo` wizard run have an "Always assume host to be up" rule, so a real host
  check would flip a faked DOWN back to UP. `fakeping` disables the check first. `restore`
  re-enables the host check and injects UP and PING OK, but leaves the PING check disabled (demo
  baseline); for a real host re-enable it with `cmk "ENABLE_SVC_CHECK;<host>;PING"`.
- Keep the output text free of `;` (the command separator) and single quotes (they break the
  `lq '…'` quoting).

Timing to expect throughout: the poller polls every 15 seconds
(`POLL_INTERVAL_SECONDS` in `deploy/compose.yaml`, default `DEFAULT_POLL_INTERVAL_SECONDS` in
`scripts/mqtt_poller.py`); allow about two poll cycles (up to ~30 seconds) for a card to appear,
split, or clear.

## Scenario A — single host down, one card

Audience narrative: "a device just went offline."

```bash
cmk "DISABLE_HOST_CHECK;<plain_host>"
cmk "PROCESS_HOST_CHECK_RESULT;<plain_host>;1;CRITICAL - <ip>: rta nan, lost 100%"
```

What the audience sees (within ~2 poll cycles): exactly one incident card,
`"{plain_host label} — {duration}"`, appears in the Incidents pane at the top of the right-hand column with a criticality badge. It
has no consequence line, because the root isn't counted as a consequence and there are none. No
other host changes — a plain host with no managed children never produces a second card or dims
anything else.

Recover:

```bash
cmk "PROCESS_HOST_CHECK_RESULT;<plain_host>;0;OK - <ip> rta 0.412ms lost 0%"
cmk "ENABLE_HOST_CHECK;<plain_host>"
```

What the audience sees: the card disappears within ~2 more poll cycles.

## Scenario B — managed switch/host down, children UNREACH

Audience narrative: "a switch went down, and everything behind it lost its own check path."

```bash
cmk "DISABLE_HOST_CHECK;<managed_switch>"
cmk "PROCESS_HOST_CHECK_RESULT;<managed_switch>;1;CRITICAL - <ip>: rta nan, lost 100%"
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
cmk "PROCESS_HOST_CHECK_RESULT;<managed_switch>;0;OK - <ip> rta 0.412ms lost 0%"
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
cmk "PROCESS_HOST_CHECK_RESULT;<child_1>;1;CRITICAL - <ip>: rta nan, lost 100%"
cmk "DISABLE_HOST_CHECK;<child_2>"
cmk "PROCESS_HOST_CHECK_RESULT;<child_2>;1;CRITICAL - <ip>: rta nan, lost 100%"
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
cmk "PROCESS_HOST_CHECK_RESULT;<child_1>;0;OK - <ip> rta 0.412ms lost 0%"
cmk "ENABLE_HOST_CHECK;<child_1>"
```

What the audience sees: the switch's inferred card is replaced by a single-host incident card
rooted at the still-down `<child_2>` — `"{child_2 label} — {duration}"`, no "Inferred" badge, no
dashed border on the switch (it only appears when at least two children are non-OK with at
least one DOWN — with only one child still down, the grouping rule no longer treats the switch
as an inferred root).

**Clear:**

```bash
cmk "PROCESS_HOST_CHECK_RESULT;<child_2>;0;OK - <ip> rta 0.412ms lost 0%"
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
mosquitto_sub -u wsreader -P wsreader -t 'sites/<site_id>/lan/incidents/#' -v -C 1 -W 5
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

Admin-mode fakes are kept fresh by the poller keepalive (every 30 s) and do not go STALE. Manual
`fakeping` fakes still go STALE after a few minutes because nothing refreshes them; re-run
`fakeping` or use admin mode.
