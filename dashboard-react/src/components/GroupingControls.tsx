// The tree pane's grouping controls: a select choosing the grouping mode plus a checkbox
// choosing severity ordering (D-32). Both values and their setters are owned by the caller
// (IndexRoute, via useGroupingPrefs) -- this component is a pure, value-agnostic renderer.
//
// D-32's first binding constraint is extensibility: a third grouping mode must be addable by
// appending one entry to GROUPING_OPTIONS and teaching groupKeyFor the new mode. Nothing in
// this component branches on the specific values "type"/"folder" -- mode flows straight
// through from the <select>'s value to onModeChange without ever being compared to a literal.

import type { ChangeEvent } from "react";
import { Checkbox, Select } from "kone-design-system";
import type { SelectOption } from "kone-design-system";
import type { GroupingMode } from "../lib/types";

export const GROUPING_OPTIONS: SelectOption[] = [
  { value: "type", label: "Group by type" },
  { value: "folder", label: "Group by folder" },
];

export interface GroupingControlsProps {
  mode: GroupingMode;
  orderBySeverity: boolean;
  onModeChange: (mode: GroupingMode) => void;
  onOrderChange: (orderBySeverity: boolean) => void;
}

export function GroupingControls({ mode, orderBySeverity, onModeChange, onOrderChange }: GroupingControlsProps) {
  function handleModeChange(event: ChangeEvent<HTMLSelectElement>) {
    // event.target.value is one of GROUPING_OPTIONS's own values by construction (the
    // <select> only ever renders those options), passed straight through with no comparison.
    onModeChange(event.target.value as GroupingMode);
  }

  function handleOrderChange(event: ChangeEvent<HTMLInputElement>) {
    onOrderChange(event.target.checked);
  }

  return (
    <div className="flex flex-col gap-3 border-b border-neutral-150 p-3">
      <Select
        id="grouping-mode"
        label="Group by"
        options={GROUPING_OPTIONS}
        value={mode}
        onChange={handleModeChange}
      />
      <Checkbox id="order-by-severity" label="Order by severity" checked={orderBySeverity} onChange={handleOrderChange} />
    </div>
  );
}
