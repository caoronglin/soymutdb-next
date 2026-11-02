/**
 * CSS color resolution for the canvas.
 *
 * The design system declares its chart palette in oklch, for example
 * "--chart-1: oklch(0.55 0.14 152)". A canvas renderer cannot paint that: it
 * needs concrete sRGB bytes. So the theme bridge resolves every palette entry
 * through here before it reaches the engine.
 *
 * This is a real conversion, not a string passthrough. getComputedStyle
 * returns the declared oklch text verbatim, and handing that to the engine
 * silently produced an unpaintable chart.
 *
 * Supported: hex (3/4/6/8), rgb()/rgba() in legacy and modern syntax,
 * color(srgb ...), oklch(), oklab(). Anything else is returned unchanged and
 * marked unresolved, because guessing would hide the problem, not fix it.
 */

export interface ResolvedColor {
  /** A canvas-paintable color: #rrggbb, #rrggbbaa, rgb() or rgba(). */
  readonly value: string;
  /** True when the input was understood and converted. */
  readonly resolved: boolean;
}

const NAMED: Record<string, [number, number, number]> = {
  black: [0, 0, 0],
  white: [255, 255, 255],
  red: [255, 0, 0],
  green: [0, 128, 0],
  blue: [0, 0, 255],
  gray: [128, 128, 128],
  grey: [128, 128, 128],
  transparent: [0, 0, 0],
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function toHexPair(value: number): string {
  return Math.round(clamp(value, 0, 255)).toString(16).padStart(2, "0");
}

function rgbToString(r: number, g: number, b: number, alpha: number | null): string {
  if (alpha !== null && alpha < 1) {
    const a = Math.round(clamp(alpha, 0, 1) * 1000) / 1000;
    return "rgba(" + Math.round(r) + ", " + Math.round(g) + ", " + Math.round(b) + ", " + a + ")";
  }
  return "#" + toHexPair(r) + toHexPair(g) + toHexPair(b);
}

/** sRGB transfer function, the inverse of the one used to encode oklab. */
function gammaEncode(channel: number): number {
  const sign = channel < 0 ? -1 : 1;
  const abs = Math.abs(channel);
  const encoded = abs <= 0.0031308 ? 12.92 * abs : 1.055 * Math.pow(abs, 1 / 2.4) - 0.055;
  return clamp(sign * encoded, 0, 1) * 255;
}

/** OKLab to linear sRGB, using Bjorn Ottosson's matrices. */
function oklabToLinearSrgb(L: number, a: number, bb: number): [number, number, number] {
  const l_ = L + 0.3963377774 * a + 0.2158037573 * bb;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * bb;
  const s_ = L - 0.0894841775 * a - 1.291485548 * bb;
  const l = l_ * l_ * l_;
  const m = m_ * m_ * m_;
  const s = s_ * s_ * s_;
  const r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s;
  const g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s;
  const b = -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s;
  return [r, g, b];
}

interface FunctionalParts {
  values: number[];
  alpha: number | null;
  tokens: string[];
}

/** Split a functional-notation body into numbers plus an optional alpha. */
function parts(input: string): FunctionalParts {
  const split = input.split("/");
  const tokens = split[0].trim().split(/[\s,]+/).filter(Boolean);
  // A trailing percent sign is stripped but not rescaled; the rgb branch
  // decides whether the number is 0-1 or 0-100 from the token itself.
  const numeric = (token: string) => {
    return token.endsWith("%") ? Number(token.slice(0, -1)) : Number(token);
  };
  const values = tokens.map(numeric).filter((value) => Number.isFinite(value));
  let alpha: number | null = null;
  if (split[1] !== undefined) {
    const raw = split[1].trim();
    alpha = raw.endsWith("%") ? Number(raw.slice(0, -1)) / 100 : Number(raw);
  }
  return { values, alpha, tokens };
}

function oklabToString(L: number, a: number, b: number, alpha: number | null, fallback: string): ResolvedColor {
  // oklab lightness runs 0..1 with small a/b axes. A wildly out-of-range value
  // means we did not actually parse a color.
  if (!Number.isFinite(L) || L < -0.5 || L > 1.5) {
    return { value: fallback, resolved: false };
  }
  const linear = oklabToLinearSrgb(L, a, b);
  const r = gammaEncode(linear[0]);
  const g = gammaEncode(linear[1]);
  const bl = gammaEncode(linear[2]);
  return { value: rgbToString(r, g, bl, alpha), resolved: true };
}

function hexPair(text: string, offset: number): number {
  return parseInt(text.slice(offset, offset + 2), 16);
}

function expandNibble(c: string): number {
  return parseInt(c + c, 16);
}

/**
 * Convert one CSS color into something a canvas can paint.
 *
 * Out-of-gamut oklch colors are clamped per channel rather than rejected: the
 * portal palette is authored for sRGB, so clamping only trims rounding drift.
 */
export function resolveCssColor(input: string): ResolvedColor {
  const raw = (input ?? "").trim();
  if (!raw) return { value: raw, resolved: false };

  const lower = raw.toLowerCase();

  // A var() reference has no computable value outside a live style engine, so
  // it is reported as unresolved rather than passed off as paintable. Callers
  // that need it must hand over the resolved color (resolveChartTheme does).
  if (lower.includes("var(")) return { value: raw, resolved: false };

  const named = NAMED[lower];
  if (named) {
    const alpha = lower === "transparent" ? 0 : null;
    return { value: rgbToString(named[0], named[1], named[2], alpha), resolved: true };
  }

  if (lower.startsWith("#")) {
    const hex = lower.slice(1);
    if (/^[0-9a-f]{3}$/.test(hex)) {
      const channels = hex.split("").map(expandNibble);
      return { value: rgbToString(channels[0], channels[1], channels[2], null), resolved: true };
    }
    if (/^[0-9a-f]{4}$/.test(hex)) {
      const channels = hex.split("").map(expandNibble);
      return { value: rgbToString(channels[0], channels[1], channels[2], channels[3] / 255), resolved: true };
    }
    if (/^[0-9a-f]{6}$/.test(hex)) {
      const rgb = [hexPair(hex, 0), hexPair(hex, 2), hexPair(hex, 4)];
      return { value: rgbToString(rgb[0], rgb[1], rgb[2], null), resolved: true };
    }
    if (/^[0-9a-f]{8}$/.test(hex)) {
      const rgb = [hexPair(hex, 0), hexPair(hex, 2), hexPair(hex, 4)];
      return { value: rgbToString(rgb[0], rgb[1], rgb[2], hexPair(hex, 6) / 255), resolved: true };
    }
    return { value: raw, resolved: false };
  }

  const functional = /^(rgba?|oklch|oklab|color|lab|lch|hsl|hsla)\(([^)]*)\)$/.exec(lower);
  if (!functional) return { value: raw, resolved: false };

  const name = functional[1];
  const body = functional[2];
  const parsed = parts(body);

  if (name === "rgb" || name === "rgba") {
    if (parsed.values.length < 3) return { value: raw, resolved: false };
    // Legacy comma-separated alpha, as in rgba(78, 155, 74, 0.5). This is
    // scoped to rgb() on purpose: color(srgb 1 0 0) also has four tokens, but
    // its fourth one is a channel, not an alpha.
    let alpha = parsed.alpha;
    if (alpha === null && parsed.tokens.length === 4) {
      const legacy = Number(parsed.tokens[3]);
      if (Number.isFinite(legacy)) alpha = legacy;
    }
    // Legacy percentages and modern "none" are both tolerated.
    const scale = (value: number, index: number) => {
      const token = parsed.tokens[index] ?? "";
      return token.endsWith("%") ? (value / 100) * 255 : value;
    };
    const rgb = parsed.values.slice(0, 3).map((value, index) => scale(value, index));
    return { value: rgbToString(rgb[0], rgb[1], rgb[2], alpha), resolved: true };
  }

  if (name === "oklch" || name === "lch") {
    if (parsed.values.length < 3) return { value: raw, resolved: false };
    const radians = (parsed.values[2] * Math.PI) / 180;
    const a = parsed.values[1] * Math.cos(radians);
    const b = parsed.values[1] * Math.sin(radians);
    return oklabToString(parsed.values[0], a, b, parsed.alpha, raw);
  }

  if (name === "oklab" || name === "lab") {
    if (parsed.values.length < 3) return { value: raw, resolved: false };
    return oklabToString(parsed.values[0], parsed.values[1], parsed.values[2], parsed.alpha, raw);
  }

  if (name === "color" && parsed.values.length >= 3) {
    // Only srgb is safe to treat as already-converted bytes.
    if (!/^srgb/.test(body.trim())) return { value: raw, resolved: false };
    const rgb = parsed.values.slice(0, 3).map((value) => value * 255);
    return { value: rgbToString(rgb[0], rgb[1], rgb[2], parsed.alpha), resolved: true };
  }

  // hsl() and anything else is passed through rather than guessed.
  return { value: raw, resolved: false };
}

/** Resolve a single palette entry, falling back to the original text. */
export function paintable(color: string): string {
  return resolveCssColor(color).value;
}

/** True when one entry resolved to paintable bytes. */
export function isPaintable(color: string): boolean {
  return resolveCssColor(color).resolved;
}

/** True when every entry resolved to paintable bytes. */
export function isPaintablePalette(colors: readonly string[]): boolean {
  return colors.every(isPaintable);
}
