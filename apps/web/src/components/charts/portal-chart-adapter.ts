/**
 * Portal-side adapter for the five analytics / expression charts.
 *
 * The portal renders those charts through `@soymutdb/charts` instead of
 * ECharts. The facade takes an already-resolved theme, an animation policy
 * and a *long* data format (one row per category per series), while the portal
 * receives wide rows from the API. This module owns that translation, and
 * nothing else: the components keep their own layout, i18n and empty states.
 *
 * It is named portal-chart-adapter rather than chart-adapter so the portal
 * helper never collides with the console's own adapter in
 * apps/admin/src/components/charts.
 *
 * Every function that can be pure is pure and exported, so the mapping rules
 * (chromosome prefix stripping, impact ordering, first-value-wins grouping)
 * are testable without React and without the chart engine.
 */
import * as React from "react";

import {
  resolveChartTheme,
  type ChartAxisFormatter,
  type ChartAnimationInput,
  type ChartAnimationIntensity,
  type ChartDefinition,
  type ChartGradientSpec,
  type ChartThemeInput,
  type ChartThemeMode,
  type ChartTooltipFormatter,
} from "@soymutdb/charts";

import { useTheme } from "../../lib/theme-provider";
import { useAnimation } from "../../lib/animation-context";

/** The drawing height the ECharts components used: h-72. */
export const PORTAL_CHART_HEIGHT = 288;

/** The compact drawing height h-64, which impact-distribution alone used. */
export const PORTAL_CHART_HEIGHT_COMPACT = 256;

/** One row of the facade's single-series long format. */
export interface PortalCategoryRow {
  category: string;
  value: number;
}

/** One row of the facade's dated, multi-series long format. */
export interface PortalDatedRow {
  date: string;
  series: string;
  value: number;
}

/** One row of the facade's grouped (category x series) long format. */
export interface PortalGroupedRow {
  category: string;
  series: string;
  value: number;
}

/**
 * Resolve the portal theme for the facade.
 *
 * The mode comes from the portal's own theme provider, and the colors are read
 * off the document by resolveChartTheme, exactly as the ECharts hook read
 * them: a canvas renderer cannot resolve a CSS custom property at paint time.
 * Passing the resolved arrays (rather than the named palette) is what lets a
 * definition name a concrete color -- the chromosome gradient needs two of
 * them -- while still tracking the current theme.
 */
export function resolvePortalChartTheme(mode: ChartThemeMode): ChartThemeInput {
  const root = typeof document === "undefined" ? null : document.documentElement;
  const resolved = resolveChartTheme({ mode }, root);
  return { mode, palette: resolved.categorical, impact: resolved.impact };
}

export function usePortalChartTheme(): ChartThemeInput {
  const { theme } = useTheme();
  return React.useMemo(() => resolvePortalChartTheme(theme), [theme]);
}

/**
 * Forward the portal's motion policy.
 *
 * intensity from the animation provider is already an effective mode
 * ("off" | "minimal" | "standard"), which is exactly the facade's
 * vocabulary. reduced wins over it, so a reduced-motion session stays still
 * even if the stored preference still says otherwise.
 */
export function portalChartAnimation(
  reduced: boolean,
  intensity: ChartAnimationIntensity,
): ChartAnimationInput {
  return { reduced, intensity: reduced ? "off" : intensity };
}

export function usePortalChartAnimation(): ChartAnimationInput {
  const { reduced, intensity } = useAnimation();
  return React.useMemo(() => portalChartAnimation(reduced, intensity), [reduced, intensity]);
}

/**
 * The facade mirrors its lifecycle onto the canvas host as data-status. The
 * portal's charts keep their own loading skeleton, which the facade does not
 * render, so the skeleton follows that attribute instead of a second
 * engine-loading signal that would drift from it.
 */
export type PortalChartStatus = "idle" | "loading" | "rendered" | "failed";

const CANVAS_SELECTOR = '[data-testid="chart-canvas"]';

export function readPortalChartStatus(root: HTMLElement | null): PortalChartStatus | null {
  const status = root?.querySelector(CANVAS_SELECTOR)?.getAttribute("data-status");
  return status === "idle" || status === "loading" || status === "rendered" || status === "failed"
    ? status
    : null;
}

/**
 * The facade's own lifecycle state for the chart inside root.
 *
 * enabled is false when the component renders no chart at all (the empty
 * state), and the hook then reports no status, so neither the skeleton nor a
 * drawn-state overlay can appear over the Empty placeholder.
 */
export function usePortalChartStatus(
  root: React.RefObject<HTMLElement | null>,
  enabled: boolean,
): PortalChartStatus | null {
  const [status, setStatus] = React.useState<PortalChartStatus | null>(null);

  React.useEffect(() => {
    const element = root.current;
    if (!element || !enabled) {
      setStatus(null);
      return;
    }
    const sync = () => setStatus(readPortalChartStatus(element));
    sync();
    if (typeof MutationObserver === "undefined") return;
    const observer = new MutationObserver(sync);
    observer.observe(element, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["data-status"],
    });
    return () => observer.disconnect();
  }, [root, enabled]);

  return enabled ? status : null;
}

/**
 * True while the chart is on screen but not yet drawn.
 */
export function usePortalChartLoading(
  root: React.RefObject<HTMLElement | null>,
  enabled: boolean,
): boolean {
  const status = usePortalChartStatus(root, enabled);
  if (!enabled) return false;
  return status === null || status === "idle" || status === "loading";
}

/**
 * The compact count formatter the ECharts value axes used on the density,
 * impact and release-trend charts: millions as "1.0M", thousands as "1K",
 * anything smaller as-is.
 *
 * It is a component prop rather than a definition field, because it is a
 * function and the definition must stay serializable. Module scope keeps its
 * identity stable across renders.
 */
export const portalCountAxisFormatter: ChartAxisFormatter = (value) => {
  if (value >= 1e6) return (value / 1e6).toFixed(1) + "M";
  if (value >= 1e3) return (value / 1e3).toFixed(0) + "K";
  return String(value);
};

/* ------------------------------------------------------------------ *
 * Data mappings.
 * ------------------------------------------------------------------ */

/**
 * Non-finite measures are dropped everywhere.
 *
 * A missing measurement is not a value; passing NaN through would put it in
 * the y domain and let the engine decide how to draw it.
 */
function isDrawable(value: number): boolean {
  return Number.isFinite(value);
}

/**
 * Chromosome density: {chromosome, variantCount} -> one bar per category.
 *
 * The axis label drops the chr prefix, which the ECharts version did by
 * slicing the string before the chart ever saw it.
 */
export function toPortalDensityRows(
  data: ReadonlyArray<{ chromosome: string; variantCount: number }>,
): PortalCategoryRow[] {
  const rows: PortalCategoryRow[] = [];
  for (const datum of data) {
    if (!isDrawable(datum.variantCount)) continue;
    rows.push({ category: datum.chromosome.replace("chr", ""), value: datum.variantCount });
  }
  return rows;
}

/** Variant types: {name, value} -> one slice per category. */
export function toPortalVariantTypeRows(
  data: ReadonlyArray<{ name: string; value: number }>,
): PortalCategoryRow[] {
  const rows: PortalCategoryRow[] = [];
  for (const datum of data) {
    if (!isDrawable(datum.value)) continue;
    rows.push({ category: datum.name, value: datum.value });
  }
  return rows;
}

/**
 * Impact severities, in the order the chart always drew them.
 *
 * The fixed order is also what makes the semantic colors land on the right
 * bar: the facade assigns the impact palette -- high, moderate, low,
 * modifier -- to the category domain in order, and a payload that arrives in a
 * different order must not reshuffle the colors.
 */
export const PORTAL_IMPACT_ORDER = ["HIGH", "MODERATE", "LOW", "MODIFIER"] as const;

export type PortalImpact = (typeof PORTAL_IMPACT_ORDER)[number];

export function toPortalImpactRows(
  data: ReadonlyArray<{ impact: PortalImpact; count: number }>,
): PortalCategoryRow[] {
  const rows: PortalCategoryRow[] = [];
  for (const impact of PORTAL_IMPACT_ORDER) {
    const match = data.find((datum) => datum.impact === impact);
    if (!match || !isDrawable(match.count)) continue;
    rows.push({ category: impact, value: match.count });
  }
  return rows;
}

/**
 * The two release-trend series keep the names the legend always showed. These
 * are data values, not labels: they are drawn in the legend and printed in the
 * tooltip, so they are part of the visible contract.
 */
export const PORTAL_CUMULATIVE_SERIES = "Cumulative";
export const PORTAL_NEW_SERIES = "New";

/**
 * Release trend: one row per date per series.
 *
 * The endpoint returns both measures on one row per release; the facade
 * groups by a color field instead, so each measure becomes its own row. Row
 * order follows date, then series, which is the order the ordinal color scale
 * must see.
 */
export function toPortalTrendRows(
  data: ReadonlyArray<{ date: string; cumulative: number; newVariants: number }>,
): PortalDatedRow[] {
  const rows: PortalDatedRow[] = [];
  for (const datum of data) {
    if (isDrawable(datum.cumulative)) {
      rows.push({ date: datum.date, series: PORTAL_CUMULATIVE_SERIES, value: datum.cumulative });
    }
    if (isDrawable(datum.newVariants)) {
      rows.push({ date: datum.date, series: PORTAL_NEW_SERIES, value: datum.newVariants });
    }
  }
  return rows;
}

/**
 * Expression: one row per tissue per treatment.
 *
 * Two historic behaviours are load-bearing and are kept deliberately:
 *
 *   - first value wins. The ECharts version resolved a cell with a Map.has
 *     guard, so a duplicated (treatment, tissue) pair keeps the first value
 *     and drops the rest. Last-write-wins would change the number.
 *   - the cartesian product is filled with zeroes. The old series were built
 *     as one bar vector per treatment over every tissue, "?? 0", so a missing
 *     combination was a zero-height bar rather than a gap in the group.
 */
export function toPortalExpressionRows(
  data: ReadonlyArray<{ tissue: string; mean_fpkm: number; treatment: string }>,
): PortalGroupedRow[] {
  const treatmentSet = new Set<string>();
  const tissueSet = new Set<string>();
  const values = new Map<string, Map<string, number>>();

  for (const datum of data) {
    treatmentSet.add(datum.treatment);
    tissueSet.add(datum.tissue);
    const byTissue = values.get(datum.treatment) ?? new Map<string, number>();
    if (!byTissue.has(datum.tissue)) byTissue.set(datum.tissue, datum.mean_fpkm);
    values.set(datum.treatment, byTissue);
  }

  // Default sort, as before: the categories and the legend kept the order this
  // exact comparison produced.
  const treatments = [...treatmentSet].sort();
  const tissues = [...tissueSet].sort();

  const rows: PortalGroupedRow[] = [];
  for (const tissue of tissues) {
    for (const treatment of treatments) {
      rows.push({
        category: tissue,
        series: treatment,
        value: values.get(treatment)?.get(tissue) ?? 0,
      });
    }
  }
  return rows;
}

/* ------------------------------------------------------------------ *
 * Definitions.
 * ------------------------------------------------------------------ */

/**
 * Variant types: a donut, one slice per variant type.
 *
 * innerRadius is the ratio of the old radius ["55%", "78%"] ring
 * (55 / 78 ~ 0.7). The centre total the ECharts series printed is not part of
 * the facade's contract, so the component draws it as an accessible DOM
 * overlay over the ring rather than asking the engine for a centre label.
 *
 * legend: true declares that this chart always showed a legend. Its
 * orientation (vertical, right of the ring) and placement are not expressible
 * yet -- the facade carries a boolean -- so the legend renders wherever the
 * engine puts it until the shared legend options land.
 */
export function portalVariantTypeDefinition(): ChartDefinition {
  return {
    kind: "donut",
    x: "category",
    y: "value",
    innerRadius: 0.7,
    categoryOrder: "appearance",
    palette: "categorical",
    valueFormat: "integer",
    legend: true,
  };
}

/**
 * Where the donut ring sits in the chart box, as percentages.
 *
 * The ECharts version offset the ring to center ["38%", "50%"] to leave room
 * for the vertical legend on the right. The facade cannot place a legend yet,
 * so the ring is currently centred and the centre-total overlay has to be
 * centred with it. When shared can put the legend on the right this becomes
 * 38, and the overlay follows because both read this one constant.
 */
export const PORTAL_DONUT_RING_CENTER = { x: 50, y: 50 } as const;

/**
 * The chromosome bars keep their vertical two-stop gradient. The colors are
 * passed in resolved, because the facade builds the gradient as a CSS string
 * and does not resolve custom properties inside it.
 */
export function portalDensityGradient(palette: readonly string[]): ChartGradientSpec {
  return {
    from: palette[0] ?? "var(--chart-1)",
    to: palette[3] ?? "var(--chart-4)",
    direction: "vertical",
  };
}

export function portalDensityDefinition(gradient: ChartGradientSpec): ChartDefinition {
  return {
    kind: "interval",
    x: "category",
    y: "value",
    categoryOrder: "appearance",
    palette: "categorical",
    gradient,
    valueFormat: "integer",
  };
}

/**
 * Impact: a bar per severity, painted with the semantic impact tokens.
 *
 * orientation "horizontal" transposes the plot, so the severity reads on the
 * vertical axis again as it did in ECharts, with the same fixed order and the
 * same four semantic colors. The label gutter the old grid.left of 80 reserved
 * has no equivalent in the facade; the engine's own axis padding is used.
 */
export function portalImpactDefinition(): ChartDefinition {
  return {
    kind: "interval",
    x: "category",
    y: "value",
    orientation: "horizontal",
    categoryOrder: "appearance",
    palette: "impact",
    valueFormat: "integer",
  };
}

/**
 * Release trend: two lines over the release dates.
 *
 * The palette is explicit so the series keep the colors they always used --
 * chart-1 for Cumulative, chart-3 for New. A named palette would have handed
 * New the second categorical color instead.
 *
 * New keeps its thinner dashed stroke. The cumulative area does NOT appear
 * yet: ChartSeriesSpec carries markType for exactly this, but the runtime
 * still builds one mark for the whole chart, so declaring markType "area"
 * here would be a definition that renders nothing and a test that proves
 * nothing. It lands with the runtime mapping, as
 * seriesStyle.Cumulative.markType "area" plus its own gradient ramp.
 *
 * The old smooth: true curve has no serializable field either.
 */
export function portalTrendDefinition(palette: readonly string[]): ChartDefinition {
  return {
    kind: "line",
    x: "date",
    y: "value",
    color: "series",
    categoryOrder: "appearance",
    palette: [palette[0] ?? "var(--chart-1)", palette[2] ?? "var(--chart-3)"],
    legend: true,
    valueFormat: "integer",
    seriesStyle: {
      [PORTAL_NEW_SERIES]: { style: { lineDash: [4, 4], lineWidth: 1.5 } },
    },
  };
}

/**
 * Expression: grouped bars, one group per tissue, one bar per treatment.
 *
 * The value axis keeps the "Mean FPKM" title it had. valueFormat is left
 * unset on purpose: the facade rides the formatter onto the axis labels
 * whenever an axis is titled, which would turn 1.2 into 1.20. The two-decimal
 * precision belongs to the tooltip, where the old chart put it.
 *
 * Tissue labels were rotated 30 degrees once there were more than six of
 * them, which is why the builder takes the category count: the rule is
 * conditional on the data, not a fixed chart setting.
 */
export function portalExpressionDefinition(tissueCount: number): ChartDefinition {
  return {
    kind: "interval",
    x: "category",
    y: "value",
    color: "series",
    categoryOrder: "appearance",
    palette: "categorical",
    legend: true,
    axisLabels: { y: "Mean FPKM" },
    xAxis: { labelsRotation: tissueCount > 6 ? 30 : 0 },
  };
}

/* ------------------------------------------------------------------ *
 * Tooltips.
 *
 * A tooltip renderer is a component prop, never part of the
 * serializable definition, so these live here and are passed in.
 * ------------------------------------------------------------------ */

function rowValue(datum: Record<string, unknown>): number {
  const value = datum.value;
  return typeof value === "number" ? value : Number(value);
}

function rowCategory(datum: Record<string, unknown>): string {
  return String(datum.category ?? "");
}

function rowSeries(datum: Record<string, unknown>): string {
  return String(datum.series ?? "");
}

/** "SNP: 1,234 (56.7%)" -- the share the donut centre used to carry. */
export function formatVariantTypeTooltip(total: number): ChartTooltipFormatter {
  return ({ datum }) => {
    const value = rowValue(datum);
    const percent = total > 0 ? Math.round((value / total) * 10000) / 100 : 0;
    return rowCategory(datum) + ": " + value.toLocaleString() + " (" + percent + "%)";
  };
}

/** "1: 12,345 variants" -- the axis-triggered tooltip of the density chart. */
export function formatDensityTooltip(): ChartTooltipFormatter {
  return ({ datum }) => rowCategory(datum) + ": " + rowValue(datum).toLocaleString() + " variants";
}

/** "HIGH: 431" -- the impact tooltip, unlabelled as before. */
export function formatImpactTooltip(): ChartTooltipFormatter {
  return ({ datum }) => rowCategory(datum) + ": " + rowValue(datum).toLocaleString();
}

/**
 * "Cumulative: 12,345" for every measure of the hovered date.
 *
 * The facade asks for one datum at a time, so the row separator stays with the
 * G2 tooltip rather than being spliced into the string here.
 */
export function formatTrendTooltip(): ChartTooltipFormatter {
  return ({ datum }) => rowSeries(datum) + ": " + rowValue(datum).toLocaleString();
}

/** "Control: 4.25 FPKM" -- two decimals, as the grouped-bar tooltip had. */
export function formatExpressionTooltip(): ChartTooltipFormatter {
  return ({ datum }) => rowSeries(datum) + ": " + rowValue(datum).toFixed(2) + " FPKM";
}
