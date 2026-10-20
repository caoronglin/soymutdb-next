/**
 * Public chart contract for @soymutdb/charts.
 *
 * ChartDefinition is engine-neutral and serializable: it carries field names
 * and small option tokens, never an engine option object and never a function.
 * That is deliberate -- a definition must survive JSON.stringify so it can be
 * cached, logged, compared and asserted without the chart engine loaded.
 * Anything needing a function (a custom tooltip renderer) is passed as a prop
 * on ChartFigure / ChartCanvas, never embedded here.
 *
 * This replaces the previous "ChartDefinition = EChartsOption" alias.
 */

/** The visual encodings the facade can build. */
export type ChartKind =
  | "interval"
  | "line"
  | "area"
  | "point"
  | "pie"
  | "donut"
  | "cell"
  | "bubble"
  | "polar"
  | "radial";

/** How the categorical axis is ordered. */
export type ChartCategoryOrder = "appearance" | "asc" | "desc";

/**
 * Named palettes, or explicit resolved colors.
 *
 * A resolved string[] may contain CSS custom properties such as
 * "var(--chart-1)"; the engine resolves them at paint time. Consumers with no
 * theme provider -- the admin console, for instance -- pass resolved colors
 * directly instead of relying on CSS variables being present.
 */
export type ChartPaletteSpec = "categorical" | "sequential" | "impact" | readonly string[];

/** An explicit two-stop gradient, replacing the old engine gradient import. */
export interface ChartGradientSpec {
  readonly from: string;
  readonly to: string;
  /** Defaults to "vertical". */
  readonly direction?: "vertical" | "horizontal";
}

/**
 * An alpha ramp over one series' own palette color. Defaults: from/to take
 * the series color, fromOpacity 0.3, toOpacity 0.02, vertical direction.
 */
export interface ChartSeriesGradient {
  readonly from?: string;
  readonly to?: string;
  readonly fromOpacity?: number;
  readonly toOpacity?: number;
  readonly direction?: "vertical" | "horizontal";
}

/**
 * Per-series area gradients, keyed by the value of the definition's color
 * field.
 *
 * Serializable, and deliberately one ramp per series. This does not merge a
 * multi-series chart into a single gradient.
 */
export type ChartSeriesGradients = Readonly<Record<string, ChartSeriesGradient>>;

/**
 * A named value format. Tokens keep the definition serializable; the facade
 * resolves them to a formatter at render time. A raw format template such as
 * ".2f" is also accepted.
 */
export type ChartValueFormat =
  | "integer"
  | "decimal"
  | "percent"
  | "compact"
  | "bytes"
  | (string & {});

/** Serializable tooltip intent. A custom renderer is a component prop. */
export interface ChartTooltipSpec {
  /** Defaults to true. */
  readonly show?: boolean;
  /** Overrides valueFormat for the tooltip only. */
  readonly valueFormat?: ChartValueFormat;
  /** Label shown in the tooltip body; defaults to the value field name. */
  readonly label?: string;
}

export interface ChartAxisLabels {
  readonly x?: string;
  readonly y?: string;
}

/**
 * Explicit axis configuration.
 *
 * scale is stated rather than inferred because consumers need both shapes: a
 * horizontal bar chart puts the category on y, a bubble plot puts a value on
 * x above an inverted category on y, and a heatmap puts categories on both.
 */
export interface ChartAxisOptions {
  readonly scale?: "category" | "value";
  /** Invert the axis, so the first domain entry is drawn at the far end. */
  readonly reverse?: boolean;
  /** Tick label rotation in degrees. 45 is what the dense grids use. */
  readonly labelsRotation?: number;
  /** Overrides axisLabels for this axis. */
  readonly title?: string;
}

/** Per-series style, keyed by the value of the definition's color field. */
export interface ChartSeriesSpec {
  /** Draw this series as a different mark from its siblings. */
  readonly markType?: "line" | "area" | "bar" | "point";
  /** This series' own alpha ramp. */
  readonly gradient?: ChartSeriesGradient;
  readonly style?: ChartSeriesStyle;
}

export interface ChartSeriesStyle {
  readonly lineDash?: readonly number[];
  readonly lineWidth?: number;
  readonly fill?: string;
  readonly stroke?: string;
  readonly fillOpacity?: number;
}

/** Per-datum style a consumer computes in its own mapping module. */
export interface ChartDatumStyle {
  readonly fill?: string;
  readonly stroke?: string;
  readonly r?: number;
  readonly opacity?: number;
}

export interface ChartPointsStyle {
  readonly size?: number;
  readonly fill?: string;
  readonly stroke?: string;
}

/** Bar corner radius and width, passed straight through to the mark style. */
export interface ChartBarStyle {
  readonly radius?: number;
  readonly width?: number;
}

export type ChartLegendPosition = "top" | "bottom" | "left" | "right";

/**
 * Legend configuration.
 *
 * A bare boolean is still accepted and means exactly what it meant before:
 * true shows the legend, false hides it. The object form adds placement and
 * orientation, which a compact card genuinely needs.
 */
export type ChartLegend =
  | boolean
  | {
      readonly show?: boolean;
      readonly position?: ChartLegendPosition;
      /** "vertical" stacks the entries, which a right-hand legend needs. */
      readonly orientation?: "horizontal" | "vertical";
      /** Explicit entries, for a continuous colour scale. */
      readonly labels?: readonly string[];
    };

/**
 * The single serializable chart contract.
 *
 * x and y are the two primary channels. Their meaning depends on kind:
 * cartesian kinds read them as horizontal/vertical, pie/donut read x as the
 * arc field and y as the value, polar/radial read them as angle/radius.
 * Unused channels are simply absent.
 */
export interface ChartDefinition {
  readonly kind: ChartKind;
  /** Horizontal / angular / arc category field. */
  readonly x: string;
  /** Vertical / radial value field. */
  readonly y: string;
  /** Grouping field, when the chart encodes more than one series. */
  readonly color?: string;
  /** Size channel -- used by bubble. */
  readonly size?: string;
  /** Stack the value channel. Used by interval and polar. */
  readonly stack?: boolean;
  /** Hole ratio, 0-1. Used by donut; ignored by pie. */
  readonly innerRadius?: number;
  readonly categoryOrder?: ChartCategoryOrder;
  /** Pins an explicit ordinal domain, overriding categoryOrder. */
  readonly categoryDomain?: readonly string[];
  readonly palette?: ChartPaletteSpec;
  readonly gradient?: ChartGradientSpec;
  /** Per-series alpha ramps, keyed by the color field's value. */
  readonly seriesGradients?: ChartSeriesGradients;
  /**
   * Draw point symbols on line/area charts. Defaults to false: the charts
   * this facade replaces all hid symbols, so defaulting to true would change
   * every existing chart's appearance.
   */
  readonly showPoints?: boolean;
  readonly valueFormat?: ChartValueFormat;
  readonly tooltip?: ChartTooltipSpec;
  /** Show or place the legend. A bare boolean keeps its original meaning. */
  readonly legend?: ChartLegend;
  /** Bar corner radius and width. */
  readonly barStyle?: ChartBarStyle;
  readonly axisLabels?: ChartAxisLabels;
  /** Per-chart override of the component-level animation policy. */
  readonly animate?: boolean;
  /** Inner padding ratio around the plot area, 0-1. */
  readonly padding?: number;
  /** "horizontal" transposes the plot, so the category reads on y. */
  readonly orientation?: "vertical" | "horizontal";
  readonly xAxis?: ChartAxisOptions;
  readonly yAxis?: ChartAxisOptions;
  /**
   * Size channel domain and pixel range. Defaults to the data extent and
   * [4, 20]; the sqrt transform reproduces the radius semantics the existing
   * bubble chart used, where a linear ratio makes small terms invisible.
   */
  readonly sizeDomain?: readonly [number, number];
  readonly sizeRange?: readonly [number, number];
  readonly sizeTransform?: "linear" | "sqrt";
  /** Continuous colour domain, for the heatmap's clamped value range. */
  readonly colorDomain?: readonly [number, number];
  /** Three-stop diverging ramp, for a z-scored grid centred on zero. */
  readonly colorRange?: readonly [string, string, string];
  /** Draw a value label inside each cell. Consumers decide using their own limit. */
  readonly cellLabels?: boolean;
  /** Alternating background bands behind the plot. */
  readonly splitArea?: boolean;
  /** Per-series mark type, gradient and style, keyed by the color field. */
  readonly seriesStyle?: Readonly<Record<string, ChartSeriesSpec>>;
  /** Style for the companion point mark added by showPoints. */
  readonly pointsStyle?: ChartPointsStyle;
  /** Text drawn in the centre of a donut or pie. */
  readonly centerText?: string;
}

/** A category/value pair -- the shape every summary endpoint returns. */
export interface CategoryValue {
  category: string;
  value: number;
}

/** A dated point for trend charts. */
export interface TrendPoint {
  date: string;
  value: number;
}

/** A category/value pair that also belongs to a named series. */
export interface SeriesValue extends CategoryValue {
  series: string;
}

export const CHART_HEIGHT = 280;

export interface CategoryChartOptions {
  /** Label for the numeric axis. */
  valueLabel?: string;
  /** Group the bars by this field instead of drawing one series. */
  seriesKey?: "series";
  /** Ordinal order of the categories. Defaults to "appearance". */
  categoryOrder?: ChartCategoryOrder;
}

/**
 * A bar chart over one categorical field. With seriesKey "series", each named
 * series is rendered as a separate bar group for every category.
 *
 * The x axis stays a band (categorical) axis, which is the semantics the portal
 * already depends on.
 */
export function categoryBarChart<TDatum extends CategoryValue>(
  _data: readonly TDatum[],
  options: CategoryChartOptions = {},
): ChartDefinition {
  const grouped = options.seriesKey === "series";
  return {
    kind: "interval",
    x: "category",
    y: "value",
    ...(grouped ? { color: "series" } : {}),
    categoryOrder: options.categoryOrder ?? "appearance",
    palette: "categorical",
    valueFormat: "integer",
    legend: grouped,
    ...(options.valueLabel ? { axisLabels: { y: options.valueLabel } } : {}),
  };
}

/**
 * An area chart over ISO date strings.
 *
 * The date field stays on a band axis on purpose. Converting it to a
 * quantitative time scale is a regression that was previously documented in
 * docs/dev/vue-parity/README.md; ISO date strings are treated as ordered
 * categories, which keeps sparse series aligned.
 */
export function trendAreaChart(_data: readonly TrendPoint[]): ChartDefinition {
  return {
    kind: "area",
    x: "date",
    y: "value",
    categoryOrder: "appearance",
    palette: "categorical",
    gradient: { from: "var(--chart-1)", to: "var(--chart-1)", direction: "vertical" },
    valueFormat: "integer",
    legend: false,
    axisLabels: { y: "Variants" },
  };
}
