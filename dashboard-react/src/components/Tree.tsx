// The device tree pane. Open-group state is a Set<string> LIFTED to the caller rather than
// local useState, so (a) more than one group can be open at once -- the design system's
// single-open collapsible primitive cannot represent that -- and (b) a future re-sort or
// collapsed-group requirement is a plain set operation, never per-node internal state a
// reorder would destroy.

import type { TreeGroupNode } from "../lib/treeModel";
import { TreeNode } from "./TreeNode";

export interface TreeProps {
  groups: TreeGroupNode[];
  openKeys: Set<string>;
  onToggle: (key: string) => void;
}

export function Tree({ groups, openKeys, onToggle }: TreeProps) {
  if (groups.length === 0) {
    return <p className="p-3 text-sm text-fg-tertiary">No devices</p>;
  }

  return (
    <div role="tree" aria-label="Device tree">
      {groups.map((group) => (
        <TreeNode
          key={group.key}
          node={group}
          depth={0}
          isOpen={openKeys.has(group.key)}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}
