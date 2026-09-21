import { ReactNode } from "react";

export interface TableColumn<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  sortable?: boolean;
}

export type SortDirection = "asc" | "desc" | undefined;

export interface TableProps<T> {
  columns: TableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  sortKey?: string;
  sortDirection?: SortDirection;
  onSort?: (key: string) => void;
}

/** Canonical structured-data table: scan, compare, sort, act on many rows. */
export function Table<T>({ columns, rows, rowKey, sortKey, sortDirection, onSort }: TableProps<T>) {
  return (
    <table className="w-full border-collapse text-left text-sm">
      <thead>
        <tr className="border-b border-neutral-200">
          {columns.map((col) => (
            <th key={col.key} className="px-3 py-2.5 font-semibold text-fg-primary">
              {col.sortable ? (
                <button
                  onClick={() => onSort?.(col.key)}
                  className="inline-flex items-center gap-1 hover:text-fg-brand"
                >
                  {col.header}
                  <span aria-hidden className="text-xs text-fg-tertiary">
                    {sortKey === col.key ? (sortDirection === "asc" ? "↑" : "↓") : "↕"}
                  </span>
                </button>
              ) : (
                col.header
              )}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={rowKey(row)} className="border-b border-neutral-150 hover:bg-bg-surface-hover">
            {columns.map((col) => (
              <td key={col.key} className="px-3 py-3 text-fg-primary">
                {col.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export interface StatTileProps {
  label: string;
  value: ReactNode;
  icon?: ReactNode;
  tone?: "neutral" | "danger";
}

/** Summary tile used above a table, e.g. counts by status. */
export function StatTile({ label, value, icon, tone = "neutral" }: StatTileProps) {
  return (
    <div
      className={[
        "flex min-w-[140px] items-center justify-between rounded-md px-4 py-3",
        tone === "danger" ? "bg-alert-light" : "bg-bg-subtle",
      ].join(" ")}
    >
      <div>
        <p className="text-sm text-fg-secondary">{label}</p>
        <p className="text-xl font-semibold text-fg-primary">{value}</p>
      </div>
      {icon && <span className={tone === "danger" ? "text-fg-danger" : "text-fg-tertiary"}>{icon}</span>}
    </div>
  );
}
