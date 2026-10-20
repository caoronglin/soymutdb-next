/**
 * The portal declares its chart palette in oklch. A canvas cannot paint oklch
 * text, so these conversions are load-bearing, not cosmetic: if they regress,
 * charts silently render in a fallback color.
 */
import { describe, expect, it } from "vitest";

import { isPaintable, isPaintablePalette, paintable, resolveCssColor } from "./color";
import { FALLBACK_CATEGORICAL_PALETTE, resolveChartTheme } from "./theme";

describe("resolveCssColor", () => {
  it("converts hex forms to paintable hex or rgba", () => {
    expect(resolveCssColor("#4e9b4a")).toEqual({ value: "#4e9b4a", resolved: true });
    expect(resolveCssColor("#abc")).toEqual({ value: "#aabbcc", resolved: true });
    expect(resolveCssColor("#4e9b4a80").value).toBe("rgba(78, 155, 74, 0.502)");
  });

  it("converts the oklch palette the portal actually ships", () => {
    // --chart-1 is oklch(0.55 0.14 152) in apps/web/src/style.css.
    const result = resolveCssColor("oklch(0.55 0.14 152)");
    expect(result.resolved).toBe(true);
    expect(result.value).toMatch(/^#[0-9a-f]{6}$/);
    const r = parseInt(result.value.slice(1, 3), 16);
    const g = parseInt(result.value.slice(3, 5), 16);
    const b = parseInt(result.value.slice(5, 7), 16);
    // It must be a green, not black. A black chart is exactly the failure this
    // conversion exists to prevent.
    expect(g).toBeGreaterThan(r);
    expect(g).toBeGreaterThan(b);
  });

  it("converts oklab and color(srgb ...)", () => {
    expect(resolveCssColor("oklab(0.5 0 -0.02)").resolved).toBe(true);
    expect(resolveCssColor("color(srgb 1 0 0)")).toEqual({ value: "#ff0000", resolved: true });
  });

  it("handles rgb() in legacy and modern syntax", () => {
    expect(resolveCssColor("rgb(78, 155, 74)")).toEqual({ value: "#4e9b4a", resolved: true });
    expect(resolveCssColor("rgba(78, 155, 74, 0.5)").value).toBe("rgba(78, 155, 74, 0.5)");
    // 10%/50%/25% of 255 rounds to 26/128/64.
    expect(resolveCssColor("rgb(10% 50% 25%)").value).toBe("#1a8040");
  });

  it("marks unknown syntax as unresolved instead of guessing", () => {
    expect(resolveCssColor("hsl(120 50% 50%)").resolved).toBe(false);
    expect(resolveCssColor("color(display-p3 1 0 0)").resolved).toBe(false);
    expect(resolveCssColor("not-a-color").resolved).toBe(false);
    expect(resolveCssColor("").resolved).toBe(false);
  });

  it("converts the alpha channel of oklch", () => {
    expect(resolveCssColor("oklch(0.55 0.14 152 / 0.25)").value).toMatch(/^rgba\(/);
  });
});

describe("theme bridge color handling", () => {
  it("converts an explicitly supplied oklch palette to paintable colors", () => {
    const theme = resolveChartTheme({ palette: ["oklch(0.55 0.14 152)", "oklch(0.7 0.1 150)"] });
    expect(isPaintablePalette(theme.categorical)).toBe(true);
    expect(theme.unresolvedColors).toEqual([]);
  });

  it("leaves an already-paintable palette untouched", () => {
    const theme = resolveChartTheme({ palette: ["#2f855a", "#75a987"] });
    expect(theme.categorical).toEqual(["#2f855a", "#75a987"]);
  });

  it("falls back to the historical hex colors when nothing is supplied", () => {
    const theme = resolveChartTheme({});
    expect(theme.categorical).toEqual([...FALLBACK_CATEGORICAL_PALETTE]);
    expect(isPaintablePalette(theme.categorical)).toBe(true);
  });

  it("reports a color it could not resolve rather than swallowing it", () => {
    const theme = resolveChartTheme({ palette: ["hsl(120 50% 50%)"] });
    expect(theme.unresolvedColors.length).toBeGreaterThan(0);
    expect(isPaintable("hsl(120 50% 50%)")).toBe(false);
  });

  it("paints through paintable()", () => {
    expect(paintable("oklch(0.55 0.14 152)")).toMatch(/^#/);
  });
});
