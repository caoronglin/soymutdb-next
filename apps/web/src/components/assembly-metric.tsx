/**
 * Rendering for one assembly statistic.
 *
 * `AssemblyMetric.value` is `null` whenever the platform could not derive the
 * number, and a reason is then attached. Two states must stay distinguishable
 * on screen:
 *
 * - a number: the aggregate ran and produced a count (a genuine `0` included);
 * - "not counted": the aggregate could not answer, with the reason stated.
 *
 * Rendering `null` as `0` would publish a measurement nobody made, and `null` as
 * a bare dash would collide with a genuine zero. This is the same rule the
 * comparative page applies to `coverage`: absence is said in words.
 */
import { useTranslation } from "react-i18next";
import type { AssemblyMetric as AssemblyMetricValue } from "@soymutdb/api-client";
import { Tooltip } from "@/lib/antd";
import { formatNumber } from "../lib/format";

const KNOWN_REASONS = new Set([
  "no_chromosomes",
  "no_genes",
  "no_transcripts",
  "no_protein_sequences",
  "no_linked_downloads",
]);

/** Translation key for a metric's reason, or `null` for an unrecognised code. */
export function metricReasonKey(reason: string | null): string | null {
  if (!reason) return null;
  return KNOWN_REASONS.has(reason) ? `assemblies.metric.reason.${reason}` : null;
}

/** True only when the metric carries a real count. */
export function hasCount(metric: AssemblyMetricValue | undefined | null): boolean {
  return metric?.value !== null && metric?.value !== undefined;
}

/**
 * Genomic magnitudes in base pairs: an exact 6-digit number is unreadable in a
 * table cell, so genome sizes are shown in Mb/Gb. Everything else (gene and
 * transcript counts) is small enough to print exactly.
 */
export function formatBasePairs(value: number): string {
  const units: Array<[number, string]> = [
    [1_000_000_000, "Gb"],
    [1_000_000, "Mb"],
    [1_000, "kb"],
  ];
  for (const [size, unit] of units) {
    if (value >= size) {
      return `${(value / size).toFixed(1)} ${unit}`;
    }
  }
  return `${formatNumber(value)} bp`;
}

export function AssemblyMetricText({
  metric,
  basePairs = false,
  testId,
}: {
  metric: AssemblyMetricValue | undefined | null;
  basePairs?: boolean;
  testId?: string;
}) {
  const { t } = useTranslation();

  if (!metric || metric.value === null || metric.value === undefined) {
    const reasonKey = metricReasonKey(metric?.reason ?? null);
    const reason = reasonKey ? t(reasonKey) : (metric?.reason ?? "");
    return (
      <Tooltip title={reason || undefined}>
        <span
          className="text-xs italic text-muted-foreground"
          data-metric-state="unknown"
          data-metric-reason={metric?.reason ?? "unspecified"}
          data-testid={testId}
        >
          {t("assemblies.metric.unknown")}
        </span>
      </Tooltip>
    );
  }

  const exact = basePairs ? `${formatNumber(metric.value)} bp` : formatNumber(metric.value);
  return (
    <span
      className="font-mono tabular-nums"
      data-metric-state="known"
      data-testid={testId}
      title={basePairs ? exact : undefined}
    >
      {basePairs ? formatBasePairs(metric.value) : exact}
    </span>
  );
}
