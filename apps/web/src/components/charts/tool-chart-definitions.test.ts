// @vitest-environment jsdom
/**
 * Guards the adapter draft against the two ways it could go wrong: inventing a
 * field the shared package cannot honour, and drifting from the mapping the
 * charts already render. Five assertions, no engine involved.
 */
import { describe, expect, it } from "vitest";

import {
  buildEnrichmentCanvasData,
  buildEnrichmentChartDefinition,
  buildExpPatternCanvasData,
  buildExpPatternChartDefinition,
  enrichmentCanvasTooltipFormatter,
  enrichmentCanvasAxisDomain,
  expPatternCanvasTooltipFormatter,
  type EnrichmentCanvasDatum,
} from "./tool-chart-definitions";
import type { EnrichmentChartRow } from "./tool-enrichment-mapping";

/** Every key ChartDefinition declares today. */
const CONTRACT_KEYS = [
  "animate",
  "axisLabels",
  "categoryDomain",
  "categoryOrder",
  "cellLabels",
  "centerText",
  "color",
  "colorDomain",
  "colorRange",
  "gradient",
  "innerRadius",
  "kind",
  "legend",
  "orientation",
  "padding",
  "palette",
  "pointsStyle",
  "seriesGradients",
  "seriesStyle",
  "showPoints",
  "size",
  "sizeDomain",
  "sizeRange",
  "sizeTransform",
  "splitArea",
  "stack",
  "tooltip",
  "valueFormat",
  "x",
  "xAxis",
  "y",
  "yAxis",
];

const rows: EnrichmentChartRow[] = [
  { id: "GO:1", name: "binding", p: 1e-5, q: 1e-10, size: 40, es: -1.5 },
  { id: "GO:2", name: "membrane part", p: 0.02, q: 0.5, size: 4 },
];

const matrix = {
  genes: ["g1", "g2"],
  conditions: ["c1", "c2"],
  matrix: [
    [1.5, null],
    [-0.5, 2.25],
  ],
  value_range: [-0.5, 2.25] as [number, number],
  scale: "zscore" as const,
};

describe("definition candidates", () => {
  it("use only fields the shared contract declares, and stay serializable", () => {
    for (const definition of [
      buildEnrichmentChartDefinition(rows, { isGsea: true, view: "bubble" }),
      buildEnrichmentChartDefinition(rows, { isGsea: false, view: "bar" }),
      buildExpPatternChartDefinition(matrix),
    ]) {
      for (const key of Object.keys(definition)) {
        expect(CONTRACT_KEYS).toContain(key);
      }
      expect(JSON.parse(JSON.stringify(definition))).toEqual(definition);
    }
  });

  it("pin the category domain the axis and the points share", () => {
    const definition = buildEnrichmentChartDefinition(rows, { isGsea: true, view: "bar" });
    const labels = buildEnrichmentCanvasData(rows, { isGsea: true }).map((d) => d.termLabel);
    // The y axis takes its domain from the row order, so the order is the
    // contract -- `enrichmentCanvasAxisDomain` is what the rows must follow.
    expect(labels).toEqual(enrichmentCanvasAxisDomain(rows));
    expect(definition.yAxis).toMatchObject({ scale: "category", reverse: true });
    expect(buildExpPatternChartDefinition(matrix).categoryDomain).toEqual(["c1", "c2"]);
  });

  it("carry the same numbers the mapping already computes", () => {
    // Axis order puts the most significant term last, at the bottom.
    const last = buildEnrichmentCanvasData(rows, { isGsea: true }).at(-1)!;
    expect(last.logQ).toBe(10);
    expect(last.radius).toBe(24);
    expect(last.color).toBe("var(--impact-low)");
    expect(buildEnrichmentCanvasData(rows, { isGsea: false }).every((d) => d.color === "var(--chart-2)")).toBe(true);
    expect(buildExpPatternCanvasData(matrix).map((cell) => cell.value)).toEqual([1.5, -0.5, 2.25]);
  });

  it("pairs each colour with its own term when the caller's order differs", () => {
    // Unsorted input: GO:2 first, most significant term last.
    const [first] = buildEnrichmentCanvasData(rows, { isGsea: true });
    const byTerm = new Map(buildEnrichmentCanvasData(rows, { isGsea: true }).map((d) => [d.term, d.color]));
    expect(byTerm.get("binding")).toBe("var(--impact-low)");
    expect(byTerm.get("membrane part")).toBe("var(--chart-1)");
    expect(first.color).toBe("var(--chart-1)");
  });
});

describe("shared tooltip formatters", () => {
  it("return escaped text, never the legacy HTML", () => {
    const hostile = { ...rows[0], name: '<img src=x onerror="a">' };
    const [datum] = buildEnrichmentCanvasData([hostile], { isGsea: true });
    const enrichment = enrichmentCanvasTooltipFormatter(true)({
      datum: datum as unknown as Record<string, unknown>,
      definition: buildEnrichmentChartDefinition([hostile], { isGsea: true, view: "bubble" }),
    });
    expect(enrichment).not.toContain("<img");
    expect(enrichment).not.toContain("<b>");
    expect(enrichment.startsWith("&lt;img")).toBe(true);

    const cell = { ...buildExpPatternCanvasData(matrix)[0], condition: "<b>c</b>" };
    const heatmap = expPatternCanvasTooltipFormatter({
      datum: cell as unknown as Record<string, unknown>,
      definition: buildExpPatternChartDefinition(matrix),
    });
    expect(heatmap).toBe("g1 · &lt;b&gt;c&lt;/b&gt; · 1.50");
  });

  it("tolerate a datum that is missing the optional fields", () => {
    const html = enrichmentCanvasTooltipFormatter(false)({
      datum: {} as Partial<EnrichmentCanvasDatum> as Record<string, unknown>,
      definition: buildEnrichmentChartDefinition(rows, { isGsea: false, view: "bar" }),
    });
    expect(html.startsWith("\n")).toBe(true);
  });
});
