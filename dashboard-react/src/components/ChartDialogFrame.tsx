// Modal shell shared by the forecast dialog and the history dialogs: scrim, role="dialog"
// panel, header row (title, extra badges, Range select, Close), Escape and Tab trap.
//
// The design system has no Dialog component, so this is a fixed scrim plus a role="dialog"
// panel, like the admin confirm dialog.

import { useEffect, useRef, type ChangeEvent, type KeyboardEvent, type ReactNode } from "react";
import { Button, Select } from "kone-design-system";
import type { HistoryDays } from "../lib/historyClient";

const RANGE_OPTIONS = [
  { value: "14", label: "14 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
];

export interface ChartDialogFrameProps {
  title: string;
  headerExtra?: ReactNode;
  range: HistoryDays;
  onRangeChange: (range: HistoryDays) => void;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}

export function ChartDialogFrame({
  title,
  headerExtra,
  range,
  onRangeChange,
  onClose,
  children,
  footer,
}: ChartDialogFrameProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const trapTab = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Tab" || !panelRef.current) return;
    const focusable = panelRef.current.querySelectorAll<HTMLElement>(
      'button:not([disabled]), select:not([disabled]), [tabindex="0"]',
    );
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
      data-testid="forecast-scrim"
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="forecast-dialog-title"
        className="max-h-[90vh] w-full max-w-[880px] overflow-auto rounded-md bg-bg-surface p-6 shadow-lg"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={trapTab}
      >
        <div className="flex items-start gap-4 rounded-md bg-bg-subtle p-4">
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <h2 id="forecast-dialog-title" className="truncate text-xl font-semibold text-fg-primary">
              {title}
            </h2>
            {headerExtra}
          </div>
          <div className="w-32 shrink-0">
            <Select
              id="forecast-range"
              label="Range"
              options={RANGE_OPTIONS}
              value={String(range)}
              onChange={(event: ChangeEvent<HTMLSelectElement>) =>
                onRangeChange(Number(event.target.value) as HistoryDays)
              }
            />
          </div>
          <Button ref={closeRef} variant="neutral" size="sm" onClick={onClose} aria-label="Close">
            Close
          </Button>
        </div>

        <div className="mt-4">{children}</div>

        {footer}
      </div>
    </div>
  );
}
