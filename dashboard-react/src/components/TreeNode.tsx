// One tree group node and its device children. Copies the design system's single-open
// collapsible's accessible markup pattern where it is right -- a real
// <button type="button"> with aria-expanded, a decorative chevron <span aria-hidden> that
// rotates when open -- and diverges where that pattern cannot serve a tree: no outer
// rounded-md border box per node (that produces nested boxes, not indentation),
// depth-driven left padding, and a severity-derived accent from node.worst via
// stateMapping.badgeForState, never a second colour table.

import { Link, useLocation } from "react-router";
import { Badge, Checkbox } from "kone-design-system";
import { hostsInFolder, isAdminMode } from "../lib/adminMode";
import { deviceTypeMaskUrl } from "../lib/mapIcons";
import { hostHref, incidentHref } from "../lib/searchLinks";
import { badgeForState } from "../lib/stateMapping";
import type { TreeGroupNode } from "../lib/treeModel";
import type { GroupingMode } from "../lib/types";
import { useAdminStore } from "../store/adminStore";
import { useMapFocusStore } from "../store/mapFocusStore";
import { useAppStore } from "../store/useAppStore";
import { StateBadgeForState } from "./StateBadge";

const INDENT_PX = 16;
const ROW_START_PX = 12;

// Presentational lookup from Badge's abstract `color` prop to a border utility class --
// not a duplicate severity table. The severity itself always comes from badgeForState().
const ACCENT_BORDER_CLASS: Record<string, string> = {
  success: "border-fg-success",
  warning: "border-fg-warning",
  danger: "border-fg-danger",
};

export interface TreeNodeProps {
  node: TreeGroupNode;
  depth: number;
  isOpen: boolean;
  onToggle: (key: string) => void;
  groupingMode?: GroupingMode;
}

export function TreeNode({
  node,
  depth,
  isOpen,
  onToggle,
  groupingMode,
}: TreeNodeProps) {
  const { search } = useLocation();
  // Admin selection (D-12): the admin store and device map are read unconditionally (hooks),
  // but every admin branch below is gated on isAdminMode() so the non-admin DOM is unchanged.
  const admin = isAdminMode();
  const selected = useAdminStore((s) => s.selected);
  const faked = useAdminStore((s) => s.faked);
  const toggleSelected = useAdminStore((s) => s.toggleSelected);
  const setSelected = useAdminStore((s) => s.setSelected);
  const replaceSelection = useAdminStore((s) => s.replaceSelection);
  const allDevices = useAppStore((s) => s.devices);
  const folderAdmin = admin && groupingMode === "folder";
  const folderIds = folderAdmin ? hostsInFolder(node.key, allDevices) : [];
  const folderSelected = folderIds.filter((id) => selected.has(id)).length;
  const folderChecked =
    folderIds.length > 0 && folderSelected === folderIds.length;
  const spec = badgeForState(node.worst);
  const accentClass = ACCENT_BORDER_CLASS[spec.color] ?? "border-neutral-300";

  const header = (
    <button
      type="button"
      onClick={() => onToggle(node.key)}
      aria-expanded={isOpen}
      style={{ paddingLeft: depth * INDENT_PX + ROW_START_PX }}
      className={[
        "flex w-full items-center gap-2 border-l-4 py-2 pr-3 text-left hover:bg-bg-subtle-hover",
        accentClass,
      ].join(" ")}
    >
      <span
        className={[
          "flex h-5 w-5 shrink-0 items-center justify-center text-fg-secondary transition-transform",
          isOpen ? "rotate-180" : "",
        ].join(" ")}
        aria-hidden
      >
        &#9660;
      </span>
      <span className="flex-1 truncate text-sm font-semibold text-fg-primary">
        {node.label}
      </span>
      {node.hatched && (
        <>
          {/* Visible partial-data marker -- decorative, the accessible name comes from the
                sr-only text below so a screen reader doesn't get a redundant/undescribed glyph. */}
          <span
            aria-hidden
            title="Partial data — some devices in this group are stale"
            className="h-2 w-2 shrink-0 rounded-full border border-dashed border-fg-tertiary"
          />
          <span className="sr-only">, some devices have stale data</span>
        </>
      )}
      <span className="shrink-0 text-xs text-fg-tertiary">
        {node.nonOkCount} / {node.total}
      </span>
      {folderAdmin && folderSelected > 0 && (
        <span className="shrink-0 text-xs text-fg-tertiary">
          {folderSelected}/{folderIds.length} selected
        </span>
      )}
      <StateBadgeForState state={node.worst} />
    </button>
  );

  return (
    <div role="treeitem" aria-expanded={isOpen}>
      {folderAdmin ? (
        <div className="flex items-center">
          <span
            className="shrink-0"
            style={{ paddingLeft: depth * INDENT_PX + 4 }}
          >
            <Checkbox
              size="sm"
              aria-label="Select all hosts in this folder"
              title="Select all hosts in this folder"
              checked={folderChecked}
              indeterminate={folderSelected > 0 && !folderChecked}
              onChange={() => setSelected(folderIds, !folderChecked)}
            />
          </span>
          <div className="flex-1">{header}</div>
        </div>
      ) : (
        header
      )}
      {isOpen && (
        <div role="group">
          {node.children.map((device) => {
            const displayState = device.stale ? "STALE" : device.state;
            const ariaLabel = device.dimmed
              ? `${device.label} — part of an open incident`
              : `${device.label} — ${displayState}`;
            const isSelected = admin && selected.has(device.id);
            return (
              <div
                key={device.id}
                role="treeitem"
                style={{ paddingLeft: (depth + 1) * INDENT_PX + ROW_START_PX }}
                aria-label={ariaLabel}
                className={[
                  "flex items-center pr-3",
                  isSelected ? "border-l-4 border-brand bg-brand-light" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
              >
                {admin && (
                  <Checkbox
                    size="sm"
                    aria-label={device.label}
                    checked={selected.has(device.id)}
                    onChange={() => toggleSelected(device.id)}
                  />
                )}
                <Link
                  to={hostHref(search, device.id)}
                  onClick={(event) => {
                    if (admin) {
                      // Admin mode: a row click selects, it never navigates or opens details.
                      event.preventDefault();
                      if (event.ctrlKey || event.metaKey) {
                        toggleSelected(device.id);
                      } else {
                        replaceSelection([device.id]);
                      }
                    }
                  }}
                  onDoubleClick={() => {
                    // Outside admin mode a double-click also centres the map on the host (the
                    // first click already opened its details). In admin mode a double-click is
                    // just two selection clicks.
                    if (!admin) {
                      useMapFocusStore.getState().requestCenter(device.id);
                    }
                  }}
                  className={[
                    "flex flex-1 items-center gap-2 py-1.5 text-sm hover:bg-bg-subtle-hover",
                    device.dimmed ? "opacity-50" : "",
                  ].join(" ")}
                >
                  <span
                    aria-hidden
                    data-device-type={device.deviceType ?? "other"}
                    className="inline-block h-4 w-4 shrink-0 bg-current"
                    style={{
                      maskImage: deviceTypeMaskUrl(device.deviceType),
                      WebkitMaskImage: deviceTypeMaskUrl(device.deviceType),
                      maskSize: "contain",
                      WebkitMaskSize: "contain",
                      maskRepeat: "no-repeat",
                      WebkitMaskRepeat: "no-repeat",
                    }}
                  />
                  {device.tagGroupMissing && (
                    <span
                      role="img"
                      title="Device-type tag group is absent site-wide"
                      aria-label="Device-type tag group is absent site-wide"
                      className="icon-warning-triangle-filled text-fg-warning"
                    />
                  )}
                  <span
                    className="flex-1 truncate text-fg-primary"
                    title={device.address || undefined}
                  >
                    {device.label}
                  </span>
                </Link>
                {device.dimmed && device.incidentId ? (
                  <Link to={incidentHref(search, device.incidentId)}>
                    <Badge color="neutral" variant="outline">
                      See incident
                    </Badge>
                  </Link>
                ) : device.inferredRoot ? (
                  <Badge color="warning" variant="soft">
                    Inferred, not confirmed
                  </Badge>
                ) : (
                  <StateBadgeForState state={displayState} />
                )}
                {admin && faked[device.id] && (
                  <span className="ml-1">
                    <Badge color="neutral" variant="outline">
                      FAKED
                    </Badge>
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
