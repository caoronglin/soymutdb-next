// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import {
  buildExpPatternCells,
  expPatternCellTuple,
  expPatternColorRange,
  expPatternDescription,
  expPatternHasData,
  expPatternLabelRotation,
  expPatternShowsCellLabels,
  expPatternTooltipHtml,
  expPatternTooltipText,
  expPatternValueDomain,
  expPatternValueTableRow,
  fmtExpPatternValue,
  type ExpPatternMatrix,
} from "./tool-exppattern-mapping";
import { escapeChartText } from "./tool-chart-text";

function matrix(over: Partial<ExpPatternMatrix> = {}): ExpPatternMatrix {
  return {
    genes: ["g1", "g2"],
    conditions: ["c1", "c2"],
    matrix: [
      [1, 2],
      [3, 4],
    ],
    value_range: [1, 4],
    scale: "zscore",
    ...over,
  };
}

describe("buildExpPatternCells", () => {
  it("emits [conditionIndex, geneIndex, value] in row-major order", () => {
    const cells = buildExpPatternCells(matrix());
    expect(cells.map(expPatternCellTuple)).toEqual([
      [0, 0, 1],
      [1, 0, 2],
      [0, 1, 3],
      [1, 1, 4],
    ]);
  });

  it("skips missing, undefined and NaN cells instead of plotting them as zero", () => {
    const cells = buildExpPatternCells(
      matrix({
        matrix: [
          [null, 2],
          [Number.NaN, undefined as unknown as number],
        ],
      }),
    );
    expect(cells.map(expPatternCellTuple)).toEqual([[1, 0, 2]]);
  });

  it("carries the gene and condition names with the indices", () => {
    const [cell] = buildExpPatternCells(matrix());
    expect(cell.gene).toBe("g1");
    expect(cell.condition).toBe("c1");
  });

  it("returns nothing for an all-null matrix", () => {
    expect(buildExpPatternCells(matrix({ matrix: [[null, null], [null, null]] }))).toEqual([]);
  });
});

describe("expPatternValueDomain", () => {
  it("uses the response value_range as the colour domain", () => {
    expect(expPatternValueDomain(matrix({ value_range: [-2.5, 3] }))).toEqual({ min: -2.5, max: 3 });
  });

  it("falls back to 0/1 per bound rather than collapsing the scale", () => {
    expect(expPatternValueDomain(matrix({ value_range: [null, null] }))).toEqual({ min: 0, max: 1 });
    expect(expPatternValueDomain(matrix({ value_range: [null, 7] }))).toEqual({ min: 0, max: 7 });
  });
});

describe("expPatternColorRange", () => {
  it("diverges through the neutral midpoint for z-scores", () => {
    expect(expPatternColorRange("zscore")).toEqual(["var(--impact-low)", "#F6F8F6", "var(--chart-1)"]);
  });

  it("stays on the ordered green ramp for raw FPKM", () => {
    expect(expPatternColorRange("none")).toEqual(["var(--chart-5)", "var(--chart-3)", "var(--chart-1)"]);
  });

  it("keeps the two scales distinguishable", () => {
    expect(expPatternColorRange("zscore")).not.toEqual(expPatternColorRange("none"));
  });
});

describe("labels", () => {
  it("draws cell labels up to 50 cells and stops there", () => {
    const make = (count: number) =>
      buildExpPatternCells(
        matrix({
          genes: Array.from({ length: 10 }, (_, i) => `g${i}`),
          conditions: Array.from({ length: 10 }, (_, i) => `c${i}`),
          matrix: Array.from({ length: 10 }, (_, i) => Array.from({ length: 10 }, (_, j) => i + j)),
        }),
      ).slice(0, count);
    expect(expPatternShowsCellLabels(make(50))).toBe(true);
    expect(expPatternShowsCellLabels(make(51))).toBe(false);
  });

  it("rotates condition labels only past six columns", () => {
    expect(expPatternLabelRotation(6)).toBe(0);
    expect(expPatternLabelRotation(7)).toBe(45);
  });
});

describe("expPatternHasData", () => {
  it("needs both a condition and one non-null measurement", () => {
    expect(expPatternHasData(matrix())).toBe(true);
    expect(expPatternHasData(matrix({ conditions: [] }))).toBe(false);
    expect(expPatternHasData(matrix({ matrix: [[null, null], [null, null]] }))).toBe(false);
  });
});

describe("tooltips and tables", () => {
  const [cell] = buildExpPatternCells(matrix());

  it("renders gene, condition and the value at two decimals", () => {
    expect(expPatternTooltipHtml({ ...cell, value: 1.005 })).toBe("g1<br/>c1<br/><strong>1.00</strong>");
  });

  it("renders the shared-facade tooltip as escaped text with no markup of ours", () => {
    expect(expPatternTooltipText(cell)).toBe("g1 · c1 · 1.00");
    const hostile = expPatternTooltipText({ ...cell, gene: "<img src=x>", condition: "a&b" });
    expect(hostile).toBe("&lt;img src=x&gt; · a&amp;b · 1.00");
    expect(hostile).not.toContain("<img");
  });

  it("escapes every character that can start markup or break an attribute", () => {
    expect(escapeChartText(`&<>"'`)).toBe("&amp;&lt;&gt;&quot;&#39;");
  });

  it("dashes a missing measurement in the shared value format", () => {
    expect(fmtExpPatternValue(null)).toBe("—");
    expect(fmtExpPatternValue(Number.NaN)).toBe("—");
    expect(fmtExpPatternValue(2)).toBe("2.00");
    expect(fmtExpPatternValue(-0.5)).toBe("-0.50");
  });

  it("tabulates the exact value", () => {
    expect(expPatternValueTableRow(cell)).toEqual(["g1", "c1", "1.00"]);
  });

  it("describes the grid shape and its domain for assistive tech", () => {
    expect(expPatternDescription(matrix({ value_range: [-2, 3] }))).toBe(
      "2 genes x 2 conditions, values -2.00 to 3.00.",
    );
  });
});
