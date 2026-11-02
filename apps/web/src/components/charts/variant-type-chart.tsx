/**
 * VariantTypeChart — donut chart of variant type distribution.
 * Lazy-loaded via React.lazy in routes that use it.
 *
 * Drawn by @soymutdb/charts. The props, the layout, the loading skeleton, the
 * empty state and the sr-only caption are unchanged; only the engine and the
 * row shape behind them moved.
 */
import * as React from "react";
import { useTranslation } from "react-i18next";
import { ChartCanvas } from "@soymutdb/charts";
import { Empty } from "@/lib/antd";
import { cn } from "@/lib/cn";
import {
  PORTAL_CHART_HEIGHT,
  PORTAL_DONUT_RING_CENTER,
  formatVariantTypeTooltip,
  portalVariantTypeDefinition,
  toPortalVariantTypeRows,
  usePortalChartAnimation,
  usePortalChartLoading,
  usePortalChartStatus,
  usePortalChartTheme,
} from "./portal-chart-adapter";

export interface VariantTypeChartProps {
  data: ReadonlyArray<{ name: string; value: number }>;
  className?: string;
}

export function VariantTypeChart({ data, className }: VariantTypeChartProps) {
  const { t } = useTranslation();
  const host = React.useRef<HTMLDivElement | null>(null);
  const theme = usePortalChartTheme();
  const animation = usePortalChartAnimation();

  const rows = React.useMemo(() => toPortalVariantTypeRows(data), [data]);
  const total = React.useMemo(() => data.reduce((sum, d) => sum + d.value, 0), [data]);
  const loading = usePortalChartLoading(host, rows.length > 0);
  const status = usePortalChartStatus(host, rows.length > 0);
  const tooltipFormatter = React.useMemo(() => formatVariantTypeTooltip(total), [total]);

  return (
    <figure className={cn("relative", className)}>
      <div ref={host} className="relative h-72 w-full">
        {rows.length > 0 ? (
          <ChartCanvas
            definition={portalVariantTypeDefinition()}
            data={rows}
            label={t("charts.variantTypeTitle")}
            height={PORTAL_CHART_HEIGHT}
            theme={theme}
            animation={animation}
            tooltipFormatter={tooltipFormatter}
          />
        ) : null}
        {/*
          The total the ECharts series printed in the middle of the ring.
          It is drawn as DOM rather than asked of the engine, which has no
          centre label, and it is aria-hidden because the sr-only caption below
          already carries the same numbers -- an accessible name must not read
          them twice. It is anchored to the ring's centre rather than to the
          box, so it stays on the hole when the legend moves the ring. It
          appears only once the chart is actually drawn, so it never sits over
          the skeleton or the Empty placeholder.
        */}
        {status === "rendered" ? (
          <div
            className="pointer-events-none absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center"
            style={{
              left: PORTAL_DONUT_RING_CENTER.x + "%",
              top: PORTAL_DONUT_RING_CENTER.y + "%",
            }}
            aria-hidden
          >
            <span className="font-display text-[22px] font-semibold leading-none text-foreground">
              {total.toLocaleString()}
            </span>
            <span className="mt-1.5 text-[11px] text-muted-foreground">{t("charts.variantTypeTotal")}</span>
          </div>
        ) : null}
      </div>
      {loading ? <div className="skeleton-pulse absolute inset-0 rounded-lg bg-muted/40" aria-hidden /> : null}
      {data.length === 0 ? <Empty className="absolute inset-0 flex items-center justify-center" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : null}
      <figcaption className="sr-only">
        {t("charts.variantTypeDescription", { values: data.map((d) => `${d.name} ${d.value.toLocaleString()}`).join(", ") })}
      </figcaption>
    </figure>
  );
}
