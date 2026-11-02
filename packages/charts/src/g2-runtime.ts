/**
 * The selective chart engine runtime.
 *
 * This module is imported **lazily** by ChartCanvas, so the engine never
 * lands in the page's initial JavaScript. It deliberately does not pull the
 * engine's full stdlib: only the components the facade's chart kinds actually
 * need are registered, because the complete chart dependency closure is held
 * against a 370 KiB budget.
 *
 * Relationship to a1-runtime.ts: that file is the A1 measurement instrument
 * and is kept frozen, because its measured closure (317,618 B gzip) is
 * accepted evidence. This is the production copy of the same selective
 * library plus exactly three additions that the production chart kinds need
 * and the A1 probe did not use:
 *
 *   coordinate.theta   pie/donut. G2 infers no axes for a theta coordinate
 *                      (esm/runtime/component.js returns null per scale), so
 *                      nothing else is required. Theta is Transpose + Polar,
 *                      and Transpose was already registered.
 *   coordinate.polar   polar. Its axes infer to axisArc and axisLinear, both
 *                      already registered.
 *   transform.stackY   stacked interval/polar. Encode transforms resolve from
 *                      the "transform" namespace, which the selective library
 *                      does not otherwise provide.
 */

import { Cartesian, Transpose, Theta, Polar, Radial } from "@antv/g2/esm/coordinate/index";
import { Constant, Field, Transform, Column } from "@antv/g2/esm/encode/index";
import { Interval, Area, Line, Point, Cell } from "@antv/g2/esm/mark/index";
import { Category10, Category20 } from "@antv/g2/esm/palette/index";
import {
  Linear as ScaleLinear,
  Ordinal as ScaleOrdinal,
  Band as ScaleBand,
  Identity as ScaleIdenity,
  Point as ScalePoint,
  Time as ScaleTime,
  Log as ScaleLog,
  Pow as ScalePow,
  Threshold as ScaleThreshold,
  Quantile as ScaleQuantile,
  Quantize as ScaleQuantize,
  Sqrt as ScaleSqrt,
  Sequential as ScaleSequential,
  Constant as ScaleConstant,
} from "@antv/g2/esm/scale/index";
import { Classic, Light } from "@antv/g2/esm/theme/index";
import {
  AxisLinear,
  AxisArc,
  AxisX,
  AxisY,
  AxisRadar,
  LegendCategory,
  LegendContinuous,
  LegendContinuousBlock,
  LegendContinuousBlockSize,
  LegendContinuousSize,
  TitleComponent,
  SliderX,
  SliderY,
  ScrollbarX,
  ScrollbarY,
  Legends,
} from "@antv/g2/esm/component/index";
import {
  ScaleInX,
  ScaleOutX,
  ScaleInY,
  ScaleOutY,
  WaveIn,
  FadeIn,
  FadeOut,
  Morphing,
} from "@antv/g2/esm/animation/index";
import {
  Tooltip,
  LegendFilter,
  LegendHighlight,
  SliderFilter,
  Poptip,
  Event,
  ScrollbarFilter,
} from "@antv/g2/esm/interaction/index";
import { Mark, View } from "@antv/g2/esm/composition/index";
import { LabelShape } from "@antv/g2/esm/shape/index";
import { Inline } from "@antv/g2/esm/data/index";
import { StackY } from "@antv/g2/esm/transform/index";
import { Runtime } from "@antv/g2/esm/api/runtime";

import type { ChartDatumStyle, ChartDefinition, ChartSeriesSpec } from "./definitions";
import { createValueFormatter, expandColorRange, gradientCss, seriesGradientCss } from "./format";
import { resolvePalette, type ResolvedChartTheme } from "./theme";

export const CHART_LIBRARY = {
  "data.inline": Inline,
  "coordinate.cartesian": Cartesian,
  "coordinate.transpose": Transpose,
  "coordinate.theta": Theta,
  "coordinate.polar": Polar,
  "coordinate.radial": Radial,
  "encode.constant": Constant,
  "encode.field": Field,
  "encode.transform": Transform,
  "encode.column": Column,
  "mark.interval": Interval,
  "mark.area": Area,
  "mark.line": Line,
  "mark.point": Point,
  "mark.cell": Cell,
  "shape.label.label": LabelShape,
  "palette.category10": Category10,
  "palette.category20": Category20,
  "scale.linear": ScaleLinear,
  "scale.ordinal": ScaleOrdinal,
  "scale.band": ScaleBand,
  "scale.identity": ScaleIdenity,
  "scale.point": ScalePoint,
  "scale.time": ScaleTime,
  "scale.log": ScaleLog,
  "scale.pow": ScalePow,
  "scale.sqrt": ScaleSqrt,
  "scale.threshold": ScaleThreshold,
  "scale.quantile": ScaleQuantile,
  "scale.quantize": ScaleQuantize,
  "scale.sequential": ScaleSequential,
  "scale.constant": ScaleConstant,
  // G2 5.4.8 defaults a chart's theme type to "light"
  // (esm/runtime/plot.js inferTheme), and useLibrary("theme", lib) then
  // resolves "theme.light". Registering only "theme.classic" made every chart
  // throw Unknown Component: theme.light in the browser.
  "theme.light": Light,
  "theme.classic": Classic,
  "transform.stackY": StackY,
  "component.axisX": AxisX,
  "component.axisY": AxisY,
  "component.axisRadar": AxisRadar,
  "component.axisLinear": AxisLinear,
  "component.axisArc": AxisArc,
  "component.legendCategory": LegendCategory,
  "component.legendContinuous": LegendContinuous,
  "component.legendContinuousBlock": LegendContinuousBlock,
  "component.legendContinuousBlockSize": LegendContinuousBlockSize,
  "component.legendContinuousSize": LegendContinuousSize,
  "component.legends": Legends,
  "component.title": TitleComponent,
  "component.sliderX": SliderX,
  "component.sliderY": SliderY,
  "component.scrollbarX": ScrollbarX,
  "component.scrollbarY": ScrollbarY,
  "animation.scaleInX": ScaleInX,
  "animation.scaleOutX": ScaleOutX,
  "animation.scaleInY": ScaleInY,
  "animation.scaleOutY": ScaleOutY,
  "animation.waveIn": WaveIn,
  "animation.fadeIn": FadeIn,
  "animation.fadeOut": FadeOut,
  "animation.morphing": Morphing,
  "interaction.tooltip": Tooltip,
  "interaction.legendFilter": LegendFilter,
  "interaction.legendHighlight": LegendHighlight,
  "interaction.sliderFilter": SliderFilter,
  "interaction.scrollbarFilter": ScrollbarFilter,
  "interaction.poptip": Poptip,
  "interaction.event": Event,
  "composition.mark": Mark,
  "composition.view": View,
};

/** A raw datum as the consumer supplies it. */
export type ChartDatum = Record<string, unknown>;

export interface BuildChartOptions {
  readonly definition: ChartDefinition;
  readonly data: readonly ChartDatum[];
  readonly theme: ResolvedChartTheme;
  readonly animate: boolean;
  readonly tooltipFormatter?: (context: { datum: ChartDatum; definition: ChartDefinition }) => string;
  /**
   * Formats value-axis tick labels. A prop, not part of ChartDefinition, so a
   * definition stays serializable and a consumer can reuse an existing
   * formatter such as formatFileSize verbatim.
   */
  readonly axisFormatter?: (value: number) => string;
  /**
   * Per-datum style for charts whose point color or radius is computed by the
   * consumer's own mapping module (the enrichment bubble colors by sign of a
   * score and sizes by a square-root ratio). A prop, so the definition stays
   * serializable.
   */
  readonly datumStyle?: (datum: ChartDatum) => ChartDatumStyle;
}

/** Per-axis scale type, honouring the explicit declaration when present. */
function axisScale(
  declared: "category" | "value" | undefined,
  fallback: "category" | "value",
): "category" | "value" {
  return declared ?? fallback;
}

/** Ordinal domain for the x channel, honouring domain / order / appearance. */
export function resolveCategoryDomain(
  data: readonly ChartDatum[],
  definition: ChartDefinition,
): string[] | null {
  if (definition.categoryDomain && definition.categoryDomain.length) {
    return [...definition.categoryDomain];
  }
  const values: string[] = [];
  const seen = new Set<string>();
  for (const row of data) {
    const value = row[definition.x];
    const key = value === null || value === undefined ? "" : String(value);
    if (!seen.has(key)) {
      seen.add(key);
      values.push(key);
    }
  }
  if (definition.categoryOrder === "asc") return [...values].sort((a, b) => a.localeCompare(b));
  if (definition.categoryOrder === "desc") return [...values].sort((a, b) => b.localeCompare(a));
  return values.length ? values : null;
}

const CARTESIAN_KINDS = new Set(["interval", "line", "area", "point", "bubble", "cell", "stack"]);

/** Distinct values of the color field, in first-appearance order. */
function distinctSeries(data: readonly ChartDatum[], field: string): string[] {
  const seen = new Set<string>();
  const order: string[] = [];
  for (const row of data) {
    const key = String(row[field] ?? "");
    if (!seen.has(key)) {
      seen.add(key);
      order.push(key);
    }
  }
  return order;
}

interface SeriesGroup {
  readonly key: string;
  readonly spec: ChartSeriesSpec | undefined;
  readonly markType: string | undefined;
  readonly color: string;
  readonly rows: ChartDatum[];
}

/**
 * Split rows by the color field, one group per series.
 *
 * Used when siblings genuinely need different marks, such as a cumulative
 * area beside a dashed increment line. This does not merge series: each group
 * keeps its own rows, color and mark.
 */
function groupBySeries(data: readonly ChartDatum[], field: string): SeriesGroup[] {
  const order: string[] = [];
  const buckets = new Map<string, ChartDatum[]>();
  for (const row of data) {
    const key = String(row[field] ?? "");
    if (!buckets.has(key)) {
      buckets.set(key, []);
      order.push(key);
    }
    buckets.get(key)!.push(row);
  }
  return order.map((key) => ({ key, rows: buckets.get(key)!, spec: undefined, markType: undefined, color: "" }));
}

/** Translate the serializable definition into engine options. */
export function buildChartOptions(options: BuildChartOptions): Record<string, unknown> {
  const { definition, data, theme, animate, tooltipFormatter, axisFormatter, datumStyle } = options;
  const kind = definition.kind;
  const palette = resolvePalette(definition.palette, theme);
  const domain = resolveCategoryDomain(data, definition);
  const gradient = gradientCss(definition.gradient);

  const isAngular = kind === "pie" || kind === "donut";
  const isRadialFamily = kind === "polar" || kind === "radial";

  const formatter = createValueFormatter(definition.tooltip?.valueFormat ?? definition.valueFormat);

  // Axis configuration rides on the scale's guide. That is the mechanism G2
  // actually reads: inferComponent pulls the axis partial options out of
  // scale.guide, and runtime/component.js then calls labelFormatter per tick.
  const xGuide: Record<string, unknown> = {};
  const xTitle = definition.xAxis?.title ?? definition.axisLabels?.x;
  if (xTitle) xGuide.title = xTitle;
  if (definition.xAxis?.labelsRotation !== undefined) {
    xGuide.labelRotate = definition.xAxis.labelsRotation;
  }
  if (definition.splitArea) xGuide.splitArea = true;
  // The value axis is whichever axis carries the value. A horizontal chart
  // transposes the plot, so the value axis becomes x; formatting y there would
  // leave the visible axis unformatted.
  const transposed = definition.orientation === "horizontal";
  const valueAxisIsX = transposed;
  const yGuide: Record<string, unknown> = {
    labelFormatter: valueAxisIsX ? undefined : (axisFormatter ?? formatter),
  };
  if (valueAxisIsX) delete yGuide.labelFormatter;
  const yTitle = definition.yAxis?.title ?? definition.axisLabels?.y;
  if (yTitle) yGuide.title = yTitle;
  if (definition.yAxis?.labelsRotation !== undefined) {
    yGuide.labelRotate = definition.yAxis.labelsRotation;
  }
  if (definition.splitArea) yGuide.splitArea = true;
  if (valueAxisIsX) xGuide.labelFormatter = axisFormatter ?? formatter;

  const xIsCategory = axisScale(
    definition.xAxis?.scale,
    isAngular ? "category" : kind === "bubble" || kind === "point" ? "value" : "category",
  );
  const yIsCategory = axisScale(definition.yAxis?.scale, isAngular ? "value" : "value");

  const xScale: Record<string, unknown> =
    xIsCategory === "category"
      ? { type: "band", domain: domain ?? [], paddingInner: 0.2 }
      : { type: "linear" };
  if (definition.xAxis?.reverse) xScale.reverse = true;

  const yScale: Record<string, unknown> = { type: "linear", min: 0 };
  if (isAngular || kind === "radial") delete yScale.min;
  if (yIsCategory === "category") {
    yScale.type = "band";
    delete yScale.min;
    yScale.domain = [...new Set(data.map((datum) => datum[definition.y]).filter((value) => value != null))];
    yScale.paddingInner = 0.2;
  }
  if (definition.yAxis?.reverse) yScale.reverse = true;

  const ramp = expandColorRange(definition.colorRange);
  const colorValues = data.map((datum) => Number(datum[definition.color ?? definition.y]))
    .filter(Number.isFinite);
  const rampExtent = definition.colorDomain ?? [
    colorValues.length ? Math.min(...colorValues) : 0,
    colorValues.length ? Math.max(...colorValues) : 1,
  ];
  const continuousColorScale = ramp
    ? {
        type: "linear",
        range: ramp,
        domain: ramp.map((_, index) => rampExtent[0] +
          (rampExtent[1] - rampExtent[0]) * index / (ramp.length - 1)),
        clamp: true,
      }
    : {
        type: "sequential",
        palette: definition.palette === "impact" ? "oranges" : "ylGnBu",
        ...(definition.colorDomain
          ? { domain: [definition.colorDomain[0], definition.colorDomain[1]], clamp: true }
          : {}),
      };
  const colorScale = definition.color
    ? definition.kind === "cell"
      ? continuousColorScale
      : { type: "ordinal" as const, domain: undefined, palette, legend: definition.legend !== false }
    : undefined;

  // The heatmap draws its value into the cell color channel rather than into a
  // grouping channel, so a cell chart without an explicit color field still
  // needs a continuous color scale.
  const cellColorScale =
    definition.kind === "cell" && !definition.color
      ? continuousColorScale
      : undefined;

  // A heatmap paints its value through the color channel, so the cell kind
  // needs the value field there even when no grouping field is named.
  const colorField =
    definition.color ?? (definition.kind === "cell" ? definition.y : undefined);

  const encode: Record<string, unknown> = isAngular
    ? { y: { type: "field", value: definition.y }, color: { type: "field", value: definition.x } }
    : {
        x: { type: "field", value: definition.x },
        y: { type: "field", value: definition.y },
        ...(colorField ? { color: { type: "field", value: colorField } } : {}),
        ...(definition.size ? { size: { type: "field", value: definition.size } } : {}),
      };

  const markType =
    kind === "cell"
      ? "cell"
      : kind === "point" || kind === "bubble"
        ? "point"
        : kind === "line"
          ? "line"
          : kind === "area"
            ? "area"
            : "interval";

  // A legend spec: a bare boolean means exactly what it always meant.
  const legendSpec = definition.legend;
  const legendEnabled =
    legendSpec === undefined ? definition.color !== undefined : legendSpec !== false;
  const legendOptions =
    legendSpec !== undefined && typeof legendSpec === "object" ? legendSpec : undefined;
  const legendPosition = legendOptions?.position ?? "top";
  // A continuous colour scale draws a legendContinuous; a discrete one draws a
  // legendCategory. Passing explicit labels is how a consumer controls the
  // entries of a continuous legend rather than losing them silently.
  const continuousLegend =
    kind === "cell" || (colorScale && colorScale.type === "sequential");
  const legend: Record<string, unknown> = {
    legend: legendEnabled ? {
      color: {
        position: legendPosition,
        ...(legendOptions?.orientation ? { orientation: legendOptions.orientation } : {}),
        ...(legendOptions?.labels ? {
          tickCount: legendOptions.labels.length,
          labelFormatter: continuousLegend
            ? (_value: unknown, index: number) => legendOptions.labels?.[index] ?? ""
            : (_value: unknown, index: number) => legendOptions.labels?.[index] ?? String(_value),
        } : {}),
      },
    } : false,
  };

  const style: Record<string, unknown> = {};
  const label: Record<string, unknown> = {};
  if (gradient) style.fill = gradient;
  if (kind === "line") style.lineWidth = 2;
  if (definition.kind === "point" || definition.kind === "bubble") style.fillOpacity = 0.85;

  // Per-series alpha ramps. Each series keeps its own fill: this never merges
  // a multi-series chart into a single gradient. The callback reads the
  // series value out of the datum so the ramp is picked per series.
  const seriesGradients = definition.seriesGradients;
  if (seriesGradients && definition.color) {
    const colorField = definition.color;
    const seriesKeys = distinctSeries(data, colorField);
    style.fill = (datum: ChartDatum) => {
      const key = String(datum[colorField] ?? "");
      const spec = seriesGradients[key];
      const position = seriesKeys.indexOf(key);
      const base = palette[position < 0 ? 0 : position % palette.length];
      return seriesGradientCss(spec, base) ?? base;
    };
  }

  // Per-series mark type and style, so two sibling series can be different
  // marks (a cumulative area beside a dashed increment line) without merging
  // them or splitting the chart.
  const seriesStyle = definition.seriesStyle;
  if (seriesStyle && definition.color) {
    const colorField = definition.color;
    const keys = distinctSeries(data, colorField);
    const specFor = (datum: ChartDatum) => {
      const key = String(datum[colorField] ?? "");
      const position = keys.indexOf(key);
      const base = palette[position < 0 ? 0 : position % palette.length];
      const spec = seriesStyle[key];
      const ramp = seriesGradientCss(spec?.gradient ?? seriesGradients?.[key], base);
      return { spec, base, ramp };
    };
    if (style.fill === undefined || typeof style.fill === "function") {
      const previous = typeof style.fill === "function" ? style.fill : null;
      style.fill = (datum: ChartDatum) => {
        const { spec, base, ramp } = specFor(datum);
        return spec?.style?.fill ?? ramp ?? (previous ? previous(datum) : base);
      };
    }
    const mergedLine: Record<string, unknown> = {};
    style.lineDash = (datum: ChartDatum) => {
      const dash = specFor(datum).spec?.style?.lineDash;
      return dash ?? [];
    };
    style.lineWidth = (datum: ChartDatum) =>
      specFor(datum).spec?.style?.lineWidth ?? (kind === "line" ? 2 : mergedLine.width);
  }

  // Bubble radius. The sqrt transform reproduces 8 + 16 * sqrt(size / max):
  // a linear ratio makes small terms invisible and overshoots the largest one.
  const sizeRange = definition.sizeRange ?? [8, 24];
  const sizeTransform = definition.sizeTransform ?? (kind === "bubble" ? "sqrt" : "linear");
  const sizeField = definition.size;
  const sizeDomain = definition.sizeDomain;
  if (sizeField) {
    const values = data
      .map((row) => Number(row[sizeField]))
      .filter((value) => Number.isFinite(value));
    const maxValue = sizeDomain
      ? sizeDomain[1]
      : values.length
        ? Math.max(...values)
        : 1;
    style.r = (datum: ChartDatum) => {
      const value = Number(datum[sizeField]);
      if (!Number.isFinite(value)) return sizeRange[0];
      const min = sizeDomain ? sizeDomain[0] : 0;
      const ratio =
        sizeTransform === "sqrt"
          ? Math.sqrt(Math.max(0, value) / Math.max(1e-9, maxValue))
          : (value - min) / Math.max(1e-9, maxValue - min);
      // sizeRange is [min, max]; the span is what scales the ratio. With the
      // default [8, 24] this is exactly 8 + 16 * ratio.
      return sizeRange[0] + (sizeRange[1] - sizeRange[0]) * Math.min(1, Math.max(0, ratio));
    };
    // G2 constructs point geometry from the size channel before applying
    // shape styles. Supplying only style.r leaves the default size scale in
    // control, making the smallest bubble nearly invisible.
    encode.size = { type: "transform", value: style.r };
  }

  // Per-datum style from the consumer's own mapping module wins over
  // everything computed above, because it is the most specific.
  if (datumStyle) {
    const previous = typeof style.fill === "function" ? style.fill : null;
    style.fill = (datum: ChartDatum) => {
      const computed = datumStyle(datum);
      return (computed.fill as string) ?? (previous ? previous(datum) : "");
    };
    if (sizeField === undefined) {
      style.r = (datum: ChartDatum) => {
        const computed = datumStyle(datum);
        return (computed.r as number) ?? 4;
      };
    }
  }

  // Cell value labels. The decision of whether to draw them belongs to the
  // consumer (its own cell-count limit); this only maps the choice.
  if (definition.cellLabels && kind === "cell") {
    label.field = definition.y;
    label.text = (datum: ChartDatum) => String(datum[definition.y] ?? "");
  }

  // Bar corner radius and width pass straight through. Kept as plain style
  // keys rather than a bar-specific abstraction.
  if (definition.barStyle) {
    if (definition.barStyle.radius !== undefined) style.radius = definition.barStyle.radius;
    if (definition.barStyle.width !== undefined) style.width = definition.barStyle.width;
  }

  const coordinate = isAngular
    ? { type: "theta", innerRadius: kind === "donut" ? definition.innerRadius ?? 0.6 : 0 }
    : definition.orientation === "horizontal"
      ? { transform: [{ type: "transpose" }] }
    : isRadialFamily
      ? { type: kind }
      : undefined;

  const tooltip = definition.tooltip?.show === false
    ? false
    : {
        title: definition.x,
        items: tooltipFormatter
          ? [(datum: ChartDatum) => ({
              name: definition.tooltip?.label ?? definition.y,
              value: tooltipFormatter({ datum, definition }),
            })]
          : [{
              field: definition.y,
              name: definition.tooltip?.label ?? definition.y,
              valueFormatter: formatter,
            }],
      };

  const mark: Record<string, unknown> = {
    type: markType,
    data: [...data],
    encode,
    ...(definition.stack ? { transform: [{ type: "stackY" }] } : {}),
    ...(coordinate ? { coordinate } : {}),
    scale: {
      x: { ...xScale, guide: xGuide },
      y: { ...yScale, guide: yGuide },
      ...(definition.size
        ? {
            size: {
              type: "identity",
            },
          }
        : {}),
      ...(colorScale ? { color: colorScale } : {}),
      ...(cellColorScale ? { color: cellColorScale } : {}),
    },
    ...(definition.padding !== undefined ? { padding: definition.padding } : {}),
    ...(Object.keys(label).length ? { label } : {}),
    style,
    animate: animate,
    tooltip,
    interaction: { tooltip: tooltip !== false },
    ...(definition.legend === false ? { legend: false } : {}),
    ...legend,
    // The engine holds the theme as plot state, so the resolved theme travels
    // with the options rather than through the constructor, which only takes
    // a theme name.
    theme: { type: "light", ...themeOverrides(theme) },
  };

  // G2's line and area marks draw only the path; they never emit point
  // symbols. showPoints therefore defaults to false, and only adds a
  // companion point mark when explicitly requested.
  if (definition.seriesStyle && definition.color) {
    const grouped = groupBySeries(data, definition.color);
    const groups: SeriesGroup[] = grouped.map((group, index) => {
      const spec = definition.seriesStyle?.[group.key];
      return {
        key: group.key,
        rows: group.rows,
        spec,
        markType: spec?.markType,
        color: palette[index % palette.length],
      };
    });
    const wantsSplit = groups.some((group) => group.markType && group.markType !== markType);
    if (wantsSplit) {
      const children = groups.map((group) => {
        const groupStyleRecord: Record<string, unknown> = { ...style };
        const groupFill = group.spec?.gradient
          ? seriesGradientCss(group.spec.gradient, group.color)
          : undefined;
        if (groupFill) groupStyleRecord.fill = groupFill;
        const overrides = group.spec?.style;
        if (overrides) Object.assign(groupStyleRecord, overrides);
        const groupMark: Record<string, unknown> = {
          type: group.markType ?? markType,
          data: group.rows,
          encode,
          ...(coordinate ? { coordinate } : {}),
          scale: mark.scale,
          style: groupStyleRecord,
          animate: animate,
          tooltip,
          interaction: { tooltip: tooltip !== false },
          theme: mark.theme,
        };
        return groupMark;
      });
      return { type: "view", children };
    }
  }

  if (definition.showPoints && (kind === "line" || kind === "area")) {
    const points = {
      type: "point",
      data: [...data],
      encode,
      style: { fillOpacity: 0.85, ...(definition.pointsStyle ?? {}) },
    };
    return { type: "view", children: [mark, points] };
  }

  return mark;
}

export type ChartInstance = {
  options(options: Record<string, unknown>): void;
  render(): Promise<unknown>;
  resize(width?: number, height?: number): Promise<unknown>;
  destroy(): void;
};

/** Create a runtime bound to the facade's selective library. */
export function createChart(
  container: HTMLElement,
  width: number,
  height: number,
  chartOptions: Record<string, unknown>,
): ChartInstance {
  const chart = new Runtime({
    container,
    width,
    height,
    autoFit: false,
    lib: CHART_LIBRARY,
    theme: "light",
  });
  chart.options(chartOptions);
  return {
    options: (options) => { chart.options(options); },
    render: () => chart.render(),
    resize: (nextWidth = width, nextHeight = height) => chart.changeSize(nextWidth, nextHeight),
    destroy: () => chart.destroy(),
  };
}

/** Merge the resolved theme onto the engine's theme object. */
export function themeOverrides(theme: ResolvedChartTheme): Record<string, unknown> {
  return {
    axis: { stroke: theme.axisColor, labelFill: theme.labelColor, gridStroke: theme.gridColor },
    legend: { labelFill: theme.labelColor },
    view: { plotFill: "transparent", contentFill: "transparent" },
  };
}

export { CARTESIAN_KINDS };
