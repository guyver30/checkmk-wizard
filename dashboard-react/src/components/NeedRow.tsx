// One row of the Service needs pane. Two lines: tier badge, host and date; then what, source
// and (trend needs only) the confidence badge with its history span. The narration is the
// analytics service's own text, rendered verbatim as a React text node (never as HTML, and
// never composed in the browser).

import { useState } from "react";
import { Link, useLocation } from "react-router";
import { Badge, Button, Tooltip } from "kone-design-system";
import { ForecastDialog } from "./ForecastDialog";
import { TriageMenu } from "./TriageMenu";
import { TIER_BADGE, formatClock } from "../lib/needDisplay";
import { hostHref } from "../lib/searchLinks";
import type { ForecastConfidence, NeedPayload } from "../lib/types";

export interface NeedRowProps {
  need: NeedPayload;
  hostLabel: string;
  nowMs: number;
  highlighted: boolean;
  dimmed: boolean;
  // Topology edit mode: shows the Triage menu; never rendered in view mode.
  editMode: boolean;
}

const CONFIDENCE_VARIANT: Record<ForecastConfidence, "outline" | "soft" | "solid"> = {
  high: "solid",
  medium: "soft",
  low: "outline",
};

// "12 Oct", with the year appended only when it differs from the current one.
function formatDay(iso: string, nowMs: number): string | null {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) {
    return null;
  }
  const date = new Date(ms);
  const sameYear = date.getFullYear() === new Date(nowMs).getFullYear();
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
  }).format(date);
}

function formatHours(hours: number): string {
  if (hours < 1) {
    return `${Math.max(1, Math.round(hours * 60))} min`;
  }
  if (hours < 48) {
    return `${Math.round(hours)} h`;
  }
  return `${Math.round(hours / 24)} d`;
}

function sustainedDuration(need: NeedPayload): string | null {
  if (need.window_hours === null || need.sustained_fraction === null) {
    return null;
  }
  return formatHours(need.window_hours * need.sustained_fraction);
}

function sinceClock(since: string): string | null {
  const ms = Date.parse(since);
  return Number.isNaN(ms) ? null : formatClock(ms);
}

function dateText(need: NeedPayload, nowMs: number): string {
  if (need.source === "trend") {
    const day = need.crit_date ? formatDay(need.crit_date, nowMs) : null;
    return day ? `Critical by ${day}` : "Critical date unknown";
  }
  if (need.source === "sustained") {
    const duration = sustainedDuration(need);
    return duration ? `Critical for ${duration}` : "Critical";
  }
  const clock = sinceClock(need.since);
  if (need.service === "") {
    return clock ? `Down since ${clock}` : "Down";
  }
  return clock ? `Failing since ${clock}` : "Failing";
}

function sourceLabel(need: NeedPayload): string {
  if (need.source === "trend") {
    return "Trending to limit";
  }
  if (need.source === "sustained") {
    const duration = sustainedDuration(need);
    return duration ? `Over limit for ${duration}` : "Over limit";
  }
  return "Failing now";
}

function whatText(need: NeedPayload): string {
  if (need.service === "") {
    return "Host";
  }
  return need.metric ? `${need.service} · ${need.metric}` : need.service;
}

function triageCaption(need: NeedPayload): string | null {
  const triage = need.triage;
  if (triage === null || triage.action === "cancel") {
    return null;
  }
  const verb = triage.action === "downgrade" ? "Downgraded" : "Upgraded";
  const by = triage.by ? ` by ${triage.by}` : "";
  const setAt = Date.parse(triage.set_at);
  const when = Number.isNaN(setAt) ? "" : `, ${formatClock(setAt)}`;
  return `${verb} from ${need.computed_tier}${by}${when}`;
}

export function NeedRow({ need, hostLabel, nowMs, highlighted, dimmed, editMode }: NeedRowProps) {
  const { search } = useLocation();
  const [chartOpen, setChartOpen] = useState(false);
  const tier = TIER_BADGE[need.tier];
  const lowConfidence = need.source === "trend" && need.confidence === "low";
  const caption = triageCaption(need);
  const rowClass = [
    "flex min-h-14 flex-col gap-1 border-l-4 p-2 text-left",
    highlighted ? "border-brand bg-brand-light" : "border-transparent hover:bg-bg-subtle",
    dimmed ? "opacity-60" : "",
  ].join(" ");

  const link = (
    <Link to={hostHref(search, need.host)} className={rowClass} aria-current={highlighted ? "true" : undefined}>
      <span className="flex min-w-0 items-center gap-2">
        <Badge color={tier.color} variant={tier.variant}>
          {tier.label}
        </Badge>
        <span className="min-w-0 flex-1 truncate text-sm font-semibold text-fg-primary">{hostLabel}</span>
        <span
          className={["shrink-0 text-xs", lowConfidence ? "text-fg-secondary" : "text-fg-primary"].join(" ")}
        >
          {dateText(need, nowMs)}
        </span>
      </span>
      <span className="flex min-w-0 items-center gap-2 text-xs text-fg-secondary">
        <span className="truncate">{whatText(need)}</span>
        <span className="shrink-0">{sourceLabel(need)}</span>
        {need.source === "trend" && need.confidence !== null && (
          <span className="flex shrink-0 items-center gap-1">
            <Badge color="neutral" variant={CONFIDENCE_VARIANT[need.confidence]}>
              {`Confidence: ${need.confidence}`}
            </Badge>
            {need.history_days !== null && <span>{`${need.history_days} days of history`}</span>}
          </span>
        )}
      </span>
      {caption && <span className="text-xs text-fg-secondary">{caption}</span>}
    </Link>
  );

  return (
    <li data-need-id={need.id} data-tier={need.tier} className="list-none [&>span]:w-full">
      {need.narration ? (
        <Tooltip content={need.narration} position="bottom">
          {link}
        </Tooltip>
      ) : (
        link
      )}
      {(need.source === "trend" || editMode) && (
        <div className="flex items-center justify-end gap-2 px-2 pb-1">
          {need.source === "trend" && (
            <Button variant="tertiary" size="sm" onClick={() => setChartOpen(true)}>
              View chart
            </Button>
          )}
          {editMode && <TriageMenu need={need} hostLabel={hostLabel} />}
        </div>
      )}
      {chartOpen && (
        <ForecastDialog
          host={need.host}
          service={need.service}
          metric={need.metric}
          onClose={() => setChartOpen(false)}
        />
      )}
    </li>
  );
}
