import type { ReactNode } from "react";
import { usePaneLayout } from "../hooks/usePaneLayout";
import { Splitter } from "./Splitter";

export interface ThreePaneLayoutProps {
  tree: ReactNode;
  centreTop: ReactNode;
  centreBottom: ReactNode;
}

// Width/height a collapsed pane's rail occupies -- just enough for its restore button.
const COLLAPSED_RAIL_PX = 40;

interface CollapsiblePaneProps {
  title: string;
  collapsed: boolean;
  onToggleCollapse: () => void;
  children: ReactNode;
}

function CollapsiblePane({ title, collapsed, onToggleCollapse, children }: CollapsiblePaneProps) {
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-bg-surface">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-neutral-150 px-3 py-2">
        {!collapsed && <span className="truncate text-sm font-semibold text-fg-primary">{title}</span>}
        <button
          type="button"
          aria-expanded={!collapsed}
          aria-label={collapsed ? `Expand ${title.toLowerCase()}` : `Collapse ${title.toLowerCase()}`}
          onClick={onToggleCollapse}
          className="shrink-0 rounded-sm border border-neutral-300 px-2 py-1 text-xs text-fg-secondary hover:bg-bg-subtle-hover"
        >
          {collapsed ? "Expand" : "Collapse"}
        </button>
      </div>
      {/* A collapsed pane unmounts its content -- only the rail with the restore button remains. */}
      {!collapsed && <div className="min-h-0 flex-1 overflow-auto">{children}</div>}
    </div>
  );
}

/**
 * The three-pane shell: a full-height tree pane on the left, and a centre column split into
 * centreTop (flexible) and centreBottom (the event history, sized by eventsHeight). Per D-31,
 * this wraps its pane contents as props rather than nesting layout structure inside them, so
 * later plans fill slots without ever restructuring this grid.
 */
export function ThreePaneLayout({ tree, centreTop, centreBottom }: ThreePaneLayoutProps) {
  const { sizes, collapsed, setSize, toggleCollapse, commit, bounds } = usePaneLayout();

  const treeColumnWidth = collapsed.tree ? COLLAPSED_RAIL_PX : sizes.tree;
  const eventsRowHeight = collapsed.events ? COLLAPSED_RAIL_PX : sizes.events;

  return (
    <div className="grid h-full w-full" style={{ gridTemplateColumns: `${treeColumnWidth}px 4px 1fr` }}>
      <CollapsiblePane title="Device tree" collapsed={collapsed.tree} onToggleCollapse={() => toggleCollapse("tree")}>
        {tree}
      </CollapsiblePane>

      <Splitter
        orientation="vertical"
        value={sizes.tree}
        min={bounds.tree.min}
        max={bounds.tree.max}
        label="Resize device tree"
        onResize={(next) => setSize("tree", next)}
        onResizeCommit={commit}
      />

      <div className="grid h-full min-h-0 min-w-0" style={{ gridTemplateRows: `1fr 4px ${eventsRowHeight}px` }}>
        <div className="min-h-0 overflow-auto bg-bg-surface">{centreTop}</div>

        <Splitter
          orientation="horizontal"
          value={sizes.events}
          min={bounds.events.min}
          max={bounds.events.max}
          label="Resize event history"
          onResize={(next) => setSize("events", next)}
          onResizeCommit={commit}
        />

        <CollapsiblePane
          title="Event history"
          collapsed={collapsed.events}
          onToggleCollapse={() => toggleCollapse("events")}
        >
          {centreBottom}
        </CollapsiblePane>
      </div>
    </div>
  );
}
