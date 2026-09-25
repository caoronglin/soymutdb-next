/**
 * Chart definitions for the portal.
 *
 * A definition is a TanStack Charts *spec*: the marks to draw plus the scales
 * they bind to. Keeping them here — rather than in the views — is what makes the
 * runtime swappable: a version bump, or a different chart library, changes this
 * module and nothing else.
 *
 * The data is bound into the mark when the definition is built, so a view
 * memoizes one definition per dataset (see `useChartDefinition`). Every chart in
 * the portal also renders its exact-value table; that lives in `ChartFigure`,
 * not here.
 */
import { areaY, barY, defineChart } from "@tanstack/charts";
import { scaleBand } from "@tanstack/charts/scales/band";
import { scaleLinear } from "@tanstack/charts/scales/linear";
import type { ChartDefinition as RuntimeChartDefinition } from "@tanstack/vue-charts";

export type ChartDefinition = RuntimeChartDefinition<never, never, never>;

/** A category/value pair — the shape every summary endpoint returns. */
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

/** Band scale for the categorical axis of every bar chart here. */
const categoryScale = () => scaleBand<string>().padding(0.12);

export interface CategoryChartOptions {
  /** Label for the numeric axis. */
  valueLabel?: string;
  /** Group the bars by this field instead of drawing one series. */
  seriesKey?: "series";
}

/**
 * A bar chart over one categorical field.
 *
 * `seriesKey: "series"` splits each category into a bar per series, which is how
 * the consequence/impact and mutagen charts read.
 */
export function categoryBarChart<TDatum extends CategoryValue>(
  data: readonly TDatum[],
  options: CategoryChartOptions = {},
): ChartDefinition {
  return defineChart({
    marks: [
      barY(data, {
        x: (datum: TDatum) => datum.category,
        y: (datum: TDatum) => datum.value,
        ...(options.seriesKey === "series"
          ? ({ z: (datum: TDatum & Partial<SeriesValue>) => datum.series ?? "" } as never)
          : {}),
      }),
    ],
    scales: {
      x: { scale: categoryScale },
      y: { scale: scaleLinear, nice: true, grid: true, axis: { label: options.valueLabel ?? "" } },
    },
  }) as unknown as ChartDefinition;
}

/** An area chart over a date-like x axis. */
export function trendAreaChart(data: readonly TrendPoint[]): ChartDefinition {
  return defineChart({
    marks: [areaY(data, { x: (datum: TrendPoint) => datum.date, y: (datum: TrendPoint) => datum.value })],
    scales: {
      x: { scale: scaleLinear, nice: true, grid: true, axis: { label: "Date" } },
      y: { scale: scaleLinear, nice: true, grid: true, axis: { label: "Variants" } },
    },
  }) as unknown as ChartDefinition;
}

export { areaY, barY, defineChart, scaleBand, scaleLinear };
