// @vitest-environment jsdom
/**
 * Locks what the route hands the shared chart facade for the heatmap.
 *
 * ChartFigure is stubbed so the assertions can read the props; no engine is
 * loaded and no pixels are produced. The cell rules, ramps and label cut-off
 * themselves are covered by the mapping and adapter suites.
 */
import * as React from "react";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { stableT } from "@/test/mocks";

const runtime = vi.hoisted(() => ({ props: null as unknown, colorScale: null as unknown }));

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: unknown) => ({ options }),
  Link: "a",
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: stableT }),
}));

vi.mock("../../components/charts/tool-chart-figure", () => ({
  ToolChartFigure: (props: unknown) => {
    runtime.props = props;
    return <div data-testid="tool-chart-figure" />;
  },
  ToolColorScale: (props: unknown) => {
    runtime.colorScale = props;
    return <div data-testid="tool-color-scale" />;
  },
}));

const { ExpPatternHeatmap } = await import("./exppattern");
type Result = Parameters<typeof ExpPatternHeatmap>[0]["result"];

interface FigureProps {
  definition: Record<string, unknown>;
  data: Array<Record<string, unknown>>;
  label: string;
  description?: string;
  tableColumns: readonly string[];
  tableRow: (datum: never) => string[];
  tooltipFormatter: (context: { datum: Record<string, unknown>; definition: unknown }) => string;
}

function result(over: Partial<Result> = {}): Result {
  return {
    assembly_id: 5,
    release_id: 1,
    assembly_name: "Glycine max",
    assembly_version: "v5",
    genes: ["g1", "g2"],
    conditions: ["c1", "c2", "c3"],
    matrix: [
      [1.5, null, -0.5],
      [0, 2.25, 3],
    ],
    row_order: [0, 1],
    clustering: "none",
    value_range: [-0.5, 3],
    missing_genes: [],
    scale: "zscore",
    ...over,
  } as Result;
}

function renderHeatmap(value: Result) {
  render(<ExpPatternHeatmap result={value} />);
  return runtime.props as FigureProps;
}

describe("ExpPatternHeatmap", () => {
  it("asks for categories on both axes and the value in the colour channel", () => {
    const { definition } = renderHeatmap(result());
    expect(definition.kind).toBe("cell");
    expect(definition.x).toBe("condition");
    expect(definition.y).toBe("gene");
    expect(definition.color).toBe("value");
    expect(definition.xAxis).toMatchObject({ scale: "category" });
    expect(definition.yAxis).toMatchObject({ scale: "category" });
    expect(definition.categoryDomain).toEqual(["c1", "c2", "c3"]);
  });

  it("clamps the colour domain to the response value_range", () => {
    expect(renderHeatmap(result({ value_range: [-1.25, 4] })).definition.colorDomain).toEqual([-1.25, 4]);
    expect(renderHeatmap(result({ value_range: [null, null] })).definition.colorDomain).toEqual([0, 1]);
  });

  it("diverges through the neutral midpoint for z-scores and stays ordered for FPKM", () => {
    expect(renderHeatmap(result({ scale: "zscore" })).definition.colorRange).toEqual([
      "var(--impact-low)",
      "#F6F8F6",
      "var(--chart-1)",
    ]);
    expect(renderHeatmap(result({ scale: "none" })).definition.colorRange).toEqual([
      "var(--chart-5)",
      "var(--chart-3)",
      "var(--chart-1)",
    ]);
  });

  it("plots one row per non-missing cell, in row-major order", () => {
    const { data } = renderHeatmap(result());
    expect(data).toEqual([
      { gene: "g1", condition: "c1", value: 1.5 },
      { gene: "g1", condition: "c3", value: -0.5 },
      { gene: "g2", condition: "c1", value: 0 },
      { gene: "g2", condition: "c2", value: 2.25 },
      { gene: "g2", condition: "c3", value: 3 },
    ]);
  });

  it("keeps the split areas and the 50-cell label cut-off", () => {
    expect(renderHeatmap(result()).definition.splitArea).toBe(true);
    const grid = (side: number) => ({
      genes: Array.from({ length: side }, (_, i) => `g${i}`),
      conditions: Array.from({ length: side }, (_, i) => `c${i}`),
      matrix: Array.from({ length: side }, (_, i) => Array.from({ length: side }, (_, j) => i + j)),
    });
    expect(renderHeatmap(result(grid(7))).definition.cellLabels).toBe(true); // 49 cells
    expect(renderHeatmap(result(grid(8))).definition.cellLabels).toBe(false); // 64 cells
  });

  it("rotates condition labels only past six columns", () => {
    expect(renderHeatmap(result()).definition.xAxis).toMatchObject({ labelsRotation: 0 });
    const many = result({ conditions: Array.from({ length: 7 }, (_, i) => `c${i}`) });
    expect(renderHeatmap(many).definition.xAxis).toMatchObject({ labelsRotation: 45 });
  });

  it("gives the tooltip escaped text for gene and condition", () => {
    const figure = renderHeatmap(result());
    const text = figure.tooltipFormatter({
      datum: { gene: "g2", condition: "<b>c2</b>", value: 2.255 },
      definition: figure.definition,
    });
    expect(text).toBe("g2 · &lt;b&gt;c2&lt;/b&gt; · 2.25");
    expect(text).not.toContain("<b>");
  });

  it("keeps the accessible name and an exact-value row per cell", () => {
    const figure = renderHeatmap(result());
    expect(figure.label).toBe("Expression pattern heatmap");
    expect(figure.description).toBe("Expression pattern heatmap");
    expect(figure.tableRow(figure.data[0] as never)).toEqual(["g1", "c1", "1.50"]);
  });
});
