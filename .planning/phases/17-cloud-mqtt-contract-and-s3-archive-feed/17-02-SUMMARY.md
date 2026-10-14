---
phase: 17-cloud-mqtt-contract-and-s3-archive-feed
plan: 02
subsystem: infra
tags: [mosquitto, mqtt, bridge, compose, acl]
requires: [17-01]
provides:
  - Validating renderer and template for an out-only Mosquitto cloud bridge
  - Read-only local bridge login, queue limits, include_dir
  - Cloud broker ACL example
  - Compose/env wiring for SITE_SEN, cloud broker settings, metrics heartbeat
affects: [17-04, 17-05, 17-07, 17-08]
key-files:
  created:
    - deploy/mosquitto.bridge.template
    - deploy/render-mosquitto-bridge.sh
    - deploy/mosquitto.cloud-acl.example
    - deploy/certs/.gitkeep
    - tests/test_mosquitto_bridge_render.py
  modified:
    - deploy/mosquitto.conf
    - deploy/mosquitto.acl.template
    - deploy/compose.yaml
    - deploy/init-env.sh
    - deploy/.env.example
    - tests/test_mosquitto_acl.py
    - .gitignore
requirements-completed: [CLOUD-BRIDGE, CLOUD-ACL, CLOUD-SEN]
completed: 2026-10-14
---

# Phase 17 Plan 02: Cloud bridge broker side Summary

A rendered, out-only Mosquitto bridge remaps `sites/<site_id>/` to `app/<SEN>/<site_id>/` on the cloud broker over TLS, opt-in via `CLOUD_BROKER_HOST`, with a fail-closed validating renderer.

## Commits

- 0852e4c: bridge template, renderer, render tests
- 52ea4c1: mosquitto.conf queue limits + include_dir, `user bridge` ACL, cloud ACL example, ACL tests
- c79dec8: compose, init-env, .env.example, certs dir, .gitignore

## Verification (actually run)

- `uv run pytest tests/test_mosquitto_bridge_render.py tests/test_mosquitto_acl.py -q`: 65 passed
- `sh -n deploy/render-mosquitto-bridge.sh`, `bash -n deploy/init-env.sh`: clean
- compose.yaml parses as YAML; `SITE_SEN=${SITE_SEN:-}` appears 4 times; `git check-ignore deploy/certs/cloud-ca.pem` prints the path
- Not verified: the compose entrypoint was not executed in a container, and TLS (`bridge_cafile`) was not exercised (also not covered by 17-01).

## Deviations from Plan

- [Rule 3] Worktree base differed from the expected base; reset to a69d2bd per the branch check.
- The `test_compose_wires_the_bridge_renderer` test was written in Task 1's test file (committed in Task 1) rather than Task 3; it was deselected for Task 1's run and passes after Task 3.
- The ACL/conf test additions were applied with a one-off `python3` heredoc rather than `uv run`; no project code depends on it.

## Flagged assumptions for user review

- FA-1: `topic #` also forwards `lan/poller/status` per poll cycle (about every 15 s) and throttled device status. D-06 excludes status as a stream. Decision requested: accept as the cloud liveness signal, or replace `topic #` with per-subtree `topic` lines (template-only change).
- FA-2: Cloud feed opt-in by `CLOUD_BROKER_HOST`; compose does not hard-fail on empty `SITE_SEN`.
- FA-3: `max_queued_messages 20000` / `max_queued_bytes 104857600` are global per-client limits (up to about 100 MB per backlogged client), applied even with no bridge.
- FA-4: cloud/bridge passwords restricted to `[A-Za-z0-9_.~=+-]` (1-256).
- FA-5: bridge remote username is the SEN; sites sharing a SEN share the login and are told apart by `remote_clientid bridge-<SEN>-<site_id>`.

## Known Stubs

None.

## Self-Check: PASSED
