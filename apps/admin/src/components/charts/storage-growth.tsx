import * as React from "react";
import { ChartCanvas } from "@soymutdb/charts";
import type { ChartDefinition, ChartTooltipContext } from "@soymutdb/charts";
import { useTranslation } from "react-i18next";
import { cn } from "../../lib/cn";
import { formatFileSize } from "../../lib/format";
// Relative for the same reason as the sibling charts: this app's vitest config
// has no "@/" alias.
import { Empty, ProCard } from "../../lib/antd";
import {
  ADMIN_CHART_HEIGHT,
  STORAGE_SERIES_COLORS,
  type ChartTrendRow,
  toTrendRows,
  useAdminChartAnimation,
  useAdminChartTheme,
} from "./chart-adapter";
export interface StorageGrowthDataPoint {
  date: string;
  bytes: number;
}

interface StorageGrowthChartProps {
  data: StorageGrowthDataPoint[];
  className?: string;
}

/**
 * Area chart showing cumulative storage growth over time.
 *
 * Values are formatted as human-readable file sizes (KB/MB/GB/TB) through the
 * console's own formatFileSize, both in the tooltip and -- once the facade
 * carries an axis formatter -- on the y axis.
 */
export function StorageGrowthChart({ data, className }: StorageGrowthChartProps) {
  const { t } = useTranslation();
  const theme = useAdminChartTheme(STORAGE_SERIES_COLORS);
  const animation = useAdminChartAnimation();

  const rows = React.useMemo<ChartTrendRow[]>(
    () => toTrendRows(data, (datum) => datum.bytes),
    [data],
  );

  const definition = React.useMemo<ChartDefinition>(
    () => ({
      kind: "area",
      x: "date",
      y: "value",
      categoryOrder: "appearance",
      palette: STORAGE_SERIES_COLORS,
      legend: false,
      gradient: { from: "rgba(78, 155, 74, 0.3)", to: "rgba(78, 155, 74, 0.02)" },
      // BLOCKED(chart-adapter): the y axis used formatFileSize. The facade
      // resolves axis labels from the serializable valueFormat token, and its
      // "bytes" token prints KiB/MiB/GiB, which is not the console's output.
      // The axis formatter prop has been requested; until it lands the axis
      // stays on the default numeric formatter rather than silently changing
      // the units. Do not set valueFormat here without checking that.
    }),
    [],
  );

  const tooltipFormatter = React.useMemo(
    () =>
      ({ datum }: ChartTooltipContext) =>
        formatFileSize(Number(datum.value)),
    [],
  );

  const hasData = data.length > 0;

  return (
    <ProCard className={cn(className)} title={t("admin.charts.storageGrowth", { defaultValue: "Storage Growth" })}>
        <div className="relative h-64 w-full">
          {hasData ? (
            <ChartCanvas
              definition={definition}
              data={rows}
              label={t("admin.charts.storageGrowthAria", { defaultValue: "Storage growth chart" })}
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
