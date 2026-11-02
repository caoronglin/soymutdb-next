/**
 * Expression-pattern heatmap semantics, lifted out of
 * routes/tools/exppattern.tsx.
 *
 * Same contract as the enrichment mapping next to it: engine-free, prefixed,
 * and exhaustively unit-tested, so the cell coordinates, the colour domain and
 * the tooltip cannot drift while the renderer is swapped underneath.
 */

import { chartTooltipText } from "./tool-chart-text";

export type ExpPatternScale = "zscore" | "none";

/** Above this many cells the chart warns that the grid is dense. */
export const EXP_PATTERN_LARGE_MATRIX_CELLS = 2000;

/** Cell labels stop being drawn past this count; they turn into noise. */
export const EXP_PATTERN_LABEL_CELL_LIMIT = 50;

/** Condition labels rotate once there are more than this many columns. */
export const EXP_PATTERN_ROTATE_LABEL_THRESHOLD = 6;

/** Both axes carry alternating background bands in the current renderer. */
export const EXP_PATTERN_SPLIT_AREA = true;

/** The neutral midpoint of the z-score ramp. */
export const EXP_PATTERN_ZSCORE_MIDDLE = "#F6F8F6";

/**
 * Diverging ramp for z-scored data (centred on 0) and the ordered ramp for
 * raw FPKM. The two are deliberately different: FPKM has no meaningful zero,
 * so a diverging ramp would invent one.
 */
export const EXP_PATTERN_COLOR_RANGES: Readonly<Record<ExpPatternScale, readonly [string, string, string]>> = {
  zscore: ["var(--impact-low)", EXP_PATTERN_ZSCORE_MIDDLE, "var(--chart-1)"],
  none: ["var(--chart-5)", "var(--chart-3)", "var(--chart-1)"],
};

export function expPatternColorRange(scale: ExpPatternScale): readonly [string, string, string] {
  return EXP_PATTERN_COLOR_RANGES[scale] ?? EXP_PATTERN_COLOR_RANGES.none;
}

/** The matrix slice the heatmap reads. */
export interface ExpPatternMatrix {
  readonly genes: readonly string[];
  readonly conditions: readonly string[];
  readonly matrix: readonly (readonly (number | null)[])[];
  /** [min, max] over non-null cells; entries may be null when empty. */
  readonly value_range: readonly [number | null, number | null];
  readonly scale: ExpPatternScale;
}

/** One painted cell. */
export interface ExpPatternCell {
  /** Column index: the ECharts tuple's first coordinate. */
  readonly conditionIndex: number;
  /** Row index: the ECharts tuple's second coordinate. */
  readonly geneIndex: number;
  readonly gene: string;
  readonly condition: string;
  readonly value: number;
}

/**
 * Cells to paint, in `[conditionIndex, geneIndex, value]` order.
 *
 * Missing, undefined and NaN entries are skipped rather than plotted as zero:
 * a missing measurement is not a low measurement. Row-major iteration keeps
 * the emitted order identical to the original double loop.
 */
export function buildExpPatternCells(source: ExpPatternMatrix): ExpPatternCell[] {
  const cells: ExpPatternCell[] = [];
  for (let i = 0; i < source.genes.length; i += 1) {
    for (let j = 0; j < source.conditions.length; j += 1) {
      const value = source.matrix[i]?.[j];
      if (value === null || value === undefined || Number.isNaN(value)) continue;
      cells.push({
        conditionIndex: j,
        geneIndex: i,
        gene: source.genes[i] ?? "",
        condition: source.conditions[j] ?? "",
        value,
      });
    }
  }
  return cells;
}

/** The `[j, i, v]` tuple a cartesian mark consumes for one cell. */
export function expPatternCellTuple(cell: ExpPatternCell): [number, number, number] {
  return [cell.conditionIndex, cell.geneIndex, cell.value];
}

/**
 * The continuous colour domain, taken from the response's `value_range`.
 * A missing bound falls back to 0 / 1 rather than collapsing the scale.
 */
export function expPatternValueDomain(source: ExpPatternMatrix): { min: number; max: number } {
  const [min, max] = source.value_range ?? [null, null];
  return { min: min ?? 0, max: max ?? 1 };
}

/** Cell labels are drawn only while the grid stays small. */
export function expPatternShowsCellLabels(cells: readonly ExpPatternCell[]): boolean {
  return cells.length <= EXP_PATTERN_LABEL_CELL_LIMIT;
}

/** True once there is at least one condition and one non-null measurement. */
export function expPatternHasData(source: ExpPatternMatrix): boolean {
  if (source.conditions.length === 0) return false;
  return source.matrix.some((row) => row.some((value) => value !== null));
}

/** Condition labels tilt once the columns get too dense to read upright. */
export function expPatternLabelRotation(conditionCount: number): 0 | 45 {
  return conditionCount > EXP_PATTERN_ROTATE_LABEL_THRESHOLD ? 45 : 0;
}

/**
 * Tooltip body for one cell, as HTML.
 *
 * ECharts-only: it echoes gene and condition unescaped, exactly as the legacy
 * chart did, and the shared formatter must not reuse it. Use
 * `expPatternTooltipText` for the shared facade.
 */
export function expPatternTooltipHtml(cell: ExpPatternCell): string {
  return `${cell.gene}<br/>${cell.condition}<br/><strong>${cell.value.toFixed(2)}</strong>`;
}

/**
 * Tooltip body for one cell as safe text: no markup of our own, every
 * interpolated value escaped. This is the form the shared formatter takes.
 */
export function expPatternTooltipText(cell: ExpPatternCell): string {
  return chartTooltipText([cell.gene, cell.condition, fmtExpPatternValue(cell.value)]);
}

/** The shared matrix cell format: an em dash for a missing measurement. */
export function fmtExpPatternValue(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(2);
}

/** Column headers for the exact-value table fallback. */
export function expPatternValueTableRow(cell: ExpPatternCell): string[] {
  return [cell.gene, cell.condition, fmtExpPatternValue(cell.value)];
}

/** Accessible description: the grid's shape and its value domain. */
export function expPatternDescription(source: ExpPatternMatrix): string {
  const domain = expPatternValueDomain(source);
  return `${source.genes.length} genes x ${source.conditions.length} conditions, values ${fmtExpPatternValue(
    domain.min,
  )} to ${fmtExpPatternValue(domain.max)}.`;
}
