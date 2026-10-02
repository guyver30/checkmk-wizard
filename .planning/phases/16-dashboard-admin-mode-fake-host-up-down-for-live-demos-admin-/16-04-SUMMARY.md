---
phase: 16-dashboard-admin-mode-fake-host-up-down-for-live-demos-admin-
plan: 04
subsystem: dashboard-react
tags: [admin-mode, mqtt, zustand]
requires: []
provides:
  - admin-mode detection and wsadmin login loading
  - useAdminStore (selection, faked map, pending command, last result, configError)
  - publishAdminCommand and admin topic subscriptions/routing
  - pure helpers hostsInFolder and previewCascade
affects: [16-05, 16-06]
key-files:
  created:
    - dashboard-react/src/lib/adminMode.ts
    - dashboard-react/src/lib/adminMode.test.ts
    - dashboard-react/src/store/adminStore.ts
    - dashboard-react/src/store/adminStore.test.ts
  modified:
    - dashboard-react/src/lib/runtimeConfig.ts
    - dashboard-react/src/main.tsx
    - dashboard-react/src/store/mqttClient.ts
    - dashboard-react/src/store/mqttClient.test.ts
decisions:
  - "Admin mode is read once at module load from location.search"
  - "Command ids built from Date.now/Math.random, not crypto.randomUUID (plain-http LAN)"
metrics:
  tasks: 2
  files: 8
  completed: 2026-10-02
---

# Phase 16 Plan 04: Browser-side admin foundation Summary

Admin-mode plumbing for the React dashboard: `?admin=1` detection, wsadmin login fetched from `/admin-config.json` only in admin mode, a dedicated admin store, admin topic subscription/routing on the single MQTT connection, and `publishAdminCommand` (QoS 1, retain false) with ack correlation. No UI yet.

## Commits
- ed604c9: adminMode helpers and runtimeConfig.applyAdminCredentials
- ac1ccba: adminStore, mqttClient admin routing/publish, main.tsx wiring

## Exports for Plans 05 and 06
- `lib/adminMode.ts`: `isAdminMode`, `detectAdminMode`, `__setAdminModeForTests`, `loadAdminConfig`, `parseAdminConfig`, `buildAdminCommand`, `newCommandId`, `parseAdminAck`, `parseAdminFaked`, `hostsInFolder`, `previewCascade`, `ADMIN_TOPIC_CMD/ACK/FAKED`, `ADMIN_MAX_HOSTS`, types `AdminAction`, `FakedState`, `AdminCommand`, `AdminAck`, `AdminAckEntry`
- `lib/runtimeConfig.ts`: `applyAdminCredentials`
- `store/adminStore.ts`: `useAdminStore` (state: `selected`, `faked`, `fakedReceived`, `pending`, `lastResult`, `configError`; actions: `toggleSelected`, `setSelected`, `clearSelection`, `setPending`, `expirePending`, `setConfigError`, `handleAdminMessage`), `__resetAdminStoreForTests`, types `AdminPending`, `AdminResult`
- `store/mqttClient.ts`: `publishAdminCommand(action, hosts): string | null`, `ADMIN_SUBSCRIBE_TOPICS`

Note: `expirePending` is exported but nothing calls it yet; the UI plan must start the ack timeout timer.

## Verification (actually run)
- `npm run test` (whole suite): 42 files, 578 tests passed
- `npm run typecheck`: exit 0
- `npm run lint`: no errors; 6 pre-existing warnings in unrelated components (not touched)
- Acceptance greps: no "admin" in useAppStore.ts, no `retain: true` in mqttClient.ts
- Not verified: behavior against a live broker/wsadmin login (needs the full stack from Plans 01-03).

## Deviations from Plan
None. `npm ci` was run in the worktree's dashboard-react to obtain node_modules (lockfile install, no new packages).

## Known Stubs
None.

## Self-Check: PASSED
