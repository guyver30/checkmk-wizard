import { ReactNode } from "react";

export interface NavItem {
  id: string;
  label: string;
  active?: boolean;
  onClick?: () => void;
}

export interface NavBarProps {
  appName: string;
  logo?: ReactNode;
  items?: NavItem[];
  actions?: ReactNode;
  user?: { name: string; avatar?: ReactNode };
}

/**
 * Desktop main navigation. Clicking the logo/app name should go to the app's
 * home, not kone.com, per the source guideline. Limit nav items to under 5;
 * on narrow viewports, collapse items into a Menu instead (see Menu.tsx).
 */
export function NavBar({ appName, logo, items = [], actions, user }: NavBarProps) {
  return (
    <header className="flex h-14 items-center gap-6 border-b border-neutral-150 bg-bg-surface px-6">
      <a href="#" className="flex items-center gap-2 font-semibold text-fg-primary">
        {logo}
        {appName}
      </a>
      <nav className="flex flex-1 items-center gap-6">
        {items.map((item) => (
          <button
            key={item.id}
            onClick={item.onClick}
            className={[
              "border-b-2 py-4 text-sm font-medium",
              item.active ? "border-brand text-fg-brand" : "border-transparent text-fg-primary hover:text-fg-brand",
            ].join(" ")}
          >
            {item.label}
          </button>
        ))}
      </nav>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
      {user && (
        <div className="flex items-center gap-2 text-sm font-medium text-fg-primary">
          {user.avatar ?? (
            <span className="flex h-7 w-7 items-center justify-center rounded-pill bg-brand-light text-fg-brand">
              {user.name.charAt(0)}
            </span>
          )}
          {user.name}
        </div>
      )}
    </header>
  );
}

export interface AppBarProps {
  title: string;
  onBack?: () => void;
  actions?: ReactNode;
  align?: "left" | "center";
}

/** Compact single-row bar for mobile / sub-pages, with an optional back action. */
export function AppBar({ title, onBack, actions, align = "left" }: AppBarProps) {
  return (
    <header className="flex h-14 items-center gap-3 border-b border-neutral-150 bg-bg-surface px-4">
      {onBack && (
        <button
          onClick={onBack}
          aria-label="Back"
          className="flex h-8 w-8 items-center justify-center rounded-pill bg-brand-light text-fg-brand"
        >
          &#8592;
        </button>
      )}
      <h1 className={["flex-1 text-base font-semibold text-fg-primary", align === "center" ? "text-center" : ""].join(" ")}>
        {title}
      </h1>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  );
}
