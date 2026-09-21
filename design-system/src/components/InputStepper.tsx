export type InputStepperSize = "sm" | "md";

export interface InputStepperProps {
  label?: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  size?: InputStepperSize;
  disabled?: boolean;
  error?: boolean;
  onChange: (value: number) => void;
}

const sizeClasses: Record<InputStepperSize, string> = {
  sm: "h-8 text-sm",
  md: "h-9 text-base",
};

export function InputStepper({
  label,
  value,
  min = -Infinity,
  max = Infinity,
  step = 1,
  size = "sm",
  disabled = false,
  error = false,
  onChange,
}: InputStepperProps) {
  const clamp = (n: number) => Math.min(max, Math.max(min, n));

  return (
    <label className="flex flex-col gap-1.5">
      {label && <span className="text-sm font-medium text-fg-primary">{label}</span>}
      <span
        className={[
          "inline-flex w-fit items-stretch overflow-hidden rounded-sm border bg-bg-surface",
          error ? "border-alert" : "border-neutral-300",
          disabled ? "opacity-60" : "",
          sizeClasses[size],
        ].join(" ")}
      >
        <button
          type="button"
          disabled={disabled || value <= min}
          onClick={() => onChange(clamp(value - step))}
          aria-label="Decrease"
          className="flex w-8 items-center justify-center border-r border-neutral-300 text-fg-secondary hover:bg-bg-surface-hover disabled:cursor-not-allowed disabled:text-fg-disabled"
        >
          &#8722;
        </button>
        <span className="flex w-10 items-center justify-center text-fg-primary">{value}</span>
        <button
          type="button"
          disabled={disabled || value >= max}
          onClick={() => onChange(clamp(value + step))}
          aria-label="Increase"
          className="flex w-8 items-center justify-center border-l border-neutral-300 text-fg-secondary hover:bg-bg-surface-hover disabled:cursor-not-allowed disabled:text-fg-disabled"
        >
          &#43;
        </button>
      </span>
    </label>
  );
}
