# Quick Task 260925-cqn Summary

Event history rows now show local `YYYY-MM-DD HH:MM:SS`, a From/To datetime-local range filter with Clear sits above the list, and the poller's events cap is 1000 (default, compose, test).

## Commits
- 9924364: formatDateTime + eventFilter helpers (tests written first, RED observed, then GREEN)
- 2b7361c: EventRow/EventHistory UI + tests
- d16d1a0: cap 1000, docs (poller default, compose, test, Podman doc row, dashboard README section 5a)

## Verification actually run
- `npx vitest run` (lib files): 31 passed. Full `npm test`: 35 files, 338 tests passed. `npm run typecheck` clean. `npm run build` succeeded (only the pre-existing chunk-size warning).
- `EventHistory.tsx` has exactly one `reverse()` call (grep -c = 1).
- `uv run pytest tests/test_mqtt_poller.py -q`: 164 passed.
- `uvx ruff check --no-cache`: reports 26 findings here, not the stated 7. All are in files this task did not touch (docs/src/mqtt_notify.py 7, docs/src/mqtt_publisher_changes.py 12, tests/test_site.py 4, tests/test_wizard.py 2, src/checkmk_wizard/wizard.py 1). No finding in scripts/mqtt_poller.py or tests/test_mqtt_poller.py. I did not establish the baseline count on the parent commit (the 7 vs 26 difference is unexplained; likely a different invocation scope).

## Payload / limits verification
- Payload size, VERIFIED: 1000 entries shaped like run_cycle() events (real isoformat timestamp, 40-char device_id, event/from/to), serialised with `json.dumps` exactly as `_publish_json` does (scripts/mqtt_poller.py:1237), measured 161000 bytes via a scratchpad script run with `uv run`.
- Mosquitto limits, VERIFIED for config: `grep` of deploy/mosquitto.conf shows no `max_packet_size`, `message_size_limit`, or `websockets_*` options (only `protocol websockets` on listener 9001). ASSUMED (from mosquitto.conf(5) knowledge, not re-fetched via context7 or tested): defaults are unlimited (0) beyond the MQTT protocol maximum, and fragmented WebSocket frames are handled by the broker.
- Client limit, VERIFIED: mqttClient.ts:79-84 passes no `properties.maximumPacketSize`. In mqtt 5.16.0 the check is opt-in (`node_modules/mqtt/build/lib/handlers/index.js:24-33`, only rejects when `options.properties.maximumPacketSize` is set), so incoming packets are unlimited by default.
- Transport path, VERIFIED: browser connects to `ws://${location.hostname}:${WS_PORT}` (mqttClient.ts:77) and compose maps host 9002 -> container 9001 (deploy/compose.yaml:66), directly to mosquitto, so no nginx proxy buffer applies.
- NOT live-tested, ASSUMED: an end-to-end publish of the 1000-entry array through a running broker to a browser. `podman` and `mosquitto_pub` are not available in this environment. Also not visually checked in a browser: layout of the filter bar inside the pane (only jsdom tests).

## Deviations
- None to plan behavior. Note: heredoc-style Bash was refused by the worktree guard, so files were written via Write/Edit; no effect on results.
- README line about `HISTORY_MAX_ENTRIES` corrected (config.ts:20-21,48 confirm it mirrors the per-device history bound, value 20). New README section is numbered "5a" to avoid renumbering later sections.
- The worktree started at a4b5fa0 and was reset to b3d6bc2 per the branch check.

## Self-Check
Files created/modified verified present via git status/commits; commits 9924364 and 2b7361c exist.
