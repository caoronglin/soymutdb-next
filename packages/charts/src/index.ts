/**
 * Public surface of @soymutdb/charts.
 *
 * Consumers import from here, never from the chart runtime directly. Nothing
 * below re-exports an engine type, so no route module can reach the engine by
 * accident and no definition can drift into engine syntax.
 */

export { ChartFigure, type ChartFigureProps } from "./ChartFigure";

export {
  ChartCanvas,
  shouldAnimate,
  type ChartAxisFormatter,
  type ChartDatumStyleFn,
  type ChartAnimationInput,
  type ChartAnimationIntensity,
  type ChartCanvasProps,
  type ChartCanvasStatus,
  type ChartTooltipContext,
  type ChartTooltipFormatter,
} from "./ChartCanvas";

export {
  categoryBarChart,
  trendAreaChart,
  CHART_HEIGHT,
  type CategoryChartOptions,
  type CategoryValue,
  type ChartAxisLabels,
  type ChartAxisOptions,
  type ChartCategoryOrder,
  type ChartDatumStyle,
  type ChartDefinition,
  type ChartGradientSpec,
  type ChartSeriesGradient,
  type ChartSeriesGradients,
  type ChartKind,
  type ChartPaletteSpec,
  type ChartPointsStyle,
  type ChartSeriesSpec,
  type ChartSeriesStyle,
  type ChartTooltipSpec,
  type ChartValueFormat,
  type SeriesValue,
  type TrendPoint,
} from "./definitions";

export {
  resolveChartTheme,
  resolvePalette,
  themeIdentity,
  CATEGORICAL_PALETTE_VARS,
  IMPACT_PALETTE_VARS,
  FALLBACK_CATEGORICAL_PALETTE,
  FALLBACK_IMPACT_PALETTE,
  type ChartThemeInput,
  type ChartThemeMode,
  type ResolvedChartTheme,
} from "./theme";

export { createValueFormatter, gradientCss, expandColorRange } from "./format";
export { seriesGradientCss, type SeriesGradientSpec } from "./format";
export { resolveCssColor, paintable, isPaintable, isPaintablePalette, type ResolvedColor } from "./color";
