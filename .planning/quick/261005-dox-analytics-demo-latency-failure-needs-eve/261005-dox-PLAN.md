---
phase: quick-261005-dox
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - analytics/rules.py
  - analytics/service.py
  - tests/test_analytics_rules.py
  - tests/test_analytics_service.py
  - .planning/phases/14.2-fleet-failure-prediction-and-incident-narration/14.2-CONTEXT.md
  - docs/DEPLOY-NEW-MACHINE.md
  - docs/Podman setup for checkmk, minio, mosquitto, worker.md
  - docs/MQTT-CONTRACT-WALKTHROUGH.md
autonomous: true
requirements: [DOX-LATENCY, DOX-D27-REVERSAL, DOX-TESTS, DOX-DOCS]

must_haves:
  truths:
    - "A host that goes DOWN gets a failure need published within about one POLL_INTERVAL_SECONDS (15 s) tick, not after up to 15 minutes"
    - "A DOWN host covered by an open incident (root, confirmed_down or not_observable) still gets its host-level failure need, tier from its criticality (critical=immediate, high=urgent, medium/low=standard)"
    - "Service/TCP-port CRIT failure needs for incident-covered hosts stay suppressed (D-27 unchanged for services)"
    - "A failure need is tombstoned after 2 consecutive fast ticks without it (~30 s after recovery)"
    - "Trend and sustained needs are never tombstoned by fast ticks; they still need 2 consecutive successful slow (900 s) cycles without them"
    - "ClickHouse is queried only on slow cycles; fast ticks never call history fetch functions"
    - "Cycles never overlap: one thread, a late cycle pushes the next back (skip, not queue)"
    - "Triage (downgrade/upgrade/cancel, carry_triage, auto_reset audit) works on a host-DOWN need for an incident-covered host like any other need"
  artifacts:
    - path: "analytics/rules.py"
      provides: "failure_needs with host-DOWN reversal; NeedTracker.update evaluated_sources"
      contains: "evaluated_sources"
    - path: "analytics/service.py"
      provides: "run_cycle(now, slow=...) and run_forever with fast + slow deadlines"
      contains: "poll_interval_seconds"
    - path: ".planning/phases/14.2-fleet-failure-prediction-and-incident-narration/14.2-CONTEXT.md"
      provides: "Dated D-27 / D-13 amendment"
      contains: "2026-10-05"
  key_links:
    - from: "analytics/service.py run_forever"
      to: "run_cycle(now, slow=False)"
      via: "fast deadline from config.poll_interval_seconds"
      pattern: "slow=False"
    - from: "analytics/service.py run_cycle"
      to: "NeedTracker.update"
      via: "evaluated_sources argument ({'failure'} on fast ticks or failed fetch)"
      pattern: "evaluated_sources"
---

<objective>
Cut failure-need latency for live demos and reverse D-27 for host-DOWN needs only.

1. Failure needs (pure in-memory rules over the MQTT snapshot) are evaluated on a fast tick of
   POLL_INTERVAL_SECONDS (15 s). The ClickHouse fetch, forecast publish and trend/sustained
   evaluation stay on EVAL_INTERVAL_SECONDS (900 s). Between slow cycles `_slow_candidates` is carried
   over, as it already is when ClickHouse is down.
2. A DOWN host that is covered by an open incident still gets its host-level failure need (demo
   requirement: the DOWN host shows in Needs next to its incident).

Purpose: during a demo a host taken down appears in Needs within ~15-30 s and clears ~30 s after recovery.
Output: modified analytics/rules.py, analytics/service.py, tests, and docs. No poller change and no
dashboard change unless Task 3's grep finds dedup logic. No deploy, no container restart, no push.
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/templates/summary.md
</execution_context>

<context>
@./CLAUDE.md
@analytics/rules.py
@analytics/service.py
@tests/test_analytics_rules.py
@tests/test_analytics_service.py

<interfaces>
From analytics/rules.py (current):
- RESOLVE_AFTER_CLEAN_CYCLES = 2 (line 49); RuleParams.resolve_after_clean_cycles
- Need dataclass, field `source` is "failure" | "trend" | "sustained"
- covered_hosts(open_incidents) -> set[str]  (root, confirmed_down, not_observable)
- failure_needs(statuses, services, topology_nodes, open_incidents, now, tz) -> list[Need]
  line 283: `if not isinstance(host, str) or host in covered: continue` skips BOTH the host-DOWN
  need (line 288-289) and the service CRIT needs (290-298) for covered hosts.
- tier_from_criticality(criticality) maps critical->immediate, high->urgent, medium/low->standard
- NeedTracker.update(candidates, now) -> (publish, tombstones); every open need absent from
  candidates gets missed += 1 and is tombstoned at missed >= resolve_after_clean_cycles.

From analytics/service.py (current):
- TICK_SECONDS = 30 (line 97)
- self._slow_candidates: dict[str, Need] (trend/sustained from last good fetch; restore() seeds it
  with non-failure restored needs)
- _snapshot_inputs() -> (statuses, services, nodes, incidents) copies under self.lock
- _fetch() -> (buckets, levels, hourly) | None (None when no clickhouse_url or ClickHouseError)
- _evaluate_series(fetched, now) -> (fits_by_host, slow candidates)
- _publish_forecasts(fits_by_host, now)
- publish_need(need, now): stamps generated_at, publishes retained JSON on need_status_topic(id)
- run_cycle(now) at line 604; run_forever(stop_event, clock=time.monotonic) at line 631 uses
  interval = config.eval_interval_seconds and a single next_run deadline.
- main() comment at lines 717-719 states failure needs share the 15-minute cadence and that
  most DOWN hosts are incident-covered (D-27); both statements become false.
- config.poll_interval_seconds (default 15, compose sets POLL_INTERVAL_SECONDS=15) already exists
  and is also used by rollups; reuse it, add no new env var.

Tests: tests/test_analytics_rules.py lines 229-240 (`test_no_failure_need_for_host_in_open_incident`,
`test_no_service_failure_need_for_covered_host`); tests/test_analytics_service.py fixtures `svc`,
`cycle_svc`, helpers `msg`, `published_json`, `triage_cmd`, `NOW`, `P`, fake history with
`fail_fetch`, `buckets`, `hourly`, `inserts`; `test_run_forever_runs_cycles_and_ticks_rollups_until_stopped`
at line 415 monkeypatches `svc.run_cycle = run_cycle(now)`.
</interfaces>

Chosen anti-flap behaviour (planner decision, document it in the code docstrings):
- NeedTracker.update gains an optional `evaluated_sources: frozenset[str] | set[str] | None = None`.
  None means every source was evaluated (today's behaviour). Only an absent open need whose
  `source` is in evaluated_sources accrues a missed count; other absent needs are kept and
  republished with their counter unchanged.
- Fast tick: evaluated_sources = {"failure"}. Slow tick with a successful fetch: None (all).
  Slow tick with ClickHouse down: {"failure"} (slow needs are carried over anyway).
- Result: failure needs clear after 2 absent fast ticks (~30 s); trend/sustained needs keep the
  existing "absent for 2 successful slow cycles" rule (~30 min) and are never tombstoned or
  triage-wiped by fast ticks. Without this, a trend need dropped by one slow cycle would be
  tombstoned by the very next fast tick, which silently weakens D-14/D-23 anti-flap.
  (Note: while a slow need is in `_slow_candidates` it is a candidate on every tick, so it is
  never absent on fast ticks; the guard matters only in the window after a slow cycle drops it.)
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: rules.py, host-DOWN need despite open incident and source-scoped anti-flap</name>
  <files>analytics/rules.py, tests/test_analytics_rules.py</files>
  <behavior>
    - DOWN host covered by an open incident (parametrize key over root / confirmed_down / not_observable)
      yields exactly one failure need with service "" ; parametrize criticality critical->immediate,
      high->urgent, medium->standard, low->standard.
    - Covered host that is UP with a CRIT "TCP Port 443" still yields no need (service suppression kept).
    - Covered host that is DOWN AND has a CRIT chosen service yields only the host-level need.
    - Uncovered DOWN host behaviour unchanged (existing test still passes).
    - NeedTracker.update(..., evaluated_sources={"failure"}): an open trend need absent for 5 calls is
      never tombstoned and stays in publish; an open failure need absent for 2 calls is tombstoned on
      the 2nd call (not the 1st).
    - NeedTracker.update with evaluated_sources omitted keeps today's behaviour (existing tests pass).
    - Mixed: a trend need absent on one full update (missed=1), then 3 failure-only updates (still open,
      missed stays 1), then one more full update -> tombstoned.
  </behavior>
  <action>
    In failure_needs (per locked user decision 2, reversing D-27 for host-DOWN needs only): stop skipping
    covered hosts wholesale. Keep the isinstance(host, str) guard; always evaluate the host-DOWN branch
    (tier from tier_from_criticality(node.get("criticality")), D-08, unchanged); skip only the service/TCP
    port CRIT loop when host in covered (D-27 still applies to service needs). Update the
    covered_hosts docstring and the module docstring sentence "No failure need is raised for a host
    covered by an open incident (D-27)" to say that service failure needs are suppressed for covered
    hosts while the host-DOWN need is still raised (D-27 amended 2026-10-05, demo requirement). Add a
    short why-comment at the branch.

    In NeedTracker.update add the keyword parameter evaluated_sources (default None) with the semantics
    in the context section; an absent need whose source is not evaluated is republished with its
    missed counter unchanged (not incremented, not reset). Extend the class docstring / the
    RESOLVE_AFTER_CLEAN_CYCLES comment to say the count is per evaluation of that need's source, so
    failure needs clear after 2 fast ticks and trend/sustained after 2 successful slow cycles.
    Standard library only, keep from __future__ annotations, no other behaviour change (carry_triage,
    since preservation, auto_resets untouched).

    Tests: rewrite test_no_failure_need_for_host_in_open_incident into a test asserting the need IS
    raised for each covered key and each criticality tier, with a comment naming the reversal
    ("D-27 reversed for host-DOWN needs on 2026-10-05, quick 261005-dox: the DOWN host must show in
    Needs next to its incident"). Keep test_no_service_failure_need_for_covered_host. Add the tracker
    tests from the behavior block. Write the tests first, see them fail, then implement.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && uv run pytest tests/test_analytics_rules.py tests/test_analytics_triage.py -q</automated>
  </verify>
  <done>All rules and triage tests pass; covered DOWN host yields a need with the D-08 tier; covered host service CRIT still yields none; tracker honours evaluated_sources.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: service.py, fast failure-need tick and slow ClickHouse cycle</name>
  <files>analytics/service.py, tests/test_analytics_service.py</files>
  <behavior>
    - run_cycle(NOW, slow=False) with a DOWN host publishes the failure need and never calls any
      history fetch function (use a fake history whose fetch_* raise AssertionError or count calls)
      and publishes no forecast.
    - Slow needs survive fast ticks: after run_cycle(NOW) in cycle_svc (trend need published), set
      history.buckets = {} and call run_cycle(NOW, slow=False) 5 times: no lan/needs tombstone is
      published and the trend need is still open in svc.tracker.
    - A failure need clears after the configured clean ticks: DOWN host -> run_cycle(slow=False) publishes
      need; host set UP; first fast tick no tombstone; second fast tick publishes the tombstone.
    - DOWN host covered by an open incident (feed an incident via the existing incident status message
      helper or set svc.open_incidents under svc.lock) gets a published failure need after a fast tick,
      and a triage "downgrade" command on it is applied and audited in history.need_triage like any need.
    - Existing run_cycle(NOW) tests keep passing unchanged (slow defaults to True).
    - run_forever with eval_interval_seconds=900, poll_interval_seconds=15 and a fake clock that advances
      by the wait timeout: first call is slow=True, the next 59 are slow=False, the 61st is slow=True;
      rollups ticked every pass. Update the existing run_forever test's fake run_cycle to accept slow.
  </behavior>
  <action>
    run_cycle(self, now, slow: bool = True), per locked user decision 1:
    always snapshot inputs and compute failure_needs. Only when slow: call _fetch(); on success
    _evaluate_series, _publish_forecasts and replace _slow_candidates. Always extend candidates with
    _slow_candidates.values() (existing carry-over). Pass evaluated_sources=None to tracker.update only
    when slow and the fetch succeeded, otherwise {"failure"} (anti-flap rule in the context section).
    Keep auto_reset audit rows and tombstone handling as today.

    Avoid republishing every retained need every 15 s: keep self._need_sigs: dict[str, dict] holding the
    last published payload minus generated_at, set it inside publish_need (so triage publishes update it
    too) and pop it on tombstone. On a fast tick publish only needs whose payload-minus-generated_at
    differs from the stored sig or that have no sig; on a slow tick publish all, as today (keeps the
    per-evaluation generated_at refresh documented in MQTT-CONTRACT-WALKTHROUGH). Initialise the dict in
    __init__ next to _narration_sigs (same "publish only on change" pattern).

    run_forever: keep the single thread and skip-not-queue rule. Use two deadlines: next_slow (interval
    config.eval_interval_seconds) and next_fast (interval config.poll_interval_seconds), both starting at
    clock(). Each pass: if started >= next_slow run run_cycle(self._now(), slow=True) and set
    next_slow = max(started + eval, clock()) and next_fast = max(started + poll, clock()); elif
    started >= next_fast run run_cycle(self._now(), slow=False) and set next_fast = max(started + poll,
    clock()). Same exception logging ("Evaluation cycle failed"). Rollups still ticked every pass. Wait
    max(0.0, min(TICK_SECONDS, min(next_fast, next_slow) - clock())). Update the run_forever docstring
    (fast failure-need tick vs slow ClickHouse cycle, why: demo latency, quick 261005-dox) and replace
    the main() comment at lines 717-719 with an accurate one (failure needs every POLL_INTERVAL_SECONDS
    from the in-memory MQTT snapshot, no ClickHouse; forecasts/trend/sustained every
    EVAL_INTERVAL_SECONDS; D-13 and D-27 amended 2026-10-05). Update the run_cycle docstring too.
    Do not touch scripts/mqtt_poller.py or the dashboard.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && uv run pytest tests/ -q -k analytics && uvx ruff check analytics tests/test_analytics_rules.py tests/test_analytics_service.py</automated>
  </verify>
  <done>All analytics tests pass (old and new), ruff clean; fast ticks never touch ClickHouse; slow needs survive fast ticks; failure needs clear after 2 fast ticks; run_forever schedule verified by test.</done>
</task>

<task type="auto">
  <name>Task 3: Dashboard check and documentation amendments</name>
  <files>.planning/phases/14.2-fleet-failure-prediction-and-incident-narration/14.2-CONTEXT.md, docs/DEPLOY-NEW-MACHINE.md, docs/Podman setup for checkmk, minio, mosquitto, worker.md, docs/MQTT-CONTRACT-WALKTHROUGH.md</files>
  <action>
    Dashboard (locked user decision 2): grep dashboard-react/src (NeedsPane.tsx, NeedRow.tsx,
    lib/needDisplay.ts, store/useAppStore.ts, tree-row tier marker code) for logic that drops or hides
    needs for hosts in an open incident. Planner pre-check found none (the D-27 mention in
    store/selectors.ts belongs to a different phase's decision about the fleet overview, not needs).
    If confirmed none, make no dashboard change and record "dashboard renders every need it receives,
    no change" in the SUMMARY. If dedup logic does exist, remove it for host-level failure needs, adjust
    its test and run cd dashboard-react && npx vitest run on the touched test files.

    14.2-CONTEXT.md: under D-27 (line ~181) add an indented dated amendment: "Amended 2026-10-05 (quick
    261005-dox, demo requirement: a DOWN host shows in Needs next to its incident): the host-DOWN
    failure need is raised even when the host is covered by an open incident, tier per D-08; service
    and TCP-port failure needs for covered hosts stay suppressed; trend and sustained needs unchanged."
    Under D-13 (line ~88) add a dated amendment: failure needs are evaluated every POLL_INTERVAL_SECONDS
    (15 s) from the in-memory MQTT snapshot; ClickHouse fetch, forecasts, trend and sustained needs stay
    on the 15-minute cycle; failure needs clear after 2 clean fast ticks, trend/sustained after 2 clean
    successful slow cycles. Do not rewrite the original decision text.

    docs/DEPLOY-NEW-MACHINE.md line ~91 (EVAL_INTERVAL_SECONDS row): say it controls forecasts and
    trend/sustained needs; failure needs follow POLL_INTERVAL_SECONDS (15 s). If a POLL_INTERVAL_SECONDS
    row exists for analytics, mention that it also sets the failure-need tick.

    docs/Podman setup ... worker.md: at line ~289 mention POLL_INTERVAL_SECONDS also sets the failure-need
    tick; at line ~392 say failure needs appear within about 15 s and forecasts/trend needs within the
    first slow cycle (up to EVAL_INTERVAL_SECONDS, 15 minutes). Add one sentence in the analytics
    upgrade section: picking up this change needs a full podman compose down then up -d on the deploy
    host (single-container restarts break Checkmk egress, see existing notes).

    docs/MQTT-CONTRACT-WALKTHROUGH.md line ~485 (needs topic row): update the cadence column to "when a
    need appears or changes (failure needs checked every POLL_INTERVAL_SECONDS, 15 s), after a triage
    command, and each slow evaluation cycle (default every 900 s)". Grep the doc for any statement that
    covered hosts get no failure need and amend it if found.

    Leave .planning/PROJECT.md constraints untouched (they do not mention D-27 or the cadence).
    Do not deploy, restart containers or push.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && grep -c "2026-10-05" .planning/phases/14.2-fleet-failure-prediction-and-incident-narration/14.2-CONTEXT.md && grep -n "POLL_INTERVAL_SECONDS" docs/DEPLOY-NEW-MACHINE.md docs/MQTT-CONTRACT-WALKTHROUGH.md "docs/Podman setup for checkmk, minio, mosquitto, worker.md" && grep -n "down" "docs/Podman setup for checkmk, minio, mosquitto, worker.md" | grep -i "compose"</automated>
  </verify>
  <done>CONTEXT.md has dated D-27 and D-13 amendments (count >= 2); the three docs describe the 15 s failure-need tick, the contract table row is updated, deploy doc states a full compose down/up is needed; dashboard check outcome recorded.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| broker -> analytics | Retained device status/topology/incident payloads are untrusted input to failure_needs |
| dashboard -> analytics | Triage commands on needs/triage/cmd (already validated and audited) |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-dox-01 | Denial of service | run_forever fast tick | mitigate | Single thread, skip-not-queue deadlines; fast tick does no ClickHouse I/O; publish-on-change sigs stop 15 s retained republish storms |
| T-dox-02 | Tampering | failure_needs inputs | accept | Existing isinstance guards on every field are kept; the change only removes a skip, need ids stay hashed (D-14) |
| T-dox-03 | Repudiation | triage on newly raised covered-host needs | mitigate | Same _on_triage path and history.need_triage audit rows; covered by a Task 2 test |
</threat_model>

<verification>
- uv run pytest tests/ -q passes (whole suite, not only analytics)
- uvx ruff check analytics tests clean
- No changes under scripts/ or dashboard-react/ unless Task 3 found dedup logic
</verification>

<success_criteria>
- Failure needs evaluated every POLL_INTERVAL_SECONDS without ClickHouse; slow work stays at EVAL_INTERVAL_SECONDS
- Host-DOWN need raised for incident-covered hosts with the D-08 tier; service suppression kept
- Failure needs clear after 2 clean fast ticks; trend/sustained anti-flap unchanged (2 successful slow cycles)
- Tests and docs updated as listed; user redeploys with a full podman compose down and up -d
</success_criteria>

<output>
Create `.planning/quick/261005-dox-analytics-demo-latency-failure-needs-eve/261005-dox-SUMMARY.md` when done
</output>
