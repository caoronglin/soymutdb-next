/**
 * ChromosomeDensityChart — bar chart of variant count per chromosome.
 *
 * Drawn by @soymutdb/charts. The prefix-stripped chromosome labels, the
 * vertical two-stop gradient and the 72-unit height are unchanged; only the
 * engine and the row shape behind them moved.
 */
import * as React from "react";
import { useTranslation } from "react-i18next";
import { ChartCanvas } from "@soymutdb/charts";
import { Empty } from "@/lib/antd";
import { cn } from "@/lib/cn";
import {
  PORTAL_CHART_HEIGHT,
  formatDensityTooltip,
  portalCountAxisFormatter,
  portalDensityDefinition,
  portalDensityGradient,
  toPortalDensityRows,
  usePortalChartAnimation,
  usePortalChartLoading,
  usePortalChartTheme,
} from "./portal-chart-adapter";

// Built once, not per render: `ChartCanvas` lists `tooltipFormatter` in the
// dependency array of the effect that updates the live chart, so a factory call
// written inline in the JSX re-ran a full G2 re-render on every parent render.
const tooltipFormatter = formatDensityTooltip();

export interface ChromosomeDensityChartProps {
  data: ReadonlyArray<{ chromosome: string; variantCount: number }>;
  className?: string;
}

export function ChromosomeDensityChart({ data, className }: ChromosomeDensityChartProps) {
  const { t } = useTranslation();
  const host = React.useRef<HTMLDivElement | null>(null);
  const theme = usePortalChartTheme();
  const animation = usePortalChartAnimation();

  const rows = React.useMemo(() => toPortalDensityRows(data), [data]);
  const definition = React.useMemo(
    () => portalDensityDefinition(portalDensityGradient(theme.palette ?? [])),
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
            label={t("charts.densityTitle")}
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
        {t("charts.densityDescription", { values: data.map((d) => `${d.chromosome}: ${d.variantCount.toLocaleString()}`).join(", ") })}
      </figcaption>
    </figure>
  );
}
