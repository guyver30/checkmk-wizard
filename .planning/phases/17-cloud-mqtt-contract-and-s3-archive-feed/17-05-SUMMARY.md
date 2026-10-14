---
phase: 17-cloud-mqtt-contract-and-s3-archive-feed
plan: 05
subsystem: dashboard
tags: [staleness, heartbeat, runtime-config, sen]
requires: ["17-01"]
provides:
  - isDeviceStale timestamp fallback widened by payload heartbeat_s
  - RuntimeConfig.siteSen (validated) and header SEN label
  - /config.json carries siteSen from SITE_SEN
affects: [17-04, 17-02]
key-files:
  modified:
    - dashboard-react/src/lib/staleness.ts
    - dashboard-react/src/lib/staleness.test.ts
    - dashboard-react/src/lib/types.ts
    - dashboard-react/src/lib/runtimeConfig.ts
    - dashboard-react/src/lib/runtimeConfig.test.ts
    - dashboard-react/src/App.tsx
    - dashboard-react/src/App.test.tsx
    - deploy/dashboard-nginx.conf
requirements-completed: [CLOUD-THROTTLE, CLOUD-SEN]
completed: 2026-10-14
---

# Phase 17 Plan 05: Dashboard staleness vs throttled status and SEN Summary

Timestamp-staleness threshold is now `3 x max(15, heartbeat_s)` (only finite heartbeat_s > 0 honoured), and the SPA reads a regex-validated `siteSen` from `/config.json` and shows "SEN <n>" next to the site id.

## Task commits

1. Staleness widening: 629e0e5
2. siteSen config + header: a31556a

## Verification (observed)

- `npx vitest run src/lib/staleness.test.ts src/lib/runtimeConfig.test.ts`: pass
- `npm test`: 67 files, 1022 tests passed
- `npm run typecheck`: exit 0

## Deviations from Plan

- [Rule 3] Worktree base was not the expected commit; reset to a69d2bd per the branch check. `npm ci` run in dashboard-react (node_modules absent in worktree).
- Existing `runtimeConfig.test.ts` expectations using `toEqual` were updated to include `siteSen: null` (consequence of the new field).
- Header tests were added to the existing `src/App.test.tsx` (it exists).
- nginx config was edited but not exercised against a running nginx (no live check performed).

## Known Stubs

None.

## Self-Check: PASSED
