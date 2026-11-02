/**
 * The option builder is pure and runs without an engine instance, so these
 * tests cover the translation from the serializable ChartDefinition to engine
 * options. They assert the option *shape*, not that anything was painted.
 */
import { describe, expect, it } from "vitest";

import { CHART_LIBRARY, buildChartOptions, resolveCategoryDomain, themeOverrides } from "./g2-runtime";
import { createValueFormatter, gradientCss } from "./format";
import { FALLBACK_CATEGORICAL_PALETTE, resolveChartTheme, resolvePalette } from "./theme";
import type { ChartDefinition } from "./definitions";
// The G2 field encoder reads a column out of a tabular array, so the shape the
// builder hands it is G2's own `TabularData`, not the looser local record type
// the rest of this file asserts against.
import type { TabularData } from "@antv/g2/esm/runtime/types/common";

const theme = resolveChartTheme({ mode: "light" });

/** The builder is intentionally loosely typed; this narrows it for assertions. */
interface EngineOptions {
  type: string;
  encode: {
    x: { type: "field"; value: string };
    y: { type: "field"; value: string };
    color?: { type: "field"; value: string };
    size?: { type: "field" | "transform"; value: string | ((datum: Record<string, unknown>) => number) };
  };
  transform?: Array<{ type: string }>;
  scale: {
    x: { type?: string; domain?: string[]; guide?: Record<string, unknown>; reverse?: boolean };
    y: { type?: string; guide?: Record<string, unknown>; reverse?: boolean };
    size?: { type: string };
    color?: unknown;
  };
  coordinate?: { type: string; innerRadius: number };
  style: { fill?: string | ((datum: Record<string, unknown>) => string) };
  children?: Array<Record<string, unknown>>;
  label?: { field?: string; text?: unknown };
  legend?: boolean | { color: { position: string; orientation?: string; tickCount?: number; labelFormatter?: (value: unknown, index: number) => string } };
  legendType?: string;
  legendPosition?: string;
  legendOrientation?: string;
  legendItems?: string[];
  data?: TabularData;
  theme: Record<string, unknown>;
  tooltip: false | { title: string; items: Array<((datum: Record<string, unknown>) => { name: string; value: string }) | { field: string; name: string; valueFormatter: (value: number) => string }> };
  interaction: {
    tooltip: boolean;
  };
}

function toOptions(options: Record<string, unknown>): EngineOptions {
  return options as unknown as EngineOptions;
}

function fillOf(options: EngineOptions): (datum: Record<string, unknown>) => string {
  const fill = options.style.fill;
  if (typeof fill !== "function") throw new Error("expected a per-series fill callback");
  return fill;
}

function build(definition: ChartDefinition, data: Array<Record<string, unknown>> = []) {
  return toOptions(buildChartOptions({ definition, data, theme, animate: false }));
}

describe("selective engine library", () => {
  it("encodes real records using the installed G2 field encoder", () => {
    const options = build({ kind: "interval", x: "category", y: "value" }, [
      { category: "A", value: 3 }, { category: "B", value: 7 },
    ]);
    const encoder = CHART_LIBRARY["encode.field"];
    expect(encoder(options.encode.x)(options.data!)).toEqual(["A", "B"]);
    expect(encoder(options.encode.y)(options.data!)).toEqual([3, 7]);
  });
  it("registers the default light theme G2 asks for", () => {
    expect(CHART_LIBRARY["theme.light"]).toBeTypeOf("function");
  });

  it("registers only what the production chart kinds need, not the full stdlib", () => {
    expect(CHART_LIBRARY["coordinate.theta"]).toBeTypeOf("function");
    expect(CHART_LIBRARY["coordinate.polar"]).toBeTypeOf("function");
    expect(CHART_LIBRARY["transform.stackY"]).toBeTypeOf("function");
    // A component the facade never uses must not creep in.
    const asRecord = CHART_LIBRARY as Record<string, unknown>;
    expect(asRecord["composition.facet"]).toBeUndefined();
    expect(asRecord["mark.wordCloud"]).toBeUndefined();
  });
});

describe("ordinal ordering", () => {
  const data = [
    { category: "beta", value: 1 },
    { category: "alpha", value: 2 },
    { category: "gamma", value: 3 },
  ];
  const base: ChartDefinition = { kind: "interval", x: "category", y: "value" };

  it("defaults to first-appearance order", () => {
    expect(resolveCategoryDomain(data, base)).toEqual(["beta", "alpha", "gamma"]);
  });

  it("sorts ascending and descending on request", () => {
    expect(resolveCategoryDomain(data, { ...base, categoryOrder: "asc" })).toEqual([
      "alpha",
      "beta",
      "gamma",
    ]);
    expect(resolveCategoryDomain(data, { ...base, categoryOrder: "desc" })).toEqual([
      "gamma",
      "beta",
      "alpha",
    ]);
  });

  it("lets an explicit domain win over the sort order", () => {
    expect(
      resolveCategoryDomain(data, {
        ...base,
        categoryOrder: "asc",
        categoryDomain: ["gamma", "beta"],
      }),
    ).toEqual(["gamma", "beta"]);
  });

  it("pins the ordered domain onto the x scale", () => {
    const options = build({ ...base, categoryOrder: "asc" }, data);
    expect(options.scale.x.domain).toEqual(["alpha", "beta", "gamma"]);
  });
});

describe("chart kinds map to the expected marks and coordinates", () => {
  it("maps interval, line, area and cell to their marks", () => {
    expect(build({ kind: "interval", x: "a", y: "b" }).type).toBe("interval");
    expect(build({ kind: "line", x: "a", y: "b" }).type).toBe("line");
    expect(build({ kind: "area", x: "a", y: "b" }).type).toBe("area");
    expect(build({ kind: "cell", x: "a", y: "b", color: "v" }).type).toBe("cell");
  });

  it("uses a theta coordinate for pie and a hole for donut", () => {
    const pie = build({ kind: "pie", x: "name", y: "value" });
    expect(pie.coordinate).toMatchObject({ type: "theta", innerRadius: 0 });
    expect(pie.encode).toMatchObject({ y: { type: "field", value: "value" }, color: { type: "field", value: "name" } });

    const donut = build({ kind: "donut", x: "name", y: "value", innerRadius: 0.65 });
    expect(donut.coordinate).toMatchObject({ type: "theta", innerRadius: 0.65 });
  });

  it("stacks only when asked, through the stackY mark transform", () => {
    const plain = build({ kind: "interval", x: "a", y: "b", color: "s" });
    expect(plain.transform).toBeUndefined();

    const stacked = build({ kind: "interval", x: "a", y: "b", color: "s", stack: true });
    expect(stacked.transform).toEqual([{ type: "stackY" }]);
  });

  it("uses a polar coordinate for polar and radial", () => {
    expect(build({ kind: "polar", x: "a", y: "b" }).coordinate).toMatchObject({ type: "polar" });
    expect(build({ kind: "radial", x: "a", y: "b" }).coordinate).toMatchObject({ type: "radial" });
  });

  it("carries the computed bubble radius through an identity size scale", () => {
    const options = build({ kind: "bubble", x: "a", y: "b", size: "s" });
    expect(options.encode.size?.type).toBe("transform");
    expect(options.encode.size?.value).toBeTypeOf("function");
    expect(options.scale.size).toMatchObject({ type: "identity" });
  });
});

describe("theme and palette", () => {
  it("accepts a resolved palette without any theme provider", () => {
    const resolved = resolveChartTheme({ palette: ["#a", "#b", "#c"] });
    expect(resolved.categorical).toEqual(["#a", "#b", "#c"]);
  });

  it("falls back to the historical colors when nothing is supplied", () => {
    expect(resolveChartTheme({}).categorical).toEqual([...FALLBACK_CATEGORICAL_PALETTE]);
  });

  it("selects named and explicit palettes", () => {
    expect(resolvePalette(undefined, theme)).toEqual(theme.categorical);
    expect(resolvePalette("impact", theme)).toEqual(theme.impact);
    expect(resolvePalette(["#1", "#2"], theme)).toEqual(["#1", "#2"]);
  });

  it("puts the resolved theme into the options, not the constructor", () => {
    const options = build({ kind: "interval", x: "a", y: "b" });
    expect(options.theme).toMatchObject({ type: "light" });
    expect(themeOverrides(theme)).toMatchObject({ view: { plotFill: "transparent" } });
  });

  it("turns a gradient into a CSS gradient string", () => {
    expect(gradientCss({ from: "red", to: "blue" })).toBe("linear-gradient(180deg, #ff0000, #0000ff)");
    expect(gradientCss({ from: "red", to: "blue", direction: "horizontal" })).toBe(
      "linear-gradient(90deg, #ff0000, #0000ff)",
    );
    // Gradient stops are resolved: the canvas cannot read oklch inside a
    // gradient, so an unresolved stop would drop the whole fill.
    const options = build({
      kind: "area",
      x: "a",
      y: "b",
      gradient: { from: "oklch(0.55 0.14 152)", to: "#000" },
    });
    expect(String(options.style.fill)).toContain("linear-gradient");
    expect(String(options.style.fill)).not.toContain("oklch");
  });
});

describe("tooltip and value formatting", () => {
  it("resolves the named value format tokens", () => {
    expect(createValueFormatter("integer")(1234)).toBe("1,234");
    expect(createValueFormatter("decimal")(1234.5)).toBe("1,234.50");
    expect(createValueFormatter("percent")(12.34)).toBe("12.3%");
    expect(createValueFormatter("compact")(1500)).toBe("1.5k");
    expect(createValueFormatter("bytes")(2048)).toBe("2.0 KiB");
    expect(createValueFormatter(".3f")(1.23456)).toBe("1.235");
    expect(createValueFormatter("integer")(Number.NaN)).toBe("--");
  });

  it("wires a custom tooltip formatter from a prop, keeping the definition serializable", () => {
    const definition: ChartDefinition = { kind: "interval", x: "a", y: "b" };
    expect(() => JSON.stringify(definition)).not.toThrow();

    const options = toOptions(buildChartOptions({
      definition,
      data: [],
      theme,
      animate: false,
      tooltipFormatter: ({ datum }) => "custom:" + String(datum["a"]),
    }));
    const tooltip = options.tooltip;
    if (tooltip === false) throw new Error("expected a tooltip configuration");
    const item = tooltip.items[0];
    if (typeof item !== "function") throw new Error("expected a datum tooltip item");
    expect(item({ a: "x" })).toEqual({ name: "b", value: "custom:x" });
  });

  it("turns the tooltip off when the definition asks for it", () => {
    const options = build({ kind: "interval", x: "a", y: "b", tooltip: { show: false } });
    expect(options.interaction.tooltip).toBe(false);
  });
});

describe("axis formatter", () => {
  it("puts a consumer formatter on the value-axis guide", () => {
    const formatFileSize = (bytes: number): string => {
      if (bytes <= 0) return "—";
      const units = ["B", "KB", "MB", "GB", "TB"];
      const unit = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
      return (bytes / 1024 ** unit).toFixed(1) + " " + units[unit];
    };
    const options = toOptions(
      buildChartOptions({
        definition: { kind: "line", x: "date", y: "bytes" },
        data: [],
        theme,
        animate: false,
        axisFormatter: formatFileSize,
      }),
    );
    const guide = options.scale.y.guide as Record<string, unknown>;
    expect(typeof guide.labelFormatter).toBe("function");
    const labelFormatter = guide.labelFormatter as (value: number) => string;
    // Byte-for-byte the behavior the console chart relies on today.
    expect(labelFormatter(0)).toBe("—");
    expect(labelFormatter(2048)).toBe("2.0 KB");
    expect(labelFormatter(1048576)).toBe("1.0 MB");
  });

  it("falls back to the definition valueFormat when no formatter prop is given", () => {
    const options = build({ kind: "line", x: "date", y: "bytes", valueFormat: "bytes" });
    const guide = options.scale.y.guide as Record<string, unknown>;
    const labelFormatter = guide.labelFormatter as (value: number) => string;
    expect(labelFormatter(2048)).toBe("2.0 KiB");
  });
});

describe("per-series gradients", () => {
  const data = [
    { date: "d1", bytes: 1, series: "Imported" },
    { date: "d1", bytes: 2, series: "Failed" },
  ];

  it("gives each series its own ramp without merging them", () => {
    const options = build(
      {
        kind: "area",
        x: "date",
        y: "bytes",
        color: "series",
        seriesGradients: {
          Imported: { from: "#2f7d32", fromOpacity: 0.25, toOpacity: 0.02 },
          Failed: { from: "#c0392b", fromOpacity: 0.2, toOpacity: 0.02 },
        },
      },
      data,
    );
    expect(typeof options.style.fill).toBe("function");
    const fill = fillOf(options);
    const imported = fill(data[0]);
    const failed = fill(data[1]);
    // Distinct bases, distinct ramps.
    expect(imported).toContain("47, 125, 50");
    expect(imported).toContain("0.25");
    expect(failed).toContain("192, 57, 43");
    expect(failed).toContain("0.2");
    expect(imported).not.toBe(failed);
  });

  it("falls back to the plain palette color for a series with no ramp", () => {
    const options = build(
      {
        kind: "area",
        x: "date",
        y: "bytes",
        color: "series",
        seriesGradients: { Imported: { from: "#2f7d32" } },
      },
      data,
    );
    const fill = fillOf(options);
    expect(fill(data[1])).toMatch(/^#|rgb/);
  });
});

describe("point symbols", () => {
  it("adds no point mark by default, matching the charts being replaced", () => {
    const options = build({ kind: "line", x: "date", y: "bytes" });
    expect(options.type).toBe("line");
    expect(options.children).toBeUndefined();
  });

  it("adds a companion point mark only when showPoints is requested", () => {
    const options = build({ kind: "line", x: "date", y: "bytes", showPoints: true });
    expect(options.type).toBe("view");
    expect(Array.isArray(options.children)).toBe(true);
    expect((options.children as Array<{ type: string }>).map((child) => child.type)).toEqual([
      "line",
      "point",
    ]);
  });

  it("leaves interval charts alone, since they are already discrete", () => {
    const options = build({ kind: "interval", x: "a", y: "b", showPoints: true });
    expect(options.type).toBe("interval");
    expect(options.children).toBeUndefined();
  });
});

describe("orientation and explicit axis scales", () => {
  it("transposes a horizontal chart so the category reads on y", () => {
    const options = build({ kind: "interval", x: "category", y: "value", orientation: "horizontal" });
    expect(options.coordinate).toEqual({ transform: [{ type: "transpose" }] });
  });

  it("leaves a vertical chart untransposed", () => {
    const options = build({ kind: "interval", x: "category", y: "value" });
    expect(options.coordinate).toBeUndefined();
  });

  it("supports a value x axis above a reversed category y axis", () => {
    const options = build({
      kind: "bubble",
      x: "logQ",
      y: "label",
      size: "size",
      categoryDomain: ["a", "b"],
      xAxis: { scale: "value" },
      yAxis: { scale: "category", reverse: true },
    });
    expect(options.scale.x.type).toBe("linear");
    expect(options.scale.y.type).toBe("band");
    expect(options.scale.y.reverse).toBe(true);
  });

  it("supports a heatmap with a category on both axes", () => {
    const options = build({
      kind: "cell",
      x: "condition",
      y: "gene",
      xAxis: { scale: "category" },
      yAxis: { scale: "category", reverse: true },
    });
    expect(options.scale.x.type).toBe("band");
    expect(options.scale.y.type).toBe("band");
    expect(options.scale.y.reverse).toBe(true);
    // The cell value has to reach the color channel.
    expect(options.encode.color).toEqual({ type: "field", value: "gene" });
  });

  it("rotates axis labels by the requested degrees", () => {
    const options = build({
      kind: "cell",
      x: "condition",
      y: "gene",
      xAxis: { labelsRotation: 45 },
      yAxis: { labelsRotation: 0 },
    });
    expect((options.scale.x.guide as Record<string, unknown>).labelRotate).toBe(45);
    expect((options.scale.y.guide as Record<string, unknown>).labelRotate).toBe(0);
  });

  it("puts splitArea on the axis guides", () => {
    const options = build({ kind: "cell", x: "a", y: "b", splitArea: true });
    expect((options.scale.x.guide as Record<string, unknown>).splitArea).toBe(true);
    expect((options.scale.y.guide as Record<string, unknown>).splitArea).toBe(true);
  });
});

describe("heatmap color domain and range", () => {
  it("clamps the color scale to the response value range", () => {
    const options = build({
      kind: "cell",
      x: "condition",
      y: "gene",
      colorDomain: [-2.5, 3.1],
    });
    expect(options.scale.color).toMatchObject({ domain: [-2.5, 3.1], clamp: true });
  });

  it("expands a three-stop diverging ramp to resolved colors", () => {
    const options = build({
      kind: "cell",
      x: "condition",
      y: "gene",
      colorRange: ["oklch(0.6 0.13 240)", "#F6F8F6", "oklch(0.55 0.14 152)"],
    });
    const color = options.scale.color as { type: string; range: string[] };
    expect(color.type).toBe("linear");
    expect(color.range).toHaveLength(3);
    // The middle stop stays verbatim; the oklch stops are converted.
    expect(color.range[1]).toBe("#f6f8f6");
    expect(color.range[0]).toMatch(/^#|rgb/);
    expect(color.range[2]).toMatch(/^#|rgb/);
  });
});

describe("bubble radius", () => {
  const data = [
    { x: 1, y: "a", size: 1 },
    { x: 2, y: "b", size: 100 },
  ];

  it("reproduces 8 + 16 * sqrt(size / max) by default", () => {
    const options = build({ kind: "bubble", x: "x", y: "y", size: "size" }, data);
    const r = (options.style as Record<string, (d: Record<string, unknown>) => number>).r;
    expect(r(data[0])).toBeCloseTo(8 + 16 * Math.sqrt(1 / 100), 6);
    expect(r(data[1])).toBeCloseTo(8 + 16 * Math.sqrt(1), 6);
    expect(options.scale.size).toEqual({ type: "identity" });
    const encoded = CHART_LIBRARY["encode.transform"]({ value: options.encode.size!.value as (datum: Record<string, unknown>) => number })(data);
    expect(encoded[0]).toBeCloseTo(r(data[0]), 6);
    expect(encoded[1]).toBeCloseTo(24, 6);
  });

  it("honours an explicit range", () => {
    const options = build(
      { kind: "bubble", x: "x", y: "y", size: "size", sizeRange: [4, 36] },
      data,
    );
    const r = (options.style as Record<string, (d: Record<string, unknown>) => number>).r;
    expect(r(data[1])).toBeCloseTo(36, 6);
  });

  it("supports a linear transform when the consumer asks for one", () => {
    const options = build(
      { kind: "bubble", x: "x", y: "y", size: "size", sizeTransform: "linear", sizeRange: [0, 100] },
      data,
    );
    const r = (options.style as Record<string, (d: Record<string, unknown>) => number>).r;
    expect(r(data[0])).toBeCloseTo(1, 6);
    expect(r(data[1])).toBeCloseTo(100, 6);
  });

  it("lets a consumer-supplied radius win outright", () => {
    const options = toOptions(
      buildChartOptions({
        definition: { kind: "point", x: "x", y: "y" },
        data,
        theme,
        animate: false,
        datumStyle: (datum) => ({ r: Number(datum["x"]) * 3, fill: "#123456" }),
      }),
    );
    const style = options.style as unknown as Record<string, (d: Record<string, unknown>) => number>;
    expect(style.r(data[1])).toBeCloseTo(6, 6);
  });
});

describe("per-series mark and style", () => {
  const data = [
    { date: "d1", value: 1, series: "Cumulative" },
    { date: "d1", value: 2, series: "New" },
  ];

  it("gives each series its own ramp and its own dash pattern", () => {
    const options = build(
      {
        kind: "line",
        x: "date",
        y: "value",
        color: "series",
        seriesStyle: {
          Cumulative: { gradient: { from: "#2f7d32", fromOpacity: 0.25 } },
          New: { gradient: { from: "#c0392b", fromOpacity: 0.2 }, style: { lineDash: [4, 2] } },
        },
      },
      data,
    );
    const style = options.style as unknown as Record<string, (d: Record<string, unknown>) => unknown>;
    expect(String(style.fill(data[0]))).toContain("47, 125, 50");
    expect(String(style.fill(data[1]))).toContain("192, 57, 43");
    expect(style.lineDash(data[0])).toEqual([]);
    expect(style.lineDash(data[1])).toEqual([4, 2]);
  });

  it("applies pointsStyle to the companion point mark", () => {
    const options = build({
      kind: "line",
      x: "date",
      y: "value",
      showPoints: true,
      pointsStyle: { size: 6, fill: "#2f7d32" },
    });
    const children = options.children as Array<Record<string, unknown>>;
    expect(children[1].style).toMatchObject({ size: 6, fill: "#2f7d32" });
  });
});

describe("axis formatter independence", () => {
  it("applies the formatter with no axis title at all", () => {
    const options = toOptions(
      buildChartOptions({
        definition: { kind: "line", x: "date", y: "bytes" },
        data: [],
        theme,
        animate: false,
        axisFormatter: (value) => value.toFixed(2),
      }),
    );
    const guide = options.scale.y.guide as Record<string, unknown>;
    expect(guide.title).toBeUndefined();
    expect((guide.labelFormatter as (v: number) => string)(1.2)).toBe("1.20");
  });
});

describe("value axis follows the orientation", () => {
  it("formats x, not y, when the chart is transposed", () => {
    const options = toOptions(
      buildChartOptions({
        definition: {
          kind: "interval",
          x: "category",
          y: "value",
          orientation: "horizontal",
        },
        data: [],
        theme,
        animate: false,
        axisFormatter: (value) => value.toFixed(1),
      }),
    );
    const xGuide = options.scale.x.guide as Record<string, unknown>;
    const yGuide = options.scale.y.guide as Record<string, unknown>;
    expect(typeof xGuide.labelFormatter).toBe("function");
    expect(yGuide.labelFormatter).toBeUndefined();
    expect((xGuide.labelFormatter as (v: number) => string)(2)).toBe("2.0");
  });

  it("formats y on a vertical chart", () => {
    const options = build({ kind: "interval", x: "category", y: "value" });
    const xGuide = options.scale.x.guide as Record<string, unknown>;
    expect(xGuide.labelFormatter).toBeUndefined();
    expect(options.scale.y.guide).toHaveProperty("labelFormatter");
  });
});

describe("cell labels", () => {
  it("labels cells only when the consumer asked for it", () => {
    const off = build({ kind: "cell", x: "condition", y: "gene" });
    expect(off.label).toBeUndefined();

    const on = build({ kind: "cell", x: "condition", y: "gene", cellLabels: true });
    expect(on.label).toMatchObject({ field: "gene" });
    expect(typeof (on.label as { text: unknown }).text).toBe("function");
  });
});

describe("bar style pass-through", () => {
  it("carries radius and width straight to the mark style", () => {
    const options = build({ kind: "interval", x: "a", y: "b", barStyle: { radius: 4, width: 0.6 } });
    expect(options.style).toMatchObject({ radius: 4, width: 0.6 });
  });
});

describe("legend", () => {
  it("keeps the bare boolean meaning it always had", () => {
    expect(build({ kind: "interval", x: "a", y: "b", color: "s", legend: false }).legend).toBe(false);
    expect(build({ kind: "interval", x: "a", y: "b", color: "s", legend: true }).legend).toEqual({ color: { position: "top" } });
  });

  it("places and orients a discrete legend", () => {
    const options = build({
      kind: "interval",
      x: "a",
      y: "b",
      color: "s",
      legend: { position: "right", orientation: "vertical" },
    });
    expect(options.legend).toEqual({ color: { position: "right", orientation: "vertical" } });
  });

  it("draws a continuous legend for a heatmap and keeps explicit labels", () => {
    const options = build({
      kind: "cell",
      x: "condition",
      y: "gene",
      legend: { position: "top", labels: ["low", "mid", "high"] },
    });
    const legend = options.legend;
    if (!legend || typeof legend === "boolean") throw new Error("expected color legend");
    expect(legend.color.position).toBe("top");
    expect(legend.color.tickCount).toBe(3);
    expect(legend.color.labelFormatter?.(0, 1)).toBe("mid");
  });
});

describe("per-series mark types", () => {
  const data = [
    { date: "d1", value: 10, series: "Cumulative" },
    { date: "d1", value: 2, series: "New" },
  ];

  it("splits into one child per series when siblings need different marks", () => {
    const options = build(
      {
        kind: "line",
        x: "date",
        y: "value",
        color: "series",
        seriesStyle: {
          Cumulative: { markType: "area", gradient: { from: "#2f7d32", fromOpacity: 0.25 } },
          New: { markType: "line", style: { lineDash: [4, 2] } },
        },
      },
      data,
    );
    expect(options.type).toBe("view");
    const children = options.children as Array<Record<string, unknown>>;
    expect(children.map((child) => child.type)).toEqual(["area", "line"]);
    // Each child keeps only its own rows: the series are never merged.
    expect(children[0].data).toEqual([data[0]]);
    expect(children[1].data).toEqual([data[1]]);
    expect(String((children[0].style as Record<string, unknown>).fill)).toContain("47, 125, 50");
    expect(children[1].style).toMatchObject({ lineDash: [4, 2] });
  });

  it("does not split when every series shares one mark", () => {
    const options = build(
      {
        kind: "line",
        x: "date",
        y: "value",
        color: "series",
        seriesStyle: { Cumulative: { gradient: { from: "#2f7d32" } } },
      },
      data,
    );
    expect(options.type).toBe("line");
    expect(options.children).toBeUndefined();
  });
});
