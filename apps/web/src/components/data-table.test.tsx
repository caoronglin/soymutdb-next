/**
 * The adapter's default row key, verified by rendering rather than by reading.
 *
 * The 2026-10-02 audit flagged "the call sites pass no rowKey" as a possible
 * defect, with the counter-argument that the adapter provides a default. Both
 * were untested. This file settles it:
 *
 * - a caller-supplied rowKey is used and survives a reorder;
 * - without one, the adapter still produces keys (it never renders an
 *   unkeyed/undefined-key table), and they are index-based;
 * - index-based keys are stable *within* one rendered page and change when the
 *   page changes. That is the documented limitation, stated here so it is not
 *   mistaken for a stable identity.
 */
import * as React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DataTable, type DataTableColumn } from "./data-table";

interface Row {
  id: string;
  name: string;
}

vi.mock("@/lib/antd", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@/lib/antd");
  return {
    ...actual,
    Table: ({
      rowKey,
      columns,
      dataSource,
    }: {
      rowKey: (row: unknown, index?: number) => string;
      columns: Array<{ id?: string; dataIndex?: string; key?: string; render?: (v: unknown, r: unknown) => React.ReactNode }>;
      dataSource: unknown[];
    }) => (
      <table data-testid="table">
        <tbody>
          {(dataSource as Array<Record<string, unknown>>).map((row, index) => (
            <tr key={rowKey(row, index)} data-rowkey={rowKey(row, index)}>
              {columns.map((column) => (
                <td key={column.id ?? column.key}>{column.render ? column.render(undefined, row) : String(row[column.id ?? ""])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    ),
  };
});

const rows: Row[] = [
  { id: "g1", name: "Glyma.01G000100" },
  { id: "g2", name: "Glyma.01G000200" },
];

const columns: Array<DataTableColumn<Row>> = [
  { id: "name", header: "Gene", cell: (row) => row.name },
];

function keys(): string[] {
  return [...document.querySelectorAll("tr")].map((row) => row.getAttribute("data-rowkey") ?? "");
}

afterEach(cleanup);

describe("DataTable row keys", () => {
  it("uses a caller-supplied rowKey and keeps it across a reorder", () => {
    const { rerender } = render(
      <DataTable<Row> columns={columns} data={rows} rowKey={(row) => row.id} />,
    );
    expect(keys()).toEqual(["g1", "g2"]);

    rerender(<DataTable<Row> columns={columns} data={[rows[1], rows[0]]} rowKey={(row) => row.id} />);
    expect(keys()).toEqual(["g2", "g1"]);
  });

  it("still produces keys when the caller passes none", () => {
    render(<DataTable<Row> columns={columns} data={rows} />);
    const rendered = keys();
    expect(rendered).toHaveLength(2);
    expect(rendered.every((key) => key.length > 0)).toBe(true);
    expect(new Set(rendered).size).toBe(2);
  });

  it("documents the index-based limitation instead of hiding it", () => {
    // Within one page the fallback is stable; across pages it is not. That is
    // acceptable for keyset-paginated tables whose rows are re-fetched per
    // page, and wrong for a list that prepends rows in place. The test states
    // the behaviour so a future change to the default has to be deliberate.
    const { rerender } = render(<DataTable<Row> columns={columns} data={rows} />);
    expect(keys()).toEqual(["0", "1"]);

    rerender(<DataTable<Row> columns={columns} data={[rows[0]]} />);
    expect(keys()).toEqual(["0"]);
  });

  it("renders the rows it was given", () => {
    render(<DataTable<Row> columns={columns} data={rows} rowKey={(row) => row.id} />);
    expect(screen.getByText("Glyma.01G000100")).toBeTruthy();
    expect(screen.getByText("Glyma.01G000200")).toBeTruthy();
  });
});