import { ReactNode } from "react";

export type StaticDataSize = "xs" | "sm" | "md";

const sizeClasses: Record<StaticDataSize, string> = {
  xs: "h-8 text-sm",
  sm: "h-9 text-sm",
  md: "h-10 text-base",
};

export interface StaticDataProps {
  label?: ReactNode;
  value: ReactNode;
  size?: StaticDataSize;
}

/** Non-editing (read-only) state of an input-like field -- match the size to the live control it replaces. */
export function StaticData({ label, value, size = "sm" }: StaticDataProps) {
  return (
    <div className="flex flex-col gap-1.5">
      {label && <span className="text-sm font-medium text-fg-secondary">{label}</span>}
      <span className={["flex items-center px-0.5 text-fg-primary", sizeClasses[size]].join(" ")}>{value}</span>
    </div>
  );
}
