export type ProgressColor = "brand" | "success" | "warning" | "danger";

const barColor: Record<ProgressColor, string> = {
  brand: "bg-brand",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-alert",
};

const ringColor: Record<ProgressColor, string> = {
  brand: "stroke-brand",
  success: "stroke-success",
  warning: "stroke-warning",
  danger: "stroke-alert",
};

export interface ProgressBarProps {
  label?: string;
  value: number;
  color?: ProgressColor;
  showValue?: boolean;
}

export function ProgressBar({ label, value, color = "brand", showValue = true }: ProgressBarProps) {
  const clamped = Math.min(100, Math.max(0, value));
  return (
    <div className="flex flex-col gap-1.5">
      {(label || showValue) && (
        <div className="flex items-center justify-between text-sm text-fg-primary">
          <span>{label}</span>
          {showValue && <span>{clamped}%</span>}
        </div>
      )}
      <div
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-1 w-full overflow-hidden rounded-pill bg-brand-light"
      >
        <div className={["h-full rounded-pill transition-all", barColor[color]].join(" ")} style={{ width: `${clamped}%` }} />
      </div>
    </div>
  );
}

export interface ProgressCircleProps {
  value: number;
  size?: number;
  strokeWidth?: number;
  color?: ProgressColor;
  showValue?: boolean;
}

export function ProgressCircle({ value, size = 40, strokeWidth = 4, color = "brand", showValue = false }: ProgressCircleProps) {
  const clamped = Math.min(100, Math.max(0, value));
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - clamped / 100);

  return (
    <span className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} role="progressbar" aria-valuenow={clamped} aria-valuemin={0} aria-valuemax={100}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          className="stroke-brand-light"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          className={["transition-all", ringColor[color]].join(" ")}
        />
      </svg>
      {showValue && (
        <span className="absolute text-xs font-medium text-fg-primary">{clamped}%</span>
      )}
    </span>
  );
}
