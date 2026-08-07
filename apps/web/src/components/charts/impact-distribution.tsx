/**
 * ImpactDistribution — horizontal bar chart of variant impact severity.
 * Uses the semantic impact color tokens (high/moderate/low/modifier).
 */
import type { EChartsOption } from "echarts";
import { useECharts } from "../../lib/use-echarts";
import { ChartEmptyState, cn } from "@soymutdb/ui";

export interface ImpactDistributionProps {
  data: ReadonlyArray<{ impact: "HIGH" | "MODERATE" | "LOW" | "MODIFIER"; count: number }>;
  className?: string;
}

const IMPACT_COLORS: Record<string, string> = {
  HIGH: "var(--impact-high)",
  MODERATE: "var(--impact-moderate)",
  LOW: "var(--impact-low)",
  MODIFIER: "var(--impact-modifier)",
};

export function ImpactDistribution({ data, className }: ImpactDistributionProps) {
  const ordered = ["HIGH", "MODERATE", "LOW", "MODIFIER"]
    .map((impact) => data.find((d) => d.impact === impact))
    .filter((d): d is { impact: "HIGH" | "MODERATE" | "LOW" | "MODIFIER"; count: number } => Boolean(d));

  const option: EChartsOption = {
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params) => {
        const p = (params as Array<{ name: string; value: number }>)[0];
        return `${p.name}: ${p.value.toLocaleString()}`;
      },
    },
    grid: { left: 80, right: 24, top: 8, bottom: 24 },
    xAxis: {
      type: "value",
      axisLabel: {
        fontSize: 10,
        color: "var(--muted-foreground)",
        formatter: (v: number) => (v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : String(v)),
      },
      splitLine: { lineStyle: { color: "var(--border)", type: "dashed" } },
    },
    yAxis: {
      type: "category",
      data: ordered.map((d) => d.impact),
      axisLabel: { fontSize: 11, color: "var(--foreground)", fontWeight: 500 },
      axisLine: { lineStyle: { color: "var(--border)" } },
      axisTick: { show: false },
    },
    series: [
      {
        type: "bar",
        data: ordered.map((d) => ({
          value: d.count,
          itemStyle: { color: IMPACT_COLORS[d.impact], borderRadius: [0, 3, 3, 0] },
        })),
        barWidth: "55%",
      },
    ],
  };
  const { ref, loading } = useECharts(option, [data]);

  return (
    <figure className={cn("relative", className)}>
      <div ref={ref} className="h-64 w-full" role="img" aria-label="Variant impact distribution bar chart" />
      {loading ? <div className="skeleton-pulse absolute inset-0 rounded-lg bg-muted/40" aria-hidden /> : null}
      <ChartEmptyState visible={ordered.length === 0 && !loading} />
      <figcaption className="sr-only">
        Impact distribution: {ordered.map((d) => `${d.impact} ${d.count.toLocaleString()}`).join(", ")}.
      </figcaption>
    </figure>
  );
}

export default ImpactDistribution;
