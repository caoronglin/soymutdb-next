import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { cn } from "../../lib/cn";
import { formatFileSize } from "../../lib/format";
import { Card, Empty } from "@/lib/antd";
export interface StorageGrowthDataPoint {
  date: string;
  bytes: number;
}

interface StorageGrowthChartProps {
  data: StorageGrowthDataPoint[];
  className?: string;
}

/**
 * ECharts area chart showing cumulative storage growth over time.
 * Y-axis values are formatted as human-readable file sizes (KB/MB/GB/TB).
 */
export function StorageGrowthChart({ data, className }: StorageGrowthChartProps) {
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
        valueFormatter: (v: number) => formatFileSize(v),
        backgroundColor: isDark ? "#222822" : "#ffffff",
        borderColor: isDark ? "#3a4a3a" : "#e0e5e0",
        textStyle: { color: isDark ? "#f0f4f0" : "#1a2b1a" },
      },
      grid: { left: 64, right: 16, top: 24, bottom: 32 },
      xAxis: {
        type: "category",
        data: data.map((d) => d.date),
        boundaryGap: false,
        axisLine: { lineStyle: { color: isDark ? "#3a4a3a" : "#e0e5e0" } },
        axisLabel: { color: isDark ? "#a8b8a8" : "#5a6b5a", fontSize: 11 },
      },
      yAxis: {
        type: "value",
        axisLabel: {
          color: isDark ? "#a8b8a8" : "#5a6b5a",
          fontSize: 11,
          formatter: (v: number) => formatFileSize(v),
        },
        axisLine: { lineStyle: { color: isDark ? "#3a4a3a" : "#e0e5e0" } },
        splitLine: { lineStyle: { color: isDark ? "#2a3a2a" : "#f0f4f0" } },
      },
      series: [
        {
          name: "Storage",
          type: "line",
          smooth: true,
          showSymbol: false,
          data: data.map((d) => d.bytes),
          itemStyle: { color: "#4e9b4a" },
          lineStyle: { width: 2 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(78, 155, 74, 0.3)" },
              { offset: 1, color: "rgba(78, 155, 74, 0.02)" },
            ]),
          },
        },
      ],
    });
  }, [data]);

  return (
    <Card className={cn(className)} title="Storage Growth">
        <div className="relative">
          <div ref={chartRef} className="h-64 w-full" role="img" aria-label="Storage growth chart" />
          {data.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No chart data" /> : null}
      </div>
    </Card>
  );
}

export default StorageGrowthChart;
