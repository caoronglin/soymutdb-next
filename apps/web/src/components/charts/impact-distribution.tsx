/**
 * ImpactDistribution — bar chart of variant impact severity.
 * Uses the semantic impact color tokens (high/moderate/low/modifier).
 *
 * Drawn by @soymutdb/charts. The fixed severity order, the semantic colors,
 * the 64-unit height and the caption are unchanged; the bars now read on the
 * band axis, because the facade has no transpose/orientation field.
 */
import * as React from "react";
import { useTranslation } from "react-i18next";
import { ChartCanvas } from "@soymutdb/charts";
import { Empty } from "@/lib/antd";
import { cn } from "@/lib/cn";
import {
  PORTAL_CHART_HEIGHT_COMPACT,
  formatImpactTooltip,
  portalCountAxisFormatter,
  portalImpactDefinition,
  toPortalImpactRows,
  usePortalChartAnimation,
  usePortalChartLoading,
  usePortalChartTheme,
} from "./portal-chart-adapter";

/**
 * Built once, not per render. `ChartCanvas` lists `tooltipFormatter` in the
 * dependency array of the effect that updates an existing chart in place, so a
 * factory call written inline in the JSX handed the facade a brand new function
 * on every render and re-ran a whole `buildChartOptions()` + G2 `render()` with
 * no data change.
 */
const tooltipFormatter = formatImpactTooltip();

export interface ImpactDistributionProps {
  data: ReadonlyArray<{ impact: "HIGH" | "MODERATE" | "LOW" | "MODIFIER"; count: number }>;
  className?: string;
}

export function ImpactDistribution({ data, className }: ImpactDistributionProps) {
  const { t } = useTranslation();
  const host = React.useRef<HTMLDivElement | null>(null);
  const theme = usePortalChartTheme();
  const animation = usePortalChartAnimation();

  // Severity order is a property of the chart, not of the payload, so it is
  // resolved before the rows are built and the caption lists the same order.
  const ordered = React.useMemo(() => toPortalImpactRows(data), [data]);
  const loading = usePortalChartLoading(host, ordered.length > 0);

  return (
    <figure className={cn("relative", className)}>
      <div ref={host} className="h-64 w-full">
        {ordered.length > 0 ? (
          <ChartCanvas
            definition={portalImpactDefinition()}
            data={ordered}
            label={t("charts.impactTitle")}
            height={PORTAL_CHART_HEIGHT_COMPACT}
            theme={theme}
            animation={animation}
            tooltipFormatter={tooltipFormatter}
            axisFormatter={portalCountAxisFormatter}
          />
        ) : null}
      </div>
      {loading ? <div className="skeleton-pulse absolute inset-0 rounded-lg bg-muted/40" aria-hidden /> : null}
      {ordered.length === 0 ? <Empty className="absolute inset-0 flex items-center justify-center" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : null}
      <figcaption className="sr-only">
        {t("charts.impactDescription", { values: ordered.map((d) => `${d.category} ${d.value.toLocaleString()}`).join(", ") })}
      </figcaption>
    </figure>
  );
}
