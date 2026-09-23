import { useSearchParams } from "react-router";
import { Badge, ProgressCircle } from "kone-design-system";
import type { BadgeColor, ProgressColor } from "kone-design-system";
import { gaugeColor, otherMountsLabel, smartBadge } from "../lib/gauges";
import { displayName } from "../lib/display";
import { StateBadge } from "../components/StateBadge";
import { useAppStore } from "../store/useAppStore";

// Preserves the ?id=<hostname> convention (D-19) on a route instead of a second HTML
// file (D-41) — Phase 11 removed Details from the nav, but the route stays bookmarkable.

const NO_DEVICE_HEADING = "No device selected";
const NO_DEVICE_BODY =
  "Choose a device from the fleet tree to view its live metrics and service status.";
const DEVICE_NOT_FOUND_HEADING = "Device not found";
const NO_METRICS_TEXT = "No agent metrics available for this device.";

// gaugeColor()/smartBadge() share ProgressColor with the gauge rings, which includes
// "brand" -- a value neither helper ever returns (gaugeColor falls back to "success",
// smartBadge only returns "success"/"danger"). Badge's own color type has no "brand"
// member, so narrow at the call site rather than widening Badge's type or gauges.ts's
// contract.
function toBadgeColor(color: ProgressColor): BadgeColor {
  return color === "brand" ? "info" : color;
}

function EmptyState({ heading, body }: { heading: string; body: string }) {
  return (
    <main className="px-4">
      <h1 className="text-xl font-semibold">{heading}</h1>
      <p>{body}</p>
    </main>
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

export function DetailsRoute() {
  const [searchParams] = useSearchParams();
  const id = searchParams.get("id");
  const device = useAppStore((s) => (id ? s.devices[id] : undefined));

  if (!id) {
    return <EmptyState heading={NO_DEVICE_HEADING} body={NO_DEVICE_BODY} />;
  }

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

  return (
    <main className="px-4">
      <div className="flex items-center gap-2">
        <h1 className="text-xl font-semibold">{displayName(device)}</h1>
        <StateBadge device={device} />
      </div>

      {hasAnyGauge ? (
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
      )}
    </main>
  );
}
