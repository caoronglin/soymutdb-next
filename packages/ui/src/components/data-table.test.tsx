import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import {
  DataTable,
  type DataTableColumn,
  type DataTableSort,
} from "./data-table";

interface Row {
  id: string;
  name: string;
  score: number;
}

const columns: DataTableColumn<Row>[] = [
  {
    key: "name",
    header: "Name",
    cell: (r) => r.name,
    sortable: true,
    sortAccessor: (r) => r.name,
  },
  {
    key: "score",
    header: "Score",
    cell: (r) => r.score,
    sortable: true,
    sortAccessor: (r) => r.score,
    align: "right",
  },
];

const data: Row[] = [
  { id: "1", name: "Charlie", score: 10 },
  { id: "2", name: "Alpha", score: 30 },
  { id: "3", name: "Bravo", score: 20 },
];

const rowKey = (r: Row) => r.id;

function rowsInOrder(): string[] {
  const body = screen.getAllByRole("row").slice(1);
  return body.map((tr) => tr.textContent ?? "");
}

function scoreOrder(): number[] {
  const body = screen.getAllByRole("row").slice(1);
  return body.map((tr) => {
    const score = tr.querySelectorAll("td")[1]?.textContent ?? "";
    return parseInt(score, 10);
  });
}

describe("DataTable", () => {
  it("renders column headers and row cells", () => {
    render(<DataTable columns={columns} data={data} rowKey={rowKey} />);
    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Score" })).toBeInTheDocument();
    expect(screen.getByText("Charlie")).toBeInTheDocument();
    expect(screen.getByText("30")).toBeInTheDocument();
  });

  it("sorts client-side (uncontrolled) and toggles direction", () => {
    render(<DataTable columns={columns} data={data} rowKey={rowKey} />);

    fireEvent.click(screen.getByRole("button", { name: "Sort by Name" }));
    expect(rowsInOrder()[0]).toContain("Alpha");

    fireEvent.click(screen.getByRole("button", { name: "Sort by Name" }));
    expect(rowsInOrder()[0]).toContain("Charlie");
    expect(screen.getByRole("columnheader", { name: "Name" })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
  });

  it("sorts numbers numerically", () => {
    render(<DataTable columns={columns} data={data} rowKey={rowKey} />);
    fireEvent.click(screen.getByRole("button", { name: "Sort by Score" }));
    expect(scoreOrder()).toEqual([10, 20, 30]);
  });

  it("supports controlled sorting without re-sorting data", () => {
    const onSortChange = vi.fn();
    const sort: DataTableSort = { key: "name", dir: "asc" };
    render(
      <DataTable
        columns={columns}
        data={data}
        rowKey={rowKey}
        sort={sort}
        onSortChange={onSortChange}
      />,
    );

    // Data stays in original order (server-sorted assumption).
    expect(rowsInOrder()[0]).toContain("Charlie");

    fireEvent.click(screen.getByRole("button", { name: "Sort by Name" }));
    expect(onSortChange).toHaveBeenCalledWith({ key: "name", dir: "desc" });
  });

  it("renders pagination and fires page changes", () => {
    const onPageChange = vi.fn();
    render(
      <DataTable
        columns={columns}
        data={data}
        rowKey={rowKey}
        page={1}
        pageSize={10}
        total={25}
        onPageChange={onPageChange}
      />,
    );
    expect(screen.getByText("1–10 of 25")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(onPageChange).toHaveBeenCalledWith(2);
  });

  it("hides pagination when no pagination props are given", () => {
    render(<DataTable columns={columns} data={data} rowKey={rowKey} />);
    expect(screen.queryByLabelText("Table pagination")).not.toBeInTheDocument();
  });

  it("supports row selection via header and row checkboxes", () => {
    const onSelectionChange = vi.fn();
    render(
      <DataTable
        columns={columns}
        data={data}
        rowKey={rowKey}
        selection={{ selectedKeys: [], onSelectionChange }}
      />,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: "Select all rows" }));
    expect(onSelectionChange).toHaveBeenLastCalledWith(["1", "2", "3"]);

    fireEvent.click(screen.getByRole("checkbox", { name: "Select Row 2" }));
    expect(onSelectionChange).toHaveBeenLastCalledWith(["2"]);
  });

  it("reflects controlled selection state and select-all indeterminate state", () => {
    const onSelectionChange = vi.fn();
    const { rerender } = render(
      <DataTable
        columns={columns}
        data={data}
        rowKey={rowKey}
        selection={{ selectedKeys: ["1"], onSelectionChange }}
      />,
    );
    expect(screen.getByRole("checkbox", { name: "Select Row 1" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select all rows" })).not.toBeChecked();

    rerender(
      <DataTable
        columns={columns}
        data={data}
        rowKey={rowKey}
        selection={{ selectedKeys: ["1", "2", "3"], onSelectionChange }}
      />,
    );
    expect(screen.getByRole("checkbox", { name: "Select all rows" })).toBeChecked();
  });

  it("supports column visibility toggling", () => {
    const onToggle = vi.fn();
    render(
      <DataTable
        columns={columns}
        data={data}
        rowKey={rowKey}
        columnVisibility={{ hiddenKeys: ["score"], onToggle }}
      />,
    );

    expect(screen.queryByRole("columnheader", { name: "Score" })).not.toBeInTheDocument();
    const nameCheckbox = screen.getByRole("checkbox", { name: "Name" });
    fireEvent.click(nameCheckbox);
    expect(onToggle).toHaveBeenCalledWith("name", false);
  });

  it("navigates rows with arrow keys and activates with Enter/Space", () => {
    const onRowClick = vi.fn();
    render(
      <DataTable columns={columns} data={data} rowKey={rowKey} onRowClick={onRowClick} />,
    );

    const charlieRow = screen.getByText("Charlie").closest("tr");
    const alphaRow = screen.getByText("Alpha").closest("tr");
    expect(charlieRow).not.toBeNull();
    expect(alphaRow).not.toBeNull();

    fireEvent.keyDown(charlieRow!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(alphaRow);

    fireEvent.keyDown(alphaRow!, { key: "ArrowUp" });
    expect(document.activeElement).toBe(charlieRow);

    fireEvent.keyDown(charlieRow!, { key: "Enter" });
    expect(onRowClick).toHaveBeenCalledWith(data[0]);

    fireEvent.keyDown(charlieRow!, { key: " " });
    expect(onRowClick).toHaveBeenCalledTimes(2);
  });

  it("toggles selection with Space on a focused row", () => {
    const onSelectionChange = vi.fn();
    render(
      <DataTable
        columns={columns}
        data={data}
        rowKey={rowKey}
        selection={{ selectedKeys: [], onSelectionChange }}
      />,
    );
    const charlieRow = screen.getByText("Charlie").closest("tr");
    fireEvent.keyDown(charlieRow!, { key: " " });
    expect(onSelectionChange).toHaveBeenCalledWith(["1"]);
  });

  it("renders skeleton rows while loading and a custom loading slot", () => {
    const { container, rerender } = render(
      <DataTable columns={columns} data={data} rowKey={rowKey} loading />,
    );
    expect(container.querySelectorAll(".shimmer").length).toBeGreaterThan(0);

    rerender(
      <DataTable
        columns={columns}
        data={data}
        rowKey={rowKey}
        loading
        loadingSlot={<div>custom-loading</div>}
      />,
    );
    expect(screen.getByText("custom-loading")).toBeInTheDocument();
  });

  it("renders an error state with retry and a custom error slot", () => {
    const onRetry = vi.fn();
    const { rerender } = render(
      <DataTable columns={columns} data={data} rowKey={rowKey} error="boom" onRetry={onRetry} />,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("boom");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalled();

    rerender(
      <DataTable columns={columns} data={data} rowKey={rowKey} error="boom" errorSlot={<div>custom-error</div>} />,
    );
    expect(screen.getByText("custom-error")).toBeInTheDocument();
  });

  it("renders empty state (mode-aware) and custom empty slot", () => {
    const { rerender } = render(<DataTable columns={columns} data={[]} rowKey={rowKey} />);
    expect(screen.getByRole("status")).toHaveTextContent("No data");

    rerender(
      <DataTable columns={columns} data={[]} rowKey={rowKey} emptyMode="filtered" />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("No results found");

    rerender(
      <DataTable columns={columns} data={[]} rowKey={rowKey} emptySlot={<div>custom-empty</div>} />,
    );
    expect(screen.getByText("custom-empty")).toBeInTheDocument();
  });

  it("renders compact cards in responsive mode", () => {
    render(<DataTable columns={columns} data={data} rowKey={rowKey} responsive />);
    expect(screen.getByLabelText("Data table (compact view)")).toBeInTheDocument();
    // Both layouts are in the DOM; the table keeps its accessible name.
    expect(screen.getByLabelText("Data table")).toBeInTheDocument();
  });
});
