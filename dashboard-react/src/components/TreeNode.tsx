// One tree group node and its device children. Copies the design system's single-open
// collapsible's accessible markup pattern where it is right -- a real
// <button type="button"> with aria-expanded, a decorative chevron <span aria-hidden> that
// rotates when open -- and diverges where that pattern cannot serve a tree: no outer
// rounded-md border box per node (that produces nested boxes, not indentation),
// depth-driven left padding, and a severity-derived accent from node.worst via
// stateMapping.badgeForState, never a second colour table.

import { Link } from "react-router";
import { badgeForState } from "../lib/stateMapping";
import type { TreeGroupNode } from "../lib/treeModel";
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
}

export function TreeNode({ node, depth, isOpen, onToggle }: TreeNodeProps) {
  const spec = badgeForState(node.worst);
  const accentClass = ACCENT_BORDER_CLASS[spec.color] ?? "border-neutral-300";

  return (
    <div role="treeitem" aria-expanded={isOpen}>
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
        <span className="flex-1 truncate text-sm font-semibold text-fg-primary">{node.label}</span>
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
        <StateBadgeForState state={node.worst} />
      </button>
      {isOpen && (
        <div role="group">
          {node.children.map((device) => {
            const displayState = device.stale ? "STALE" : device.state;
            return (
              <div
                key={device.id}
                role="treeitem"
                style={{ paddingLeft: (depth + 1) * INDENT_PX + ROW_START_PX }}
                aria-label={`${device.label} — ${displayState}`}
              >
                <Link
                  to={`/details?id=${encodeURIComponent(device.id)}`}
                  className="flex items-center gap-2 py-1.5 pr-3 text-sm hover:bg-bg-subtle-hover"
                >
                  <span className={device.typeIcon} aria-hidden />
                  {device.tagGroupMissing && (
                    <span
                      role="img"
                      title="Device-type tag group is absent site-wide"
                      aria-label="Device-type tag group is absent site-wide"
                      className="icon-warning-triangle-filled text-fg-warning"
                    />
                  )}
                  <span className="flex-1 truncate text-fg-primary">{device.label}</span>
                  <StateBadgeForState state={displayState} />
                </Link>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
