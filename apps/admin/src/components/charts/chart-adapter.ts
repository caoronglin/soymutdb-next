import * as React from "react";
import type { ChartAnimationInput, ChartThemeInput } from "@soymutdb/charts";

import { useAdminMotion } from "../../lib/motion-preference";

/**
 * Shared adapter between the dashboard's own chart components and the
 * "@soymutdb/charts" facade.
 *
 * The console has no chart theme provider and no shared helpers: the facade
 * deliberately takes an already-resolved theme, and the dashboard pages own
 * their own data shape. This module holds the three things all three
 * dashboard charts need, so no chart re-derives them:
 *
 *   - the resolved theme (an explicit palette plus the current data-theme
 *     mode, observed rather than read once),
 *   - the animation policy, forwarded from the console's existing motion
 *     preference instead of a new provider,
 *   - the wide-to-long row mapping the facade's color field needs.
 */

/** Matches the h-64 box the ECharts components rendered. */
export const ADMIN_CHART_HEIGHT = 256;

/**
 * The colors the three dashboard charts already used, kept verbatim so the
 * migration changes the engine and not the palette. Each chart passes its own
 * array so the ordinal color scale lands on the same swatch as before.
 */
export const IMPORT_SERIES_COLORS = ["#2f7d32", "#c0392b"] as const;
export const LATENCY_SERIES_COLORS = ["#2f7d32", "#e6a817", "#c0392b"] as const;
export const STORAGE_SERIES_COLORS = ["#4e9b4a"] as const;

export type ChartThemeMode = "light" | "dark";

/** Read the console's current theme the same way the facade's resolver does. */
export function readDocumentThemeMode(): ChartThemeMode {
  if (typeof document === "undefined") return "light";
  const root = document.documentElement;
  if (root.getAttribute("data-theme") === "dark") return "dark";
  return root.classList.contains("dark") ? "dark" : "light";
}

/**
 * Track data-theme changes.
 *
 * admin-header.tsx flips the attribute on documentElement with no context and
 * no event, so a chart that read the attribute once would keep painting in the
 * previous mode until its data changed. The facade rebuilds a chart only when
 * the theme input it was given changes, so this hook has to turn the attribute
 * into React state.
 */
export function useChartThemeMode(): ChartThemeMode {
  const [mode, setMode] = React.useState<ChartThemeMode>(readDocumentThemeMode);

  React.useEffect(() => {
    const root = document.documentElement;
    const update = () => setMode(readDocumentThemeMode());
    // Re-read once on mount: the attribute may have flipped between the first
    // render and this effect.
    update();
    const observer = new MutationObserver(update);
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);

  return mode;
}

/**
 * An explicit theme for one chart.
 *
 * The palette is passed as concrete colors on purpose: the console declares
 * its chart variables in OKLCH, and a canvas renderer cannot resolve a CSS
 * custom property or an OKLCH function at paint time.
 */
export function useAdminChartTheme(colors: readonly string[]): ChartThemeInput {
  const mode = useChartThemeMode();
  return React.useMemo<ChartThemeInput>(() => ({ mode, palette: colors }), [mode, colors]);
}

/**
 * The console's motion policy, forwarded to the facade.
 *
 * useAdminMotion already folds prefers-reduced-motion, Save-Data and the
 * device signals into one effective mode whose values match the facade's
 * ChartAnimationIntensity, so the console gains animation policy without a
 * new provider.
 */
export function useAdminChartAnimation(): ChartAnimationInput {
  const { effective } = useAdminMotion();
  return React.useMemo<ChartAnimationInput>(() => ({ intensity: effective }), [effective]);
}

/** One row of the facade's long format: a category, a named series, a value. */
export interface ChartSeriesRow {
  date: string;
  series: string;
  value: number;
}

/** A dated single-value row, for charts drawn with one series. */
export interface ChartTrendRow {
  date: string;
  value: number;
}

export interface SeriesSpec<TDatum> {
  /** The legend entry. Doubles as the color scale's domain value. */
  readonly name: string;
  readonly pick: (datum: TDatum) => number;
}

/**
 * Reshape wide dashboard rows into the long format the facade draws.
 *
 * The dashboard endpoint returns one object per day holding several measures;
 * the facade groups by a color field instead, so each measure becomes its own
 * row. Series order in the result follows specs, which is the order the
 * ordinal color scale must see. Non-finite measures are dropped: a missing
 * measurement is not a value, and the engine would otherwise have to resolve a
 * NaN into the y domain.
 */
export function toSeriesRows<TDatum extends { date: string }>(
  data: readonly TDatum[],
  specs: readonly SeriesSpec<TDatum>[],
): ChartSeriesRow[] {
  const rows: ChartSeriesRow[] = [];
  for (const datum of data) {
    for (const spec of specs) {
      const value = spec.pick(datum);
      if (Number.isFinite(value)) rows.push({ date: datum.date, series: spec.name, value });
    }
  }
  return rows;
}

/** Reshape wide rows into the single-series format a trend chart reads. */
export function toTrendRows<TDatum extends { date: string }>(
  data: readonly TDatum[],
  pick: (datum: TDatum) => number,
): ChartTrendRow[] {
  const rows: ChartTrendRow[] = [];
  for (const datum of data) {
    const value = pick(datum);
    if (Number.isFinite(value)) rows.push({ date: datum.date, value });
  }
  return rows;
}
