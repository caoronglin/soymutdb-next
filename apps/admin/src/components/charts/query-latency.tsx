import { useEffect, useRef } from "react";
import type * as echarts from "echarts";
import { useTranslation } from "react-i18next";
import { cn } from "../../lib/cn";
import { Empty, ProCard } from "@/lib/antd";
export interface QueryLatencyDataPoint {
  date: string;
  p50: number;
  p95: number;
  p99: number;
}

interface QueryLatencyChartProps {
  data: QueryLatencyDataPoint[];
  className?: string;
}

/**
 * ECharts line chart showing query latency percentiles (P50, P95, P99)
 * in milliseconds. Uses the OKLCH chart palette.
 */
export function QueryLatencyChart({ data, className }: QueryLatencyChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);
  const { t } = useTranslation();

  useEffect(() => {
    if (!chartRef.current) return;
    let disposed = false;
    void import("echarts").then((echarts) => {
      if (disposed || !chartRef.current) return;
      instanceRef.current = echarts.init(chartRef.current);
    });
    const resize = () => instanceRef.current?.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      instanceRef.current?.dispose();
      disposed = true;
    };
  }, []);

  useEffect(() => {
    if (!instanceRef.current) return;
    const isDark =
      document.documentElement.getAttribute("data-theme") === "dark";

    instanceRef.current.setOption({
      tooltip: {
        trigger: "axis",
        valueFormatter: (v: number) => `${v} ms`,
        backgroundColor: isDark ? "#222822" : "#ffffff",
        borderColor: isDark ? "#3a4a3a" : "#e0e5e0",
        textStyle: { color: isDark ? "#f0f4f0" : "#1a2b1a" },
      },
      legend: {
        data: ["P50", "P95", "P99"],
        textStyle: { color: isDark ? "#a8b8a8" : "#5a6b5a" },
        top: 0,
      },
      grid: { left: 48, right: 16, top: 36, bottom: 32 },
      xAxis: {
        type: "category",
        data: data.map((d) => d.date),
        axisLine: { lineStyle: { color: isDark ? "#3a4a3a" : "#e0e5e0" } },
        axisLabel: { color: isDark ? "#a8b8a8" : "#5a6b5a", fontSize: 11 },
      },
      yAxis: {
        type: "value",
        name: t("admin.charts.latencyMs", { defaultValue: "Latency (ms)" }),
        axisLine: { lineStyle: { color: isDark ? "#3a4a3a" : "#e0e5e0" } },
        axisLabel: { color: isDark ? "#a8b8a8" : "#5a6b5a", fontSize: 11 },
        splitLine: { lineStyle: { color: isDark ? "#2a3a2a" : "#f0f4f0" } },
      },
      series: [
        {
          name: t("admin.charts.p50", { defaultValue: "P50" }),
          type: "line",
          smooth: true,
          data: data.map((d) => d.p50),
          itemStyle: { color: "#2f7d32" },
        },
        {
          name: t("admin.charts.p95", { defaultValue: "P95" }),
          type: "line",
          smooth: true,
          data: data.map((d) => d.p95),
          itemStyle: { color: "#e6a817" },
        },
        {
          name: t("admin.charts.p99", { defaultValue: "P99" }),
          type: "line",
          smooth: true,
          data: data.map((d) => d.p99),
          itemStyle: { color: "#c0392b" },
        },
      ],
    });
  }, [data, t]);

  return (
    <ProCard className={cn(className)} title={t("admin.charts.queryLatency", { defaultValue: "Query Latency (P50 / P95 / P99)" })}>
        <div className="relative">
          <div ref={chartRef} className="h-64 w-full" role="img" aria-label={t("admin.charts.queryLatencyAria", { defaultValue: "Query latency percentiles chart" })} />
          {data.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("admin.charts.noData", { defaultValue: "No chart data" })} /> : null}
      </div>
    </ProCard>
  );
}
