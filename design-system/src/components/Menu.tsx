import { ReactNode } from "react";

export interface MenuItemData {
  id: string;
  label: string;
  icon?: ReactNode;
  danger?: boolean;
  onSelect?: () => void;
}

export interface MenuProps {
  items: MenuItemData[];
}

/** Concise, navigation-focused dropdown -- keep to 7 items or fewer. */
export function Menu({ items }: MenuProps) {
  return (
    <div className="w-56 rounded-md border border-neutral-150 bg-bg-surface py-1.5 shadow-menu" role="menu">
      {items.map((item) => (
        <button
          key={item.id}
          role="menuitem"
          onClick={item.onSelect}
          className={[
            "flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm hover:bg-bg-surface-hover",
            item.danger ? "text-fg-danger" : "text-fg-primary",
          ].join(" ")}
        >
          {item.icon && <span className="shrink-0">{item.icon}</span>}
          {item.label}
        </button>
      ))}
    </div>
  );
}
