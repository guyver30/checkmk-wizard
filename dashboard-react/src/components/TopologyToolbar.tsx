// The toolbar row between the stats strip and the topology map canvas: the D-02 "Edit
// topology" toggle, a client-side pending-changes count, and the single batched "Apply
// changes" activation. In read-only mode only the Switch renders -- no Banner/Button space is
// reserved, so a kiosk/read-only viewer sees the smallest possible chrome.

import { Banner, Button, Switch } from "kone-design-system";

const CONFIGURATION_HINT =
  "Editing is off: set TOPOLOGY_EDITOR_SECRET in deploy/.env and run the wizard.";

export interface TopologyToolbarProps {
  editMode: boolean;
  onEditModeChange: (next: boolean) => void;
  pendingCount: number;
  applying: boolean;
  onApply: () => void;
  editingConfigured: boolean;
  // When set, the switch is disabled and this text replaces the configuration hint
  // (admin mode: editing and faking states are mutually exclusive).
  disabledReason?: string;
}

export function TopologyToolbar({
  editMode,
  onEditModeChange,
  pendingCount,
  applying,
  onApply,
  editingConfigured,
  disabledReason,
}: TopologyToolbarProps) {
  return (
    <div className="flex items-center gap-2 rounded-md bg-bg-subtle p-3">
      <Switch
        label="Edit topology"
        checked={editMode}
        disabled={!editingConfigured || disabledReason !== undefined}
        onChange={(event) => onEditModeChange(event.target.checked)}
      />
      {editMode && pendingCount > 0 && (
        <Banner
          status="warning"
          message={`${pendingCount} change${pendingCount === 1 ? "" : "s"} not yet applied`}
        />
      )}
      {editMode && (
        <Button
          variant="primary"
          disabled={pendingCount === 0 || applying}
          loading={applying}
          onClick={onApply}
        >
          {applying ? "Applying…" : "Apply changes"}
        </Button>
      )}
      {disabledReason !== undefined ? (
        <span className="text-xs text-fg-tertiary">{disabledReason}</span>
      ) : (
        !editingConfigured && (
          <span className="text-xs text-fg-tertiary">{CONFIGURATION_HINT}</span>
        )
      )}
    </div>
  );
}
