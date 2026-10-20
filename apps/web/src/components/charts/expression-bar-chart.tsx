/**
 * ExpressionBarChart — grouped bar chart of mean FPKM by tissue and treatment.
 * Lazy-loaded via React.lazy in routes that use it.
 *
 * Drawn by @soymutdb/charts. The grouping rule (first value wins, missing
 * combinations filled with zero), the sorted categories and the "Mean FPKM"
 * axis title are unchanged; only the engine and the row shape behind them
 * moved.
 */
import * as React from "react";
import { useTranslation } from "react-i18next";
import { ChartCanvas } from "@soymutdb/charts";
import { Empty } from "@/lib/antd";
import { cn } from "@/lib/cn";
import {
  PORTAL_CHART_HEIGHT,
  formatExpressionTooltip,
  portalExpressionDefinition,
  toPortalExpressionRows,
  usePortalChartAnimation,
  usePortalChartLoading,
  usePortalChartTheme,
} from "./portal-chart-adapter";

export interface ExpressionBarChartProps {
  data: Array<{ tissue: string; mean_fpkm: number; treatment: string }>;
  className?: string;
}

// Built once, not per render: `ChartCanvas` lists `tooltipFormatter` in the
// dependency array of the effect that updates the live chart, so a factory call
// written inline in the JSX re-ran a full G2 re-render on every parent render.
const tooltipFormatter = formatExpressionTooltip();

export function ExpressionBarChart({ data, className }: ExpressionBarChartProps) {
  const { t } = useTranslation();
  const host = React.useRef<HTMLDivElement | null>(null);
  const theme = usePortalChartTheme();
  const animation = usePortalChartAnimation();

  const rows = React.useMemo(() => toPortalExpressionRows(data), [data]);
  // The old chart rotated the tissue labels only once there were more than six
  // of them, so the rule is a function of the category count, not of the data.
  const tissueCount = React.useMemo(() => new Set(data.map((d) => d.tissue)).size, [data]);
  const definition = React.useMemo(() => portalExpressionDefinition(tissueCount), [tissueCount]);
  const loading = usePortalChartLoading(host, rows.length > 0);

  return (
    <figure className={cn("relative", className)}>
      <div ref={host} className="h-72 w-full">
        {rows.length > 0 ? (
          <ChartCanvas
            definition={definition}
            data={rows}
            label={t("charts.expressionBarTitle")}
            height={PORTAL_CHART_HEIGHT}
            theme={theme}
            animation={animation}
            tooltipFormatter={tooltipFormatter}
          />
        ) : null}
      </div>
      {loading ? <div className="skeleton-pulse absolute inset-0 rounded-lg bg-muted/40" aria-hidden /> : null}
      {data.length === 0 ? <Empty className="absolute inset-0 flex items-center justify-center" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : null}
      <figcaption className="sr-only">
        {t("charts.expressionBarDescription")} {" "}
        {data.map((d) => `${d.tissue} ${d.treatment} ${d.mean_fpkm.toFixed(2)}`).join(", ")}.
      </figcaption>
    </figure>
  );
}
