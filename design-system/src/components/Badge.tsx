import { ReactNode } from "react";

export type BadgeColor = "neutral" | "black" | "success" | "warning" | "danger" | "info" | "purple";
export type BadgeVariant = "outline" | "soft" | "solid";

export interface BadgeProps {
  color?: BadgeColor;
  variant?: BadgeVariant;
  icon?: ReactNode;
  children: ReactNode;
}

const colorMap: Record<BadgeColor, { text: string; border: string; soft: string; solid: string }> = {
  neutral: { text: "text-fg-secondary", border: "border-neutral-300", soft: "bg-bg-subtle", solid: "bg-neutral-600" },
  black: { text: "text-fg-onwhite", border: "border-neutral-900", soft: "bg-bg-subtle", solid: "bg-neutral-900" },
  success: { text: "text-fg-success", border: "border-success", soft: "bg-success-light", solid: "bg-success" },
  warning: { text: "text-fg-warning", border: "border-warning", soft: "bg-warning-light", solid: "bg-warning" },
  danger: { text: "text-fg-danger", border: "border-alert", soft: "bg-alert-light", solid: "bg-alert" },
  info: { text: "text-fg-brand", border: "border-brand", soft: "bg-brand-light", solid: "bg-brand" },
  purple: { text: "text-purple-500", border: "border-purple-500", soft: "bg-brand-light", solid: "bg-purple-500" },
};

export function Badge({ color = "neutral", variant = "outline", icon, children }: BadgeProps) {
  const c = colorMap[color];
  const variantClasses =
    variant === "outline"
      ? `bg-bg-surface border ${c.border} ${c.text}`
      : variant === "soft"
      ? `${c.soft} ${c.text}`
      : `${c.solid} text-fg-oncolor`;

  return (
    <span
      className={["inline-flex items-center gap-1 rounded-pill px-2.5 py-1 text-xs font-medium", variantClasses].join(
        " "
      )}
    >
      {icon}
      {children}
    </span>
  );
}

export type CounterBadgeColor = "danger" | "brand" | "neutral" | "outline";

export interface CounterBadgeProps {
  count: number;
  max?: number;
  color?: CounterBadgeColor;
  /** Renders as a small dot with no number, e.g. for unread indicators. */
  dot?: boolean;
}

const counterColorMap: Record<CounterBadgeColor, string> = {
  danger: "bg-alert text-fg-oncolor",
  brand: "bg-brand text-fg-oncolor",
  neutral: "bg-bg-subtle text-fg-primary",
  outline: "bg-bg-surface text-fg-primary border border-neutral-300",
};

/** Sits on the top-right corner of an icon, or inline with a label. */
export function CounterBadge({ count, max = 99, color = "danger", dot = false }: CounterBadgeProps) {
  if (dot) {
    return <span className={["h-2.5 w-2.5 rounded-pill", counterColorMap[color].split(" ")[0]].join(" ")} aria-hidden />;
  }
  const label = count > max ? `${max}+` : String(count);
  return (
    <span
      className={[
        "inline-flex h-5 min-w-[20px] items-center justify-center rounded-pill px-1.5 text-xs font-semibold leading-none",
        counterColorMap[color],
      ].join(" ")}
    >
      {label}
    </span>
  );
}

export type StatusBadgeStatus = "connected" | "low-signal" | "entrapment" | "unknown";

const statusMap: Record<StatusBadgeStatus, { dot: string; text: string }> = {
  connected: { dot: "bg-success", text: "text-fg-primary" },
  "low-signal": { dot: "bg-warning", text: "text-fg-primary" },
  entrapment: { dot: "bg-alert", text: "text-fg-danger" },
  unknown: { dot: "bg-neutral-400", text: "text-fg-tertiary" },
};

export function StatusBadge({ status, children }: { status: StatusBadgeStatus; children: ReactNode }) {
  const s = statusMap[status];
  return (
    <span className={["inline-flex items-center gap-1.5 text-sm font-medium", s.text].join(" ")}>
      <span className={["h-2 w-2 rounded-pill", s.dot].join(" ")} aria-hidden />
      {children}
    </span>
  );
}
