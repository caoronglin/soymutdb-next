import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ImportPreviewTable, type ImportPreviewRow } from "./import-preview-table";

function makeRows(count: number): ImportPreviewRow[] {
  return Array.from({ length: count }, (_, index) => ({
    _row_key: `row-${index}`,
    gene_id: `G${index}`,
    start: index + 1,
  }));
}

describe("ImportPreviewTable", () => {
  it("renders only a visible row window and updates it after scrolling", () => {
    render(
      <ImportPreviewTable
        ariaLabel="Import preview"
        columns={["gene_id", "start"]}
        rows={makeRows(10_000)}
        rowKey={(row) => String(row._row_key)}
        height={120}
        rowHeight={30}
      />,
    );

    const grid = screen.getByRole("grid", { name: "Import preview" });
    expect(screen.getByText("G0")).toBeInTheDocument();
    expect(screen.queryByText("G9999")).not.toBeInTheDocument();
    expect(grid.querySelectorAll('[role="row"]')).toHaveLength(6);

    fireEvent.scroll(grid, { target: { scrollTop: 30 * 5_000 } });

    expect(screen.getByText("G5000")).toBeInTheDocument();
    expect(screen.queryByText("G0")).not.toBeInTheDocument();
  });

  it("commits a keyboard cell edit as a bounded patch without cloning rows", () => {
    const onPatchesChange = vi.fn();
    render(
      <ImportPreviewTable
        columns={["gene_id", "start"]}
        rows={makeRows(2)}
        rowKey={(row) => String(row._row_key)}
        editable
        onPatchesChange={onPatchesChange}
      />,
    );

    const cell = screen.getByTestId("import-preview-cell-0-gene_id");
    fireEvent.keyDown(cell, { key: "Enter" });
    const input = screen.getByRole("textbox", { name: "Edit gene_id for row row-0" });
    fireEvent.change(input, { target: { value: "GX" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onPatchesChange).toHaveBeenLastCalledWith([
      {
        row_key: "row-0",
        column_name: "gene_id",
        old_value: "G0",
        new_value: "GX",
        patch_type: "set",
      },
    ]);
    expect(screen.getByText("GX")).toBeInTheDocument();
  });

  it("rejects additional edits after the patch budget is reached", () => {
    const onPatchesChange = vi.fn();
    render(
      <ImportPreviewTable
        columns={["gene_id", "start"]}
        rows={makeRows(2)}
        rowKey={(row) => String(row._row_key)}
        editable
        maxPatches={1}
        onPatchesChange={onPatchesChange}
      />,
    );

    fireEvent.keyDown(screen.getByTestId("import-preview-cell-0-gene_id"), { key: "Enter" });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "GX" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });

    fireEvent.keyDown(screen.getByTestId("import-preview-cell-1-gene_id"), { key: "Enter" });

    expect(screen.getByRole("alert")).toHaveTextContent("Maximum of 1 pending edits reached.");
    expect(onPatchesChange).toHaveBeenCalledTimes(1);
  });
});
