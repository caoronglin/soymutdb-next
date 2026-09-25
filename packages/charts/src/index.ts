/**
 * Public surface of `@soymutdb/charts`.
 *
 * Consumers import from here, never from `@tanstack/*` directly: the exact
 * version pin and the chart vocabulary both live behind this package.
 */
import ChartFigure from "./ChartFigure.vue";

export { ChartFigure };
export {
  categoryBarChart,
  CHART_HEIGHT,
  trendAreaChart,
  type CategoryChartOptions,
  type CategoryValue,
  type ChartDefinition,
  type SeriesValue,
  type TrendPoint,
} from "./definitions";
