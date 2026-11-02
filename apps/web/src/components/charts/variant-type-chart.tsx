/**
 * VariantTypeChart — donut chart of variant type distribution.
 * Lazy-loaded via React.lazy in routes that use it.
 */
import { useTranslation } from "react-i18next";
import type { EChartsOption } from "echarts";
import { useECharts } from "../../lib/use-echarts";
import { Empty } from "@/lib/antd";
import { cn } from "@/lib/cn";

export interface VariantTypeChartProps {
  data: ReadonlyArray<{ name: string; value: number }>;
  className?: string;
}

export function VariantTypeChart({ data, className }: VariantTypeChartProps) {  const { t } = useTranslation();

  const total = data.reduce((sum, d) => sum + d.value, 0);
  const option: EChartsOption = {
    tooltip: {
      trigger: "item",
      formatter: (params) => {
        const p = params as { name: string; value: number; percent: number };
        return `${p.name}: ${p.value.toLocaleString()} (${p.percent}%)`;
      },
    },
    legend: {
      orient: "vertical",
      right: 10,
      top: "center",
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { fontSize: 12 },
    },
    series: [
      {
        name: "Variant Types",
        type: "pie",
        radius: ["55%", "78%"],
        center: ["38%", "50%"],
        avoidLabelOverlap: true,
        itemStyle: {
          borderRadius: 4,
          borderColor: "var(--background)",
          borderWidth: 2,
        },
        label: {
          show: true,
          position: "center",
          formatter: () => `{a|${total.toLocaleString()}}\n{b|Total}`,
          rich: {
            a: { fontSize: 22, fontWeight: 600, fontFamily: "Fraunces, serif", color: "var(--foreground)" },
            b: { fontSize: 11, color: "var(--muted-foreground)", padding: [6, 0, 0, 0] },
          },
        },
        emphasis: {
          label: { show: true },
          itemStyle: { shadowBlur: 10, shadowColor: "rgba(0,0,0,0.08)" },
        },
        data: data.map((d, i) => ({
          name: d.name,
          value: d.value,
          itemStyle: {
            color: [
              "var(--chart-1)",
              "var(--chart-2)",
              "var(--chart-3)",
              "var(--chart-4)",
              "var(--chart-5)",
            ][i % 5],
          },
        })),
      },
    ],
  };
  const { ref, loading } = useECharts(option, [data]);

  return (
    <figure className={cn("relative", className)}>
      <div ref={ref} className="h-72 w-full" role="img" aria-label={t("charts.variantTypeTitle")} />
      {loading ? <div className="skeleton-pulse absolute inset-0 rounded-lg bg-muted/40" aria-hidden /> : null}
      {data.length === 0 && !loading ? <Empty className="absolute inset-0 flex items-center justify-center" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : null}
      <figcaption className="sr-only">
        {t("charts.variantTypeDescription", { values: data.map((d) => `${d.name} ${d.value.toLocaleString()}`).join(", ") })}
      </figcaption>
    </figure>
  );
}
