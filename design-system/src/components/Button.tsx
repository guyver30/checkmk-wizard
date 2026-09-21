import { ButtonHTMLAttributes, forwardRef } from "react";

export type ButtonVariant = "primary" | "secondary" | "tertiary" | "destructive" | "neutral";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    "bg-bg-control-primary text-fg-oncolor hover:bg-bg-control-primary-hover active:bg-bg-control-primary-active disabled:bg-bg-control-primary-disabled disabled:text-fg-oncolor/70",
  secondary:
    "bg-brand-light text-brand hover:bg-brand-light-hover active:bg-brand-light-active disabled:bg-bg-subtle-disabled disabled:text-fg-disabled",
  tertiary:
    "bg-transparent text-brand hover:bg-brand-light active:bg-brand-light-hover disabled:bg-transparent disabled:text-fg-disabled",
  destructive:
    "bg-bg-surface text-alert border border-alert hover:bg-alert-light active:bg-alert active:text-fg-oncolor disabled:border-neutral-200 disabled:text-fg-disabled",
  neutral:
    "bg-bg-surface text-fg-primary border border-neutral-300 hover:bg-bg-surface-hover active:bg-bg-surface-active disabled:border-neutral-200 disabled:text-fg-disabled",
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-9 px-4 text-sm gap-2",
  lg: "h-11 px-5 text-base gap-2",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "primary", size = "md", loading = false, disabled, className = "", children, ...props }, ref) => {
    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={[
          "inline-flex items-center justify-center rounded-pill font-medium transition-colors",
          "focus-visible:outline-none focus-visible:shadow-focus disabled:cursor-not-allowed",
          variantClasses[variant],
          sizeClasses[size],
          className,
        ].join(" ")}
        {...props}
      >
        {loading && (
          <span
            className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
            aria-hidden
          />
        )}
        {children}
      </button>
    );
  }
);

Button.displayName = "Button";
