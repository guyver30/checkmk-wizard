import { useEffect, useRef, type ReactNode } from "react";
import { usePaneLayout } from "../hooks/usePaneLayout";
import { Splitter } from "./Splitter";

export interface ThreePaneLayoutProps {
  tree: ReactNode;
  centreTop: ReactNode;
  centreBottom: ReactNode;
  details?: ReactNode;
  detailsKey?: string | null;
  onCloseDetails?: () => void;
}

// Width/height a collapsed pane's rail occupies -- just enough for its restore button.
const COLLAPSED_RAIL_PX = 40;

// Which edge of the layout a pane sits on. It decides which way the collapse/expand chevron
// points: towards the edge the pane collapses into, and back out again.
type PaneSide = "left" | "right" | "bottom";

interface CollapsiblePaneProps {
  title: string;
  side: PaneSide;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onClose?: () => void;
  children: ReactNode;
}

// Chevron rotation per side, for the "collapse" direction; "expand" is the opposite (180deg).
const COLLAPSE_ROTATION: Record<PaneSide, number> = { left: 180, right: 0, bottom: 90 };

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

function CollapsiblePane({ title, side, collapsed, onToggleCollapse, onClose, children }: CollapsiblePaneProps) {
  const toggleLabel = collapsed ? `Expand ${title.toLowerCase()}` : `Collapse ${title.toLowerCase()}`;
  const closeLabel = `Close ${title.toLowerCase()}`;
  const collapseRotation = COLLAPSE_ROTATION[side];
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-bg-surface">
      <div
        className={[
          "flex shrink-0 items-center gap-1 border-b border-neutral-150 py-1.5",
          collapsed ? "justify-center px-1" : "justify-between px-3",
        ].join(" ")}
      >
        {!collapsed && <span className="truncate text-sm font-semibold text-fg-primary">{title}</span>}
        <div className="flex shrink-0 items-center gap-1">
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
          {!collapsed && onClose && (
            <button type="button" aria-label={closeLabel} title={closeLabel} onClick={onClose} className={ICON_BUTTON_CLASS}>
              <CloseIcon />
            </button>
          )}
        </div>
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
export function ThreePaneLayout({
  tree,
  centreTop,
  centreBottom,
  details,
  detailsKey,
  onCloseDetails,
}: ThreePaneLayoutProps) {
  const { sizes, collapsed, setSize, toggleCollapse, expand, commit, bounds } = usePaneLayout();

  const treeColumnWidth = collapsed.tree ? COLLAPSED_RAIL_PX : sizes.tree;
  const eventsRowHeight = collapsed.events ? COLLAPSED_RAIL_PX : sizes.events;
  const detailsColumnWidth = collapsed.details ? COLLAPSED_RAIL_PX : sizes.details;

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

  const gridTemplateColumns = details
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

      <div className="grid h-full min-h-0 min-w-0" style={{ gridTemplateRows: `1fr 4px ${eventsRowHeight}px` }}>
        <div className="min-h-0 overflow-auto bg-bg-surface">{centreTop}</div>

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
      </div>

      {details && (
        <>
          {/* Mirrored-value pattern, same reasoning as the event-history splitter above: sizes.details
              is the pane's own width, but this divider sits on the pane's LEFT edge, where dragging
              LEFT (into the centre column) should widen it -- the opposite of Splitter's own
              "dragging right always increases value" contract. */}
          <Splitter
            orientation="vertical"
            value={bounds.details.min + bounds.details.max - sizes.details}
            min={bounds.details.min}
            max={bounds.details.max}
            label="Resize host details"
            onResize={(next) => setSize("details", bounds.details.min + bounds.details.max - next)}
            onResizeCommit={commit}
          />

          <CollapsiblePane
            title="Host details"
            side="right"
            collapsed={collapsed.details}
            onToggleCollapse={() => toggleCollapse("details")}
            onClose={onCloseDetails}
          >
            {details}
          </CollapsiblePane>
        </>
      )}
    </div>
  );
}
