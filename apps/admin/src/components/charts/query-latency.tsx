import * as React from "react";
import { ChartCanvas } from "@soymutdb/charts";
import type { ChartDefinition, ChartTooltipContext } from "@soymutdb/charts";
import { useTranslation } from "react-i18next";
import { cn } from "../../lib/cn";
// Relative for the same reason as the sibling charts: this app's vitest config
// has no "@/" alias.
import { Empty, ProCard } from "../../lib/antd";
import {
  ADMIN_CHART_HEIGHT,
  LATENCY_SERIES_COLORS,
  type ChartSeriesRow,
  toSeriesRows,
  useAdminChartAnimation,
  useAdminChartTheme,
} from "./chart-adapter";
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

/** The legend labels this chart has always drawn, verbatim. */
const PERCENTILE_LABELS = ["P50", "P95", "P99"] as const;

/**
 * Line chart showing query latency percentiles (P50, P95, P99) in
 * milliseconds.
 *
 * The tooltip keeps the axis-triggered shape it had under ECharts: hovering a
 * date lists every percentile for that date, each in milliseconds.
 */
export function QueryLatencyChart({ data, className }: QueryLatencyChartProps) {
  const { t } = useTranslation();
  const latencyLabel = t("admin.charts.latencyMs", { defaultValue: "Latency (ms)" });
  const theme = useAdminChartTheme(LATENCY_SERIES_COLORS);
  const animation = useAdminChartAnimation();

  const rows = React.useMemo<ChartSeriesRow[]>(
    () =>
      toSeriesRows(data, [
        { name: PERCENTILE_LABELS[0], pick: (datum) => datum.p50 },
        { name: PERCENTILE_LABELS[1], pick: (datum) => datum.p95 },
        { name: PERCENTILE_LABELS[2], pick: (datum) => datum.p99 },
      ]),
    [data],
  );

  const definition = React.useMemo<ChartDefinition>(
    () => ({
      kind: "line",
      x: "date",
      y: "value",
      color: "series",
      categoryOrder: "appearance",
      palette: LATENCY_SERIES_COLORS,
      legend: true,
      axisLabels: { y: latencyLabel },
    }),
    [latencyLabel],
  );

  const tooltipFormatter = React.useMemo(() => {
    const byDate = new Map<string, string[]>();
    for (const row of rows) {
      const values = byDate.get(row.date);
      const entry = row.series + " " + row.value + " ms";
      if (values) values.push(entry);
      else byDate.set(row.date, [entry]);
    }
    return ({ datum }: ChartTooltipContext) => {
      const date = String(datum.date);
      const values = byDate.get(date);
      return values && values.length ? date + " — " + values.join(" · ") : date;
    };
  }, [rows]);

  const hasData = data.length > 0;

  return (
    <ProCard className={cn(className)} title={t("admin.charts.queryLatency", { defaultValue: "Query Latency (P50 / P95 / P99)" })}>
        <div className="relative h-64 w-full">
          {hasData ? (
            <ChartCanvas
              definition={definition}
              data={rows}
              label={t("admin.charts.queryLatencyAria", { defaultValue: "Query latency percentiles chart" })}
              height={ADMIN_CHART_HEIGHT}
              theme={theme}
              animation={animation}
              tooltipFormatter={tooltipFormatter}
            />
          ) : null}
          {hasData ? null : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("admin.charts.noData", { defaultValue: "No chart data" })} />}
      </div>
    </ProCard>
  );
}
