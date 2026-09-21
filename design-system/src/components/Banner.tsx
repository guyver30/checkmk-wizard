import { ReactNode } from "react";

export type BannerStatus = "info" | "success" | "warning" | "danger";

export interface BannerProps {
  status?: BannerStatus;
  message: ReactNode;
  icon?: ReactNode;
  onDismiss?: () => void;
}

const statusClasses: Record<BannerStatus, string> = {
  info: "bg-brand-light border-brand text-fg-primary",
  success: "bg-success-light border-success text-fg-primary",
  warning: "bg-warning-light border-warning text-fg-primary",
  danger: "bg-alert-light border-alert text-fg-primary",
};

const iconClasses: Record<BannerStatus, string> = {
  info: "bg-brand",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-alert",
};

export function Banner({ status = "info", message, icon, onDismiss }: BannerProps) {
  return (
    <div
      role="alert"
      className={["flex items-center gap-3 border-b px-4 py-3 text-sm", statusClasses[status]].join(" ")}
    >
      {icon && (
        <span
          className={[
            "flex h-5 w-5 shrink-0 items-center justify-center rounded-pill text-xs text-fg-oncolor",
            iconClasses[status],
          ].join(" ")}
        >
          {icon}
        </span>
      )}
      <p className="flex-1">{message}</p>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="shrink-0 text-fg-secondary hover:text-fg-primary"
        >
          &#10005;
        </button>
      )}
    </div>
  );
}
