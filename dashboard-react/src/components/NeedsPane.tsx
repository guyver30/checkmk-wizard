// The Service needs pane: the analytics service's predicted and observed service needs, in
// the order given (the caller sorts with selectVisibleNeeds -- this component never re-sorts).
// It is the Needs tab of AlertsPane, and triage is available here in every dashboard mode
// (2026-10-05 amendment to 14.2 D-24).

import { useState } from "react";
import { Badge, SegmentedControl, Tooltip } from "kone-design-system";
import { isStaleGeneratedAt } from "../lib/forecast";
import type { NeedPayload, NeedTier } from "../lib/types";
import { formatClock } from "../lib/needDisplay";
import { NeedRow } from "./NeedRow";

export interface NeedsPaneProps {
  // Pre-sorted, visible (non-cancelled) needs.
  needs: NeedPayload[];
  nameFor: (id: string) => string;
  nowMs: number;
  highlightedHost: string | null;
  updatedAtMs: number | null;
  reconnecting: boolean;
}

type Filter = "all" | NeedTier;

const FILTER_OPTIONS = [
  { value: "all", label: "All" },
  { value: "immediate", label: "Immediate" },
  { value: "urgent", label: "Urgent" },
  { value: "standard", label: "Standard" },
];

function FreshnessText({
  updatedAtMs,
  nowMs,
  reconnecting,
}: {
  updatedAtMs: number | null;
  nowMs: number;
  reconnecting: boolean;
}) {
  if (reconnecting) {
    return (
      <span role="status" className="text-xs text-fg-secondary">
        Reconnecting
      </span>
    );
  }
  if (updatedAtMs === null) {
    return <span role="status" className="text-xs text-fg-secondary" />;
  }
  if (isStaleGeneratedAt(updatedAtMs, nowMs)) {
    return (
      <Tooltip content="The analytics service has not published recently." position="bottom">
        <span role="status" className="text-xs text-warning">
          {`Stale, last update ${formatClock(updatedAtMs)}`}
        </span>
      </Tooltip>
    );
  }
  return (
    <span role="status" className="text-xs text-fg-secondary">
      {`Updated ${formatClock(updatedAtMs)}`}
    </span>
  );
}

export function NeedsPane({
  needs,
  nameFor,
  nowMs,
  highlightedHost,
  updatedAtMs,
  reconnecting,
}: NeedsPaneProps) {
  const [filter, setFilter] = useState<Filter>("all");
  const shown = filter === "all" ? needs : needs.filter((need) => need.tier === filter);

  return (
    <section role="region" aria-label="Service needs" className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 bg-bg-subtle p-2">
        <span className="text-sm font-semibold text-fg-primary">Service needs</span>
        <Badge color="neutral" variant="soft">
          {needs.length}
        </Badge>
        <SegmentedControl
          options={FILTER_OPTIONS}
          value={filter}
          onChange={(value) => setFilter(value as Filter)}
        />
        <span className="ml-auto">
          <FreshnessText updatedAtMs={updatedAtMs} nowMs={nowMs} reconnecting={reconnecting} />
        </span>
      </div>
      {needs.length === 0 ? (
        <div className="p-3 text-xs text-fg-tertiary">
          <h3 className="text-sm font-semibold text-fg-secondary">No service needs</h3>
          <p>Nothing is predicted to cross a limit within 90 days, and no service is failing.</p>
        </div>
      ) : shown.length === 0 ? (
        <div className="p-3 text-xs text-fg-tertiary">
          <h3 className="text-sm font-semibold text-fg-secondary">{`No ${filter} needs`}</h3>
          <p>Switch the filter to All to see the others.</p>
        </div>
      ) : (
        <ul className="flex min-h-0 flex-1 flex-col gap-2 overflow-auto p-2">
          {shown.map((need) => (
            <NeedRow
              key={need.id}
              need={need}
              hostLabel={nameFor(need.host)}
              nowMs={nowMs}
              highlighted={highlightedHost === need.host}
              dimmed={reconnecting}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
