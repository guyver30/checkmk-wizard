# Quick 261012-pst: dashboard poller-offline banner

Restores the DASH-04 poller-liveness / DASH-05 banner signal in dashboard-react.

- New `src/components/PollerOfflineBanner.tsx` (kone-design-system `Banner`, status warning). Uses
  `isPollerStale` and `pollerOfflineSince` from `lib/staleness.ts` and `formatClock` from `lib/display.ts`.
- Wired in `IndexRoute.tsx` centre column above `DiscoveredHostsBanner`, fed by the route's `useNowTick` clock.
- Wording: "Poller offline since HH:MM — device states may be out of date"; stale-but-online:
  "Poller has not reported since HH:MM — ...".
- Hidden before the first poller status and whenever `connection.phase !== "connected"`.
- Tests: `PollerOfflineBanner.test.tsx` (6) and a new describe in `IndexRoute.test.tsx` (4).
- README: "Poller offline banner" section.

Verified: `npm test` 962/962 pass, `npm run typecheck` clean, `npm run lint` exit 0 (pre-existing warnings only).
Not verified: no browser/live broker check; visual placement and the banner against a real LWT are unseen.
