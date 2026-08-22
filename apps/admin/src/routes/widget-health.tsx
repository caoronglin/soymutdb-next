import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ArrowUpRight,
  Clock,
  DatabaseZap,
  RefreshCw,
} from "lucide-react";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Badge,
} from "../lib/admin-ui";
import { widgetApi, type WidgetHealthItem } from "../lib/widget-api";


// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function latencyColor(p95: number): "success" | "warning" | "destructive" {
  if (p95 < 200) return "success";
  if (p95 < 500) return "warning";
  return "destructive";
}

function latencyBadge(p95: number): "success" | "warning" | "destructive" | "outline" {
  return latencyColor(p95);
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms.toFixed(0)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

// ---------------------------------------------------------------------------
// Bar chart: P50 / P95 latency per widget
// ---------------------------------------------------------------------------

// Lazy one-time registration of the chart modules this file renders.
let rl_echartsReady = false;

function LatencyBarChart({ widgets }: { widgets: WidgetHealthItem[] }) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!chartRef.current) return;
    if (!rl_echartsReady) {
      echarts.use([BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);
      rl_echartsReady = true;
    }
    instanceRef.current = echarts.init(chartRef.current);
    const resize = () => instanceRef.current?.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      instanceRef.current?.dispose();
    };
  }, []);

  useEffect(() => {
    if (!instanceRef.current || widgets.length === 0) return;
    const isDark =
      document.documentElement.getAttribute("data-theme") === "dark";
    const names = widgets.map((w) => w.display_name);

    instanceRef.current.setOption({
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        valueFormatter: (v: number) => `${v} ms`,
        backgroundColor: isDark ? "#222822" : "#ffffff",
        borderColor: isDark ? "#3a4a3a" : "#e0e5e0",
        textStyle: { color: isDark ? "#f0f4f0" : "#1a2b1a" },
      },
      legend: {
        data: ["P50", "P95"],
        textStyle: { color: isDark ? "#a8b8a8" : "#5a6b5a" },
        top: 0,
      },
      grid: { left: 40, right: 16, top: 36, bottom: 96 },
      xAxis: {
        type: "category",
        data: names,
        axisLabel: {
          color: isDark ? "#a8b8a8" : "#5a6b5a",
          fontSize: 10,
          rotate: 35,
          interval: 0,
        },
        axisLine: { lineStyle: { color: isDark ? "#3a4a3a" : "#e0e5e0" } },
      },
      yAxis: {
        type: "value",
        name: "ms",
        axisLabel: { color: isDark ? "#a8b8a8" : "#5a6b5a", fontSize: 11 },
        splitLine: { lineStyle: { color: isDark ? "#2a3a2a" : "#f0f4f0" } },
      },
      series: [
        {
          name: "P50",
          type: "bar",
          data: widgets.map((w) => w.p50_ms),
          itemStyle: { color: "#2f7d32", borderRadius: [4, 4, 0, 0] },
          barMaxWidth: 28,
        },
        {
          name: "P95",
          type: "bar",
          data: widgets.map((w) => w.p95_ms),
          itemStyle: { color: "#e6a817", borderRadius: [4, 4, 0, 0] },
          barMaxWidth: 28,
        },
      ],
    });
  }, [widgets]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Clock className="size-4 text-primary" />
          Latency per Widget (P50 / P95)
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div ref={chartRef} className="h-80 w-full" role="img" aria-label="Widget latency bar chart" />
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Line chart: Cache hit rate over time
// ---------------------------------------------------------------------------

function CacheHitRateChart({ widgets }: { widgets: WidgetHealthItem[] }) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);
  const [selectedWidget, setSelectedWidget] = useState<string | null>(null);

  // Default to first widget when data loads
  useEffect(() => {
    if (!selectedWidget && widgets.length > 0) {
      setSelectedWidget(widgets[0]?.name ?? null);
    }
  }, [widgets, selectedWidget]);

  useEffect(() => {
    if (!chartRef.current) return;
    if (!instanceRef.current) {
      instanceRef.current = echarts.init(chartRef.current);
      const resize = () => instanceRef.current?.resize();
      window.addEventListener("resize", resize);
      // cleanup handled on unmount via ref check below
      chartRef.current.dataset.init = "1";
    }
    const inst = instanceRef.current;
    return () => {
      if (inst && !chartRef.current?.isConnected) {
        window.removeEventListener("resize", () => inst.resize());
        inst.dispose();
      }
    };
  }, []);

  // Handle full unmount
  useEffect(() => {
    return () => {
      instanceRef.current?.dispose();
      instanceRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!instanceRef.current) return;
    const w = widgets.find((x) => x.name === selectedWidget);
    const isDark =
      document.documentElement.getAttribute("data-theme") === "dark";
    const xData = w ? w.cache_hit_history.map((p) => p.timestamp) : [];
    const yData = w ? w.cache_hit_history.map((p) => +(p.rate * 100).toFixed(1)) : [];

    instanceRef.current.setOption({
      tooltip: {
        trigger: "axis",
        valueFormatter: (v: number) => `${v}%`,
        backgroundColor: isDark ? "#222822" : "#ffffff",
        borderColor: isDark ? "#3a4a3a" : "#e0e5e0",
        textStyle: { color: isDark ? "#f0f4f0" : "#1a2b1a" },
      },
      grid: { left: 48, right: 16, top: 20, bottom: 32 },
      xAxis: {
        type: "category",
        data: xData,
        axisLabel: { color: isDark ? "#a8b8a8" : "#5a6b5a", fontSize: 10 },
        axisLine: { lineStyle: { color: isDark ? "#3a4a3a" : "#e0e5e0" } },
      },
      yAxis: {
        type: "value",
        name: "Cache Hit %",
        min: 0,
        max: 100,
        axisLabel: {
          color: isDark ? "#a8b8a8" : "#5a6b5a",
          fontSize: 11,
          formatter: "{value}%",
        },
        splitLine: { lineStyle: { color: isDark ? "#2a3a2a" : "#f0f4f0" } },
      },
      series: [
        {
          type: "line",
          smooth: true,
          data: yData,
          areaStyle: { opacity: 0.15 },
          itemStyle: { color: "#2f7d32" },
          lineStyle: { width: 2 },
        },
      ],
    });
  }, [widgets, selectedWidget]);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <DatabaseZap className="size-4 text-primary" />
            Cache Hit Rate Over Time
          </CardTitle>
          <CardDescription>
            Select a widget to view its cache hit rate trend.
          </CardDescription>
        </div>
        <select
          className="rounded-md border border-border bg-background px-3 py-1.5 text-sm"
          value={selectedWidget ?? ""}
          onChange={(e) => setSelectedWidget(e.target.value)}
          aria-label="Select widget for cache hit rate"
        >
          {widgets.map((w) => (
            <option key={w.name} value={w.name}>
              {w.display_name}
            </option>
          ))}
        </select>
      </CardHeader>
      <CardContent>
        <div ref={chartRef} className="h-64 w-full" role="img" aria-label="Cache hit rate over time" />
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function WidgetHealthPage() {
  const { data, isLoading, refetch, isRefetching } = useQuery({
    queryKey: ["admin-widget-health"],
    queryFn: () => widgetApi.health(),
    refetchInterval: 60_000, // auto-refresh every 60s
  });

  const widgets = data?.widgets ?? [];
  const totalErrors = widgets.reduce((sum, w) => sum + w.error_count, 0);
  const avgCacheHit =
    widgets.length > 0
      ? widgets.reduce((sum, w) => sum + w.cache_hit_rate, 0) / widgets.length
      : 0;
  const avgP95 =
    widgets.length > 0
      ? widgets.reduce((sum, w) => sum + w.p95_ms, 0) / widgets.length
      : 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link to="/widgets">
            <Button variant="ghost" size="sm">
              <ArrowLeft className="size-4" />
              Widgets
            </Button>
          </Link>
          <div>
            <h2 className="font-serif text-2xl font-semibold">Widget Health</h2>
            <p className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
              <Activity className="size-3.5" />
              Performance, cache efficiency, and error metrics.
              {data?.generated_at ? (
                <span className="text-xs">
                  · Updated {new Date(data.generated_at).toLocaleTimeString()}
                </span>
              ) : null}
            </p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => refetch()}
          disabled={isRefetching}
        >
          <RefreshCw className={`size-4 ${isRefetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {/* Summary stat cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">Tracked Widgets</p>
            <p className="mt-1 font-serif text-2xl font-semibold">
              {isLoading ? "…" : widgets.length}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">Avg P95 Latency</p>
            <p className="mt-1 font-serif text-2xl font-semibold">
              {isLoading ? "…" : formatMs(avgP95)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">Cache Hit Rate</p>
            <p className="mt-1 font-serif text-2xl font-semibold">
              {isLoading ? "…" : `${(avgCacheHit * 100).toFixed(1)}%`}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="flex items-center gap-1 text-xs text-muted-foreground">
              <AlertTriangle className="size-3" />
              Total Errors (24h)
            </p>
            <p
              className={`mt-1 font-serif text-2xl font-semibold ${
                totalErrors > 0 ? "text-destructive" : ""
              }`}
            >
              {isLoading ? "…" : totalErrors}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Charts */}
      <div className="grid gap-6 lg:grid-cols-2">
        {isLoading ? (
          <>
            <Card>
              <CardContent className="p-6">
                <div className="h-80 animate-pulse rounded bg-muted" />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-6">
                <div className="h-64 animate-pulse rounded bg-muted" />
              </CardContent>
            </Card>
          </>
        ) : (
          <>
            <LatencyBarChart widgets={widgets} />
            <CacheHitRateChart widgets={widgets} />
          </>
        )}
      </div>

      {/* Per-widget table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Per-Widget Breakdown</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="pb-2 pr-4 font-medium">Widget</th>
                <th className="pb-2 pr-4 font-medium">P50</th>
                <th className="pb-2 pr-4 font-medium">P95</th>
                <th className="pb-2 pr-4 font-medium">Cache Hit</th>
                <th className="pb-2 pr-4 font-medium">Requests</th>
                <th className="pb-2 pr-4 font-medium">Errors</th>
                <th className="pb-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {isLoading
                ? Array.from({ length: 5 }).map((_, i) => (
                    <tr key={i} className="border-b border-border/50">
                      {Array.from({ length: 7 }).map((_, j) => (
                        <td key={j} className="py-3 pr-4">
                          <div className="h-4 w-24 animate-pulse rounded bg-muted" />
                        </td>
                      ))}
                    </tr>
                  ))
                : widgets.map((w) => (
                    <tr key={w.name} className="border-b border-border/50">
                      <td className="py-3 pr-4">
                        <p className="font-medium">{w.display_name}</p>
                        <p className="font-mono text-xs text-muted-foreground">
                          {w.name}
                        </p>
                      </td>
                      <td className="py-3 pr-4 font-mono">{formatMs(w.p50_ms)}</td>
                      <td className="py-3 pr-4">
                        <Badge variant={latencyBadge(w.p95_ms)} className="font-mono">
                          {formatMs(w.p95_ms)}
                        </Badge>
                      </td>
                      <td className="py-3 pr-4 font-mono">
                        {(w.cache_hit_rate * 100).toFixed(1)}%
                      </td>
                      <td className="py-3 pr-4 font-mono text-muted-foreground">
                        {w.request_count.toLocaleString()}
                      </td>
                      <td className="py-3 pr-4">
                        {w.error_count > 0 ? (
                          <Badge variant="destructive">{w.error_count}</Badge>
                        ) : (
                          <span className="text-muted-foreground">0</span>
                        )}
                      </td>
                      <td className="py-3 text-right">
                        <Link
                          to="/widgets/$name"
                          params={{ name: w.name }}
                          className="inline-flex items-center text-xs text-primary hover:underline"
                        >
                          Inspect <ArrowUpRight className="ml-0.5 size-3" />
                        </Link>
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
