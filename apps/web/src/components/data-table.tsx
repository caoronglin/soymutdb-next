/**
 * DataTable — server-side paginated table built on antd's native `Table`.
 *
 * The column/prop surface is unchanged for callers (`columns` with `cell`
 * renderers, `sort`/`onSortChange` for server-side sorting, `frozen` for the
 * leading column, and the compact mobile card list), but the rendering is now
 * antd's own table: sticky header, fixed columns, loading skeleton, empty
 * state and pagination all come from the component library instead of a
 * hand-rolled `<table>`.
 */
import * as React from "react";
import { useTranslation } from "react-i18next";
import { cn } from "../lib/cn";
import { Empty, Table, type TableColumnsType, type TableProps } from "@/lib/antd";

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
  /** Loading state — renders the antd loading overlay. */
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

function columnId<T>(column: DataTableColumn<T>, index: number): string {
  return column.id ?? column.key ?? `column-${index}`;
}

function isRightAligned<T>(column: DataTableColumn<T>): boolean {
  return Boolean(column.numeric || column.align === "right");
}

export function DataTable<T>({
  columns,
  data,
  loading = false,
  // Kept on the prop surface for existing callers; antd v6's Table owns the
  // loading presentation and exposes no row-count hook.
  skeletonRows: _skeletonRows = 8,
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
}: DataTableProps<T>) {  const { t } = useTranslation();

  const antdColumns: TableColumnsType<T> = React.useMemo(
    () =>
      columns.map((column, index) => {
        const id = columnId(column, index);
        const sorted = sort?.key != null && sort.key === column.sortKey;
        return {
          key: id,
          title: column.header,
          align: isRightAligned(column) ? "right" : column.align ?? "left",
          fixed: column.frozen ? ("left" as const) : undefined,
          width: column.width,
          className: column.className,
          // The caller owns the cell renderer, so the value never comes from a
          // dataIndex; antd still needs `render` to be present per column.
          render: (_value: unknown, row: T) => column.cell(row),
          sorter: column.sortKey && onSortChange ? true : undefined,
          sortOrder: sorted ? (sort?.dir === "asc" ? ("ascend" as const) : ("descend" as const)) : null,
          showSorterTooltip: false,
        };
      }),
    [columns, sort, onSortChange],
  );

  // antd reports sorting as a column key + order; the caller's contract is a
  // server-side `sortKey`, so translate back through the column definitions.
  const handleChange: TableProps<T>["onChange"] = (_pag, _filters, sorter) => {
    if (!onSortChange) return;
    const active = Array.isArray(sorter) ? sorter[0] : sorter;
    if (!active?.order) {
      onSortChange(null);
      return;
    }
    const matched = columns.find((c, i) => columnId(c, i) === active.columnKey && c.sortKey);
    if (!matched?.sortKey) return;
    const dir = active.order === "ascend" ? "asc" : "desc";
    if (sort?.key === matched.sortKey && sort.dir === dir) {
      onSortChange(null);
      return;
    }
    onSortChange({ key: matched.sortKey, dir });
  };

  return (
    <div className={cn("flex flex-col gap-4", className)}>
      <Table<T>
        rowKey={(row, index) => rowKey?.(row) ?? String(index)}
        columns={antdColumns}
        dataSource={data}
        // antd v6 renders its own spinner overlay; `skeletonRows` is kept on the
        // prop surface for callers but has no equivalent hook in the component.
        loading={loading}
        sticky
        size="middle"
        scroll={{ x: "max-content" }}
        onChange={handleChange}
        onRow={
          onRowClick
            ? (row) => ({
                onClick: () => onRowClick(row),
                onKeyDown: (event: React.KeyboardEvent) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onRowClick(row);
                  }
                },
                tabIndex: 0,
                style: { cursor: "pointer" },
              })
            : undefined
        }
        pagination={
          pagination
            ? {
                current: pagination.page,
                total: pagination.total,
                pageSize: pagination.pageSize,
                showSizeChanger: false,
                disabled: loading,
                onChange: pagination.onPageChange,
              }
            : false
        }
        locale={{
          emptyText: (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                <>
                  <p className="font-medium">{emptyTitle}</p>
                  <p className="text-sm text-muted-foreground">{emptyDescription}</p>
                </>
              }
            />
          ),
        }}
        className={cn(responsive && data.length > 0 && "hidden md:block")}
        aria-label={ariaLabel}
      />

      {/* antd has no built-in compact card fallback below the md breakpoint. */}
      {responsive && !loading && data.length > 0 ? (
        <ul className="grid gap-3 md:hidden" aria-label={t("dataTable.compactView", { label: ariaLabel ?? t("dataTable.title") })}>
          {data.map((row, ri) => {
            const primary = columns.find((column) => column.primary) ?? columns[0];
            return (
              <li key={rowKey?.(row) ?? ri}>
                <div
                  className={cn("rounded-xl border bg-card p-4 shadow-sm", onRowClick && "cursor-pointer")}
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
                      <div key={columnId(column, ci)} className="flex items-baseline justify-between gap-3">
                        <dt className="text-xs text-muted-foreground">{column.header}</dt>
                        <dd className={cn("text-sm", isRightAligned(column) && "font-mono tabular-nums")}>
                          {column.cell(row)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
