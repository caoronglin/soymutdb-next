import { useMemo, type ReactNode } from "react";
import { Empty, Pagination, ProTable, type ProColumns, type TableProps } from "@/lib/antd";
import { cn } from "../lib/cn";
import { useTranslation } from "react-i18next";

export interface DataTableColumn<T> {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  sortable?: boolean;
  sortAccessor?: (row: T) => string | number;
  className?: string;
  align?: "left" | "center" | "right";
}

interface DataTableProps<T extends object> {
  columns: DataTableColumn<T>[];
  data: T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  page?: number;
  pageSize?: number;
  total?: number;
  onPageChange?: (page: number) => void;
  emptyTitle?: string;
  emptyDescription?: string;
  onRowClick?: (row: T) => void;
  /**
   * Horizontal scroll configuration of the table body.
   *
   * Defaults to `max-content`: a wide console table keeps its column widths
   * and the body scrolls sideways instead of collapsing every column into a
   * few unreadable pixels on a narrow screen. A route that needs a different
   * behaviour (a fixed pixel width, a vertical scroll area) passes its own
   * value; the default only applies when the prop is absent, so the existing
   * callers keep working unchanged.
   */
  scroll?: TableProps<T>["scroll"];
  className?: string;
}

/**
 * Shared admin table adapter: ProTable owns the Ant Design Pro table shell,
 * sorting, row density and empty state; callers keep the narrow DataTable
 * contract while routes are migrated onto the unified API/query layer.
 */
export function DataTable<T extends object>({
  columns,
  data,
  rowKey,
  loading = false,
  page,
  pageSize,
  total,
  onPageChange,
  emptyTitle,
  emptyDescription,
  onRowClick,
  scroll,
  className,
}: DataTableProps<T>) {
  const { t } = useTranslation();
  const resolvedEmptyTitle = emptyTitle ?? t("admin.ops.emptyTitle", { defaultValue: "No data" });
  const resolvedEmptyDescription = emptyDescription ?? t("admin.ops.emptyDescription", { defaultValue: "There are no records to display." });
  const proColumns = useMemo<ProColumns<T>[]>(
    () =>
      columns.map((column) => ({
        key: column.key,
        dataIndex: column.key,
        title: column.header,
        align: column.align,
        className: column.className,
        search: false,
        sorter: column.sortable
          ? (left, right) => {
              const get = column.sortAccessor ?? ((row: T) => (row as Record<string, unknown>)[column.key] as string | number);
              const a = get(left);
              const b = get(right);
              return a < b ? -1 : a > b ? 1 : 0;
            }
          : false,
        render: (_value, row) => column.cell(row),
      })),
    [columns],
  );

  return (
    <div className={cn("space-y-4", className)}>
      <ProTable<T>
        rowKey={(row) => rowKey(row)}
        columns={proColumns}
        dataSource={data}
        loading={loading}
        search={false}
        options={false}
        toolBarRender={false}
        tableAlertRender={false}
        pagination={false}
        cardBordered={false}
        size="small"
        // Wide console tables keep their column widths; the body scrolls
        // sideways on a narrow screen instead of squeezing every column.
        scroll={scroll ?? { x: "max-content" }}
        locale={{
          emptyText: (
            <Empty
              description={resolvedEmptyDescription ? `${resolvedEmptyTitle}: ${resolvedEmptyDescription}` : resolvedEmptyTitle}
            />
          ),
        }}
        onRow={(row) => ({
          onClick: onRowClick ? () => onRowClick(row) : undefined,
          tabIndex: onRowClick ? 0 : undefined,
          onKeyDown: onRowClick
            ? (event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onRowClick(row);
                }
              }
            : undefined,
          className: onRowClick ? "cursor-pointer" : undefined,
        })}
      />
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
