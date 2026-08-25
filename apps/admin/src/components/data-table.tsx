import { UpOutlined, DownOutlined, SwapOutlined } from "@ant-design/icons";
import { type ReactNode, useMemo, useState, useCallback } from "react";
import { cn } from "../lib/cn";
import { Empty, Pagination, Skeleton } from "@/lib/antd";
// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DataTableColumn<T> {
  /** Unique column key. */
  key: string;
  /** Header label. */
  header: string;
  /** Render the cell value for a row. */
  cell: (row: T) => ReactNode;
  /** Whether this column is sortable. */
  sortable?: boolean;
  /** Sort accessor (defaults to the key). */
  sortAccessor?: (row: T) => string | number;
  /** Optional className for cells in this column. */
  className?: string;
  /** Header alignment. */
  align?: "left" | "center" | "right";
}

interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  data: T[];
  /** Row key accessor. */
  rowKey: (row: T) => string;
  /** Loading state. */
  loading?: boolean;
  /** Current page (1-based). */
  page?: number;
  /** Items per page. */
  pageSize?: number;
  /** Total item count. */
  total?: number;
  /** Page change handler. */
  onPageChange?: (page: number) => void;
  /** Empty state message. */
  emptyTitle?: string;
  emptyDescription?: string;
  /** Optional row click handler. */
  onRowClick?: (row: T) => void;
  /** Optional className. */
  className?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Admin data table with sortable columns, pagination, and loading/empty states.
 * Keyboard navigable: column headers are buttons, rows are focusable when
 * onRowClick is provided.
 */
export function DataTable<T>({
  columns,
  data,
  rowKey,
  loading = false,
  page,
  pageSize,
  total,
  onPageChange,
  emptyTitle = "No data",
  emptyDescription = "There are no records to display.",
  onRowClick,
  className,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const handleSort = useCallback(
    (col: DataTableColumn<T>) => {
      if (!col.sortable) return;
      if (sortKey === col.key) {
        setSortDir((prev) => (prev === "asc" ? "desc" : "asc"));
      } else {
        setSortKey(col.key);
        setSortDir("asc");
      }
    },
    [sortKey],
  );

  const sortedData = useMemo(() => {
    if (!sortKey) return data;
    const col = columns.find((c) => c.key === sortKey);
    if (!col?.sortAccessor) return data;
    const accessor = col.sortAccessor;
    const factor = sortDir === "asc" ? 1 : -1;
    return [...data].sort((a, b) => {
      const av = accessor(a);
      const bv = accessor(b);
      if (av < bv) return -1 * factor;
      if (av > bv) return 1 * factor;
      return 0;
    });
  }, [data, columns, sortKey, sortDir]);

  return (
    <div className={cn("space-y-4", className)}>
      <div className="rounded-xl border border-border bg-card">
        <table>
          <thead>
            <tr className="bg-muted/40 hover:bg-muted/40">
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={cn(
                    col.align === "right" && "text-right",
                    col.align === "center" && "text-center",
                    col.className,
                  )}
                >
                  {col.sortable ? (
                    <button
                      type="button"
                      onClick={() => handleSort(col)}
                      className="inline-flex items-center gap-1 text-xs font-medium uppercase tracking-wide text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                      aria-label={`Sort by ${col.header}`}
                    >
                      {col.header}
                      {sortKey === col.key ? (
                        sortDir === "asc" ? (
                          <UpOutlined className="size-3.5" aria-hidden />
                        ) : (
                          <DownOutlined className="size-3.5" aria-hidden />
                        )
                      ) : (
                        <SwapOutlined className="size-3.5 opacity-40" aria-hidden />
                      )}
                    </button>
                  ) : (
                    <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      {col.header}
                    </span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={`skeleton-${i}`}>
                  {columns.map((col) => (
                    <td key={col.key}>
                      <Skeleton className="h-5 w-full max-w-32" />
                    </td>
                  ))}
                </tr>
              ))
            ) : sortedData.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="p-0">
                  <Empty description={emptyDescription ? `${emptyTitle}: ${emptyDescription}` : emptyTitle} />
                </td>
              </tr>
            ) : (
              sortedData.map((row) => (
                <tr
                  key={rowKey(row)}
                  className={cn(
                    onRowClick && "cursor-pointer",
                  )}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  tabIndex={onRowClick ? 0 : undefined}
                  onKeyDown={
                    onRowClick
                      ? (e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            onRowClick(row);
                          }
                        }
                      : undefined
                  }
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={cn(
                        col.align === "right" && "text-right",
                        col.align === "center" && "text-center",
                        col.className,
                      )}
                    >
                      {col.cell(row)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {page && pageSize && total !== undefined && onPageChange ? (
        <Pagination
          current={page}
          total={total}
          pageSize={pageSize}
          onChange={onPageChange}
          disabled={loading}
        />
      ) : null}
    </div>
  );
}

export default DataTable;
