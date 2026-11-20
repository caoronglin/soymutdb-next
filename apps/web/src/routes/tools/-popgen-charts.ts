/**
 * Chart mappings for the population-genetics tools.
 *
 * Kept next to the pages (and tested in `tools-popgen.test.tsx`) because the
 * numbers need their own home: the LD figure's "no genotype data" state is a
 * *contract* — `r_squared: null` means the store cannot compute LD, not that LD
 * is zero — so it is decided here rather than inline in JSX.
 */
import { categoryBarChart, type ChartDefinition } from "@soymutdb/charts";
import type { DiversityWindow, LdResponse } from "@soymutdb/api-client";

/** One bar in the sliding-window π plot. */
export interface WindowChartRow {
  /** Window midpoint as the category label (the x axis is a band axis). */
  category: string;
  value: number;
  startLabel: string;
  endLabel: string;
  segregating: number;
  piLabel: string;
}

/** Sliding-window rows: only windows with a finite π are plotted. */
export function toWindowChartRows(
  windows: readonly DiversityWindow[],
): WindowChartRow[] {
  return windows
    .filter((window) => Number.isFinite(window.pi))
    .map((window) => ({
      category: String(window.start),
      value: window.pi,
      startLabel: String(window.start),
      endLabel: String(window.end),
      segregating: window.segregating_sites,
      piLabel: window.pi.toPrecision(4),
    }));
}

/**
 * The r² heatmap contract.
 *
 * A `cell` chart puts a category on both axes and paints the value as colour,
 * so both axes are pinned to a band scale and the ordinal order follows the
 * variant order the API returned (genomic order) rather than the data order.
 */
export function buildLdHeatmapChart(legendLabel: string): ChartDefinition {
  return {
    kind: "cell",
    x: "x",
    y: "y",
    valueFormat: "decimal",
    palette: ["#f7fbff", "#6baed6", "#08306b"],
    categoryOrder: "appearance",
    axisLabels: { x: legendLabel },
    xAxis: { scale: "category", labelsRotation: 45 },
    yAxis: { scale: "category" },
    legend: false,
    colorDomain: [0, 1],
  };
}

export function buildDiversityWindowsChart(axisLabel: string): ChartDefinition {
  return {
    ...categoryBarChart<WindowChartRow>([], {
      categoryOrder: "appearance",
      valueLabel: axisLabel,
    }),
    valueFormat: "decimal",
  };
}

/**
 * How the LD panel should present itself.
 *
 * - `"matrix"` — a numeric r² matrix is present and can be drawn
 * - `"no-genotypes"` — `r_squared` is null: the store has allele frequencies
 *   only, so LD is *not computable* here. Nothing is drawn and the reason is
 *   printed; a zero-filled matrix would be a fabricated result.
 * - `"no-variants"` — the region holds no variant, so there is nothing to plot
 */
export type LdChartState = "matrix" | "no-genotypes" | "no-variants";

export function ldChartState(response: Pick<LdResponse, "r_squared" | "n_variants">): LdChartState {
  if (response.r_squared === null || response.r_squared === undefined) {
    return response.n_variants === 0 ? "no-variants" : "no-genotypes";
  }
  if (response.r_squared.length === 0) return "no-variants";
  return "matrix";
}

/**
 * Flatten the symmetric matrix into heatmap cells `(row, column, r²)`.
 *
 * The API mirrors the upper triangle, so the lower triangle is skipped to keep
 * each pair once; the diagonal (r² = 1 with itself) is kept because it is what
 * makes the matrix readable as a matrix.
 */
/**
 * One heatmap cell.
 *
 * The field names are the definition's channels, not the renderer's: a `cell`
 * chart reads `x` as the row category and `y` as the column category, and
 * paints `value` through the continuous colour scale.
 */
export interface LdCell {
  x: string;
  y: string;
  value: number;
  pair: string;
}

export function toLdCells(response: LdResponse): LdCell[] {
  if (!response.r_squared) return [];
  const labels = response.variants.map((variant) => variant.variant_id);
  const cells: LdCell[] = [];
  response.r_squared.forEach((row, rowIndex) => {
    row.forEach((value, columnIndex) => {
      if (columnIndex < rowIndex) return;
      const rowLabel = labels[rowIndex] ?? String(rowIndex);
      const columnLabel = labels[columnIndex] ?? String(columnIndex);
      cells.push({
        x: rowLabel,
        y: columnLabel,
        value,
        pair: `${rowLabel} / ${columnLabel}`,
      });
    });
  });
  return cells;
}
