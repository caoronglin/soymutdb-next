// @vitest-environment jsdom
/**
 * The states the tools' charts had before the migration and must not lose:
 * a skeleton while the canvas loads, an empty message, a failure fallback, and
 * the exact-value table -- plus the colour-scale control that replaced the
 * ECharts visualMap.
 *
 * ChartCanvas is stubbed so the status transitions can be driven directly. No
 * engine is loaded and nothing is drawn.
 */
import * as React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const runtime = vi.hoisted(() => ({ status: "loading", onFailure: null as null | (() => void) }));

vi.mock("@soymutdb/charts", () => ({
  ChartCanvas: (props: { onFailure?: (error: unknown) => void }) => {
    runtime.onFailure = props.onFailure ?? null;
    return (
      <div data-testid="chart-canvas" data-status={runtime.status} role="img" aria-label={props.label} />
    );
  },
}));

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);

const { ToolChartFigure, ToolColorScale } = await import("./tool-chart-figure");

// Several cases render more than once; without this the second case would
// query the first case's DOM.
afterEach(() => cleanup());

interface Datum {
  readonly name: string;
  readonly value: number;
}

const rows: Datum[] = [
  { name: "g1", value: 1.5 },
  { name: "g2", value: -0.5 },
];

const base = {
  definition: { kind: "cell" },
  data: rows,
  label: "Heatmap",
  description: "2 genes x 2 conditions",
  tableColumns: ["Gene", "Value"],
  tableRow: (datum: Datum) => [datum.name, datum.value.toFixed(2)],
};

describe("ToolChartFigure", () => {
  it("shows the skeleton until the canvas reports itself rendered", () => {
    runtime.status = "loading";
    const view = render(<ToolChartFigure {...base} />);
    expect(screen.getByTestId("chart-skeleton")).toBeTruthy();

    runtime.status = "rendered";
    act(() => {
      view.rerender(<ToolChartFigure {...base} />);
    });
    expect(screen.queryByTestId("chart-skeleton")).toBeNull();
  });

  it("renders no canvas and no skeleton when there is nothing to draw", () => {
    render(<ToolChartFigure {...base} data={[]} emptyText="Nothing here" />);
    expect(screen.queryByTestId("chart-canvas")).toBeNull();
    expect(screen.queryByTestId("chart-skeleton")).toBeNull();
    expect(screen.getByTestId("chart-empty").textContent).toBe("Nothing here");
    expect(screen.queryByTestId("chart-values")).toBeNull();
  });

  it("falls back to the exact-value table when the engine fails", () => {
    render(<ToolChartFigure {...base} />);
    act(() => {
      runtime.onFailure?.(new Error("engine down"));
    });
    expect(screen.getByTestId("chart-unavailable").textContent).toContain("Heatmap");
    expect(screen.queryByTestId("chart-canvas")).toBeNull();
    // The values stay reachable: a failure never costs the reader the numbers.
    expect(screen.getByTestId("chart-values").textContent).toContain("1.50");
  });

  it("keeps a details/summary row per datum with the exact values", () => {
    render(<ToolChartFigure {...base} />);
    const table = screen.getByTestId("chart-values");
    expect(table.querySelectorAll("tbody tr")).toHaveLength(rows.length);
    expect(table.textContent).toContain("g2");
    expect(table.textContent).toContain("-0.50");
  });
});

describe("ToolColorScale", () => {
  const ramp = ["var(--impact-low)", "#F6F8F6", "var(--chart-1)"] as const;

  it("shows the domain in force and the gradient behind it", () => {
    const onChange = vi.fn();
    render(
      <ToolColorScale bounds={[-2, 4]} value={[-2, 4]} ramp={ramp} onChange={onChange} label="Colour range" />,
    );
    expect(screen.getByText("-2.00 – 4.00")).toBeTruthy();
    expect(screen.getByRole("group", { name: "Colour range" })).toBeTruthy();
  });

  it("narrows the domain when the upper handle moves", () => {
    const onChange = vi.fn();
    render(<ToolColorScale bounds={[-2, 4]} value={[-2, 4]} ramp={ramp} onChange={onChange} />);
    const max = screen.getByLabelText("Colour range maximum") as HTMLInputElement;
    fireEvent.change(max, { target: { value: "1" } });
    expect(onChange).toHaveBeenCalledWith([-2, 1]);
  });

  it("keeps the lower handle from crossing the upper one", () => {
    const onChange = vi.fn();
    render(<ToolColorScale bounds={[-2, 4]} value={[-2, 4]} ramp={ramp} onChange={onChange} />);
    const min = screen.getByLabelText("Colour range minimum") as HTMLInputElement;
    // The input cannot even be dragged past the upper end; the guard is the
    // second line of defence for programmatic updates.
    expect(min.max).toBe("4");
    fireEvent.change(min, { target: { value: "9" } });
    expect(onChange).toHaveBeenCalledWith([4, 4]);
  });
});
