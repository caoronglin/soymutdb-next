// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import {
  buildEnrichmentChartData,
  enrichmentAxisLabels,
  enrichmentBubbleRadius,
  enrichmentChartValue,
  enrichmentColor,
  enrichmentDescription,
  enrichmentEscapeHtml,
  enrichmentFormatP,
  enrichmentFormatSigned,
  enrichmentLogQ,
  enrichmentMaxSize,
  enrichmentTermLabel,
  enrichmentTooltipHtml,
  enrichmentTooltipText,
  enrichmentValueTableRow,
  sortEnrichmentRowsByQ,
  ENRICHMENT_DOWN_COLOR,
  ENRICHMENT_ORA_COLOR,
  ENRICHMENT_UP_COLOR,
  type EnrichmentChartRow,
  type EnrichmentChartValue,
} from "./tool-enrichment-mapping";

function row(over: Partial<EnrichmentChartRow> = {}): EnrichmentChartRow {
  return { id: "GO:1", name: "term", p: 0.01, q: 0.001, size: 4, ...over };
}

describe("enrichmentLogQ", () => {
  it("clamps to the ceiling at both ends", () => {
    // -log10(1) is -0; only the magnitude matters here.
    expect(enrichmentLogQ(1)).toBeCloseTo(0, 10);
    expect(enrichmentLogQ(1e-10)).toBe(10);
  });

  it("renders an underflowed q at the ceiling instead of Infinity", () => {
    expect(enrichmentLogQ(0)).toBe(10);
    expect(enrichmentLogQ(-1)).toBe(10);
    expect(Number.isFinite(enrichmentLogQ(0))).toBe(true);
  });

  it("is the plain -log10 in between", () => {
    expect(enrichmentLogQ(0.01)).toBeCloseTo(2, 10);
  });
});

describe("enrichmentTermLabel", () => {
  it("falls back to the id when the name is empty", () => {
    expect(enrichmentTermLabel("", "GO:7")).toBe("GO:7");
  });

  it("truncates past 40 characters and keeps the ellipsis", () => {
    const long = "x".repeat(41);
    expect(enrichmentTermLabel(long, "GO:7")).toBe(`${"x".repeat(40)}…`);
    expect(enrichmentTermLabel("x".repeat(40), "GO:7")).toBe("x".repeat(40));
  });
});

describe("sorting and axis order", () => {
  const rows = [row({ id: "b", q: 0.5 }), row({ id: "a", q: 0.001 }), row({ id: "c", q: 0.1 })];

  it("sorts ascending by q without mutating the input", () => {
    const input = [...rows];
    expect(sortEnrichmentRowsByQ(input).map((r) => r.id)).toEqual(["a", "c", "b"]);
    expect(input.map((r) => r.id)).toEqual(["b", "a", "c"]);
  });

  it("reverses the sorted labels because the axis is inverted", () => {
    expect(enrichmentAxisLabels(rows)).toEqual(["term", "term", "term"]);
    expect(enrichmentAxisLabels([row({ id: "a", q: 0.001 }), row({ id: "b", q: 0.5 })])).toEqual([
      "term",
      "term",
    ]);
  });

  it("uses the truncated label on the axis, not the full name", () => {
    const long = "y".repeat(50);
    expect(enrichmentAxisLabels([row({ name: long })])).toEqual([`${"y".repeat(40)}…`]);
  });

  it("produces axis labels that exactly match the plotted point labels", () => {
    const mixed = [row({ id: "a", name: "alpha", q: 0.2 }), row({ id: "b", name: "", q: 0.0001 })];
    const plotted = new Set(buildEnrichmentChartData(mixed, { isGsea: false }).map((d) => d.label));
    for (const label of enrichmentAxisLabels(mixed)) expect(plotted.has(label)).toBe(true);
  });
});

describe("enrichmentBubbleRadius", () => {
  it("is 8 + 16 * sqrt(size / maxSize), not a linear ratio", () => {
    expect(enrichmentBubbleRadius(16, 16)).toBe(24);
    expect(enrichmentBubbleRadius(4, 16)).toBe(16);
    expect(enrichmentBubbleRadius(1, 16)).toBe(8 + 16 * Math.sqrt(1 / 16));
  });

  it("differs from a linear size channel", () => {
    // 8 + 16 * (4/16) would be 12; the sqrt semantics give 16.
    expect(enrichmentBubbleRadius(4, 16)).not.toBe(8 + 16 * (4 / 16));
  });

  it("keeps the ratio finite for an empty term list", () => {
    expect(enrichmentMaxSize([])).toBe(1);
  });
});

describe("enrichmentColor", () => {
  it("uses one flat colour in ORA mode", () => {
    expect(enrichmentColor(row({ es: -2 }), false)).toBe(ENRICHMENT_ORA_COLOR);
    expect(enrichmentColor(row({ es: 2 }), false)).toBe(ENRICHMENT_ORA_COLOR);
  });

  it("splits GSEA terms on the sign of ES", () => {
    expect(enrichmentColor(row({ es: -0.1 }), true)).toBe(ENRICHMENT_DOWN_COLOR);
    expect(enrichmentColor(row({ es: 0.1 }), true)).toBe(ENRICHMENT_UP_COLOR);
    expect(enrichmentColor(row({ es: 0 }), true)).toBe(ENRICHMENT_UP_COLOR);
    expect(enrichmentColor(row({}), true)).toBe(ENRICHMENT_UP_COLOR);
  });
});

describe("enrichmentTooltipHtml", () => {
  const value = enrichmentChartValue({
    logQ: 2.5,
    label: "term",
    size: 12,
    fullName: "term",
    q: 0.003162,
    p: 0.0004,
    es: -1.234,
    nes: null,
    radius: 20,
    color: ENRICHMENT_DOWN_COLOR,
  });

  it("renders two lines in ORA mode and never mentions ES", () => {
    const html = enrichmentTooltipHtml(value, false);
    expect(html).toContain("-log10(q): <b>2.50</b>");
    expect(html).toContain("q: <b>0.0032</b>");
    expect(html).toContain("p: <b>4.00e-4</b>");
    expect(html).toContain("size: <b>12</b>");
    expect(html).not.toContain("ES:");
  });

  it("adds the GSEA line and keeps NES as an en dash", () => {
    const html = enrichmentTooltipHtml(value, true);
    expect(html).toContain("ES: <b>-1.234</b>");
    expect(html).toContain("NES: <b>–</b>");
  });

  it("escapes markup in the term name", () => {
    const hostile = enrichmentChartValue({
      logQ: 1,
      label: "l",
      size: 1,
      fullName: '<img src=x onerror="alert(1)">&',
      q: 0.1,
      p: 0.2,
      es: null,
      nes: null,
      radius: 9,
      color: ENRICHMENT_ORA_COLOR,
    });
    const html = enrichmentTooltipHtml(hostile, false);
    expect(html).toContain("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&amp;");
    expect(html).not.toContain("<img");
  });

  it("escapes ampersands before angle brackets", () => {
    expect(enrichmentEscapeHtml("&lt;")).toBe("&amp;lt;");
  });
});

describe("enrichmentTooltipText", () => {
  const tuple: EnrichmentChartValue = [
    2.5,
    "term",
    12,
    "term",
    0.003162,
    0.0004,
    -1.234,
    null,
  ];

  it("reports the same facts as the HTML tooltip, with no markup of ours", () => {
    expect(enrichmentTooltipText(tuple, false)).toBe(
      "term\n-log10(q): 2.50 · q: 0.0032 · p: 4.00e-4 · size: 12",
    );
    expect(enrichmentTooltipText(tuple, true)).toContain("ES: -1.234 · NES: –");
  });

  it("escapes the term name rather than trusting it", () => {
    const hostile: EnrichmentChartValue = [1, "l", 1, '<b>x</b>"y"', 0.1, 0.2, null, null];
    const text = enrichmentTooltipText(hostile, false);
    expect(text.startsWith("&lt;b&gt;x&lt;/b&gt;&quot;y&quot;\n")).toBe(true);
    expect(text).not.toContain("<b>");
  });
});

describe("formatting helpers", () => {
  it("formats p-values the way the results table does", () => {
    expect(enrichmentFormatP(0)).toBe("0");
    expect(enrichmentFormatP(0.00001)).toBe("1.00e-5");
    expect(enrichmentFormatP(0.5)).toBe("0.5000");
  });

  it("signs enrichment scores and dashes the missing ones", () => {
    expect(enrichmentFormatSigned(1.5)).toBe("+1.500");
    expect(enrichmentFormatSigned(-1.5)).toBe("-1.500");
    expect(enrichmentFormatSigned(undefined)).toBe("–");
    expect(enrichmentFormatSigned(Number.NaN)).toBe("–");
  });
});

describe("buildEnrichmentChartData", () => {
  it("carries the 8-tuple in its documented order", () => {
    const [value] = buildEnrichmentChartData([row({ q: 0.01, p: 0.02, size: 9, es: 1 })], {
      isGsea: true,
    });
    const tuple = enrichmentChartValue(value);
    expect(tuple).toHaveLength(8);
    expect(tuple[0]).toBeCloseTo(2, 10);
    expect(tuple[2]).toBe(9);
    expect(tuple[3]).toBe("term");
    expect(tuple[4]).toBe(0.01);
    expect(tuple[5]).toBe(0.02);
    expect(tuple[6]).toBe(1);
    expect(tuple[7]).toBeNull();
  });

  it("sorts the plotted data most-significant first", () => {
    const data = buildEnrichmentChartData([row({ id: "x", q: 0.4 }), row({ id: "y", q: 0 })], {
      isGsea: false,
    });
    expect(data.map((d) => d.logQ)).toEqual([10, enrichmentLogQ(0.4)]);
  });

  it("keeps the full name while the axis label stays truncated", () => {
    const long = "z".repeat(60);
    const [datum] = buildEnrichmentChartData([row({ name: long })], { isGsea: false });
    expect(datum.fullName).toBe(long);
    expect(datum.label).toBe(`${"z".repeat(40)}…`);
  });
});

describe("accessibility text", () => {
  it("summarises every term with its clamped score and size", () => {
    expect(
      enrichmentDescription([row({ name: "alpha", q: 0.01, size: 3 }), row({ name: "", id: "GO:9", q: 0 })]),
    ).toBe("alpha 2.00 3, GO:9 10.00 4");
  });

  it("tabulates the exact values with no rounding surprise", () => {
    const [datum] = buildEnrichmentChartData([row({ q: 0.001, p: 0.02, size: 7 })], { isGsea: false });
    expect(enrichmentValueTableRow(datum)).toEqual(["term", "3.00", "0.0010", "0.0200", "7"]);
  });
});
