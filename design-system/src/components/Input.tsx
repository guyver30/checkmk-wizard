import { InputHTMLAttributes, ReactNode, TextareaHTMLAttributes, forwardRef } from "react";

export type InputSize = "xs" | "sm" | "md";

const sizeClasses: Record<InputSize, string> = {
  xs: "h-8 px-2.5 text-sm",
  sm: "h-9 px-3 text-sm",
  md: "h-10 px-3.5 text-base",
};

function fieldClasses(size: InputSize, error?: boolean) {
  return [
    "w-full rounded-sm border bg-bg-surface text-fg-primary placeholder:text-fg-placeholder transition-colors",
    "focus:outline-none focus:shadow-focus",
    error ? "border-alert focus:border-alert" : "border-neutral-300 hover:border-neutral-400 focus:border-brand",
    "disabled:cursor-not-allowed disabled:border-neutral-200 disabled:bg-bg-surface-disabled disabled:text-fg-disabled",
    sizeClasses[size],
  ].join(" ");
}

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  label?: ReactNode;
  hint?: ReactNode;
  error?: string;
  size?: InputSize;
  onClear?: () => void;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, hint, error, size = "sm", onClear, className = "", id, ...props }, ref) => {
    const showClear = Boolean(onClear && props.value);
    return (
      <label className="flex flex-col gap-1.5" htmlFor={id}>
        {label && <span className="text-sm font-medium text-fg-primary">{label}</span>}
        <span className="relative flex items-center">
          <input
            ref={ref}
            id={id}
            className={[fieldClasses(size, Boolean(error)), showClear ? "pr-8" : "", className].join(" ")}
            aria-invalid={Boolean(error)}
            {...props}
          />
          {showClear && (
            <button
              type="button"
              onClick={onClear}
              aria-label="Clear"
              className="absolute right-2.5 text-fg-tertiary hover:text-fg-primary"
            >
              &#10005;
            </button>
          )}
        </span>
        {error ? (
          <span className="text-xs text-fg-danger">{error}</span>
        ) : (
          hint && <span className="text-xs text-fg-tertiary">{hint}</span>
        )}
      </label>
    );
  }
);
Input.displayName = "Input";

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: ReactNode;
  hint?: ReactNode;
  error?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ label, hint, error, className = "", id, rows = 4, ...props }, ref) => (
    <label className="flex flex-col gap-1.5" htmlFor={id}>
      {label && <span className="text-sm font-medium text-fg-primary">{label}</span>}
      <textarea
        ref={ref}
        id={id}
        rows={rows}
        className={[
          "w-full resize-y rounded-sm border bg-bg-surface px-3 py-2 text-sm text-fg-primary placeholder:text-fg-placeholder transition-colors",
          "focus:outline-none focus:shadow-focus",
          error ? "border-alert focus:border-alert" : "border-neutral-300 hover:border-neutral-400 focus:border-brand",
          "disabled:cursor-not-allowed disabled:border-neutral-200 disabled:bg-bg-surface-disabled disabled:text-fg-disabled",
          className,
        ].join(" ")}
        aria-invalid={Boolean(error)}
        {...props}
      />
      {error ? (
        <span className="text-xs text-fg-danger">{error}</span>
      ) : (
        hint && <span className="text-xs text-fg-tertiary">{hint}</span>
      )}
    </label>
  )
);
Textarea.displayName = "Textarea";

export interface SearchProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  size?: InputSize;
  onSubmit?: () => void;
}

/** Pill-shaped, distinct from the standard Input's radius-sm field. */
export const Search = forwardRef<HTMLInputElement, SearchProps>(
  ({ size = "sm", onSubmit, className = "", placeholder = "Search", ...props }, ref) => (
    <span className="relative flex items-center">
      <span className="pointer-events-none absolute left-3 text-fg-tertiary" aria-hidden>
        &#128269;
      </span>
      <input
        ref={ref}
        type="search"
        placeholder={placeholder}
        className={[
          "rounded-pill border border-neutral-300 bg-bg-surface pl-9 text-fg-primary placeholder:text-fg-placeholder transition-colors",
          "focus:outline-none focus:border-brand focus:shadow-focus",
          "disabled:cursor-not-allowed disabled:bg-bg-surface-disabled disabled:text-fg-disabled",
          onSubmit ? "pr-9" : "pr-4",
          sizeClasses[size],
          className,
        ].join(" ")}
        {...props}
      />
      {onSubmit && (
        <button
          type="button"
          onClick={onSubmit}
          aria-label="Submit search"
          className="absolute right-1 flex h-7 w-7 items-center justify-center rounded-pill bg-brand text-fg-oncolor hover:bg-brand-hover"
        >
          &#8594;
        </button>
      )}
    </span>
  )
);
Search.displayName = "Search";
