import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { cn } from "../../lib/cn";
import { Card, Empty } from "@/lib/antd";
export interface ImportThroughputDataPoint {
  date: string;
  imported: number;
  failed: number;
}

interface ImportThroughputChartProps {
  data: ImportThroughputDataPoint[];
  className?: string;
}

/**
 * ECharts area chart showing daily import throughput (successful vs. failed).
 * Uses the OKLCH chart palette for consistency with the design system.
 */
export function ImportThroughputChart({
  data,
  className,
}: ImportThroughputChartProps) {
 const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);

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
        backgroundColor: isDark ? "#222822" : "#ffffff",
        borderColor: isDark ? "#3a4a3a" : "#e0e5e0",
        textStyle: { color: isDark ? "#f0f4f0" : "#1a2b1a" },
      },
      legend: {
        data: ["Imported", "Failed"],
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
        name: "Records",
        axisLine: { lineStyle: { color: isDark ? "#3a4a3a" : "#e0e5e0" } },
        axisLabel: { color: isDark ? "#a8b8a8" : "#5a6b5a", fontSize: 11 },
        splitLine: { lineStyle: { color: isDark ? "#2a3a2a" : "#f0f4f0" } },
      },
      series: [
        {
          name: "Imported",
          type: "line",
          smooth: true,
          data: data.map((d) => d.imported),
          itemStyle: { color: "#2f7d32" },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(47, 125, 50, 0.25)" },
              { offset: 1, color: "rgba(47, 125, 50, 0.02)" },
            ]),
          },
        },
        {
          name: "Failed",
          type: "line",
          smooth: true,
          data: data.map((d) => d.failed),
          itemStyle: { color: "#c0392b" },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(192, 57, 43, 0.2)" },
              { offset: 1, color: "rgba(192, 57, 43, 0.02)" },
            ]),
          },
        },
      ],
    });
  }, [data]);

  return (
    <Card className={cn(className)} title="Import Throughput">
        <div className="relative">
          <div ref={chartRef} className="h-64 w-full" role="img" aria-label="Import throughput chart" />
          {data.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No chart data" /> : null}
      </div>
    </Card>
  );
}

export default ImportThroughputChart;
