/**
 * ChromosomeDensityChart — bar chart of variant count per chromosome.
 */
import type { EChartsOption } from "echarts";
import { useECharts } from "../../lib/use-echarts";
import { ChartEmptyState, cn } from "@soymutdb/ui";

export interface ChromosomeDensityChartProps {
  data: ReadonlyArray<{ chromosome: string; variantCount: number }>;
  className?: string;
}

export function ChromosomeDensityChart({ data, className }: ChromosomeDensityChartProps) {
  const option: EChartsOption = {
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params) => {
        const p = (params as Array<{ name: string; value: number }>)[0];
        return `${p.name}: ${p.value.toLocaleString()} variants`;
      },
    },
    grid: { left: 48, right: 16, top: 16, bottom: 32 },
    xAxis: {
      type: "category",
      data: data.map((d) => d.chromosome.replace("chr", "")),
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
        type: "bar",
        data: data.map((d) => d.variantCount),
        itemStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: "var(--chart-1)" },
              { offset: 1, color: "var(--chart-4)" },
            ],
          },
          borderRadius: [3, 3, 0, 0],
        },
        barWidth: "60%",
        emphasis: { itemStyle: { color: "var(--chart-1)" } },
      },
    ],
  };
  const { ref, loading } = useECharts(option, [data]);

  return (
    <figure className={cn("relative", className)}>
      <div ref={ref} className="h-72 w-full" role="img" aria-label="Variant density by chromosome bar chart" />
      {loading ? <div className="skeleton-pulse absolute inset-0 rounded-lg bg-muted/40" aria-hidden /> : null}
      <ChartEmptyState visible={data.length === 0 && !loading} />
      <figcaption className="sr-only">
        Variant density across 20 chromosomes. {data.map((d) => `${d.chromosome}: ${d.variantCount.toLocaleString()}`).join(", ")}.
      </figcaption>
    </figure>
  );
}

export default ChromosomeDensityChart;
