import * as React from "react";
import { ChartCanvas } from "@soymutdb/charts";
import type { ChartDefinition } from "@soymutdb/charts";
import { useTranslation } from "react-i18next";
import { cn } from "../../lib/cn";
// Imported relatively, like the other chart helpers in this folder: the
// console's vitest config has no "@/" alias, and these three components are
// the ones with regression tests.
import { Empty, ProCard } from "../../lib/antd";
import {
  ADMIN_CHART_HEIGHT,
  IMPORT_SERIES_COLORS,
  type ChartSeriesRow,
  toSeriesRows,
  useAdminChartAnimation,
  useAdminChartTheme,
} from "./chart-adapter";
export interface ImportThroughputDataPoint {
  date: string;
  imported: number;
  failed: number;
  /**
   * Tasks of that day that are queued or still executing.
   *
   * The API used to drop them from the aggregate entirely, so a day whose
   * imports had not finished yet drew as a day with no activity. Optional
   * because an older deployment returns only the two outcome series.
   */
  running?: number;
}

interface ImportThroughputChartProps {
  data: ImportThroughputDataPoint[];
  className?: string;
}

/**
 * Area chart showing daily import throughput (successful vs. failed).
 *
 * The dashboard endpoint returns one row per day holding both measures, so the
 * rows are reshaped into the facade's long format: one row per day per series,
 * grouped by the color field. The two series keep the colors this chart always
 * used, so the engine swap does not change the palette.
 */
export function ImportThroughputChart({
  data,
  className,
}: ImportThroughputChartProps) {
  const { t } = useTranslation();
  const importedLabel = t("admin.charts.imported", { defaultValue: "Imported" });
  const failedLabel = t("admin.charts.failed", { defaultValue: "Failed" });
  const runningLabel = t("admin.charts.running", { defaultValue: "In progress" });
  const recordsLabel = t("admin.charts.records", { defaultValue: "Records" });
  const theme = useAdminChartTheme(IMPORT_SERIES_COLORS);
  const animation = useAdminChartAnimation();

  const rows = React.useMemo<ChartSeriesRow[]>(
    () =>
      toSeriesRows(data, [
        { name: importedLabel, pick: (datum) => datum.imported },
        { name: failedLabel, pick: (datum) => datum.failed },
        // Rendered only when the endpoint reports the bucket, so the legend
        // does not grow a series that is always zero on an older deployment.
        ...(data.some((datum) => (datum.running ?? 0) > 0)
          ? [{ name: runningLabel, pick: (datum: ImportThroughputDataPoint) => datum.running ?? 0 }]
          : []),
      ]),
    [data, importedLabel, failedLabel, runningLabel],
  );

  const definition = React.useMemo<ChartDefinition>(
    () => ({
      kind: "area",
      x: "date",
      y: "value",
      color: "series",
      categoryOrder: "appearance",
      palette: IMPORT_SERIES_COLORS,
      legend: true,
      valueFormat: "integer",
      axisLabels: { y: recordsLabel },
      // BLOCKED(chart-adapter): the ECharts version filled each series with its
      // own two-stop gradient. The facade declares one gradient per chart, so
      // adding one here would paint the failed series in the imported series'
      // green. Left unset until the definition can carry a gradient per series.
    }),
    [recordsLabel],
  );

  const hasData = data.length > 0;

  return (
    <ProCard className={cn(className)} title={t("admin.charts.importThroughput", { defaultValue: "Import Throughput" })}>
        <div className="relative h-64 w-full">
          {hasData ? (
            <ChartCanvas
              definition={definition}
              data={rows}
              label={t("admin.charts.importThroughputAria", { defaultValue: "Import throughput chart" })}
              height={ADMIN_CHART_HEIGHT}
              theme={theme}
              animation={animation}
            />
          ) : null}
          {hasData ? null : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("admin.charts.noData", { defaultValue: "No chart data" })} />}
      </div>
    </ProCard>
  );
}
