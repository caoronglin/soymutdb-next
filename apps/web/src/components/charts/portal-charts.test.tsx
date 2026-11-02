/**
 * Regression cover for the five portal charts now drawn by @soymutdb/charts.
 *
 * The facade is doubled, the charts are not.
 *
 * jsdom ships no canvas backend, so the real engine cannot rasterise here and
 * these tests deliberately do not claim that anything was drawn. They drive the
 * seam this migration owns: which rows reach the facade, which definition
 * describes them, what the tooltip prints, and that the empty state, the
 * theme, the motion preference and the loading skeleton each still reach the
 * chart. The double reproduces ChartCanvas's own rendered contract (role,
 * aria-label, data-testid, data-status) so the accessibility surface is
 * asserted as the facade really renders it; everything else -- the row
 * mappings, the definition builders, the formatters, the theme resolver -- is
 * the real implementation.
 */
import * as React from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const facade = vi.hoisted(() => ({
  calls: [] as Array<Record<string, unknown>>,
  status: "rendered" as string,
}));

vi.mock("@soymutdb/charts", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  const react = await import("react");
  return {
    ...actual,
    ChartCanvas: (props: Record<string, unknown>) => {
      facade.calls.push(props);
      return react.createElement("div", {
        role: "img",
        "aria-label": String(props.label),
        "data-testid": "chart-canvas",
        "data-status": facade.status,
      });
    },
  };
});

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);

const policy = vi.hoisted(() => ({
  theme: "light" as "light" | "dark",
  reduced: false,
  intensity: "standard" as "off" | "minimal" | "standard",
}));

vi.mock("../../lib/theme-provider", () => ({ useTheme: () => ({ theme: policy.theme }) }));
vi.mock("../../lib/animation-context", () => ({
  useAnimation: () => ({ reduced: policy.reduced, intensity: policy.intensity }),
}));

import { FALLBACK_CATEGORICAL_PALETTE, FALLBACK_IMPACT_PALETTE } from "@soymutdb/charts";
import { PORTAL_DONUT_RING_CENTER } from "./portal-chart-adapter";
import { ChromosomeDensityChart } from "./chromosome-density-chart";
import { ExpressionBarChart } from "./expression-bar-chart";
import { ImpactDistribution } from "./impact-distribution";
import { ReleaseTrend } from "./release-trend";
import { VariantTypeChart } from "./variant-type-chart";

type FacadeCall = Record<string, unknown>;

function lastCall(): FacadeCall {
  const call = facade.calls[facade.calls.length - 1];
  if (!call) throw new Error("the chart never reached the facade");
  return call;
}

function rowsOf(): Array<Record<string, unknown>> {
  return lastCall().data as Array<Record<string, unknown>>;
}

function definitionOf(): Record<string, unknown> {
  return lastCall().definition as Record<string, unknown>;
}

type TooltipFn = (context: {
  datum: Record<string, unknown>;
  definition: Record<string, unknown>;
}) => string;

/** Print a tooltip the way the facade would, for one row of the real data. */
function tooltipOn(datum: Record<string, unknown>): string {
  const formatter = lastCall().tooltipFormatter as TooltipFn | undefined;
  if (typeof formatter !== "function") {
    throw new Error("the chart passed no tooltip formatter");
  }
  return formatter({ datum, definition: definitionOf() });
}

function skeleton(container: HTMLElement): HTMLElement | null {
  return container.querySelector(".skeleton-pulse");
}

type AxisFormatter = (value: number) => string;

function axisFormatterOf(): AxisFormatter | undefined {
  return lastCall().axisFormatter as AxisFormatter | undefined;
}

beforeEach(() => {
  facade.calls.length = 0;
  facade.status = "rendered";
  policy.theme = "light";
  policy.reduced = false;
  policy.intensity = "standard";
});

afterEach(() => {
  cleanup();
});

describe("ChromosomeDensityChart", () => {
  const data = [
    { chromosome: "chr1", variantCount: 10 },
    { chromosome: "2", variantCount: 20 },
  ];

  it("sends one row per chromosome with the chr prefix stripped", () => {
    render(<ChromosomeDensityChart data={data} />);

    expect(rowsOf()).toEqual([
      { category: "1", value: 10 },
      { category: "2", value: 20 },
    ]);
  });

  it("keeps the interval contract, the count format and the vertical gradient", () => {
    render(<ChromosomeDensityChart data={data} />);

    const definition = definitionOf();
    expect(definition.kind).toBe("interval");
    expect(definition.x).toBe("category");
    expect(definition.y).toBe("value");
    expect(definition.categoryOrder).toBe("appearance");
    expect(definition.valueFormat).toBe("integer");
    expect(definition.gradient).toEqual({
      from: FALLBACK_CATEGORICAL_PALETTE[0],
      to: FALLBACK_CATEGORICAL_PALETTE[3],
      direction: "vertical",
    });
  });

  it("keeps the accessible name, the 72-unit height and the unit in the tooltip", () => {
    render(<ChromosomeDensityChart data={data} />);

    expect(lastCall().label).toBe("Variant density by chromosome bar chart");
    expect(lastCall().height).toBe(288);
    expect(tooltipOn({ category: "1", value: 12345 })).toBe("1: 12,345 variants");
    expect(screen.getByRole("img", { name: "Variant density by chromosome bar chart" })).toBeTruthy();
  });

  it("drops a count that is not a number instead of poisoning the axis", () => {
    render(
      <ChromosomeDensityChart
        data={[...data, { chromosome: "chr3", variantCount: Number.NaN }]}
      />,
    );

    expect(rowsOf()).toHaveLength(2);
  });
});

describe("VariantTypeChart", () => {
  const data = [
    { name: "SNP", value: 3 },
    { name: "Indel", value: 1 },
  ];

  it("declares a donut and sends one slice per variant type", () => {
    render(<VariantTypeChart data={data} />);

    expect(rowsOf()).toEqual([
      { category: "SNP", value: 3 },
      { category: "Indel", value: 1 },
    ]);
    const definition = definitionOf();
    expect(definition.kind).toBe("donut");
    expect(definition.innerRadius).toBe(0.7);
    expect(definition.palette).toBe("categorical");
  });

  it("keeps the share the donut centre used to print in the tooltip", () => {
    render(<VariantTypeChart data={data} />);

    expect(tooltipOn({ category: "SNP", value: 3 })).toBe("SNP: 3 (75%)");
    expect(tooltipOn({ category: "Indel", value: 1 })).toBe("Indel: 1 (25%)");
  });

  it("draws the total in the ring's centre once the chart is drawn", async () => {
    const view = render(<VariantTypeChart data={data} />);

    await waitFor(() => {
      expect(screen.getByText("4")).toBeTruthy();
      expect(screen.getByText("Total")).toBeTruthy();
    });
    // The caption already carries the numbers, so the overlay must not be
    // announced a second time.
    const overlay = screen.getByText("Total").closest("[aria-hidden]");
    expect(overlay).toBeTruthy();
    // Anchored to the ring, not to the box: when the legend moves the ring to
    // 38% the overlay moves with it.
    expect(overlay?.style.left).toBe(PORTAL_DONUT_RING_CENTER.x + "%");
    expect(overlay?.style.top).toBe(PORTAL_DONUT_RING_CENTER.y + "%");

    facade.status = "loading";
    view.rerender(<VariantTypeChart data={data} />);

    await waitFor(() => {
      expect(screen.queryByText("Total")).toBeNull();
    });
  });
});

describe("value axis labels", () => {
  const density = [{ chromosome: "chr1", variantCount: 10 }];
  const impact = [{ impact: "HIGH" as const, count: 4 }];
  const trend = [{ date: "2026-01-01", cumulative: 100, newVariants: 5 }];
  const expression = [{ tissue: "Brain", mean_fpkm: 1, treatment: "Control" }];

  it("keeps the compact count labels the density, impact and trend axes had", () => {
    for (const element of [
      <ChromosomeDensityChart key="d" data={density} />,
      <ImpactDistribution key="i" data={impact} />,
      <ReleaseTrend key="t" data={trend} />,
    ]) {
      const view = render(element);
      const format = axisFormatterOf();
      expect(typeof format).toBe("function");
      expect(format?.(1500000)).toBe("1.5M");
      expect(format?.(1200)).toBe("1K");
      expect(format?.(250)).toBe("250");
      view.unmount();
    }
  });

  it("leaves the expression axis alone: its counts were never compacted", () => {
    render(<ExpressionBarChart data={expression} />);

    expect(axisFormatterOf()).toBeUndefined();
  });
});

describe("ImpactDistribution", () => {
  it("draws severities in the fixed order whatever order the payload arrives in", () => {
    render(
      <ImpactDistribution
        data={[
          { impact: "LOW", count: 1 },
          { impact: "MODIFIER", count: 2 },
          { impact: "HIGH", count: 4 },
        ]}
      />,
    );

    expect(rowsOf()).toEqual([
      { category: "HIGH", value: 4 },
      { category: "LOW", value: 1 },
      { category: "MODIFIER", value: 2 },
    ]);
  });

  it("asks for the semantic impact palette and keeps the compact height", () => {
    render(<ImpactDistribution data={[{ impact: "HIGH", count: 4 }]} />);

    // The severities read on the vertical axis again, as they did in ECharts.
    expect(definitionOf().orientation).toBe("horizontal");
    expect(definitionOf().palette).toBe("impact");
    expect(lastCall().height).toBe(256);
    expect(tooltipOn({ category: "HIGH", value: 431 })).toBe("HIGH: 431");
  });

  it("resolves the four impact tokens in severity order", async () => {
    const { resolvePortalChartTheme } = await import("./portal-chart-adapter");

    expect(resolvePortalChartTheme("light").impact).toEqual([...FALLBACK_IMPACT_PALETTE]);
  });
});

describe("ReleaseTrend", () => {
  const data = [
    { date: "2026-01-01", cumulative: 100, newVariants: 5 },
    { date: "2026-02-01", cumulative: 180, newVariants: 80 },
  ];

  it("splits each release into the two named series the legend always showed", () => {
    render(<ReleaseTrend data={data} />);

    expect(rowsOf()).toEqual([
      { date: "2026-01-01", series: "Cumulative", value: 100 },
      { date: "2026-01-01", series: "New", value: 5 },
      { date: "2026-02-01", series: "Cumulative", value: 180 },
      { date: "2026-02-01", series: "New", value: 80 },
    ]);

    const definition = definitionOf();
    expect(definition.kind).toBe("line");
    expect(definition.x).toBe("date");
    expect(definition.color).toBe("series");
    expect(definition.legend).toBe(true);
  });

  it("keeps the colors the two series always used", () => {
    render(<ReleaseTrend data={data} />);

    expect(definitionOf().palette).toEqual([
      FALLBACK_CATEGORICAL_PALETTE[0],
      FALLBACK_CATEGORICAL_PALETTE[2],
    ]);
  });

  it("prints the hovered measure with its series name", () => {
    render(<ReleaseTrend data={data} />);

    expect(tooltipOn({ date: "2026-02-01", series: "Cumulative", value: 180 })).toBe(
      "Cumulative: 180",
    );
    expect(tooltipOn({ date: "2026-02-01", series: "New", value: 80 })).toBe("New: 80");
  });

  it("keeps the thinner dashed increment line", () => {
    render(<ReleaseTrend data={data} />);

    // Exact equality on purpose: the cumulative area is still missing, and
    // declaring markType for it would render nothing while looking green.
    expect(definitionOf().seriesStyle).toEqual({
      New: { style: { lineDash: [4, 4], lineWidth: 1.5 } },
    });
  });
});

describe("ExpressionBarChart", () => {
  it("groups tissues by treatment, sorted, with the axis title kept", () => {
    render(
      <ExpressionBarChart
        data={[
          { tissue: "Liver", mean_fpkm: 2, treatment: "Control" },
          { tissue: "Brain", mean_fpkm: 1, treatment: "Treated" },
          { tissue: "Brain", mean_fpkm: 3, treatment: "Control" },
        ]}
      />,
    );

    expect(rowsOf()).toEqual([
      { category: "Brain", series: "Control", value: 3 },
      { category: "Brain", series: "Treated", value: 1 },
      { category: "Liver", series: "Control", value: 2 },
      { category: "Liver", series: "Treated", value: 0 },
    ]);

    const definition = definitionOf();
    expect(definition.color).toBe("series");
    expect(definition.legend).toBe(true);
    expect(definition.axisLabels).toEqual({ y: "Mean FPKM" });
    // The value format is deliberately unset: the facade would ride it onto
    // the titled axis and render 1.20 where the old axis rendered 1.2.
    expect(definition.valueFormat).toBeUndefined();
  });

  it("keeps the first value when a tissue repeats inside one treatment", () => {
    render(
      <ExpressionBarChart
        data={[
          { tissue: "Brain", mean_fpkm: 1.5, treatment: "Control" },
          { tissue: "Brain", mean_fpkm: 9.5, treatment: "Control" },
        ]}
      />,
    );

    expect(rowsOf()).toEqual([{ category: "Brain", series: "Control", value: 1.5 }]);
  });

  it("keeps two decimals and the unit in the tooltip", () => {
    render(
      <ExpressionBarChart data={[{ tissue: "Brain", mean_fpkm: 4.25, treatment: "Control" }]} />,
    );

    expect(tooltipOn({ category: "Brain", series: "Control", value: 4.25 })).toBe(
      "Control: 4.25 FPKM",
    );
    expect(lastCall().height).toBe(288);
  });

  it("rotates the tissue labels only once there are more than six of them", () => {
    const tissues = (count: number) =>
      Array.from({ length: count }, (_, index) => ({
        tissue: "T" + String(index),
        mean_fpkm: 1,
        treatment: "Control",
      }));

    const six = render(<ExpressionBarChart data={tissues(6)} />);
    expect((definitionOf().xAxis as { labelsRotation?: number })?.labelsRotation).toBe(0);
    six.unmount();

    render(<ExpressionBarChart data={tissues(7)} />);
    expect((definitionOf().xAxis as { labelsRotation?: number })?.labelsRotation).toBe(30);
  });
});

describe("empty, data, theme and motion", () => {
  const density = [{ chromosome: "chr1", variantCount: 10 }];
  const impact = [{ impact: "HIGH" as const, count: 4 }];
  const trend = [{ date: "2026-01-01", cumulative: 100, newVariants: 5 }];
  const expression = [{ tissue: "Brain", mean_fpkm: 1, treatment: "Control" }];
  const variants = [{ name: "SNP", value: 3 }];

  it("shows the empty placeholder and no chart when there is nothing to draw", () => {
    const cases: Array<[string, React.ReactElement]> = [
      ["density", <ChromosomeDensityChart key="d" data={[]} />],
      ["variants", <VariantTypeChart key="v" data={[]} />],
      ["impact", <ImpactDistribution key="i" data={[]} />],
      ["trend", <ReleaseTrend key="t" data={[]} />],
      ["expression", <ExpressionBarChart key="e" data={[]} />],
    ];

    for (const [name, element] of cases) {
      const view = render(element);
      expect(screen.queryByTestId("chart-canvas"), name).toBeNull();
      expect(view.container.querySelector(".ant-empty"), name).toBeTruthy();
      // No chart means no skeleton sitting on top of the placeholder.
      expect(skeleton(view.container), name).toBeNull();
      view.unmount();
    }
    expect(facade.calls).toHaveLength(0);
  });

  it("swaps back to the chart as data arrives", () => {
    const view = render(<ChromosomeDensityChart data={[]} />);
    expect(screen.queryByTestId("chart-canvas")).toBeNull();

    view.rerender(<ChromosomeDensityChart data={density} />);
    expect(screen.getByTestId("chart-canvas")).toBeTruthy();
    expect(view.container.querySelector(".ant-empty")).toBeNull();

    view.rerender(<ChromosomeDensityChart data={[]} />);
    expect(screen.queryByTestId("chart-canvas")).toBeNull();
  });

  it("forwards the portal theme mode to every chart", () => {
    policy.theme = "dark";
    const cases: React.ReactElement[] = [
      <ChromosomeDensityChart key="d" data={density} />,
      <VariantTypeChart key="v" data={variants} />,
      <ImpactDistribution key="i" data={impact} />,
      <ReleaseTrend key="t" data={trend} />,
      <ExpressionBarChart key="e" data={expression} />,
    ];

    for (const element of cases) {
      const view = render(element);
      const theme = lastCall().theme as { mode?: string; palette?: string[] };
      expect(theme.mode).toBe("dark");
      expect(theme.palette?.length).toBeGreaterThan(0);
      view.unmount();
    }
  });

  it("forwards the motion policy and lets reduced motion win", () => {
    policy.intensity = "minimal";
    const view = render(<ChromosomeDensityChart data={density} />);
    expect(lastCall().animation).toEqual({ reduced: false, intensity: "minimal" });

    policy.reduced = true;
    view.rerender(<ChromosomeDensityChart data={density} />);
    expect(lastCall().animation).toEqual({ reduced: true, intensity: "off" });
  });

  it("shows the skeleton until the facade reports the chart as drawn", async () => {
    facade.status = "loading";
    const view = render(<ChromosomeDensityChart data={density} />);

    expect(skeleton(view.container)).toBeTruthy();
    expect(skeleton(view.container)?.getAttribute("aria-hidden")).toBe("true");

    facade.status = "rendered";
    view.rerender(<ChromosomeDensityChart data={density} />);

    await waitFor(() => {
      expect(skeleton(view.container)).toBeNull();
    });
  });
});

describe("tooltip formatter identity", () => {
  // `ChartCanvas` (packages/charts/src/ChartCanvas.tsx) lists `tooltipFormatter`
  // in the dependency array of the effect that updates an already-rendered chart.
  // A factory called inline in JSX therefore handed it a new function on every
  // render, so each render rebuilt every chart option and re-ran a full G2
  // render with the same rows. `VariantTypeChart` already memoized it; the other
  // four did not.
  const density = [{ chromosome: "chr1", variantCount: 10 }];
  const impact = [{ impact: "HIGH" as const, count: 4 }];
  const trend = [{ date: "2026-01-01", cumulative: 100, newVariants: 5 }];
  const expression = [{ tissue: "Brain", mean_fpkm: 1, treatment: "Control" }];
  const variants = [{ name: "SNP", value: 3 }];

  it("hands the facade the same tooltip function on a re-render", () => {
    const cases: Array<[string, React.ReactElement, React.ReactElement]> = [
      [
        "density",
        <ChromosomeDensityChart key="d" data={density} />,
        <ChromosomeDensityChart key="d" data={density} />,
      ],
      [
        "variants",
        <VariantTypeChart key="v" data={variants} />,
        <VariantTypeChart key="v" data={variants} />,
      ],
      [
        "impact",
        <ImpactDistribution key="i" data={impact} />,
        <ImpactDistribution key="i" data={impact} />,
      ],
      [
        "trend",
        <ReleaseTrend key="t" data={trend} />,
        <ReleaseTrend key="t" data={trend} />,
      ],
      [
        "expression",
        <ExpressionBarChart key="e" data={expression} />,
        <ExpressionBarChart key="e" data={expression} />,
      ],
    ];

    for (const [name, element, again] of cases) {
      const view = render(element);
      const first = lastCall().tooltipFormatter;
      expect(typeof first, name).toBe("function");
      view.rerender(again);
      expect(lastCall().tooltipFormatter, name).toBe(first);
      view.unmount();
    }
  });
});

describe("engine imports", () => {
  it("no longer reaches for ECharts or the retired hook", async () => {
    const { readFileSync } = await import("node:fs");
    const sources = [
      "variant-type-chart.tsx",
      "chromosome-density-chart.tsx",
      "impact-distribution.tsx",
      "release-trend.tsx",
      "expression-bar-chart.tsx",
    ];

    for (const name of sources) {
      const source = readFileSync(new URL(name, import.meta.url), "utf8");
      expect(source, name).not.toMatch(/from "echarts"/);
      expect(source, name).not.toMatch(/use-echarts/);
    }
  });
});
