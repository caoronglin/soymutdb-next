import { describe, expect, it } from "vitest";
import {
  formatLocus,
  parseDeepLink,
  parseLocus,
  toOneBased,
  toZeroBased,
} from "../../../../apps/jbrowse/src/deep-link";

describe("ablation scenario 11: deep-link coordinate conversion", () => {
  it("round-trips 1-based inclusive <-> 0-based half-open intervals", () => {
    for (const [start, end] of [
      [1, 1],
      [1, 1000],
      [10, 20],
      [500, 500],
      [1, 1000000],
    ]) {
      expect(toZeroBased(start, end)).toEqual([start - 1, end]);
      expect(toOneBased(...toZeroBased(start, end))).toEqual([start, end]);
    }

    expect(toZeroBased(1, 1000)).toEqual([0, 1000]);
    expect(toOneBased(0, 1000)).toEqual([1, 1000]);

    expect(formatLocus(parseLocus("chr01:1..1000")!)).toBe("chr01:1-1000");
    expect(parseLocus("chr01:1,000-1,000,000")).toEqual({
      refName: "chr01",
      start: 1000,
      end: 1000000,
    });
    expect(parseDeepLink("?locus=chr01:1-1000&assembly=v4&release=v4.0")).toEqual({
      locus: "chr01:1-1000",
      assembly: "v4",
      release: "v4.0",
    });
  });
});
