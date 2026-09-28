/**
 * Public chart definitions used by the shared React chart facade.
 *
 * The portal keeps charts behind this package so chart-runtime choices do not
 * leak into route components. Every definition is an ECharts option and is
 * paired with an exact-value table by `ChartFigure`.
 */
import type { EChartsOption } from "echarts";

export type ChartDefinition = EChartsOption;

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

export interface CategoryChartOptions {
  /** Label for the numeric axis. */
  valueLabel?: string;
  /** Group the bars by this field instead of drawing one series. */
  seriesKey?: "series";
}

/**
 * A bar chart over one categorical field. With `seriesKey: "series"`, each
 * named series is rendered as a separate bar group for every category.
 */
export function categoryBarChart<TDatum extends CategoryValue>(
  data: readonly TDatum[],
  options: CategoryChartOptions = {},
): ChartDefinition {
  const categories = [...new Set(data.map((datum) => datum.category))];
  const grouped = options.seriesKey === "series";
  const seriesNames = grouped
    ? [...new Set(data.map((datum) => (datum as TDatum & Partial<SeriesValue>).series ?? ""))]
    : [""];
  const valuesByGroup = new Map<string, Map<string, number>>();

  for (const datum of data) {
    const seriesName = grouped ? (datum as TDatum & Partial<SeriesValue>).series ?? "" : "";
    const values = valuesByGroup.get(seriesName) ?? new Map<string, number>();
    values.set(datum.category, (values.get(datum.category) ?? 0) + datum.value);
    valuesByGroup.set(seriesName, values);
  }

  return {
    color: ["#2f855a", "#75a987", "#d89b47", "#6f8fa8", "#8f79a6"],
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    ...(grouped ? { legend: { top: 4, type: "scroll" } } : {}),
    grid: { left: 56, right: 24, top: grouped ? 46 : 20, bottom: 56, containLabel: true },
    xAxis: {
      type: "category",
      data: categories,
      axisLabel: { interval: 0, rotate: categories.length > 8 ? 30 : 0 },
    },
    yAxis: { type: "value", name: options.valueLabel ?? "", nameLocation: "middle", nameGap: 42, min: 0 },
    series: seriesNames.map((name) => ({
      name,
      type: "bar" as const,
      data: categories.map((category) => valuesByGroup.get(name)?.get(category) ?? 0),
      ...(grouped ? { barGap: "15%" } : {}),
    })),
  };
}

/** An area chart over ISO date strings. */
export function trendAreaChart(data: readonly TrendPoint[]): ChartDefinition {
  return {
    color: ["#2f855a"],
    tooltip: { trigger: "axis" },
    grid: { left: 64, right: 24, top: 20, bottom: 48, containLabel: true },
    xAxis: { type: "category", boundaryGap: false, data: data.map((datum) => datum.date) },
    yAxis: { type: "value", name: "Variants", nameLocation: "middle", nameGap: 48, min: 0 },
    series: [
      {
        name: "Variants",
        type: "line",
        smooth: false,
        symbol: "circle",
        symbolSize: 5,
        areaStyle: { opacity: 0.22 },
        data: data.map((datum) => datum.value),
      },
    ],
  };
}
