/**
 * ReleaseTrend — cumulative variant count over time.
 *
 * Drawn by @soymutdb/charts. Both measures, their series names and their
 * colors are unchanged; the ECharts area fill and dashed second line are not
 * expressible in the facade's serializable definition.
 */
import * as React from "react";
import { useTranslation } from "react-i18next";
import { ChartCanvas } from "@soymutdb/charts";
import { Empty } from "@/lib/antd";
import { cn } from "@/lib/cn";
import {
  PORTAL_CHART_HEIGHT,
  formatTrendTooltip,
  portalCountAxisFormatter,
  portalTrendDefinition,
  toPortalTrendRows,
  usePortalChartAnimation,
  usePortalChartLoading,
  usePortalChartTheme,
} from "./portal-chart-adapter";

// Built once: `ChartCanvas` keys its in-place chart-update effect on this
// function's identity, so calling the factory in JSX re-rendered the whole G2
// chart on every parent render with no data change.
const tooltipFormatter = formatTrendTooltip();

export interface ReleaseTrendProps {
  data: ReadonlyArray<{ date: string; cumulative: number; newVariants: number }>;
  className?: string;
}

export function ReleaseTrend({ data, className }: ReleaseTrendProps) {
  const { t } = useTranslation();
  const host = React.useRef<HTMLDivElement | null>(null);
  const theme = usePortalChartTheme();
  const animation = usePortalChartAnimation();

  const rows = React.useMemo(() => toPortalTrendRows(data), [data]);
  const definition = React.useMemo(
    () => portalTrendDefinition(theme.palette ?? []),
    [theme],
  );
  const loading = usePortalChartLoading(host, rows.length > 0);

  return (
    <figure className={cn("relative", className)}>
      <div ref={host} className="h-72 w-full">
        {rows.length > 0 ? (
          <ChartCanvas
            definition={definition}
            data={rows}
            label={t("charts.releaseTrendTitle")}
            height={PORTAL_CHART_HEIGHT}
            theme={theme}
            animation={animation}
            tooltipFormatter={tooltipFormatter}
            axisFormatter={portalCountAxisFormatter}
          />
        ) : null}
      </div>
      {loading ? <div className="skeleton-pulse absolute inset-0 rounded-lg bg-muted/40" aria-hidden /> : null}
      {data.length === 0 ? <Empty className="absolute inset-0 flex items-center justify-center" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : null}
      <figcaption className="sr-only">
        {t("charts.releaseTrendDescription", { releases: data.length, total: data[data.length - 1]?.cumulative.toLocaleString() ?? t("common.unknown") })}
      </figcaption>
    </figure>
  );
}
