// The right column's "Incidents & needs" pane: one pane with an Incidents tab and a Needs tab,
// replacing the two separate Incidents / Service needs panes (2026-10-05 amendment to 14.2
// D-24/D-25, quick 261005-e7b). AlertsPane is the tabbed body; AlertsSummary is the combined
// header summary that ThreePaneLayout keeps visible while the pane is collapsed.
//
// Combined severity rule (AlertsSummary): the count is incidents + needs. The colour is the worst of
//   any danger incident                      -> danger / solid
//   any warning incident or immediate need   -> warning / solid
//   any urgent need                          -> warning / soft
//   any standard need                        -> neutral / outline
// Incidents outrank needs because an incident is an outage happening now, while a need is a
// service action to schedule.
//
// The tab strip is local: kone-design-system's SegmentedControl has no disabled option, no
// keyboard navigation, no aria-controls/tabpanel linkage and takes string-only labels (the tabs
// carry a count badge), so this copies its Tailwind classes to look identical.

import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Badge } from "kone-design-system";
import { readJson, writeJson } from "../lib/guardedStorage";
import { worstIncidentStatus, type Incident } from "../lib/incidents";
import { NEED_TIERS } from "../lib/forecast";
import { TIER_BADGE } from "../lib/needDisplay";
import type { NeedPayload } from "../lib/types";

const STORAGE_KEY = "dashboard-react.alertsTab.v1";

type AlertsTab = "incidents" | "needs";
const TABS: { value: AlertsTab; label: string }[] = [
  { value: "incidents", label: "Incidents" },
  { value: "needs", label: "Needs" },
];

function readStoredTab(): AlertsTab {
  const stored = readJson<unknown>(STORAGE_KEY, "incidents");
  return stored === "needs" ? "needs" : "incidents";
}

export interface AlertsPaneProps {
  incidentsPanel: ReactNode;
  needsPanel: ReactNode;
  incidentCount: number;
  needCount: number;
  // Topology edit mode: Incidents is disabled and Needs is forced; the stored choice is kept.
  editMode: boolean;
  // The ?incident= target; when set (outside edit mode) the Incidents tab is selected.
  focusIncidentId?: string | null;
}

export function AlertsPane({
  incidentsPanel,
  needsPanel,
  incidentCount,
  needCount,
  editMode,
  focusIncidentId,
}: AlertsPaneProps) {
  const [selected, setSelected] = useState<AlertsTab>(readStoredTab);
  const baseId = useId();
  const tabRefs = useRef<Record<AlertsTab, HTMLButtonElement | null>>({ incidents: null, needs: null });
  // Deriving the effective tab (rather than mutating `selected` on entering edit mode) is what
  // restores the previous tab automatically when edit mode ends.
  const active: AlertsTab = editMode ? "needs" : selected;

  const select = (tab: AlertsTab) => {
    // Edit mode leaves only Needs enabled and forces it; never overwrite the stored choice.
    if (editMode) {
      return;
    }
    setSelected(tab);
    writeJson(STORAGE_KEY, tab);
  };

  useEffect(() => {
    if (focusIncidentId && !editMode) {
      setSelected("incidents");
      writeJson(STORAGE_KEY, "incidents");
    }
  }, [focusIncidentId, editMode]);

  const enabledTabs = TABS.filter((tab) => !(editMode && tab.value === "incidents"));

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const index = enabledTabs.findIndex((tab) => tab.value === active);
    let next: number;
    switch (event.key) {
      case "ArrowRight":
        next = (index + 1) % enabledTabs.length;
        break;
      case "ArrowLeft":
        next = (index - 1 + enabledTabs.length) % enabledTabs.length;
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = enabledTabs.length - 1;
        break;
      default:
        return;
    }
    event.preventDefault();
    const target = enabledTabs[next].value;
    select(target);
    tabRefs.current[target]?.focus();
  };

  const counts: Record<AlertsTab, number> = { incidents: incidentCount, needs: needCount };
  const tabId = (tab: AlertsTab) => `${baseId}-tab-${tab}`;
  const panelId = (tab: AlertsTab) => `${baseId}-panel-${tab}`;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 p-2">
        <div role="tablist" aria-label="Incidents and needs" className="inline-flex items-center gap-0.5 rounded-pill bg-bg-subtle p-1">
          {TABS.map((tab) => {
            const isActive = tab.value === active;
            const disabled = editMode && tab.value === "incidents";
            return (
              <button
                key={tab.value}
                ref={(node) => {
                  tabRefs.current[tab.value] = node;
                }}
                id={tabId(tab.value)}
                type="button"
                role="tab"
                aria-selected={isActive}
                aria-controls={panelId(tab.value)}
                tabIndex={isActive ? 0 : -1}
                disabled={disabled}
                title={disabled ? "Unavailable in topology edit mode" : undefined}
                onClick={() => select(tab.value)}
                onKeyDown={onKeyDown}
                className={[
                  "flex items-center gap-1.5 rounded-pill px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                  isActive ? "bg-bg-surface text-fg-primary shadow-card" : "text-fg-tertiary hover:text-fg-primary",
                ].join(" ")}
              >
                {tab.label}{" "}
                <Badge color="neutral" variant="soft">
                  {counts[tab.value]}
                </Badge>
              </button>
            );
          })}
        </div>
      </div>
      <div className="min-h-0 flex-1">
        {TABS.map((tab) => (
          <div
            key={tab.value}
            id={panelId(tab.value)}
            role="tabpanel"
            aria-labelledby={tabId(tab.value)}
            hidden={tab.value !== active}
            className="h-full min-h-0"
          >
            {tab.value === "incidents" ? incidentsPanel : needsPanel}
          </div>
        ))}
      </div>
    </div>
  );
}

export function AlertsSummary({ incidents, needs }: { incidents: Incident[]; needs: NeedPayload[] }) {
  const total = incidents.length + needs.length;
  if (total === 0) {
    return <span className="truncate text-xs text-fg-tertiary">No open incidents or needs</span>;
  }
  const worstIncident = worstIncidentStatus(incidents);
  const worstNeed = NEED_TIERS.find((tier) => needs.some((need) => need.tier === tier)) ?? null;

  let severity: "danger" | "warning" | "urgent" | "standard";
  let color: "danger" | "warning" | "neutral";
  let variant: "solid" | "soft" | "outline";
  if (worstIncident === "danger") {
    [severity, color, variant] = ["danger", "danger", "solid"];
  } else if (worstIncident === "warning" || worstNeed === "immediate") {
    [severity, color, variant] = ["warning", "warning", "solid"];
  } else if (worstNeed === "urgent") {
    [severity, color, variant] = ["urgent", TIER_BADGE.urgent.color, TIER_BADGE.urgent.variant];
  } else {
    [severity, color, variant] = ["standard", TIER_BADGE.standard.color, TIER_BADGE.standard.variant];
  }

  const incidentLabel = `${incidents.length} open ${incidents.length === 1 ? "incident" : "incidents"}`;
  const needLabel = `${needs.length} service ${needs.length === 1 ? "need" : "needs"}`;
  return (
    <span data-testid="alerts-severity" data-severity={severity} aria-label={`${incidentLabel}, ${needLabel}`}>
      <Badge color={color} variant={variant}>
        {total}
      </Badge>
    </span>
  );
}
