/**
 * ReleaseTrend — cumulative variant count over time (area chart).
 */
import type { EChartsOption } from "echarts";
import { useECharts } from "../../lib/use-echarts";
import { ChartEmptyState, cn } from "../../lib/web-ui";

export interface ReleaseTrendProps {
  data: ReadonlyArray<{ date: string; cumulative: number; newVariants: number }>;
  className?: string;
}

export function ReleaseTrend({ data, className }: ReleaseTrendProps) {
  const option: EChartsOption = {
    tooltip: {
      trigger: "axis",
      formatter: (params) => {
        const arr = params as unknown as Array<{ axisValue: string; seriesName: string; value: number }>;
        return arr
          .map((p) => `${p.seriesName}: ${Number(p.value).toLocaleString()}`)
          .join("<br/>");
      },
    },
    legend: {
      top: 0,
      right: 0,
      textStyle: { fontSize: 11 },
      itemWidth: 12,
      itemHeight: 8,
    },
    grid: { left: 56, right: 16, top: 36, bottom: 32 },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: data.map((d) => d.date),
      axisLabel: { fontSize: 10, color: "var(--muted-foreground)" },
      axisLine: { lineStyle: { color: "var(--border)" } },
      axisTick: { show: false },
    },
    yAxis: {
      type: "value",
      axisLabel: {
        fontSize: 10,
        color: "var(--muted-foreground)",
        formatter: (v: number) => (v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : String(v)),
      },
      splitLine: { lineStyle: { color: "var(--border)", type: "dashed" } },
    },
    series: [
      {
        name: "Cumulative",
        type: "line",
        smooth: true,
        symbol: "circle",
        symbolSize: 6,
        showSymbol: false,
        data: data.map((d) => d.cumulative),
        lineStyle: { width: 2, color: "var(--chart-1)" },
        itemStyle: { color: "var(--chart-1)" },
        areaStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: "oklch(0.55 0.13 151 / 0.25)" },
              { offset: 1, color: "oklch(0.55 0.13 151 / 0)" },
            ],
          },
        },
      },
      {
        name: "New",
        type: "line",
        smooth: true,
        showSymbol: false,
        data: data.map((d) => d.newVariants),
        lineStyle: { width: 1.5, color: "var(--chart-3)", type: "dashed" },
        itemStyle: { color: "var(--chart-3)" },
      },
    ],
  };
  const { ref, loading } = useECharts(option, [data]);

  return (
    <figure className={cn("relative", className)}>
      <div ref={ref} className="h-72 w-full" role="img" aria-label="Release trend area chart" />
      {loading ? <div className="skeleton-pulse absolute inset-0 rounded-lg bg-muted/40" aria-hidden /> : null}
      <ChartEmptyState visible={data.length === 0 && !loading} />
      <figcaption className="sr-only">
        Variant accumulation over {data.length} releases. Latest cumulative total: {data[data.length - 1]?.cumulative.toLocaleString() ?? "unknown"}.
      </figcaption>
    </figure>
  );
}

export default ReleaseTrend;
