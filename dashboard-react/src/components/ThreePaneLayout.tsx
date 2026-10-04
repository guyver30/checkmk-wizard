import { useEffect, useRef, type ReactNode } from "react";
import { usePaneLayout } from "../hooks/usePaneLayout";
import { Splitter } from "./Splitter";

export interface ThreePaneLayoutProps {
  tree: ReactNode;
  centreTop: ReactNode;
  // Omitted (e.g. in topology edit mode) to give centreTop the whole column height.
  centreBottom?: ReactNode;
  // The right column stacks `incidents` (top) above `details` (bottom). Both are optional and
  // both are omitted in topology edit mode. `incidentsSummary` (count + severity badge) stays
  // visible in the incidents pane header even while that pane is collapsed.
  incidents?: ReactNode;
  incidentsSummary?: ReactNode;
  // The Service needs pane sits beside `incidents` (side by side from 1280px, stacked below it
  // under that), and, unlike incidents, may stay set in topology edit mode.
  needs?: ReactNode;
  needsSummary?: ReactNode;
  details?: ReactNode;
  detailsKey?: string | null;
  onCloseDetails?: () => void;
}

// Width/height a collapsed pane's rail occupies -- just enough for its restore button.
const COLLAPSED_RAIL_PX = 40;

// Narrowest right column that still fits the incidents and needs panes side by side.
const NEEDS_COLUMN_MIN_PX = 640;

// Which edge of the layout a pane sits on. It decides which way the collapse/expand chevron
// points: towards the edge the pane collapses into, and back out again.
type PaneSide = "left" | "right" | "bottom" | "top";

interface CollapsiblePaneProps {
  title: string;
  side: PaneSide;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onClose?: () => void;
  // Always-visible header content right after the title (e.g. the incidents count badge).
  headerExtra?: ReactNode;
  // How a collapsed pane looks: a "rail" is just the restore chevron (plus headerExtra) in a
  // narrow strip; a "bar" keeps the whole header and only drops the body.
  collapsedAs?: "rail" | "bar";
  children: ReactNode;
}

// Chevron rotation per side, for the "collapse" direction; "expand" is the opposite (180deg).
const COLLAPSE_ROTATION: Record<PaneSide, number> = { left: 180, right: 0, bottom: 90, top: 270 };

// Inline SVG icons (stroke = currentColor), so no icon library is added for three glyphs.
function ChevronIcon({ rotation }: { rotation: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      style={{ transform: `rotate(${rotation}deg)` }}
    >
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      aria-hidden
    >
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

const ICON_BUTTON_CLASS =
  "flex h-7 w-7 shrink-0 items-center justify-center rounded-sm text-fg-secondary hover:bg-bg-subtle-hover hover:text-fg-primary";

function CollapsiblePane({
  title,
  side,
  collapsed,
  onToggleCollapse,
  onClose,
  headerExtra,
  collapsedAs = "rail",
  children,
}: CollapsiblePaneProps) {
  const asRail = collapsed && collapsedAs === "rail";
  const toggleLabel = collapsed ? `Expand ${title.toLowerCase()}` : `Collapse ${title.toLowerCase()}`;
  const closeLabel = `Close ${title.toLowerCase()}`;
  const collapseRotation = COLLAPSE_ROTATION[side];
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-bg-surface">
      <div
        className={[
          "flex shrink-0 items-center gap-1 border-b border-neutral-150 py-1.5",
          asRail ? "flex-col justify-center px-1" : "justify-between px-3",
        ].join(" ")}
      >
        {!asRail && (
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate text-sm font-semibold text-fg-primary">{title}</span>
            {headerExtra}
          </div>
        )}
        <div className={["flex shrink-0 items-center gap-1", asRail ? "flex-col" : ""].join(" ")}>
          <button
            type="button"
            aria-expanded={!collapsed}
            aria-label={toggleLabel}
            title={toggleLabel}
            onClick={onToggleCollapse}
            className={ICON_BUTTON_CLASS}
          >
            <ChevronIcon rotation={collapsed ? collapseRotation + 180 : collapseRotation} />
          </button>
          {asRail && headerExtra}
          {!asRail && onClose && (
            <button type="button" aria-label={closeLabel} title={closeLabel} onClick={onClose} className={ICON_BUTTON_CLASS}>
              <CloseIcon />
            </button>
          )}
        </div>
      </div>
      {/* A collapsed pane unmounts its content -- only the rail/bar with the restore button remains. */}
      {!collapsed && <div className="min-h-0 flex-1 overflow-auto">{children}</div>}
    </div>
  );
}

/**
 * The three-pane shell: a full-height tree pane on the left, and a centre column split into
 * centreTop (flexible) and centreBottom (the event history, sized by eventsHeight), and an
 * optional right column stacking the Incidents pane above the Host details pane. Per D-31,
 * this wraps its pane contents as props rather than nesting layout structure inside them, so
 * later plans fill slots without ever restructuring this grid.
 */
export function ThreePaneLayout({
  tree,
  centreTop,
  centreBottom,
  incidents,
  incidentsSummary,
  needs,
  needsSummary,
  details,
  detailsKey,
  onCloseDetails,
}: ThreePaneLayoutProps) {
  const { sizes, collapsed, setSize, toggleCollapse, expand, commit, bounds } = usePaneLayout();

  const treeColumnWidth = collapsed.tree ? COLLAPSED_RAIL_PX : sizes.tree;
  const eventsRowHeight = collapsed.events ? COLLAPSED_RAIL_PX : sizes.events;

  // Right column: incidents (top) above host details (bottom). The column shrinks to a rail only
  // when every pane in it is collapsed; otherwise a collapsed pane becomes a header bar so the
  // incidents count badge and the restore chevrons stay visible without wasting column width.
  // The incidents and needs panes share the column's top cell (the "alerts" cell), side by side
  // from 1280px and stacked below that. Side by side they need more width than incidents alone
  // does, so the column never renders narrower than NEEDS_COLUMN_MIN_PX while needs is set.
  const rightColumn = Boolean(incidents || needs || details);
  const incidentsOpen = Boolean(incidents) && !collapsed.incidents;
  const needsOpen = Boolean(needs) && !collapsed.needs;
  const alertsOpen = incidentsOpen || needsOpen;
  const hasAlerts = Boolean(incidents || needs);
  const detailsOpen = Boolean(details) && !collapsed.details;
  const columnRailed = !alertsOpen && !detailsOpen;
  const openColumnWidth = needs ? Math.max(sizes.details, NEEDS_COLUMN_MIN_PX) : sizes.details;
  const detailsColumnWidth = columnRailed ? COLLAPSED_RAIL_PX : openColumnWidth;
  const stacked = hasAlerts && Boolean(details);
  let rightRows = "1fr";
  if (stacked && !columnRailed) {
    if (alertsOpen && detailsOpen) {
      rightRows = `${sizes.incidents}px 4px 1fr`;
    } else {
      rightRows = alertsOpen ? "1fr auto" : "auto 1fr";
    }
  }
  const alertsSide: PaneSide = stacked ? "top" : "right";
  // A collapsed pane drops to its header bar; the open sibling takes the rest of the cell.
  const alertCellClass = (open: boolean) =>
    ["grid min-h-0 min-w-0", open ? "flex-1" : "flex-none"].join(" ");

  // Re-expand rule (operator decision 3): a NEW host opening (detailsKey changes to a truthy,
  // different value) re-expands a collapsed pane -- the operator just asked to see a host, so a
  // stale "collapsed" state shouldn't hide it. A reload (this ref starts at the mount-time key)
  // or re-clicking the already-open host (detailsKey unchanged) never overrides a remembered
  // collapsed state -- only the Expand button does those. Known limitation: re-clicking the
  // already-open host while collapsed does not re-expand it, since the URL (and so detailsKey)
  // doesn't change.
  const previousDetailsKeyRef = useRef(detailsKey);
  useEffect(() => {
    if (detailsKey && detailsKey !== previousDetailsKeyRef.current) {
      expand("details");
    }
    previousDetailsKeyRef.current = detailsKey;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- expand is a stable function from
    // usePaneLayout (recreated each render, but its identity is never referenced by callers as
    // a dependency elsewhere in this codebase); only detailsKey should re-run this.
  }, [detailsKey]);

  const gridTemplateColumns = rightColumn
    ? `${treeColumnWidth}px 4px 1fr 4px ${detailsColumnWidth}px`
    : `${treeColumnWidth}px 4px 1fr`;

  return (
    <div className="grid h-full w-full" style={{ gridTemplateColumns }}>
      <CollapsiblePane title="Device tree" side="left" collapsed={collapsed.tree} onToggleCollapse={() => toggleCollapse("tree")}>
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

      <div
        className="grid h-full min-h-0 min-w-0"
        style={{ gridTemplateRows: centreBottom ? `1fr 4px ${eventsRowHeight}px` : "1fr" }}
      >
        <div className="min-h-0 overflow-auto bg-bg-surface">{centreTop}</div>

        {centreBottom && (
          <>
            {/* sizes.events stores the BOTTOM pane's (event history) own height, but this
                divider sits between a top pane (centreTop) that should grow when you drag DOWN --
                the natural "boundary follows the cursor" convention for a divider above a fixed-size
                pane. Splitter's own contract is the opposite: dragging down always INCREASES the
                value you give it (see Splitter.tsx's docstring, "wire that up in how they compute
                the size they pass in, not by inverting this component"). So the value/onResize here
                are mirrored around the pane's min+max range: as the mirrored value goes up (drag
                down), the real eventsHeight goes down (event history shrinks, map grows) -- and vice
                versa. Confirmed backwards in live testing before this mirroring was added
                (2026-09-23): dragging down was shrinking the map instead of growing it. */}
            <Splitter
              orientation="horizontal"
              value={bounds.events.min + bounds.events.max - sizes.events}
              min={bounds.events.min}
              max={bounds.events.max}
              label="Resize event history"
              onResize={(next) => setSize("events", bounds.events.min + bounds.events.max - next)}
              onResizeCommit={commit}
            />

            <CollapsiblePane
              title="Event history"
              side="bottom"
              collapsed={collapsed.events}
              onToggleCollapse={() => toggleCollapse("events")}
            >
              {centreBottom}
            </CollapsiblePane>
          </>
        )}
      </div>

      {rightColumn && (
        <>
          {/* Mirrored-value pattern, same reasoning as the event-history splitter above: sizes.details
              is the column's own width, but this divider sits on the column's LEFT edge, where dragging
              LEFT (into the centre column) should widen it -- the opposite of Splitter's own
              "dragging right always increases value" contract. */}
          <Splitter
            orientation="vertical"
            value={bounds.details.min + bounds.details.max - sizes.details}
            min={bounds.details.min}
            max={bounds.details.max}
            label="Resize right column"
            onResize={(next) => setSize("details", bounds.details.min + bounds.details.max - next)}
            onResizeCommit={commit}
          />

          {columnRailed ? (
            <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-bg-surface">
              {incidents && (
                <div className="shrink-0">
                  <CollapsiblePane
                    title="Incidents"
                    side="right"
                    collapsed
                    collapsedAs="rail"
                    headerExtra={incidentsSummary}
                    onToggleCollapse={() => toggleCollapse("incidents")}
                  >
                    {incidents}
                  </CollapsiblePane>
                </div>
              )}
              {needs && (
                <div className="shrink-0">
                  <CollapsiblePane
                    title="Service needs"
                    side="right"
                    collapsed
                    collapsedAs="rail"
                    headerExtra={needsSummary}
                    onToggleCollapse={() => toggleCollapse("needs")}
                  >
                    {needs}
                  </CollapsiblePane>
                </div>
              )}
              {details && (
                <div className="shrink-0">
                  <CollapsiblePane
                    title="Host details"
                    side="right"
                    collapsed
                    collapsedAs="rail"
                    onToggleCollapse={() => toggleCollapse("details")}
                    onClose={onCloseDetails}
                  >
                    {details}
                  </CollapsiblePane>
                </div>
              )}
            </div>
          ) : (
            <div className="grid h-full min-h-0 min-w-0" style={{ gridTemplateRows: rightRows }}>
              {hasAlerts && (
                <div className="flex h-full min-h-0 min-w-0 flex-col min-[1280px]:flex-row">
                  {incidents && (
                    <div className={alertCellClass(incidentsOpen)}>
                      <CollapsiblePane
                        title="Incidents"
                        side={alertsSide}
                        collapsed={collapsed.incidents}
                        collapsedAs="bar"
                        headerExtra={incidentsSummary}
                        onToggleCollapse={() => toggleCollapse("incidents")}
                      >
                        {incidents}
                      </CollapsiblePane>
                    </div>
                  )}
                  {needs && (
                    <div className={alertCellClass(needsOpen)}>
                      <CollapsiblePane
                        title="Service needs"
                        side={alertsSide}
                        collapsed={collapsed.needs}
                        collapsedAs="bar"
                        headerExtra={needsSummary}
                        onToggleCollapse={() => toggleCollapse("needs")}
                      >
                        {needs}
                      </CollapsiblePane>
                    </div>
                  )}
                </div>
              )}

              {alertsOpen && detailsOpen && (
                <Splitter
                  orientation="horizontal"
                  value={sizes.incidents}
                  min={bounds.incidents.min}
                  max={bounds.incidents.max}
                  label="Resize incidents"
                  onResize={(next) => setSize("incidents", next)}
                  onResizeCommit={commit}
                />
              )}

              {details && (
                <CollapsiblePane
                  title="Host details"
                  side={stacked ? "bottom" : "right"}
                  collapsed={collapsed.details}
                  collapsedAs="bar"
                  onToggleCollapse={() => toggleCollapse("details")}
                  onClose={onCloseDetails}
                >
                  {details}
                </CollapsiblePane>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
