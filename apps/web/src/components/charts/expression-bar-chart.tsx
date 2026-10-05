/**
 * ExpressionBarChart — grouped bar chart of mean FPKM by tissue and treatment.
 * Lazy-loaded via React.lazy in routes that use it.
 */
import { useTranslation } from "react-i18next";
import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import { useECharts } from "../../lib/use-echarts";
import { Empty } from "@/lib/antd";
import { cn } from "@/lib/cn";

export interface ExpressionBarChartProps {
  data: Array<{ tissue: string; mean_fpkm: number; treatment: string }>;
  className?: string;
}

export function ExpressionBarChart({ data, className }: ExpressionBarChartProps) {  const { t } = useTranslation();

  // Group once so series construction does not repeatedly scan all input rows.
  const { treatments, tissues, valuesByTreatment } = useMemo(() => {
    const treatmentSet = new Set<string>();
    const tissueSet = new Set<string>();
    const values = new Map<string, Map<string, number>>();
    for (const datum of data) {
      treatmentSet.add(datum.treatment);
      tissueSet.add(datum.tissue);
      const byTissue = values.get(datum.treatment) ?? new Map<string, number>();
      // Preserve the first value to retain the historic Array.find behavior.
      if (!byTissue.has(datum.tissue)) byTissue.set(datum.tissue, datum.mean_fpkm);
      values.set(datum.treatment, byTissue);
    }
    return {
      treatments: [...treatmentSet].sort(),
      tissues: [...tissueSet].sort(),
      valuesByTreatment: values,
    };
  }, [data]);

  const option: EChartsOption = {
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params) => {
        const items = Array.isArray(params) ? params : [params];
        return items
          .map((p) => {
            const pp = p as { seriesName: string; value: number };
            return `${pp.seriesName}: ${pp.value.toFixed(2)} FPKM`;
          })
          .join("<br/>");
      },
    },
    legend: {
      data: treatments,
      top: 0,
      textStyle: { fontSize: 12, color: "var(--muted-foreground)" },
    },
    grid: { left: 60, right: 16, top: 40, bottom: 48 },
    xAxis: {
      type: "category",
      data: tissues,
      axisLabel: {
        fontSize: 10,
        color: "var(--muted-foreground)",
        rotate: tissues.length > 6 ? 30 : 0,
      },
      axisLine: { lineStyle: { color: "var(--border)" } },
      axisTick: { alignWithLabel: true },
    },
    yAxis: {
      type: "value",
      name: "Mean FPKM",
      nameTextStyle: { fontSize: 10, color: "var(--muted-foreground)" },
      axisLabel: {
        fontSize: 10,
        color: "var(--muted-foreground)",
      },
      splitLine: { lineStyle: { color: "var(--border)", type: "dashed" } },
    },
    series: treatments.map((treatment, i) => ({
      name: treatment,
      type: "bar" as const,
      barWidth: `${Math.max(8, 80 / treatments.length)}%`,
      itemStyle: {
        color: [`var(--chart-1)`, `var(--chart-2)`, `var(--chart-3)`, `var(--chart-4)`, `var(--chart-5)`][i % 5],
        borderRadius: [2, 2, 0, 0],
      },
      data: tissues.map(
        (tissue) => valuesByTreatment.get(treatment)?.get(tissue) ?? 0,
      ),
    })),
  };

  const { ref, loading } = useECharts(option, [data]);

  return (
    <figure className={cn("relative", className)}>
      <div
        ref={ref}
        className="h-72 w-full"
        role="img"
        aria-label={t("charts.expressionBarTitle")}
      />
      {loading ? (
        <div className="skeleton-pulse absolute inset-0 rounded-lg bg-muted/40" aria-hidden />
      ) : null}
      {data.length === 0 && !loading ? <Empty className="absolute inset-0 flex items-center justify-center" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : null}
      <figcaption className="sr-only">
        {t("charts.expressionBarDescription")} {" "}
        {data.map((d) => `${d.tissue} ${d.treatment} ${d.mean_fpkm.toFixed(2)}`).join(", ")}.
      </figcaption>
    </figure>
  );
}

export default ExpressionBarChart;
