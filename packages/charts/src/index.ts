/**
 * Public surface of `@soymutdb/charts`.
 *
 * Consumers import from here, never from the chart runtime directly.
 */
export { ChartFigure, type ChartFigureProps } from "./ChartFigure";
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
