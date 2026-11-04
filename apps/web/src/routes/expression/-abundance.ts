/**
 * Expression abundance → chart mapping for one library.
 *
 * Two invariants live here so the page cannot get them wrong:
 *
 * 1. A `null` measurement is *not measured*, so it is dropped rather than
 *    plotted as 0 — a zero bar for an absent value claims the gene was silent.
 * 2. The unit is part of the chart's value-axis label. FPKM and TPM are
 *    different normalisations; an axis that says "Value" leaves the reader
 *    guessing which one they are looking at.
 */
import { categoryBarChart, type ChartDefinition } from "@soymutdb/charts";
import type { ExpressionSearchRecord } from "@soymutdb/api-client";

export type AbundanceUnit = "fpkm" | "tpm";

/** One plotted point: the definition's `category`/`value` channels. */
export interface AbundanceDatum {
  category: string;
  value: number;
}

const FORMATTER = new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 });

/**
 * Points for the distribution chart, ordered by descending abundance so the
 * tallest bars are the ones the reader came for.
 */
export function libraryAbundanceRows(
  rows: readonly ExpressionSearchRecord[],
  unit: AbundanceUnit,
  missingGeneLabel = "—",
): AbundanceDatum[] {
  const points: AbundanceDatum[] = [];
  for (const row of rows) {
    const raw = unit === "fpkm" ? row.fpkm : row.tpm;
    if (raw === null || raw === undefined || !Number.isFinite(raw)) continue;
    points.push({ category: row.gene_id || missingGeneLabel, value: raw });
  }
  return points.sort((left, right) => right.value - left.value);
}

/** Format a point's value for the exact-value table. */
export function formatAbundance(value: number): string {
  return FORMATTER.format(value);
}

/**
 * The chart contract. `categoryBarChart` is the facade's own interval helper,
 * so no engine option is constructed here; the unit-bearing axis label is
 * passed through its `valueLabel` option.
 */
export function buildLibraryAbundanceChart(
  unit: AbundanceUnit,
  unitLabel: string,
): ChartDefinition {
  return {
    ...categoryBarChart<AbundanceDatum>([], {
      categoryOrder: "appearance",
      valueLabel: `${unitLabel} (${unit.toUpperCase()})`,
    }),
    valueFormat: "decimal",
  };
}
