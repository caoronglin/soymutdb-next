/**
 * DataTable — server-side paginated table with sticky header, optional
 * frozen leading column, skeleton loading, and empty/error states.
 *
 * Built on @tanstack/react-table for column defs and sorting, but renders
 * a plain table for full control over styling and virtualization hooks.
 */
import * as React from "react";
import { cn } from "../lib/cn";
import { Pagination } from "@/lib/antd";
import { ArrowDownOutlined, ArrowUpOutlined, SwapOutlined, InboxOutlined } from "@ant-design/icons";

export interface DataTableColumn<T> {
  id?: string;
  key?: string;
  header: React.ReactNode;
  /** Render a cell for the row. */
  cell: (row: T) => React.ReactNode;
  /** Sortable column key (sent to the server). */
  sortKey?: string;
  /** Freeze this column to the left (max 1 recommended). */
  frozen?: boolean;
  /** Right-align numeric columns. */
  numeric?: boolean;
  /** Package-compatible cell alignment. */
  align?: "left" | "center" | "right";
  /** Use this column as the compact-card heading. */
  primary?: boolean;
  /** Optional class for the cell. */
  className?: string;
  /** Optional width hint. */
  width?: string;
}

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  data: T[];
  /** Loading state — renders skeleton rows. */
  loading?: boolean;
  /** Number of skeleton rows to show while loading (default 8). */
  skeletonRows?: number;
  /** Empty state message. */
  emptyTitle?: string;
  emptyDescription?: string;
  /** Pagination props. Omit to hide pagination. */
  pagination?: {
    page: number;
    totalPages: number;
    total: number;
    pageSize: number;
    onPageChange: (page: number) => void;
  };
  /** Current sort key + direction. */
  sort?: { key: string; dir: "asc" | "desc" } | null;
  /** Sort change handler. */
  onSortChange?: (sort: { key: string; dir: "asc" | "desc" } | null) => void;
  /** Row click handler. */
  onRowClick?: (row: T) => void;
  /** Stable key accessor used by the package-compatible surface. */
  rowKey?: (row: T) => string;
  /** Render compact cards below the md breakpoint. */
  responsive?: boolean;
  /** Accessible label for the table. */
  ariaLabel?: string;
  className?: string;
}

export function DataTable<T>({
  columns,
  data,
  loading = false,
  skeletonRows = 8,
  emptyTitle = "No results found",
  emptyDescription = "Try adjusting your filters or search query.",
  pagination,
  sort,
  onSortChange,
  onRowClick,
  rowKey,
  responsive = false,
  ariaLabel,
  className,
}: DataTableProps<T>) {
  const columnKey = (column: DataTableColumn<T>, index: number) =>
    column.id ?? column.key ?? `column-${index}`;
  const isRightAligned = (column: DataTableColumn<T>) =>
    column.numeric || column.align === "right";
  const handleSort = (col: DataTableColumn<T>) => {
    if (!col.sortKey || !onSortChange) return;
    if (sort?.key === col.sortKey) {
      onSortChange(sort.dir === "asc" ? { key: col.sortKey, dir: "desc" } : null);
    } else {
      onSortChange({ key: col.sortKey, dir: "asc" });
    }
  };

  return (
    <div className={cn("flex flex-col gap-4", className)}>
      <div
        className={cn(
          "overflow-x-auto rounded-xl border bg-card shadow-sm",
          responsive && !loading && data.length > 0 && "hidden md:block",
        )}
      >
        <table className="w-full border-collapse text-sm" aria-label={ariaLabel}>
          <thead className="sticky top-0 z-10 bg-muted/50 backdrop-blur">
            <tr className="border-b">
              {columns.map((col, ci) => {
                const isSorted = sort?.key === col.sortKey;
                return (
                  <th
                    key={columnKey(col, ci)}
                    scope="col"
                    className={cn(
                      "px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground",
                      isRightAligned(col) && "text-right",
                      col.align === "center" && "text-center",
                      col.frozen && "sticky left-0 z-20 bg-muted/50 backdrop-blur",
                      col.sortKey && "cursor-pointer select-none",
                      col.className,
                    )}
                    style={{ width: col.width }}
                    aria-sort={isSorted ? (sort?.dir === "asc" ? "ascending" : "descending") : undefined}
                  >
                    {col.sortKey ? (
                      <button
                        type="button"
                        className={cn(
                          "inline-flex items-center gap-1 transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          isRightAligned(col) && "flex-row-reverse",
                          isSorted && "text-foreground",
                        )}
                        onClick={() => handleSort(col)}
                      >
                        {col.header}
                        {isSorted ? (
                          sort?.dir === "asc" ? (
                            <ArrowUpOutlined className="size-3.5" aria-hidden />
                          ) : (
                            <ArrowDownOutlined className="size-3.5" aria-hidden />
                          )
                        ) : (
                          <SwapOutlined className="size-3.5 opacity-40" aria-hidden />
                        )}
                      </button>
                    ) : (
                      col.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: skeletonRows }).map((_, ri) => (
                <tr key={`skel-${ri}`} className="border-b last:border-0">
                  {columns.map((col, ci) => (
                    <td
                      key={columnKey(col, ci)}
                      className={cn(
                        "px-4 py-3",
                        isRightAligned(col) && "text-right",
                        col.align === "center" && "text-center",
                        col.frozen && "sticky left-0 z-10 bg-card",
                      )}
                    >
                      <div className="h-4 w-full max-w-[120px] animate-pulse rounded bg-muted/70" />
                    </td>
                  ))}
                </tr>
              ))
            ) : data.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-12">
                  <div className="flex flex-col items-center gap-3 text-center">
                    <div className="flex size-10 items-center justify-center rounded-full bg-muted">
                      <InboxOutlined className="size-5 text-muted-foreground" aria-hidden />
                    </div>
                    <p className="font-medium">{emptyTitle}</p>
                    <p className="max-w-sm text-sm text-muted-foreground">{emptyDescription}</p>
                  </div>
                </td>
              </tr>
            ) : (
              data.map((row, ri) => (
                <tr
                  key={rowKey?.(row) ?? ri}
                  className={cn(
                    "group/row border-b last:border-0 transition-colors hover:bg-muted/50",
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
                  {columns.map((col, ci) => (
                    <td
                      key={columnKey(col, ci)}
                      className={cn(
                        "px-4 py-3 align-middle",
                        isRightAligned(col) && "text-right font-mono tabular-nums",
                        col.align === "center" && "text-center",
                        col.frozen && "sticky left-0 z-10 bg-card transition-colors group-hover/row:bg-muted/50",
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
      {responsive && !loading && data.length > 0 ? (
        <ul className="grid gap-3 md:hidden" aria-label={`${ariaLabel ?? "Data table"} compact view`}>
          {data.map((row, ri) => {
            const primary = columns.find((column) => column.primary) ?? columns[0];
            return (
              <li key={rowKey?.(row) ?? ri}>
                <div
                  className={cn(
                    "rounded-xl border bg-card p-4 shadow-sm",
                    onRowClick && "cursor-pointer",
                  )}
                  tabIndex={onRowClick ? 0 : undefined}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  onKeyDown={
                    onRowClick
                      ? (event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            onRowClick(row);
                          }
                        }
                      : undefined
                  }
                >
                  {primary ? <div className="font-medium">{primary.cell(row)}</div> : null}
                  <dl className="mt-3 grid gap-2">
                    {columns.filter((column) => column !== primary).map((column, ci) => (
                      <div key={columnKey(column, ci)} className="flex items-baseline justify-between gap-3">
                        <dt className="text-xs text-muted-foreground">{column.header}</dt>
                        <dd className={cn("text-sm", isRightAligned(column) && "font-mono tabular-nums")}>{column.cell(row)}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}
      {pagination ? (
        <Pagination
          current={pagination.page}
          total={pagination.total}
          pageSize={pagination.pageSize}
          showSizeChanger={false}
          disabled={loading}
          onChange={pagination.onPageChange}
        />
      ) : null}
    </div>
  );
}
