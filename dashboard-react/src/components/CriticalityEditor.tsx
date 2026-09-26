// DASH-16 edit-mode panel: an operator sets a selected host's business criticality tier,
// per-service criticality, and depends-on links. Every field write is optimistic (this
// component's own local state updates immediately) and goes straight to Checkmk through
// lib/checkmkWrite.ts's label writers -- there is no per-field Set/Save button and no second
// pending-count/Apply flow (D-06/D-07): a successful write calls the same onSaved the map's
// own edits call, and IndexRoute feeds both into the one "N changes not yet applied" Banner.
//
// No DOM access beyond this component's own rendering, no broker connection, no direct
// network calls -- writes go through checkmkWrite.ts's exported functions only.

import { useState, type ChangeEvent } from "react";
import { MultiSelect, Select } from "kone-design-system";
import type { MultiSelectOption, SelectOption } from "kone-design-system";
import { CRITICALITY_TIERS, isCriticalityTier, type CriticalityTier } from "../lib/incidents";
import { setCriticality, setServiceCriticality, updateDependsOn } from "../lib/checkmkWrite";
import type { TopologyNode } from "../lib/types";

const CRITICALITY_LABELS: Record<CriticalityTier, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

const CRITICALITY_OPTIONS: SelectOption[] = CRITICALITY_TIERS.map((tier) => ({
  value: tier,
  label: CRITICALITY_LABELS[tier],
}));

const SERVICE_CRITICALITY_OPTIONS: SelectOption[] = [
  { value: "default", label: "Default" },
  ...CRITICALITY_OPTIONS,
];

const COULD_NOT_SAVE = {
  title: "Couldn't save that",
  body: "Checkmk rejected the update. Check that the device still exists, then try again.",
};

// The topology node carries already-parsed values (not label strings) for
// service_criticality/depends_on -- these guards accept a Record/string[] and drop anything
// else, mirroring checkmkWrite.ts's label-string parsers' "never raise on bad input" posture.
function serviceCriticalityFromNode(value: unknown): Record<string, CriticalityTier> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  const result: Record<string, CriticalityTier> = {};
  for (const [name, tier] of Object.entries(value as Record<string, unknown>)) {
    if (isCriticalityTier(tier)) {
      result[name] = tier;
    }
  }
  return result;
}

function dependsOnFromNode(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((id): id is string => typeof id === "string") : [];
}

export interface CriticalityEditorFailure {
  title: string;
  body: string;
}

export interface CriticalityEditorProps {
  hostIds: string[];
  nameFor: (id: string) => string;
  selectedHost: string | null;
  onSelectHost: (id: string | null) => void;
  node: TopologyNode | undefined;
  serviceNames: string[];
  onSaved: () => void;
  onFailed: (failure: CriticalityEditorFailure) => void;
}

export function CriticalityEditor({
  hostIds,
  nameFor,
  selectedHost,
  onSelectHost,
  node,
  serviceNames,
  onSaved,
  onFailed,
}: CriticalityEditorProps) {
  const [collapsed, setCollapsed] = useState(false);

  const nodeCriticality = isCriticalityTier(node?.criticality) ? node.criticality : "low";
  const nodeServiceCriticalityKey = JSON.stringify(serviceCriticalityFromNode(node?.service_criticality));
  const nodeDependsOnKey = JSON.stringify(dependsOnFromNode(node?.depends_on));

  const [criticality, setCriticalityState] = useState<CriticalityTier>(nodeCriticality);
  const [serviceCriticality, setServiceCriticalityState] = useState<Record<string, CriticalityTier>>(() =>
    JSON.parse(nodeServiceCriticalityKey),
  );
  const [dependsOn, setDependsOnState] = useState<string[]>(() => JSON.parse(nodeDependsOnKey));

  // Resets the panel's optimistic local state when the selected host changes, or when the
  // topology's own persisted values for it change (e.g. once the pending changes are activated
  // and the next poll catches up) -- keyed on the derived values themselves, not the `node`
  // object reference, so a write this panel just made optimistically is never immediately
  // clobbered by an unrelated re-render that produces a new-but-same-valued node object.
  // Adjusting state during render (rather than in an effect) per
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  // -- this reset is a direct response to a prop change, not a synchronization with an external
  // system, so it belongs in the render itself. The initial useState calls above seed the very
  // first render's values; this comparison only ever fires on a later prop change.
  const resetKey = `${selectedHost ?? ""}|${nodeCriticality}|${nodeServiceCriticalityKey}|${nodeDependsOnKey}`;
  const [lastResetKey, setLastResetKey] = useState(resetKey);
  if (resetKey !== lastResetKey) {
    setLastResetKey(resetKey);
    setCriticalityState(nodeCriticality);
    setServiceCriticalityState(JSON.parse(nodeServiceCriticalityKey));
    setDependsOnState(JSON.parse(nodeDependsOnKey));
  }

  function handleHostCriticalityChange(event: ChangeEvent<HTMLSelectElement>) {
    const tier = event.target.value;
    if (!selectedHost || !isCriticalityTier(tier)) {
      return;
    }
    const previous = criticality;
    setCriticalityState(tier);
    setCriticality(selectedHost, tier)
      .then(onSaved)
      .catch(() => {
        setCriticalityState(previous);
        onFailed(COULD_NOT_SAVE);
      });
  }

  function handleServiceCriticalityChange(name: string, event: ChangeEvent<HTMLSelectElement>) {
    if (!selectedHost) {
      return;
    }
    const raw = event.target.value;
    const tier: CriticalityTier | null = isCriticalityTier(raw) ? raw : null;
    const previous = serviceCriticality;
    const next = { ...previous };
    if (tier === null) {
      delete next[name];
    } else {
      next[name] = tier;
    }
    setServiceCriticalityState(next);
    setServiceCriticality(selectedHost, name, tier)
      .then(onSaved)
      .catch(() => {
        setServiceCriticalityState(previous);
        onFailed(COULD_NOT_SAVE);
      });
  }

  // One window.confirm per removed id (a MultiSelect checkbox toggle changes exactly one id at
  // a time, but this stays correct for any batch). A declined confirm makes no write at all and
  // leaves the removed id selected -- dependsOn's local state is only updated after every
  // removal in this call has been confirmed.
  function handleDependsOnChange(newIds: string[]) {
    if (!selectedHost) {
      return;
    }
    const removed = dependsOn.filter((id) => !newIds.includes(id));
    for (const removedId of removed) {
      const confirmed = window.confirm(
        `Remove this dependency?\n\n${nameFor(selectedHost)} will no longer be counted as affected by ${nameFor(removedId)}'s incidents. This won't take effect until you press Apply changes.`,
      );
      if (!confirmed) {
        return;
      }
    }
    const previous = dependsOn;
    setDependsOnState(newIds);
    updateDependsOn(selectedHost, () => newIds)
      .then(onSaved)
      .catch(() => {
        setDependsOnState(previous);
        onFailed(COULD_NOT_SAVE);
      });
  }

  const deviceOptions: SelectOption[] = hostIds.map((id) => ({ value: id, label: nameFor(id) }));
  const serviceRows = Array.from(new Set([...serviceNames, ...Object.keys(serviceCriticality)])).sort();
  const dependsOnOptions: MultiSelectOption[] = hostIds
    .filter((id) => id !== selectedHost)
    .map((id) => ({ value: id, label: nameFor(id) }));

  return (
    <section aria-label="Criticality & dependencies" className="flex flex-col gap-2 rounded-md bg-bg-subtle p-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Criticality & dependencies</h2>
        <button
          type="button"
          className="text-xs underline"
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((value) => !value)}
        >
          {collapsed ? "Show" : "Hide"}
        </button>
      </div>
      {!collapsed && (
        <>
          <Select
            id="criticality-editor-device"
            label="Device"
            options={deviceOptions}
            placeholder="Select a device"
            value={selectedHost ?? ""}
            onChange={(event: ChangeEvent<HTMLSelectElement>) => onSelectHost(event.target.value || null)}
          />
          {!selectedHost && (
            <p className="text-xs text-fg-tertiary">
              Select a device on the map or from the list to edit its criticality.
            </p>
          )}
          {selectedHost && (
            <>
              <Select
                id="criticality-editor-host-tier"
                label="Host criticality"
                options={CRITICALITY_OPTIONS}
                value={criticality}
                onChange={handleHostCriticalityChange}
              />
              {serviceRows.length > 0 && (
                <div className="flex flex-col gap-1">
                  <h3 className="text-xs font-semibold">Per-service criticality</h3>
                  {serviceRows.map((name) => (
                    <div key={name} className="flex items-center gap-2">
                      <span className="flex-1 text-xs">{name}</span>
                      <Select
                        id={`criticality-editor-service-${name}`}
                        aria-label={name}
                        options={SERVICE_CRITICALITY_OPTIONS}
                        value={serviceCriticality[name] ?? "default"}
                        onChange={(event: ChangeEvent<HTMLSelectElement>) =>
                          handleServiceCriticalityChange(name, event)
                        }
                      />
                    </div>
                  ))}
                </div>
              )}
              <MultiSelect
                label="Depends on"
                options={dependsOnOptions}
                value={dependsOn}
                onChange={handleDependsOnChange}
                placeholder="Search devices…"
              />
            </>
          )}
        </>
      )}
    </section>
  );
}
