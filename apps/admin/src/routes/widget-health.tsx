import { RiseOutlined, WarningOutlined, ArrowLeftOutlined, ExportOutlined, ClockCircleOutlined, ThunderboltOutlined, ReloadOutlined } from "@ant-design/icons";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { Badge, Button, Card, Typography } from "@/lib/antd";
import { widgetApi, type WidgetHealthItem } from "../lib/widget-api";
import { useTranslation } from "react-i18next";


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

const EMPTY_WIDGETS: WidgetHealthItem[] = [];

// ---------------------------------------------------------------------------
// Bar chart: P50 / P95 latency per widget
// ---------------------------------------------------------------------------

// Lazy one-time registration of the chart modules this file renders.
let rl_echartsReady = false;

function ensureEchartsReady(): void {
  if (rl_echartsReady) return;
  echarts.use([BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);
  rl_echartsReady = true;
}

function LatencyBarChart({ widgets }: { widgets: WidgetHealthItem[] }) {
  const { t } = useTranslation();
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!chartRef.current) return;
    ensureEchartsReady();
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

        <Typography.Title level={5}>
          <ClockCircleOutlined className="size-4 text-primary" />
          {t("admin.ops.latencyPerWidget", { defaultValue: "Latency per Widget (P50 / P95)" })}
        </Typography.Title>


        <div ref={chartRef} className="h-80 w-full" role="img" aria-label={t("admin.ops.latencyChartAria", { defaultValue: "Widget latency bar chart" })} />

    </Card>
  );
}

// ---------------------------------------------------------------------------
// Line chart: Cache hit rate over time
// ---------------------------------------------------------------------------

function CacheHitRateChart({ widgets }: { widgets: WidgetHealthItem[] }) {
  const { t } = useTranslation();
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);
  const [selectedWidget, setSelectedWidget] = useState<string | null>(null);

  const selectedWidgetName =
    selectedWidget && widgets.some((widget) => widget.name === selectedWidget)
      ? selectedWidget
      : widgets[0]?.name ?? null;

  useEffect(() => {
    const element = chartRef.current;
    if (!element) return;
    ensureEchartsReady();
    const instance = echarts.init(element);
    instanceRef.current = instance;
    const resize = () => instance.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      instance.dispose();
      if (instanceRef.current === instance) instanceRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!instanceRef.current) return;
    const w = widgets.find((x) => x.name === selectedWidgetName);
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
        name: t("admin.ops.cacheHitPercent", { defaultValue: "Cache Hit %" }),
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
  }, [widgets, selectedWidgetName, t]);

  return (
    <Card>

        <div>
          <Typography.Title level={5}>
            <ThunderboltOutlined className="size-4 text-primary" />
            {t("admin.ops.cacheHitRateTitle", { defaultValue: "Cache Hit Rate Over Time" })}
          </Typography.Title>
          <Typography.Text type="secondary">
            {t("admin.ops.cacheHitRateSubtitle", { defaultValue: "Select a widget to view its cache hit rate trend." })}
          </Typography.Text>
        </div>
        <select
          className="rounded-md border border-border bg-background px-3 py-1.5 text-sm"
          value={selectedWidgetName ?? ""}
          onChange={(e) => setSelectedWidget(e.target.value)}
          aria-label={t("admin.ops.cacheHitSelectAria", { defaultValue: "Select widget for cache hit rate" })}
        >
          {widgets.map((w) => (
            <option key={w.name} value={w.name}>
              {w.display_name}
            </option>
          ))}
        </select>


        <div ref={chartRef} className="h-64 w-full" role="img" aria-label={t("admin.ops.cacheHitRateAria", { defaultValue: "Cache hit rate over time" })} />

    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function WidgetHealthPage() {
  const { t } = useTranslation();
  const { data, isLoading, refetch, isRefetching } = useQuery({
    queryKey: ["admin-widget-health"],
    queryFn: () => widgetApi.health(),
    refetchInterval: 60_000, // auto-refresh every 60s
  });

  const widgets = data?.widgets ?? EMPTY_WIDGETS;
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
            <Button type="text" size="small">
              <ArrowLeftOutlined className="size-4" />
              {t("admin.ops.widgets", { defaultValue: "Widgets" })}
            </Button>
          </Link>
          <div>
            <h2 className="font-serif text-2xl font-semibold">{t("admin.ops.widgetHealthTitle", { defaultValue: "Widget Health" })}</h2>
            <p className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
              <RiseOutlined className="size-3.5" />
              {t("admin.ops.widgetHealthSubtitle", { defaultValue: "Performance, cache efficiency, and error metrics." })}
              {data?.generated_at ? (
                <span className="text-xs">
                  · {t("admin.ops.updatedAt", { time: new Date(data.generated_at).toLocaleTimeString(), defaultValue: "Updated {{time}}" })}
                </span>
              ) : null}
            </p>
          </div>
        </div>
        <Button

          size="small"
          onClick={() => refetch()}
          disabled={isRefetching}
        >
          <ReloadOutlined className={`size-4 ${isRefetching ? "animate-spin" : ""}`} />
          {t("admin.ops.refresh", { defaultValue: "Refresh" })}
        </Button>
      </div>

      {/* Summary stat cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <div className="p-4">
            <p className="text-xs text-muted-foreground">{t("admin.ops.trackedWidgets", { defaultValue: "Tracked Widgets" })}</p>
            <p className="mt-1 font-serif text-2xl font-semibold">
              {isLoading ? "…" : widgets.length}
            </p>
          </div>
        </Card>
        <Card>
          <div className="p-4">
            <p className="text-xs text-muted-foreground">{t("admin.ops.avgP95Latency", { defaultValue: "Avg P95 Latency" })}</p>
            <p className="mt-1 font-serif text-2xl font-semibold">
              {isLoading ? "…" : formatMs(avgP95)}
            </p>
          </div>
        </Card>
        <Card>
          <div className="p-4">
            <p className="text-xs text-muted-foreground">{t("admin.ops.cacheHitRate", { defaultValue: "Cache Hit Rate" })}</p>
            <p className="mt-1 font-serif text-2xl font-semibold">
              {isLoading ? "…" : `${(avgCacheHit * 100).toFixed(1)}%`}
            </p>
          </div>
        </Card>
        <Card>
          <div className="p-4">
            <p className="flex items-center gap-1 text-xs text-muted-foreground">
              <WarningOutlined className="size-3" />
              {t("admin.ops.totalErrors24h", { defaultValue: "Total Errors (24h)" })}
            </p>
            <p
              className={`mt-1 font-serif text-2xl font-semibold ${
                totalErrors > 0 ? "text-destructive" : ""
              }`}
            >
              {isLoading ? "…" : totalErrors}
            </p>
          </div>
        </Card>
      </div>

      {/* Charts */}
      <div className="grid gap-6 lg:grid-cols-2">
        {isLoading ? (
          <>
            <Card>
              <div className="p-6">
                <div className="h-80 animate-pulse rounded bg-muted" />
              </div>
            </Card>
            <Card>
              <div className="p-6">
                <div className="h-64 animate-pulse rounded bg-muted" />
              </div>
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

          <Typography.Title level={5}>{t("admin.ops.perWidgetBreakdown", { defaultValue: "Per-Widget Breakdown" })}</Typography.Title>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="pb-2 pr-4 font-medium">{t("admin.ops.widgetColumn", { defaultValue: "Widget" })}</th>
                <th className="pb-2 pr-4 font-medium">P50</th>
                <th className="pb-2 pr-4 font-medium">P95</th>
                <th className="pb-2 pr-4 font-medium">{t("admin.ops.cacheHitColumn", { defaultValue: "Cache Hit" })}</th>
                <th className="pb-2 pr-4 font-medium">{t("admin.ops.requests", { defaultValue: "Requests" })}</th>
                <th className="pb-2 pr-4 font-medium">{t("admin.ops.errors", { defaultValue: "Errors" })}</th>
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
                        <Badge color={latencyBadge(w.p95_ms)} className="font-mono">
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
                          <Badge color="red">{w.error_count}</Badge>
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
                          {t("admin.ops.inspect", { defaultValue: "Inspect" })} <ExportOutlined className="ml-0.5 size-3" />
                        </Link>
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
