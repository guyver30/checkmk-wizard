// DASH-04 poller-liveness half / DASH-05 banner: tells the operator the poller itself has gone
// quiet, so device states that look current may not be.
//
// Two triggers, both derived by lib/staleness.ts: the retained `lan/poller/status` payload says
// "offline" (the poller's MQTT will fired), or its last_poll is older than the staleness
// threshold while the status still reads online (poller hung but the broker connection is up).
//
// Suppressed while the MQTT connection itself is not "connected": the header's
// ConnectionIndicator already says so, and a retained poller payload received before the drop is
// not evidence about the poller. Also nothing before the first poller status has arrived.
// `nowMs` comes from the route's single useNowTick clock; this component adds no timer.

import { Banner } from "kone-design-system";
import { formatClock } from "../lib/display";
import { isPollerStale, pollerOfflineSince } from "../lib/staleness";
import { useAppStore } from "../store/useAppStore";

export interface PollerOfflineBannerProps {
  nowMs: number;
}

export function PollerOfflineBanner({ nowMs }: PollerOfflineBannerProps) {
  const pollerStatus = useAppStore((s) => s.pollerStatus);
  const lastKnown = useAppStore((s) => s.lastKnownPollerTimestamp);
  const connected = useAppStore((s) => s.connection.phase === "connected");

  if (!connected || !pollerStatus || !isPollerStale(pollerStatus, nowMs)) {
    return null;
  }

  const since = pollerOfflineSince(pollerStatus, lastKnown);
  const clock = formatClock(since ? since.toISOString() : null);
  const offline = pollerStatus.status === "offline";
  const message = offline
    ? `Poller offline since ${clock} — device states may be out of date`
    : `Poller has not reported since ${clock} — device states may be out of date`;

  return (
    <div data-testid="poller-offline-banner">
      <Banner status="warning" message={message} />
    </div>
  );
}
