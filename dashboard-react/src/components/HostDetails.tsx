import { useMemo, useRef, useState } from "react";
import { Badge, Button, ProgressCircle, Table } from "kone-design-system";
import type { BadgeColor, ProgressColor, TableColumn } from "kone-design-system";
import { gaugeColor, loadAveragesLabel, loadGaugePercent, otherMountsLabel, smartBadge } from "../lib/gauges";
import { classifyAgentServices } from "../lib/agentDetail";
import { compareServices } from "../lib/serviceSort";
import { displayNameWithAddress } from "../lib/display";
import { StateBadge, StateBadgeForState } from "./StateBadge";
import { selectVisibleNeeds } from "../lib/forecast";
import { TIER_BADGE, formatClock } from "../lib/needDisplay";
import { ForecastDialog } from "./ForecastDialog";
import { useAppStore } from "../store/useAppStore";
import type { FitPayload, ForecastConfidence, NeedPayload, ServiceEntry } from "../lib/types";

// The host details view: gauges, agent-host focused view and services table for one
// device. Lives in the overview's right-hand pane (opened at ?host=<id>, see ThreePaneLayout /
// IndexRoute) rather than its own route -- a bookmarked/shared old /details route link (with
// its id in ?id=) redirects here via App.tsx's DetailsRedirect.

const DEVICE_NOT_FOUND_HEADING = "Device not found";
const NO_METRICS_TEXT = "No agent metrics available for this device.";
const SERVICES_NOT_ARRIVED_TEXT =
  "Service data has not arrived yet — it should appear within one poll cycle.";
const NO_ADDITIONAL_SERVICES_TEXT = "No additional services.";
const NO_CHOSEN_SERVICES_TEXT = "No services were selected for monitoring in the wizard.";

// The TCP-port check reports no output text, so that table drops the Output column.
const PORT_COLUMNS: TableColumn<ServiceEntry>[] = [
  { key: "service", header: "Service", render: (row) => row.description },
  {
    key: "status",
    header: "Status",
    render: (row) => <StateBadgeForState state={row.state ?? "UNKNOWN"} />,
  },
];

const SERVICE_COLUMNS: TableColumn<ServiceEntry>[] = [
  { key: "service", header: "Service", render: (row) => row.description },
  {
    key: "status",
    header: "Status",
    render: (row) => <StateBadgeForState state={row.state ?? "UNKNOWN"} />,
  },
  {
    key: "output",
    header: "Output",
    render: (row) => <span className="text-sm">{row.plugin_output}</span>,
  },
];

// gaugeColor()/smartBadge() share ProgressColor with the gauge rings, which includes
// "brand" -- a value neither helper ever returns (gaugeColor falls back to "success",
// smartBadge only returns "success"/"danger"). Badge's own color type has no "brand"
// member, so narrow at the call site rather than widening Badge's type or gauges.ts's
// contract.
function toBadgeColor(color: ProgressColor): BadgeColor {
  return color === "brand" ? "info" : color;
}

const CONFIDENCE_VARIANT: Record<ForecastConfidence, "outline" | "soft" | "solid"> = {
  high: "solid",
  medium: "soft",
  low: "outline",
};

// Same date wording as the Service needs pane rows (NeedRow), kept local because that file
// does not export its helpers; "12 Oct", with the year only when it differs from the current one.
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

function needDateText(need: NeedPayload, nowMs: number): string {
  if (need.source === "trend") {
    const day = need.crit_date ? formatDay(need.crit_date, nowMs) : null;
    return day ? `Critical by ${day}` : "Critical date unknown";
  }
  if (need.source === "sustained") {
    if (need.window_hours === null || need.sustained_fraction === null) {
      return "Critical";
    }
    return `Critical for ${formatHours(need.window_hours * need.sustained_fraction)}`;
  }
  const since = Date.parse(need.since);
  const clock = Number.isNaN(since) ? null : formatClock(since);
  if (need.service === "") {
    return clock ? `Down since ${clock}` : "Down";
  }
  return clock ? `Failing since ${clock}` : "Failing";
}

function needWhat(need: NeedPayload): string {
  if (need.service === "") {
    return "Host";
  }
  return need.metric ? `${need.service} · ${need.metric}` : need.service;
}

function fitCaption(fit: FitPayload, nowMs: number): string {
  if (fit.status === "stable") {
    return "Stable";
  }
  if (fit.status === "no_clear_trend") {
    return "No clear trend";
  }
  const day = fit.crit_date ? formatDay(fit.crit_date, nowMs) : null;
  return day ? `Trending, Critical by ${day}` : "Trending";
}

function formatValue(fit: FitPayload): string {
  if (fit.last_value === null) {
    return "";
  }
  const value = Math.round(fit.last_value * 10) / 10;
  return fit.unit ? `${value} ${fit.unit}` : String(value);
}

function EmptyState({ heading, body }: { heading: string; body: string }) {
  return (
    <div className="px-4 py-3">
      <h1 className="text-xl font-semibold">{heading}</h1>
      <p>{body}</p>
    </div>
  );
}

function isPercent(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

// A gauge value overlay -- ProgressCircle's own `showValue` renders at a fixed text-xs
// (12px), too small for the "headline" number this route needs (UI-SPEC "Typography"
// override). Each gauge column below writes its own ProgressCircle inline (not a shared
// column component) so the override is set explicitly once per gauge.
function GaugeValue({ percent }: { percent: number }) {
  return (
    <span className="absolute inset-0 flex items-center justify-center text-2xl font-semibold text-fg-primary">
      {Math.round(percent)}%
    </span>
  );
}

// Centre text for the Load gauge: the 1-minute load with two decimals, no % sign.
function LoadGaugeValue({ load }: { load: number }) {
  return (
    <span className="absolute inset-0 flex items-center justify-center text-2xl font-semibold text-fg-primary">
      {load.toFixed(2)}
    </span>
  );
}

export function HostDetails({ id }: { id: string }) {
  const device = useAppStore((s) => s.devices[id]);
  const services = useAppStore((s) => s.services[id]);
  const needRecord = useAppStore((s) => s.needs);
  const forecast = useAppStore((s) => s.forecasts[id]);
  const [chart, setChart] = useState<{ service: string; metric: string } | null>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  const [nowMs] = useState(() => Date.now());
  const hostNeeds = useMemo(
    () => selectVisibleNeeds(needRecord).filter((need) => need.host === id),
    [needRecord, id],
  );

  if (!device) {
    return (
      <EmptyState
        heading={DEVICE_NOT_FOUND_HEADING}
        body={`No device with ID '${id}' is currently known. It may have been removed, or the ID may be mistyped.`}
      />
    );
  }

  const hasAnyGauge =
    typeof device.cpu_percent === "number" ||
    typeof device.cpu_load1 === "number" ||
    typeof device.ram_percent === "number" ||
    typeof device.disk_percent === "number";

  const otherMountsText = otherMountsLabel(device.disk_other_worst_percent);
  const smart = smartBadge(device.smart_total, device.smart_failing);

  const diskExtra =
    otherMountsText || smart ? (
      <div className="flex flex-col items-center gap-1">
        {otherMountsText && (
          <Badge
            variant="soft"
            color={toBadgeColor(
              gaugeColor(
                device.disk_other_worst_percent,
                device.disk_other_worst_warn,
                device.disk_other_worst_crit,
              ),
            )}
          >
            {otherMountsText}
          </Badge>
        )}
        {smart && (
          <Badge variant="soft" color={toBadgeColor(smart.color)}>
            {smart.text}
          </Badge>
        )}
      </div>
    ) : undefined;

  const gauges = (
    hasAnyGauge ? (
          <section className="bg-bg-surface rounded-lg shadow-card p-6">
            <div className="flex flex-row flex-wrap items-start justify-center gap-8">
              {isPercent(device.cpu_percent) && (
                <div className="flex flex-col items-center gap-2" aria-label="CPU utilisation">
                  <span className="relative inline-flex">
                    <ProgressCircle
                      value={device.cpu_percent}
                      color={gaugeColor(device.cpu_percent, device.cpu_warn, device.cpu_crit)}
                      size={96}
                      strokeWidth={8}
                      showValue={false}
                    />
                    <GaugeValue percent={device.cpu_percent} />
                  </span>
                  <span className="text-sm font-semibold">CPU</span>
                </div>
              )}
              {isPercent(device.cpu_load1) && (
                <div className="flex flex-col items-center gap-2" aria-label="CPU load">
                  <span className="relative inline-flex">
                    <ProgressCircle
                      value={loadGaugePercent(device.cpu_load1, device.cpu_load_crit) ?? 0}
                      color={gaugeColor(device.cpu_load1, device.cpu_load_warn, device.cpu_load_crit)}
                      size={96}
                      strokeWidth={8}
                      showValue={false}
                    />
                    <LoadGaugeValue load={device.cpu_load1} />
                  </span>
                  <span className="text-sm font-semibold">Load</span>
                  <span className="text-xs text-fg-tertiary">
                    {loadAveragesLabel(device.cpu_load1, device.cpu_load5, device.cpu_load15)}
                  </span>
                </div>
              )}
              {isPercent(device.ram_percent) && (
                <div className="flex flex-col items-center gap-2" aria-label="Memory used">
                  <span className="relative inline-flex">
                    <ProgressCircle
                      value={device.ram_percent}
                      color={gaugeColor(device.ram_percent, device.ram_warn, device.ram_crit)}
                      size={96}
                      strokeWidth={8}
                      showValue={false}
                    />
                    <GaugeValue percent={device.ram_percent} />
                  </span>
                  <span className="text-sm font-semibold">RAM</span>
                </div>
              )}
              {isPercent(device.disk_percent) && (
                <div className="flex flex-col items-center gap-2" aria-label="Disk used">
                  <span className="relative inline-flex">
                    <ProgressCircle
                      value={device.disk_percent}
                      color={gaugeColor(device.disk_percent, device.disk_warn, device.disk_crit)}
                      size={96}
                      strokeWidth={8}
                      showValue={false}
                    />
                    <GaugeValue percent={device.disk_percent} />
                  </span>
                  <span className="text-sm font-semibold">Disk</span>
                  {diskExtra}
                </div>
              )}
            </div>
          </section>
        ) : (
          <p>{NO_METRICS_TEXT}</p>
        )
  );

  const openChart = (service: string, metric: string, trigger: HTMLElement) => {
    triggerRef.current = trigger;
    setChart({ service, metric });
  };
  const closeChart = () => {
    setChart(null);
    // The dialog unmounts, so hand focus back to the entry that opened it.
    triggerRef.current?.focus();
  };

  const needsSection =
    hostNeeds.length > 0 ? (
      <section className="mt-3">
        <h2 className="text-sm font-semibold">Service needs</h2>
        <ul className="mt-1 flex flex-col gap-2">
          {hostNeeds.map((need) => {
            const tier = TIER_BADGE[need.tier];
            return (
              <li key={need.id} className="flex list-none flex-col gap-1 rounded-md bg-bg-surface p-2 shadow-card">
                <span className="flex min-w-0 items-center gap-2">
                  <Badge color={tier.color} variant={tier.variant}>
                    {tier.label}
                  </Badge>
                  <span className="min-w-0 flex-1 truncate text-sm font-semibold">{needWhat(need)}</span>
                  <span className="shrink-0 text-xs">{needDateText(need, nowMs)}</span>
                </span>
                {need.source === "trend" && need.confidence !== null && (
                  <span className="flex items-center gap-2 text-xs text-fg-secondary">
                    <Badge color="neutral" variant={CONFIDENCE_VARIANT[need.confidence]}>
                      {`Confidence: ${need.confidence}`}
                    </Badge>
                    {need.history_days !== null && <span>{`${need.history_days} days of history`}</span>}
                  </span>
                )}
                {need.narration && <p className="text-sm text-fg-secondary">{need.narration}</p>}
                {need.source === "trend" && need.metric !== "" && (
                  <span>
                    <Button
                      variant="tertiary"
                      size="sm"
                      onClick={(event) => openChart(need.service, need.metric, event.currentTarget)}
                    >
                      View chart
                    </Button>
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      </section>
    ) : null;

  const trendsSection =
    forecast && forecast.fits.length > 0 ? (
      <section className="mt-3">
        <h2 className="text-sm font-semibold">Trends</h2>
        <ul className="mt-1 flex flex-col">
          {forecast.fits.map((fit) => {
            const value = formatValue(fit);
            return (
              <li key={`${fit.service}|${fit.metric}`} className="list-none">
                <Button
                  variant="tertiary"
                  size="sm"
                  onClick={(event) => openChart(fit.service, fit.metric, event.currentTarget)}
                >
                  {`${fit.service} · ${fit.metric}${value ? ` ${value}` : ""} ${fitCaption(fit, nowMs)}`}
                </Button>
              </li>
            );
          })}
        </ul>
      </section>
    ) : null;

  const chartDialog = chart ? (
    <ForecastDialog host={id} service={chart.service} metric={chart.metric} onClose={closeChart} />
  ) : null;

  // Agent hosts get the focused view (2026-09-25): gauges, SMART (inside the disk gauge),
  // agent connection, uptime, the services chosen in the wizard and the monitored TCP ports
  // -- no generic service table and no history. Hosts without an agent keep the full view.
  const agent = services ? classifyAgentServices(services) : undefined;
  if (agent?.isAgentHost) {
    const chosen = agent.chosenServices.slice().sort(compareServices);
    const ports = agent.tcpPorts.slice().sort(compareServices);
    return (
      <div className="px-4 py-3">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold">{displayNameWithAddress(device)}</h1>
          <StateBadge device={device} />
        </div>

        {gauges}

        {needsSection}
        {trendsSection}

        <section className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
          <span className="flex items-center gap-2">
            <span className="font-semibold">Checkmk agent</span>
            {agent.agentConnected === null ? (
              <Badge variant="soft" color="neutral">Unknown</Badge>
            ) : (
              <Badge variant="soft" color={agent.agentConnected ? "success" : "danger"}>
                {agent.agentConnected ? "Connected" : "Not connected"}
              </Badge>
            )}
          </span>
          {agent.uptime && (
            <span className="flex items-center gap-2">
              <span className="font-semibold">Uptime</span>
              <span>{agent.uptime.plugin_output}</span>
            </span>
          )}
        </section>

        <section className="mt-3">
          <h2 className="text-sm font-semibold">Monitored services</h2>
          {chosen.length === 0 ? (
            <p className="text-sm text-fg-tertiary">{NO_CHOSEN_SERVICES_TEXT}</p>
          ) : (
            <Table columns={SERVICE_COLUMNS} rows={chosen} rowKey={(row) => row.description ?? ""} />
          )}
        </section>

        {ports.length > 0 && (
          <section className="mt-3">
            <h2 className="text-sm font-semibold">TCP ports</h2>
            <Table columns={PORT_COLUMNS} rows={ports} rowKey={(row) => row.description ?? ""} />
          </section>
        )}
        {chartDialog}
      </div>
    );
  }

  // Copied before sorting -- sorting the store's array in place would mutate shared state,
  // the exact hazard EventHistory.tsx's dated slice().reverse() comment documents.
  const sortedServices = (services ?? []).slice().sort(compareServices);
  const serviceRowKey = (row: ServiceEntry) =>
    row.description || String(sortedServices.indexOf(row));

  return (
    <div className="px-4 py-3">
      <div className="flex items-center gap-2">
        <h1 className="text-xl font-semibold">{displayNameWithAddress(device)}</h1>
        <StateBadge device={device} />
      </div>

      {gauges}

      {needsSection}
      {trendsSection}

      <section className="mt-3">
        {services === undefined ? (
          <p className="text-sm text-fg-tertiary">{SERVICES_NOT_ARRIVED_TEXT}</p>
        ) : services.length === 0 ? (
          <p className="text-center text-sm text-fg-tertiary">{NO_ADDITIONAL_SERVICES_TEXT}</p>
        ) : (
          <Table columns={SERVICE_COLUMNS} rows={sortedServices} rowKey={serviceRowKey} />
        )}
      </section>

      {chartDialog}
    </div>
  );
}
