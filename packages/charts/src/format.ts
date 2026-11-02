/**
 * Value formatting for axes, tooltips and legends.
 *
 * The tokens live in the serializable ChartDefinition; the functions that
 * implement them live here, at render time. Keeping them apart is what lets a
 * definition stay JSON-safe.
 */

import type { ChartValueFormat } from "./definitions";
import { paintable, resolveCssColor } from "./color";

function groupThousands(input: string): string {
  const [whole, fraction] = input.split(".");
  const sign = whole.startsWith("-") ? "-" : "";
  const digits = sign ? whole.slice(1) : whole;
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return fraction === undefined ? sign + grouped : sign + grouped + "." + fraction;
}

/** Resolve a ChartValueFormat token to a formatter. */
export function createValueFormatter(format: ChartValueFormat | undefined): (value: number) => string {
  if (!format) return (value) => String(value);

  switch (format) {
    case "integer":
      return (value) => (Number.isFinite(value) ? groupThousands(String(Math.round(value))) : "--");
    case "decimal":
      return (value) => (Number.isFinite(value) ? groupThousands(value.toFixed(2)) : "--");
    case "percent":
      return (value) => (Number.isFinite(value) ? groupThousands(value.toFixed(1)) + "%" : "--");
    case "compact":
      return (value) => {
        if (!Number.isFinite(value)) return "--";
        const abs = Math.abs(value);
        if (abs >= 1_000_000_000) return (value / 1_000_000_000).toFixed(1) + "B";
        if (abs >= 1_000_000) return (value / 1_000_000).toFixed(1) + "M";
        if (abs >= 1_000) return (value / 1_000).toFixed(1) + "k";
        return String(value);
      };
    case "bytes": {
      const units = ["B", "KiB", "MiB", "GiB", "TiB"];
      return (value) => {
        if (!Number.isFinite(value)) return "--";
        let size = Math.abs(value);
        let unit = 0;
        while (size >= 1024 && unit < units.length - 1) {
          size /= 1024;
          unit += 1;
        }
        const sign = value < 0 ? "-" : "";
        return sign + (unit === 0 ? String(size) : size.toFixed(1)) + " " + units[unit];
      };
    }
    default:
      break;
  }

  // An explicit format template, e.g. ".2f". Anything unrecognised falls back
  // to the raw value rather than rendering "NaN" or throwing mid-render.
  const precision = /^\.(\d+)f$/.exec(format);
  if (precision) {
    const digits = Number(precision[1]);
    return (value) => (Number.isFinite(value) ? value.toFixed(digits) : "--");
  }
  return (value) => (Number.isFinite(value) ? groupThousands(String(value)) : "--");
}

/**
 * A two-stop gradient expressed as a CSS gradient string.
 *
 * This replaces the engine-specific gradient object that used to be imported
 * at the call site: the definition now carries two colors, and the shape is
 * built here.
 */
export function gradientCss(gradient: { from: string; to: string; direction?: "vertical" | "horizontal" } | undefined): string | undefined {
  if (!gradient) return undefined;
  const angle = gradient.direction === "horizontal" ? "90deg" : "180deg";
  // Both stops are resolved: a canvas cannot resolve var(--chart-1) inside a
  // CSS gradient, so an unresolved stop would silently drop the whole fill.
  const from = paintable(gradient.from);
  const to = paintable(gradient.to);
  return "linear-gradient(" + angle + ", " + from + ", " + to + ")";
}

/** Expand a three-stop diverging ramp into the stops a sequential scale wants. */
export function expandColorRange(range: readonly [string, string, string] | undefined): string[] | undefined {
  if (!range) return undefined;
  return [paintable(range[0]), paintable(range[1]), paintable(range[2])];
}

/** An alpha-ramped gradient over one series color. */
export interface SeriesGradientSpec {
  readonly from?: string;
  readonly to?: string;
  readonly fromOpacity?: number;
  readonly toOpacity?: number;
  readonly direction?: "vertical" | "horizontal";
}

/** Pull "r, g, b" out of a color the engine can paint. */
function channels(color: string): [number, number, number] {
  const resolved = resolveCssColor(color).value;
  const hex = /^#([0-9a-f]{6})$/i.exec(resolved);
  if (hex) {
    const text = hex[1];
    const r = parseInt(text.slice(0, 2), 16);
    const g = parseInt(text.slice(2, 4), 16);
    const b = parseInt(text.slice(4, 6), 16);
    return [r, g, b];
  }
  const rgb = /^rgba?\(([^)]+)\)/i.exec(resolved);
  if (rgb) {
    const parsed = rgb[1].split(",").map((part) => Number(part.trim()));
    return [parsed[0] || 0, parsed[1] || 0, parsed[2] || 0];
  }
  return [0, 0, 0];
}

/**
 * Build one series' area gradient.
 *
 * Each series keeps its own fill. This deliberately does not merge a
 * multi-series chart into a single ramp; baseColor is the series' palette
 * entry, so a per-series spec only has to state the alpha ramp.
 */
export function seriesGradientCss(gradient: SeriesGradientSpec | undefined, baseColor: string): string | undefined {
  if (!gradient) return undefined;
  const from = gradient.from ?? baseColor;
  const to = gradient.to ?? from;
  const startAlpha = gradient.fromOpacity ?? 0.3;
  const endAlpha = gradient.toOpacity ?? 0.02;
  const a = channels(from);
  const b = channels(to);
  const first = "rgba(" + a[0] + ", " + a[1] + ", " + a[2] + ", " + startAlpha + ")";
  const second = "rgba(" + b[0] + ", " + b[1] + ", " + b[2] + ", " + endAlpha + ")";
  const angle = gradient.direction === "horizontal" ? "90deg" : "180deg";
  return "linear-gradient(" + angle + ", " + first + ", " + second + ")";
}
