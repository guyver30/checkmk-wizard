import { ReactNode } from "react";
import { Button } from "./Button";

export type MessageStatus = "info" | "success" | "warning" | "danger";

const iconBgClasses: Record<MessageStatus, string> = {
  info: "bg-brand-light text-fg-brand",
  success: "bg-success-light text-fg-success",
  warning: "bg-warning-light text-fg-warning",
  danger: "bg-alert-light text-fg-danger",
};

export interface MessageProps {
  status?: MessageStatus;
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm?: () => void;
  onCancel?: () => void;
  /** The source guideline notes built-in (inline) messages should have no shadow. */
  shadow?: boolean;
}

export function Message({
  status = "info",
  title,
  description,
  icon,
  confirmLabel = "OK",
  cancelLabel = "Cancel",
  onConfirm,
  onCancel,
  shadow = true,
}: MessageProps) {
  return (
    <div
      className={["flex gap-3 rounded-lg border border-neutral-150 bg-bg-surface p-4", shadow ? "shadow-card" : ""].join(
        " "
      )}
    >
      <span
        className={["flex h-6 w-6 shrink-0 items-center justify-center rounded-pill", iconBgClasses[status]].join(
          " "
        )}
      >
        {icon}
      </span>
      <div className="flex-1">
        <p className="text-sm font-semibold text-fg-primary">{title}</p>
        {description && <p className="mt-1 text-sm text-fg-secondary">{description}</p>}
        {(onConfirm || onCancel) && (
          <div className="mt-3 flex justify-end gap-2">
            {onCancel && (
              <Button variant="secondary" size="sm" onClick={onCancel}>
                {cancelLabel}
              </Button>
            )}
            {onConfirm && (
              <Button variant="primary" size="sm" onClick={onConfirm}>
                {confirmLabel}
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
