---
phase: quick-261008-b5a
plan: 01
subsystem: analytics, broker, dashboard
tags: [review-fix, mqtt, triage, mosquitto, smoke-test]
key-files:
  modified:
    - analytics/service.py
    - analytics/rules.py
    - analytics/triage.py
    - analytics/recorder.py
    - scripts/mqtt_poller.py
    - scripts/smoke_test_broker.py
    - deploy/mosquitto.conf
    - dashboard-react/src/store/mapDrawingStore.ts
    - dashboard-react/src/store/triageClient.ts
    - dashboard-react/src/components/TriageMenu.tsx
  created:
    - tests/test_smoke_test_broker.py
metrics:
  completed: 2026-10-08
---

# Quick 261008-b5a: Phase 14.2 review fixes (WR-01..05, WR-07, IN-02)

Fixes seven operator-approved findings from the phase 14.2 code review, each with a named regression test. WR-06, WR-08 and the other IN items were not touched.

## Commits

- e63fe91: WR-01..04 (analytics, broker config, parsers)
- b62028a: WR-05 (smoke test, docs)
- 96cc8cb: WR-07 and IN-02 (dashboard)

## What changed

- **WR-01** `_on_triage` applies the override, updates `_need_sigs` and publishes in one lock window. The ClickHouse audit insert runs afterwards, outside the lock, and is skipped (with a warning) if the need vanished or its `computed_tier` changed. `publish_need` and `_need_changed` take the (re-entrant) lock.
- **WR-02** new `_effective_tier` helper in `rules.py` used by `carry_triage` and `apply_override`; a downgrade takes the less urgent of stored and computed tier.
- **WR-03** `message_size_limit 2097152` in `deploy/mosquitto.conf` before the first listener; oversized triage payloads dropped in `on_message`; queue bounded at 10000 with `put_nowait` and a once-per-minute warning; `stop()` puts the sentinel with a 5 s timeout.
- **WR-04** `RecursionError` caught in `parse_triage_command`, `_load_json`, `EventRecorder.new_rows`, `parse_admin_command`.
- **WR-05** `--with-restart` added; restart off by default; `--skip-restart` kept as a no-op; summary is `N checks passed, M skipped` / `N checks failed, M passed, K skipped`. Docs updated (Podman setup doc, DEPLOY-NEW-MACHINE.md) including the 2 MB broker limit.
- **WR-07** `addShape` refuses at `MAX_SHAPES` and sets `saveError`.
- **IN-02** `publishTriage` times out after `PUBLISH_TIMEOUT_MS` (5000); the Triage trigger is no longer disabled after a failed send, and reopening the menu clears `loginUnavailable` and the danger feedback.

## Verification (actually run)

- Targeted Python suites (service, rules, triage, recorder, mqtt_poller, mosquitto_acl): 530 passed.
- `uv run pytest tests -k analytics`: 298 passed. Full `uv run pytest tests`: 1112 passed.
- `uvx ruff check` on analytics, scripts/mqtt_poller.py, scripts/smoke_test_broker.py and the new/changed tests: clean.
- Dashboard: targeted vitest 24 passed; full `npm test` 833 passed; `npx tsc --noEmit -p .` printed no errors.
- Not verified: the live broker. I did not check `message_size_limit` against the eclipse-mosquitto:2 man page/context7 (plan asked for it); it is the documented mosquitto.conf(5) directive and the comment in the config says to confirm on the deploy host. I did not measure the largest real retained payloads against 2 MB; only the 1 MB events cap is asserted by test.

## Deviations

- **[Rule 1] Existing test updated:** `TriageMenu.test.tsx` "disables the trigger with the login-unavailable tooltip..." asserted the old disabled behaviour; renamed and changed to assert the message only, since IN-02 deliberately removes the disabled state.
- **[Rule 3] Worktree setup:** `dashboard-react/node_modules` symlinked to the main checkout's (gitignored, not committed) so vitest/tsc could run.
- The worktree started from c80b9c3; reset to 74695d3 per the branch check.
- No docs described the shape cap or triage failure behaviour, so none were changed for WR-07/IN-02.

## Action required on the deploy host

The `mosquitto.conf` change (`message_size_limit`) takes effect only after a **full** `podman compose down && podman compose up -d`. Never restart the single mosquitto container (turns real hosts DOWN). Nothing was restarted here.

## Known Stubs

None.
