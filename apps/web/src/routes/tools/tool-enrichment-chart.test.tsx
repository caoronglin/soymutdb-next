// @vitest-environment jsdom
/**
 * Locks what the route hands the shared chart facade.
 *
 * ChartFigure is stubbed so the assertions can read the props the route passes:
 * the definition, the rows, the per-datum style and the tooltip formatter.
 * That is a wiring test, not a rendering one -- no pixels are produced here,
 * and the engine is never loaded. The numbers themselves are covered by the
 * mapping and adapter suites.
 */
import * as React from "react";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { stableT } from "@/test/mocks";

const runtime = vi.hoisted(() => ({ props: null as unknown }));

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
  ToolColorScale: () => <div data-testid="tool-color-scale" />,
}));

const { EnrichmentSignificanceChart } = await import("./enrichment");
type Row = Parameters<typeof EnrichmentSignificanceChart>[0]["rows"][number];

interface FigureProps {
  definition: Record<string, unknown>;
  data: Array<Record<string, unknown>>;
  label: string;
  description?: string;
  tableColumns: readonly string[];
  tableRow: (datum: never) => string[];
  tooltipFormatter: (context: { datum: Record<string, unknown>; definition: unknown }) => string;
  datumStyle?: (datum: Record<string, unknown>) => { fill?: string };
}

const rows: Row[] = [
  { id: "GO:2", name: "membrane part", p: 0.02, q: 0.5, size: 4 },
  { id: "GO:1", name: "binding", p: 1e-5, q: 1e-10, size: 40, es: -1.5 },
  { id: "GO:3", name: "a term whose name is far longer than forty characters", p: 0.03, q: 0.1, size: 16, es: 2 },
];

function renderChart(isGsea: boolean, view: "bubble" | "bar") {
  render(<EnrichmentSignificanceChart rows={rows} isGsea={isGsea} view={view} />);
  return runtime.props as FigureProps;
}

describe("EnrichmentSignificanceChart", () => {
  it("asks for a value axis on x and a reversed category axis on y", () => {
    const { definition } = renderChart(false, "bubble");
    expect(definition.x).toBe("logQ");
    expect(definition.y).toBe("termLabel");
    expect(definition.xAxis).toMatchObject({ scale: "value" });
    expect(definition.yAxis).toMatchObject({ scale: "category", reverse: true });
  });

  it("keeps the sqrt radius semantics through the shared size scale", () => {
    const bubble = renderChart(false, "bubble").definition;
    expect(bubble.kind).toBe("bubble");
    expect(bubble.size).toBe("size");
    expect(bubble.sizeTransform).toBe("sqrt");
    // sizeRange is [min, max] and the runtime adds (max - min) * ratio, so the
    // largest term lands on 8 + 16 = 24, never on 16.
    expect(bubble.sizeRange).toEqual([8, 24]);
    expect(bubble.sizeDomain).toEqual([0, 40]);

    // The bar view carries the same values without a size channel.
    const bar = renderChart(false, "bar").definition;
    expect(bar.kind).toBe("interval");
    expect(bar.size).toBeUndefined();
  });

  it("emits the rows in the axis order the reversed y axis needs", () => {
    const { data, definition } = renderChart(false, "bubble");
    // Ascending q is GO:1, GO:3, GO:2; the reversed axis puts the first row at
    // the top, which is the order the ECharts chart drew.
    expect(data.map((d) => d.logQ)).toEqual([
      -Math.log10(0.5),
      -Math.log10(0.1),
      10,
    ]);
    expect(data[2].termLabel).toBe("binding");
    expect(definition.yAxis).toMatchObject({ reverse: true });
  });

  it("matches the row label against the truncated axis label", () => {
    const { data } = renderChart(false, "bubble");
    const name = "a term whose name is far longer than forty characters";
    const long = data.find((d) => d.term === name);
    expect(long?.termLabel).toBe(`${name.slice(0, 40)}…`);
  });

  it("paints ORA flat and GSEA by the sign of ES", () => {
    const ora = renderChart(false, "bubble");
    expect(new Set(ora.data.map((d) => d.color))).toEqual(new Set(["var(--chart-2)"]));

    const gsea = renderChart(true, "bubble");
    expect(gsea.datumStyle?.(gsea.data[2])).toEqual({ fill: "var(--impact-low)" });
    expect(gsea.datumStyle?.(gsea.data[1])).toEqual({ fill: "var(--chart-1)" });
  });

  it("gives the tooltip escaped text, never the legacy HTML", () => {
    const figure = renderChart(true, "bubble");
    const html = figure.tooltipFormatter({
      datum: { ...figure.data[2], term: '<img src=x onerror="a">' },
      definition: figure.definition,
    });
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<div");
    expect(html.startsWith("&lt;img")).toBe(true);
    expect(html).toContain("-log10(q): 10.00");
    expect(html).toContain("NES: –");
  });

  it("keeps the accessible name and an exact-value table for every row", () => {
    const figure = renderChart(false, "bubble");
    expect(figure.label).toBe("Significance plot");
    expect(figure.description).toContain("binding 10.00 40");
    expect(figure.tableColumns).toHaveLength(5);
    expect(figure.tableRow(figure.data[0] as never)).toHaveLength(5);
  });
});
