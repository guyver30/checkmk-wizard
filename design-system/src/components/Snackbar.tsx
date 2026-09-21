import { ReactNode } from "react";

export type SnackbarStatus = "info" | "success" | "warning" | "danger";

export interface SnackbarProps {
  status?: SnackbarStatus;
  message: ReactNode;
  actionLabel?: string;
  onAction?: () => void;
  icon?: ReactNode;
}

const statusClasses: Record<SnackbarStatus, { border: string; icon: string }> = {
  info: { border: "border-brand", icon: "bg-brand" },
  success: { border: "border-success", icon: "bg-success" },
  warning: { border: "border-warning", icon: "bg-warning" },
  danger: { border: "border-alert", icon: "bg-alert" },
};

export function Snackbar({ status = "info", message, actionLabel, onAction, icon }: SnackbarProps) {
  const s = statusClasses[status];
  return (
    <div
      role="status"
      className={["flex items-center gap-3 rounded-lg border bg-bg-surface px-4 py-3 shadow-card", s.border].join(
        " "
      )}
    >
      <span
        className={[
          "flex h-5 w-5 shrink-0 items-center justify-center rounded-pill text-xs text-fg-oncolor",
          s.icon,
        ].join(" ")}
      >
        {icon}
      </span>
      <p className="flex-1 text-sm text-fg-primary">{message}</p>
      {actionLabel && (
        <button type="button" onClick={onAction} className="text-sm font-medium text-fg-link hover:text-brand-active">
          {actionLabel}
        </button>
      )}
    </div>
  );
}
