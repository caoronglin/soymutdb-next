import { describe, expect, it } from "vitest";

import { computeTicks, formatBp, niceStep } from "./ruler";

describe("ruler math", () => {
  it("picks nice 1/2/5 x 10^n steps", () => {
    expect(niceStep(1)).toBe(1);
    expect(niceStep(1.2)).toBe(2);
    expect(niceStep(3)).toBe(5);
    expect(niceStep(6)).toBe(10);
    expect(niceStep(0)).toBe(1);
  });

  it("formats base positions with deterministic grouping", () => {
    expect(formatBp(1)).toBe("1");
    expect(formatBp(1000)).toBe("1,000");
    expect(formatBp(1234567)).toBe("1,234,567");
  });

  it("emits increasing ticks within the region", () => {
    const ticks = computeTicks({ start: 0, end: 1000 }, 800, 80);
    expect(ticks.length).toBeGreaterThan(0);
    for (let i = 1; i < ticks.length; i += 1) {
      expect(ticks[i].bp).toBeGreaterThan(ticks[i - 1].bp);
      expect(ticks[i].x).toBeGreaterThan(ticks[i - 1].x);
    }
    expect(ticks[0].bp).toBeGreaterThanOrEqual(0);
    expect(ticks[ticks.length - 1].bp).toBeLessThanOrEqual(1000);
  });

  it("returns no ticks for degenerate inputs", () => {
    expect(computeTicks({ start: 0, end: 0 }, 800)).toEqual([]);
    expect(computeTicks({ start: 0, end: 100 }, 0)).toEqual([]);
  });
});
