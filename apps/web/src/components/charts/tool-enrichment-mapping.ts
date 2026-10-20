/**
 * Enrichment chart semantics, lifted out of routes/tools/enrichment.tsx.
 *
 * Every number the significance plot shows is computed here, once, so the
 * route's option builder and any future shared-facade chart read the same
 * values. The functions are deliberately engine-free: no ECharts option, no
 * G2 options, no React. That is what makes them unit-testable and what keeps a
 * migration from silently changing what the chart means.
 *
 * Names are prefixed (`enrichment*`) on purpose. The portal chart modules own
 * their own helpers, and a bare `logQ` / `escapeHtml` / `fmtP` would collide
 * the moment both sides are bundled together.
 */

import { chartTooltipText } from "./tool-chart-text";

/** The row shape the significance plot consumes. */
export interface EnrichmentChartRow {
  readonly id: string;
  readonly name: string;
  readonly p: number;
  readonly q: number;
  readonly size: number;
  readonly es?: number;
}

export type EnrichmentChartView = "bubble" | "bar";

/** -log10(q) is drawn against this ceiling; q = 0 (underflow) lands on it. */
export const ENRICHMENT_LOG_Q_CEILING = 10;

/** Term names longer than this are truncated on the category axis. */
export const ENRICHMENT_TERM_LABEL_LIMIT = 40;

/** Bubble radius bounds, in the same arbitrary pixel unit ECharts used. */
export const ENRICHMENT_BUBBLE_MIN_RADIUS = 8;
export const ENRICHMENT_BUBBLE_RADIUS_SPAN = 16;

export const ENRICHMENT_UP_COLOR = "var(--chart-1)";
export const ENRICHMENT_DOWN_COLOR = "var(--impact-low)";
export const ENRICHMENT_ORA_COLOR = "var(--chart-2)";

/** p-value formatting shared by the tooltip and the results table. */
export function enrichmentFormatP(value: number): string {
  if (value === 0) return "0";
  if (value < 0.001) return value.toExponential(2);
  return value.toFixed(4);
}

/** Signed enrichment-score formatting; undefined renders as an en dash. */
export function enrichmentFormatSigned(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return "–";
  return `${value >= 0 ? "+" : ""}${value.toFixed(3)}`;
}

/**
 * Escape term names for the legacy HTML tooltip body.
 *
 * Escapes exactly the four characters the original formatter escaped, so the
 * rendered tooltip is byte-identical. `escapeChartText` in ./tool-chart-text is
 * the stricter one and is what the shared formatter path uses.
 */
export function enrichmentEscapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** -log10(q), clamped: q = 0 (underflow) renders at the ceiling. */
export function enrichmentLogQ(q: number): number {
  return q <= 0 ? ENRICHMENT_LOG_Q_CEILING : Math.min(ENRICHMENT_LOG_Q_CEILING, -Math.log10(q));
}

/**
 * Truncated label shared by the category axis and the series data.
 *
 * Both sides must produce byte-identical strings: the plotted points are
 * matched back to the axis by this exact string, so a second implementation
 * would silently drop points.
 */
export function enrichmentTermLabel(name: string, id: string): string {
  const label = name || id;
  return label.length > ENRICHMENT_TERM_LABEL_LIMIT
    ? `${label.slice(0, ENRICHMENT_TERM_LABEL_LIMIT)}…`
    : label;
}

/** Most significant (smallest q) first. Never mutates the caller's array. */
export function sortEnrichmentRowsByQ(rows: readonly EnrichmentChartRow[]): EnrichmentChartRow[] {
  return [...rows].sort((a, b) => a.q - b.q);
}

/**
 * The category axis domain, in the exact order the axis consumes it.
 *
 * This is `sorted.map(termLabel).reverse()` and the reversal is load-bearing:
 * the axis is inverted, so the first entry is drawn at the top. A caller that
 * re-sorts here breaks the plot.
 */
export function enrichmentAxisLabels(rows: readonly EnrichmentChartRow[]): string[] {
  return sortEnrichmentRowsByQ(rows)
    .map((row) => enrichmentTermLabel(row.name, row.id))
    .reverse();
}

/** Largest term size, floored at 1 so the bubble radius ratio stays finite. */
export function enrichmentMaxSize(rows: readonly EnrichmentChartRow[]): number {
  return Math.max(1, ...rows.map((row) => row.size));
}

/**
 * Bubble radius: 8 + 16 * sqrt(size / maxSize).
 *
 * The square root is the semantics, not decoration -- a linear size channel
 * makes small terms invisible and blows the largest one past the plot area.
 * Do not replace this with a plain linear ratio.
 */
export function enrichmentBubbleRadius(size: number, maxSize: number): number {
  return ENRICHMENT_BUBBLE_MIN_RADIUS + ENRICHMENT_BUBBLE_RADIUS_SPAN * Math.sqrt(size / maxSize);
}

/**
 * Point colour. GSEA splits on the sign of ES; ORA is a single flat colour.
 * An ES of exactly 0 is not negative, so it reads as "up", as before.
 */
export function enrichmentColor(row: EnrichmentChartRow, isGsea: boolean): string {
  if (!isGsea) return ENRICHMENT_ORA_COLOR;
  return row.es !== undefined && row.es < 0 ? ENRICHMENT_DOWN_COLOR : ENRICHMENT_UP_COLOR;
}

/** One plotted term: every value the tooltip and the exact-value table read. */
export interface EnrichmentChartDatum {
  /** -log10(q), clamped to the ceiling. */
  readonly logQ: number;
  /** The truncated axis label. */
  readonly label: string;
  /** Member gene count. */
  readonly size: number;
  /** The untruncated name (or the id when the name is empty). */
  readonly fullName: string;
  readonly q: number;
  readonly p: number;
  readonly es: number | null;
  /** Always null: the plot was never given NES. See the note on the tooltip. */
  readonly nes: number | null;
  /** Encoded radius, in pixels. */
  readonly radius: number;
  readonly color: string;
}

/**
 * The 8-tuple the series data carries, in the original order:
 * [logQ, label, size, fullName, q, p, es, nes].
 *
 * The tooltip indexes positionally, so this order is part of the contract.
 */
export type EnrichmentChartValue = [
  number,
  string,
  number,
  string,
  number,
  number,
  number | null,
  number | null,
];

export function buildEnrichmentChartData(
  rows: readonly EnrichmentChartRow[],
  options: { readonly isGsea: boolean },
): EnrichmentChartDatum[] {
  const maxSize = enrichmentMaxSize(rows);
  return sortEnrichmentRowsByQ(rows).map((row) => ({
    logQ: enrichmentLogQ(row.q),
    label: enrichmentTermLabel(row.name, row.id),
    size: row.size,
    fullName: row.name || row.id,
    q: row.q,
    p: row.p,
    es: row.es ?? null,
    nes: null,
    radius: enrichmentBubbleRadius(row.size, maxSize),
    color: enrichmentColor(row, options.isGsea),
  }));
}

export function enrichmentChartValue(datum: EnrichmentChartDatum): EnrichmentChartValue {
  return [datum.logQ, datum.label, datum.size, datum.fullName, datum.q, datum.p, datum.es, datum.nes];
}

/**
 * Tooltip body for one plotted term.
 *
 * Reads the 8-tuple positionally, exactly as the original formatter did, and
 * emits the same lines. The GSEA line is appended only in GSEA mode. NES keeps
 * rendering as an en dash because the plot is never handed one: the table row
 * that feeds this chart drops `nes` before it reaches the plot. Restoring NES
 * is a behaviour change, so it is reported rather than done here.
 */
export function enrichmentTooltipHtml(value: EnrichmentChartValue, isGsea: boolean): string {
  const [logQ, , size, fullName, q, p, es, nes] = value;
  const lines = [
    `<div style="max-width:320px;font-weight:600;word-break:break-word">${enrichmentEscapeHtml(fullName)}</div>`,
    `<div style="color:var(--muted-foreground);margin-top:2px">-log10(q): <b>${logQ.toFixed(2)}</b> · q: <b>${enrichmentFormatP(q)}</b> · p: <b>${enrichmentFormatP(p)}</b> · size: <b>${size}</b></div>`,
  ];
  if (isGsea) {
    lines.push(
      `<div style="color:var(--muted-foreground);margin-top:2px">ES: <b>${es === null ? "–" : enrichmentFormatSigned(es)}</b> · NES: <b>${nes === null ? "–" : enrichmentFormatSigned(nes)}</b></div>`,
    );
  }
  return lines.join("");
}

/**
 * Tooltip body for one plotted term as safe text: no markup of our own, every
 * interpolated value escaped. This is the form the shared formatter takes.
 * It reports the same facts as `enrichmentTooltipHtml`, including the en dash
 * for a missing NES, so switching renderers changes the presentation and not
 * the content.
 */
export function enrichmentTooltipText(value: EnrichmentChartValue, isGsea: boolean): string {
  const [logQ, , size, fullName, q, p, es, nes] = value;
  const facts = [
    `-log10(q): ${logQ.toFixed(2)}`,
    `q: ${enrichmentFormatP(q)}`,
    `p: ${enrichmentFormatP(p)}`,
    `size: ${size}`,
  ];
  if (isGsea) {
    facts.push(`ES: ${es === null ? "–" : enrichmentFormatSigned(es)}`);
    facts.push(`NES: ${nes === null ? "–" : enrichmentFormatSigned(nes)}`);
  }
  // The term name leads the line and is escaped like every other part.
  return chartTooltipText([fullName], "\n") + "\n" + chartTooltipText(facts, " · ");
}

/**
 * Accessible summary the figure caption reads, one entry per term.
 * Plain text, so it survives whichever renderer draws the figure.
 */
export function enrichmentDescription(rows: readonly EnrichmentChartRow[]): string {
  return rows
    .map((row) => `${row.name || row.id} ${enrichmentLogQ(row.q).toFixed(2)} ${row.size}`)
    .join(", ");
}

/** Column headers for the exact-value table fallback. */
export function enrichmentValueTableRow(datum: EnrichmentChartDatum): string[] {
  return [
    datum.fullName,
    datum.logQ.toFixed(2),
    enrichmentFormatP(datum.q),
    enrichmentFormatP(datum.p),
    String(datum.size),
  ];
}
