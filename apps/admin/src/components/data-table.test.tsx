import * as React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);

/**
 * A local double of the antd facade.
 *
 * The shared double renders plain DOM, which is enough for route tests but
 * hides the props this component is about: the scroll configuration of the
 * table body. This double reports it as `data-scroll-x` and keeps the cell
 * rendering of the shared double, so the assertions below exercise the
 * component's own props rather than the double's markup.
 */
vi.mock("@/lib/antd", () => ({
  Empty: ({ description }: { description?: React.ReactNode }) => <div data-testid="empty">{description}</div>,
  Pagination: ({ current, total }: { current?: number; total?: number }) => (
    <div data-testid="pagination" data-current={String(current)} data-total={String(total)} />
  ),
  ProTable: (props: {
    columns?: Array<{
      key?: string;
      dataIndex?: string;
      render?: (value: unknown, row: Record<string, unknown>, index: number) => React.ReactNode;
    }>;
    dataSource?: Array<Record<string, unknown>>;
    scroll?: { x?: number | string | true; y?: number | string };
    locale?: { emptyText?: React.ReactNode };
    onRow?: (row: Record<string, unknown>) => { onClick?: () => void; tabIndex?: number };
  }) => {
    const rows = props.dataSource ?? [];
    const emptyText = props.locale?.emptyText;
    if (rows.length === 0) {
      return (
        <table
          data-testid="pro-table"
          data-scroll-x={props.scroll?.x === undefined ? undefined : String(props.scroll.x)}
        >
          <tbody>
            <tr>
              <td>{emptyText}</td>
            </tr>
          </tbody>
        </table>
      );
    }
    return (
      <table
        data-testid="pro-table"
        data-scroll-x={props.scroll?.x === undefined ? undefined : String(props.scroll.x)}
      >
        <tbody>
          {rows.map((row, index) => {
            const rowProps = props.onRow?.(row);
            return (
              <tr key={String(row.id)} onClick={rowProps?.onClick} tabIndex={rowProps?.tabIndex}>
                {(props.columns ?? []).map((column, columnIndex) => (
                  <td key={column.key ?? columnIndex}>
                    {column.render
                      ? column.render(row[column.dataIndex ?? column.key ?? ""], row, index)
                      : null}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    );
  },
}));

import { DataTable, type DataTableColumn } from "./data-table";

interface Row {
  id: string;
  name: string;
}

const columns: DataTableColumn<Row>[] = [
  { key: "name", header: "Name", cell: (row) => row.name },
];

const data: Row[] = [{ id: "r1", name: "First record" }];

describe("admin shared table", () => {
  it("keeps a wide table scrollable instead of squeezing its columns", () => {
    render(<DataTable<Row> columns={columns} data={data} rowKey={(row) => row.id} />);

    expect(screen.getByTestId("pro-table").dataset.scrollX).toBe("max-content");
  });

  it("lets a route override the scroll configuration explicitly", () => {
    render(
      <DataTable<Row>
        columns={columns}
        data={data}
        rowKey={(row) => row.id}
        scroll={{ x: 1200 }}
      />,
    );

    expect(screen.getByTestId("pro-table").dataset.scrollX).toBe("1200");
  });

  it("keeps the existing column, row and paging contract working", () => {
    const onPageChange = vi.fn();
    render(
      <DataTable<Row>
        columns={columns}
        data={data}
        rowKey={(row) => row.id}
        page={2}
        pageSize={10}
        total={42}
        onPageChange={onPageChange}
      />,
    );

    expect(screen.getByText("First record")).toBeTruthy();
    const pagination = screen.getByTestId("pagination");
    expect(pagination.dataset.current).toBe("2");
    expect(pagination.dataset.total).toBe("42");
    expect(onPageChange).not.toHaveBeenCalled();
  });

  it("renders the empty state when there is nothing to show", () => {
    render(<DataTable<Row> columns={columns} data={[]} rowKey={(row) => row.id} />);

    expect(screen.getByTestId("empty")).toBeTruthy();
    expect(screen.queryByTestId("pagination")).toBeNull();
  });

  it("keeps the row click handler working", () => {
    const onRowClick = vi.fn();
    render(
      <DataTable<Row>
        columns={columns}
        data={data}
        rowKey={(row) => row.id}
        onRowClick={onRowClick}
      />,
    );

    fireEvent.click(screen.getByText("First record"));
    expect(onRowClick).toHaveBeenCalledWith(data[0]);
  });
});
