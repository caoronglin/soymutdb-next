// @vitest-environment node
/**
 * The bubble radius, checked against the real runtime.
 *
 * The chart's own contract says the size scale is [min, max] and the runtime
 * computes min + (max - min) * ratio. Asserting our definition against a
 * hand-written copy of that formula proves nothing, so this suite calls the
 * shared `buildChartOptions` and then the `style.r` callback it actually
 * returns, at the domain minimum, the maximum and a midpoint.
 *
 * No chart is drawn here and no canvas exists; this is option construction,
 * which is the part the consumer owns.
 */
import { describe, expect, it } from "vitest";

import { resolveChartTheme } from "@soymutdb/charts";
// Deep import on purpose: buildChartOptions is the function under test and the
// package's public entry deliberately does not re-export engine-facing code.
import { buildChartOptions } from "../../../../../packages/charts/src/g2-runtime";

import { buildEnrichmentCanvasData, buildEnrichmentChartDefinition } from "./tool-chart-definitions";
import { enrichmentBubbleRadius, type EnrichmentChartRow } from "./tool-enrichment-mapping";

const rows: EnrichmentChartRow[] = [
  { id: "GO:1", name: "small", p: 0.01, q: 0.25, size: 1 },
  { id: "GO:2", name: "middle", p: 0.01, q: 0.01, size: 11 },
  { id: "GO:3", name: "largest", p: 0.01, q: 1e-10, size: 16 },
];

/** Build the real options and return the runtime's own radius callback. */
function radiusCallback(): (datum: Record<string, unknown>) => number {
  const options = buildChartOptions({
    definition: buildEnrichmentChartDefinition(rows, { isGsea: false, view: "bubble" }),
    data: buildEnrichmentCanvasData(rows, { isGsea: false }) as unknown as Array<Record<string, unknown>>,
    theme: resolveChartTheme(),
    animate: false,
  });
  const style = options.style as { r?: (datum: Record<string, unknown>) => number };
  if (typeof style?.r !== "function") throw new Error("the runtime did not build a radius callback");
  return style.r;
}

describe("bubble radius, through the real buildChartOptions", () => {
  it("gives the domain minimum 8 and the largest term 24", () => {
    const radius = radiusCallback();
    // The scale domain starts at 0, so 8 is the radius at 0 and at any
    // missing value; a term of size 1 sits a quarter of the way in.
    expect(radius({ size: 0 })).toBeCloseTo(8, 6);
    expect(radius({ size: 1 })).toBeCloseTo(8 + 16 * Math.sqrt(1 / 16), 6);
    expect(radius({ size: 16 })).toBeCloseTo(24, 6);
  });

  it("interpolates by sqrt in the middle, not linearly", () => {
    const radius = radiusCallback();
    expect(radius({ size: 11 })).toBeCloseTo(enrichmentBubbleRadius(11, 16), 6);
    // A linear size channel would put the midpoint at 8 + 16 * 11/16 = 19.
    expect(radius({ size: 11 })).not.toBeCloseTo(19, 1);
    expect(radius({ size: 11 })).toBeCloseTo(8 + 16 * Math.sqrt(11 / 16), 6);
  });

  it("floors a missing or non-numeric size at the minimum radius", () => {
    const radius = radiusCallback();
    expect(radius({ size: Number.NaN })).toBe(8);
    expect(radius({})).toBe(8);
  });

  it("matches the mapping's own radius for every row", () => {
    const radius = radiusCallback();
    for (const datum of buildEnrichmentCanvasData(rows, { isGsea: false })) {
      expect(radius(datum)).toBeCloseTo(datum.radius, 6);
    }
  });
});
