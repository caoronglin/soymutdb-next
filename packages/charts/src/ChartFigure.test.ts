import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChartFigure, categoryBarChart, trendAreaChart } from "./index";

vi.mock("echarts", () => ({
  init: () => {
    throw new Error("mock chart renderer failure");
  },
}));

interface TestDatum {
  category: string;
  value: number;
}

let roots: Array<{ root: Root; host: HTMLDivElement }> = [];

async function render(element: React.ReactElement) {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  roots.push({ root, host });
  await act(async () => {
    root.render(element);
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  return host;
}

beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
});

afterEach(async () => {
  await act(async () => {
    for (const { root, host } of roots) {
      root.unmount();
      host.remove();
    }
  });
  roots = [];
});

describe("chart definitions", () => {
  it("builds a categorical bar chart with readable categories and values", () => {
    const definition = categoryBarChart<TestDatum>([
      { category: "missense", value: 4 },
      { category: "frameshift", value: 2 },
    ]);
    expect(definition.xAxis).toMatchObject({ type: "category", data: ["missense", "frameshift"] });
    expect(definition.series).toEqual([
      { name: "", type: "bar", data: [4, 2] },
    ]);
  });

  it("groups bars by named series", () => {
    const definition = categoryBarChart(
      [
        { category: "leaf", value: 3, series: "v4" },
        { category: "leaf", value: 5, series: "v5" },
      ],
      { seriesKey: "series" },
    );
    expect(definition.series).toEqual([
      { name: "v4", type: "bar", data: [3], barGap: "15%" },
      { name: "v5", type: "bar", data: [5], barGap: "15%" },
    ]);
  });

  it("uses a categorical date axis for trends", () => {
    const definition = trendAreaChart([{ date: "2026-09-26", value: 2 }]);
    expect(definition.xAxis).toMatchObject({ type: "category", data: ["2026-09-26"] });
    expect(definition.series).toMatchObject([{ type: "line", data: [2], areaStyle: { opacity: 0.22 } }]);
  });
});

describe("ChartFigure", () => {
  it("shows an empty state instead of creating an empty chart", async () => {
    const host = await render(
      React.createElement(ChartFigure<TestDatum>, {
        definition: categoryBarChart([]),
        data: [],
        label: "Variant types",
        tableColumns: ["Type", "Count"],
        tableRow: (datum) => [datum.category, String(datum.value)],
      }),
    );

    expect(host.querySelector('[data-testid="chart-empty"]')?.textContent).toContain("No data");
    expect(host.querySelector('[data-testid="chart-values"]')).toBeNull();
  });

  it("keeps the exact-value table available when the chart runtime fails", async () => {
    const host = await render(
      React.createElement(ChartFigure<TestDatum>, {
        definition: categoryBarChart([{ category: "missense", value: 4 }]),
        data: [{ category: "missense", value: 4 }],
        label: "Variant types",
        description: "Variant counts by consequence",
        tableColumns: ["Type", "Count"],
        tableRow: (datum) => [datum.category, String(datum.value)],
      }),
    );

    expect(host.querySelector('[data-testid="chart-unavailable"]')?.textContent).toContain("could not be drawn");
    expect(host.querySelector('[data-testid="chart-values"]')?.textContent).toContain("missense");
    expect(host.querySelector('[data-testid="chart-values"]')?.textContent).toContain("4");
    // The fallback renders no `role="img"` wrapper, so the description stays
    // reachable as visually hidden text rather than via aria-describedby.
    expect(host.querySelector('[data-testid="chart-unavailable"]')?.textContent).toContain(
      "Variant counts by consequence",
    );
  });
});
