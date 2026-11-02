/**
 * The tool charts' adapter to @soymutdb/charts.
 *
 * This is where the enrichment significance plot and the expression heatmap
 * meet the shared facade. The charts' *semantics* live next door, in
 * tool-enrichment-mapping and tool-exppattern-mapping, and stay engine-free;
 * this module only translates them into the serializable contract
 * (ChartDefinition), the Canvas rows, the per-datum style and the tooltip
 * formatter the shared runtime actually consumes.
 *
 * Three decisions worth knowing before editing anything here:
 *
 * 1. Category axes. The contract states the three shapes this facade has to
 *    cover: a horizontal bar puts the category on y, a bubble puts a value on
 *    x above an inverted category on y, a heatmap puts categories on both. So
 *    every definition here names its axis scales explicitly -- the runtime's
 *    defaults assume a categorical x.
 *
 * 2. Axis order is appearance order. `categoryDomain` pins the x domain only;
 *    a category y axis takes its domain from the order the rows arrive in. The
 *    enrichment rows are therefore emitted in exactly the order
 *    `enrichmentAxisLabels` returns, and `yAxis.reverse` puts the first entry at
 *    the top, which is what the ECharts chart drew. Do not re-sort the rows.
 *
 * 3. Tooltips are safe text. The engine renders whatever the formatter returns
 *    as markup, so every interpolated value -- term name, gene, condition -- is
 *    escaped. The legacy HTML tooltips stay in the mapping modules for the
 *    ECharts path only; they are not reused here.
 */

import type { ChartDatumStyle, ChartDefinition, ChartTooltipFormatter } from "@soymutdb/charts";

import {
  buildEnrichmentChartData,
  enrichmentAxisLabels,
  enrichmentFormatP,
  enrichmentMaxSize,
  enrichmentTooltipText,
  ENRICHMENT_BUBBLE_MIN_RADIUS,
  ENRICHMENT_BUBBLE_RADIUS_SPAN,
  type EnrichmentChartRow,
  type EnrichmentChartValue,
  type EnrichmentChartView,
} from "./tool-enrichment-mapping";
import {
  buildExpPatternCells,
  expPatternColorRange,
  expPatternShowsCellLabels,
  expPatternTooltipText,
  expPatternValueDomain,
  fmtExpPatternValue,
  EXP_PATTERN_SPLIT_AREA,
  type ExpPatternMatrix,
} from "./tool-exppattern-mapping";

/** One row handed to ChartCanvas. Named fields, never a positional tuple. */
export interface EnrichmentCanvasDatum {
  readonly term: string;
  readonly termLabel: string;
  readonly logQ: number;
  readonly q: number;
  readonly p: number;
  readonly size: number;
  readonly radius: number;
  readonly es: number | null;
  readonly nes: number | null;
  /** Resolved by the mapping, which owns the up/down rule. */
  readonly color: string;
}

/**
 * Canvas rows, emitted in axis order (see the note in the file header).
 *
 * `radius` travels with the row as a cross-check only: the drawn radius is
 * encoded through the shared size scale (`sizeTransform: "sqrt"`), which is
 * the same 8 + 16 * sqrt(size / maxSize) the mapping computes.
 */
export function buildEnrichmentCanvasData(
  rows: readonly EnrichmentChartRow[],
  options: { readonly isGsea: boolean },
): EnrichmentCanvasDatum[] {
  // The mapping already sorted by q and already resolved each row's colour.
  // Reading colour back off the sorted datum (rather than indexing back into
  // the caller's unsorted array) is what keeps a term from inheriting another
  // term's colour when the two orders differ.
  return buildEnrichmentChartData(rows, options)
    .map((datum) => ({
      term: datum.fullName,
      termLabel: datum.label,
      logQ: datum.logQ,
      q: datum.q,
      p: datum.p,
      size: datum.size,
      radius: datum.radius,
      es: datum.es,
      nes: datum.nes,
      color: datum.color,
    }))
    .reverse();
}

/**
 * The significance plot: bubble, or a horizontal bar of the same values.
 *
 * `axisTitle` is passed in rather than hard-coded because the portal
 * translates it. The bar view keeps the same fields, order, colours and
 * tooltip as the bubble; only the mark differs.
 */
export function buildEnrichmentChartDefinition(
  rows: readonly EnrichmentChartRow[],
  options: { readonly isGsea: boolean; readonly view: EnrichmentChartView; readonly axisTitle?: string },
): ChartDefinition {
  const bubble = options.view === "bubble";
  return {
    kind: bubble ? "bubble" : "interval",
    x: "logQ",
    y: "termLabel",
    ...(bubble
      ? {
          size: "size",
          // The runtime reads sizeRange[0] + (sizeRange[1] - sizeRange[0]) * sqrt(value / max),
          // which is the radius formula this chart has always used. NOTE the
          // range is [min, max], not [min, span]: the runtime computes
          // min + (max - min) * ratio, so the largest term's radius is 24.
          sizeRange: [
            ENRICHMENT_BUBBLE_MIN_RADIUS,
            ENRICHMENT_BUBBLE_MIN_RADIUS + ENRICHMENT_BUBBLE_RADIUS_SPAN,
          ],
          sizeDomain: [0, enrichmentMaxSize(rows)],
          sizeTransform: "sqrt" as const,
        }
      : {}),
    xAxis: { scale: "value", ...(options.axisTitle ? { title: options.axisTitle } : {}) },
    yAxis: { scale: "category", reverse: true },
    valueFormat: ".2f",
    tooltip: { show: true, valueFormat: ".2f" },
    legend: false,
  };
}

/** Per-datum fill: the GSEA up/down split, or ORA's single colour. */
export function enrichmentDatumStyle(datum: Record<string, unknown>): ChartDatumStyle {
  return { fill: typeof datum.color === "string" ? datum.color : "var(--chart-2)" };
}

/** Shared-facade tooltip for the significance plot: escaped text, no markup. */
export function enrichmentCanvasTooltipFormatter(isGsea: boolean): ChartTooltipFormatter {
  return (context) => {
    const datum = context.datum as Partial<EnrichmentCanvasDatum>;
    const value: EnrichmentChartValue = [
      typeof datum.logQ === "number" ? datum.logQ : 0,
      typeof datum.termLabel === "string" ? datum.termLabel : "",
      typeof datum.size === "number" ? datum.size : 0,
      typeof datum.term === "string" ? datum.term : "",
      typeof datum.q === "number" ? datum.q : 0,
      typeof datum.p === "number" ? datum.p : 0,
      typeof datum.es === "number" ? datum.es : null,
      typeof datum.nes === "number" ? datum.nes : null,
    ];
    return enrichmentTooltipText(value, isGsea);
  };
}

/** Exact-value table fallback: one row per plotted term. */
export function enrichmentCanvasTableRow(datum: EnrichmentCanvasDatum): string[] {
  return [
    datum.term,
    datum.logQ.toFixed(2),
    enrichmentFormatP(datum.q),
    enrichmentFormatP(datum.p),
    String(datum.size),
  ];
}

/** Column headers for the exact-value table fallback. */
export const ENRICHMENT_CANVAS_TABLE_COLUMNS = ["Term", "-log10(q)", "q", "p", "Genes"] as const;

/** The axis domain the rows are ordered against, for assertions and tests. */
export function enrichmentCanvasAxisDomain(rows: readonly EnrichmentChartRow[]): string[] {
  return enrichmentAxisLabels(rows);
}

// -------------------------------------------------------------------------
// Expression pattern heatmap
// -------------------------------------------------------------------------

/** One heatmap cell handed to ChartCanvas. */
export interface ExpPatternCanvasDatum {
  readonly gene: string;
  readonly condition: string;
  readonly value: number;
}

export function buildExpPatternCanvasData(source: ExpPatternMatrix): ExpPatternCanvasDatum[] {
  return buildExpPatternCells(source).map((cell) => ({
    gene: cell.gene,
    condition: cell.condition,
    value: cell.value,
  }));
}

/**
 * The heatmap: categories on both axes, the value in the colour channel.
 *
 * `color` is named explicitly. A cell kind without a colour field falls back to
 * the y field for the colour channel, which for this chart is the gene -- so
 * leaving it out would paint genes instead of values.
 */
export function buildExpPatternChartDefinition(source: ExpPatternMatrix): ChartDefinition {
  const domain = expPatternValueDomain(source);
  return {
    kind: "cell",
    x: "condition",
    y: "gene",
    color: "value",
    categoryDomain: [...source.conditions],
    colorDomain: [domain.min, domain.max],
    colorRange: expPatternColorRange(source.scale),
    cellLabels: expPatternShowsCellLabels(buildExpPatternCells(source)),
    splitArea: EXP_PATTERN_SPLIT_AREA,
    xAxis: { scale: "category", labelsRotation: source.conditions.length > 6 ? 45 : 0 },
    yAxis: { scale: "category" },
    valueFormat: ".2f",
    tooltip: { show: true, valueFormat: ".2f" },
    legend: false,
  };
}

/**
 * The same heatmap with a narrowed colour domain, for when the consumer's
 * colour scale has been dragged. The domain only re-maps colour; the rows and
 * the exact-value table are untouched, which is what the ECharts visualMap did.
 */
export function buildExpPatternChartDefinitionWithDomain(
  source: ExpPatternMatrix,
  colorDomain: readonly [number, number],
): ChartDefinition {
  return { ...buildExpPatternChartDefinition(source), colorDomain: [colorDomain[0], colorDomain[1]] };
}

/** Shared-facade tooltip for a heatmap cell: escaped gene and condition. */
export const expPatternCanvasTooltipFormatter: ChartTooltipFormatter = (context) => {
  const datum = context.datum as Partial<ExpPatternCanvasDatum>;
  return expPatternTooltipText({
    gene: typeof datum.gene === "string" ? datum.gene : "",
    condition: typeof datum.condition === "string" ? datum.condition : "",
    conditionIndex: 0,
    geneIndex: 0,
    value: typeof datum.value === "number" ? datum.value : Number.NaN,
  });
};

/** Exact-value table fallback: one row per painted cell. */
export function expPatternCanvasTableRow(datum: ExpPatternCanvasDatum): string[] {
  return [datum.gene, datum.condition, fmtExpPatternValue(datum.value)];
}

/** Column headers for the exact-value table fallback. */
export const EXP_PATTERN_CANVAS_TABLE_COLUMNS = ["Gene", "Condition", "Value"] as const;
