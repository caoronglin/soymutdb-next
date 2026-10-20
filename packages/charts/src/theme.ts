/**
 * The chart theme bridge.
 *
 * The engine has no automatic theme inheritance, and the admin console has no
 * theme provider at all. So the facade never *requires* a provider: it takes
 * an already-resolved palette when the consumer has one, otherwise it reads
 * the portal CSS custom properties, otherwise it falls back to a built-in
 * default. Nothing here requires a React context.
 *
 * The previous implementation imported the gradient type from the chart
 * engine. That import is gone: gradients are now plain two-stop color pairs
 * declared in the serializable ChartDefinition.
 */

import type { ChartPaletteSpec } from "./definitions";
import { isPaintable, paintable } from "./color";

export type ChartThemeMode = "light" | "dark" | "auto";

/**
 * What a consumer may pass in. Every field is optional and every field is
 * already resolved -- no provider, no hook, no global lookup is required.
 */
export interface ChartThemeInput {
  readonly mode?: ChartThemeMode;
  /** Explicit resolved categorical colors. Wins over CSS variables. */
  readonly palette?: readonly string[];
  /** Explicit resolved impact colors (high/moderate/low/modifier). */
  readonly impact?: readonly string[];
  /** Explicit resolved sequential ramp. */
  readonly sequential?: readonly string[];
}

export interface ResolvedChartTheme {
  readonly mode: "light" | "dark";
  readonly categorical: readonly string[];
  readonly impact: readonly string[];
  readonly sequential: readonly string[];
  readonly axisColor: string;
  readonly labelColor: string;
  readonly gridColor: string;
  /**
   * Palette entries the bridge could not turn into paintable bytes. The
   * chart still renders, but those entries are a real defect and are
   * surfaced rather than silently swallowed.
   */
  readonly unresolvedColors: readonly string[];
}

/** CSS custom properties the portal already ships. */
export const CATEGORICAL_PALETTE_VARS = [
  "--chart-1",
  "--chart-2",
  "--chart-3",
  "--chart-4",
  "--chart-5",
] as const;

export const IMPACT_PALETTE_VARS = [
  "--impact-high",
  "--impact-moderate",
  "--impact-low",
  "--impact-modifier",
] as const;

const SEQUENTIAL_PALETTE_VARS = [
  "--chart-5",
  "--chart-4",
  "--chart-3",
  "--chart-2",
  "--chart-1",
] as const;

/**
 * The colors this package shipped before the CSS variables existed. Keeping
 * them as the fallback means a chart rendered with no theme input looks the
 * same as it did on the old engine.
 */
export const FALLBACK_CATEGORICAL_PALETTE = [
  "#2f855a",
  "#75a987",
  "#d89b47",
  "#6f8fa8",
  "#8f79a6",
] as const;

export const FALLBACK_IMPACT_PALETTE = ["#b23c2b", "#c98a2e", "#3b6ea5", "#4a6b58"] as const;

/**
 * Reads a CSS custom property list off a root element and converts every
 * entry to a canvas-paintable color.
 *
 * The conversion is mandatory, not cosmetic: the portal declares oklch, and
 * an engine handed oklch text paints nothing. Consumers that cannot rely on
 * CSS being loaded (the admin console) pass explicit hex instead.
 */
function readVars(names: readonly string[], root: Element | null | undefined): string[] | null {
  if (!root || typeof root.getAttribute !== "function") return null;
  const computed = typeof getComputedStyle === "function" ? getComputedStyle(root) : null;
  const values: string[] = [];
  for (const name of names) {
    const value = computed?.getPropertyValue(name) || root.getAttribute(name);
    const trimmed = (value ?? "").trim();
    if (!trimmed) return null;
    values.push(paintable(trimmed));
  }
  return values;
}

/** Normalize a caller-supplied palette to paintable colors. */
function normalize(colors: readonly string[]): string[] {
  return colors.map((color) => paintable(color));
}

function detectMode(root: Element | null | undefined): "light" | "dark" {
  const ownerDocument = root?.ownerDocument ?? (typeof document === "undefined" ? undefined : document);
  const docEl = ownerDocument?.documentElement;
  if (!docEl) return "light";
  const attribute = docEl.getAttribute("data-theme");
  if (attribute === "dark") return "dark";
  if (typeof docEl.classList?.contains === "function" && docEl.classList.contains("dark")) {
    return "dark";
  }
  return "light";
}

/**
 * Resolve the theme. Explicit input always wins; CSS variables are the
 * portal path; the built-in fallback is the admin/no-stylesheet path.
 */
export function resolveChartTheme(
  input: ChartThemeInput = {},
  root?: Element | null,
): ResolvedChartTheme {
  const mode = input.mode === "auto" || input.mode === undefined ? detectMode(root) : input.mode;

  const categorical: string[] =
    input.palette && input.palette.length
      ? normalize(input.palette)
      : readVars(CATEGORICAL_PALETTE_VARS, root) ?? [...FALLBACK_CATEGORICAL_PALETTE];

  const impact: string[] =
    input.impact && input.impact.length
      ? normalize(input.impact)
      : readVars(IMPACT_PALETTE_VARS, root) ?? [...FALLBACK_IMPACT_PALETTE];

  const sequential: string[] =
    input.sequential && input.sequential.length
      ? normalize(input.sequential)
      : readVars(SEQUENTIAL_PALETTE_VARS, root) ?? [...categorical];

  const unresolvedColors = [...categorical, ...impact, ...sequential].filter((color) =>
    !isPaintable(color),
  );

  return mode === "dark"
    ? {
        mode,
        categorical,
        impact,
        sequential,
        axisColor: "#8c9bab",
        labelColor: "#c9d2dc",
        gridColor: "#2b3540",
        unresolvedColors,
      }
    : {
        mode,
        categorical,
        impact,
        sequential,
        axisColor: "#5a6a7a",
        labelColor: "#22303c",
        gridColor: "#d7dee6",
        unresolvedColors,
      };
}

/** Pick the concrete colors a definition's palette spec asks for. */
export function resolvePalette(
  spec: ChartPaletteSpec | undefined,
  theme: ResolvedChartTheme,
): string[] {
  if (Array.isArray(spec)) return [...spec];
  if (spec === "impact") return [...theme.impact];
  if (spec === "sequential") return [...theme.sequential];
  return [...theme.categorical];
}

/**
 * A stable, order-sensitive key for the theme inputs that must force the
 * chart to be torn down and rebuilt. G2 themes are object state on the plot,
 * so a theme swap is a dispose + recreate, not an in-place update.
 */
export function themeIdentity(input: ChartThemeInput | undefined, root?: Element | null): string {
  const resolved = resolveChartTheme(input ?? {}, root);
  return JSON.stringify([
    resolved.mode,
    resolved.categorical,
    resolved.impact,
    resolved.sequential,
    resolved.axisColor,
    resolved.labelColor,
    resolved.gridColor,
    resolved.unresolvedColors,
  ]);
}
