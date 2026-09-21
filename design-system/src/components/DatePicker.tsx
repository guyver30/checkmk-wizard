import { useState } from "react";

const WEEKDAYS = ["M", "T", "W", "T", "F", "Sa", "Su"];
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function daysInMonth(year: number, month: number) {
  return new Date(year, month + 1, 0).getDate();
}

function startWeekday(year: number, month: number) {
  const day = new Date(year, month, 1).getDay(); // 0 = Sunday
  return (day + 6) % 7; // convert to Monday-first
}

export interface CalendarProps {
  value?: Date;
  viewDate: Date;
  onSelect: (date: Date) => void;
  onViewChange: (date: Date) => void;
}

/** Month-grid calendar, Monday-first, matching the source date-picker sheet. */
export function Calendar({ value, viewDate, onSelect, onViewChange }: CalendarProps) {
  const year = viewDate.getFullYear();
  const month = viewDate.getMonth();
  const total = daysInMonth(year, month);
  const offset = startWeekday(year, month);
  const cells = [...Array(offset).fill(null), ...Array.from({ length: total }, (_, i) => i + 1)];

  return (
    <div className="w-72 rounded-md border border-neutral-150 bg-bg-surface p-4 shadow-menu">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm font-semibold text-fg-brand">
          {MONTHS[month]} {year}
        </span>
        <div className="flex items-center gap-1">
          <button
            aria-label="Previous month"
            onClick={() => onViewChange(new Date(year, month - 1, 1))}
            className="flex h-6 w-6 items-center justify-center rounded-pill text-fg-secondary hover:bg-bg-surface-hover"
          >
            &#8249;
          </button>
          <button
            aria-label="Next month"
            onClick={() => onViewChange(new Date(year, month + 1, 1))}
            className="flex h-6 w-6 items-center justify-center rounded-pill text-fg-secondary hover:bg-bg-surface-hover"
          >
            &#8250;
          </button>
        </div>
      </div>
      <div className="grid grid-cols-7 gap-y-1 text-center text-xs text-fg-tertiary">
        {WEEKDAYS.map((d, i) => (
          <span key={i}>{d}</span>
        ))}
        {cells.map((day, i) => {
          const isSelected =
            day !== null &&
            value &&
            value.getFullYear() === year &&
            value.getMonth() === month &&
            value.getDate() === day;
          return (
            <button
              key={i}
              disabled={day === null}
              onClick={() => day && onSelect(new Date(year, month, day))}
              className={[
                "flex h-8 w-8 items-center justify-center rounded-pill text-sm",
                day === null ? "invisible" : isSelected ? "bg-brand text-fg-oncolor" : "text-fg-primary hover:bg-bg-surface-hover",
              ].join(" ")}
            >
              {day}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export interface DatePickerProps {
  label?: string;
  value?: Date;
  onChange: (date: Date) => void;
  error?: string;
  disabled?: boolean;
}

function formatDate(date?: Date) {
  if (!date) return "";
  return `${String(date.getDate()).padStart(2, "0")}/${String(date.getMonth() + 1).padStart(2, "0")}/${date.getFullYear()}`;
}

/** Input field specifically for date values -- prefer the browser default input where possible. */
export function DatePicker({ label, value, onChange, error, disabled }: DatePickerProps) {
  const [open, setOpen] = useState(false);
  const [viewDate, setViewDate] = useState(value ?? new Date());

  return (
    <div className="relative flex flex-col gap-1.5">
      {label && <span className="text-sm font-medium text-fg-primary">{label}</span>}
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className={[
          "flex h-9 items-center justify-between rounded-sm border bg-bg-surface px-3 text-sm transition-colors",
          error ? "border-alert" : "border-neutral-300 hover:border-neutral-400",
          open ? "border-brand shadow-focus" : "",
          disabled ? "cursor-not-allowed border-neutral-200 bg-bg-surface-disabled text-fg-disabled" : "text-fg-primary",
        ].join(" ")}
      >
        <span className={value ? "" : "text-fg-placeholder"}>{value ? formatDate(value) : "Select date"}</span>
        <span aria-hidden>&#128197;</span>
      </button>
      {error && <span className="text-xs text-fg-danger">{error}</span>}
      {open && !disabled && (
        <div className="absolute top-full z-10 mt-1">
          <Calendar
            value={value}
            viewDate={viewDate}
            onViewChange={setViewDate}
            onSelect={(date) => {
              onChange(date);
              setOpen(false);
            }}
          />
        </div>
      )}
    </div>
  );
}
