import { describe, expect, it } from "vitest";

import { clipToRegion, layoutIntervals } from "./track-layout";

describe("clipToRegion", () => {
  it("clips to the visible window and drops disjoint intervals", () => {
    expect(clipToRegion({ start: 10, end: 30 }, { start: 20, end: 25 })).toEqual({ start: 20, end: 25 });
    expect(clipToRegion({ start: 10, end: 19 }, { start: 20, end: 25 })).toBeNull();
    expect(clipToRegion({ start: 20, end: 20 }, { start: 0, end: 100 })).toBeNull();
  });
});

describe("layoutIntervals", () => {
  it("keeps non-overlapping intervals on one row", () => {
    const result = layoutIntervals(
      [
        { id: "a", start: 0, end: 10 },
        { id: "b", start: 10, end: 20 },
      ],
      { start: 0, end: 100 },
      100,
      { gapPx: 0 },
    );
    expect(result.rowCount).toBe(1);
    expect(result.placed.map((p) => p.id)).toEqual(["a", "b"]);
  });

  it("pushes overlapping intervals onto separate rows", () => {
    const result = layoutIntervals(
      [
        { id: "a", start: 0, end: 50 },
        { id: "b", start: 10, end: 60 },
      ],
      { start: 0, end: 100 },
      100,
      { gapPx: 0 },
    );
    expect(result.rowCount).toBe(2);
    expect(result.placed.find((p) => p.id === "b")?.row).toBe(1);
  });

  it("maps base coordinates to screen x and clips off-screen intervals", () => {
    const result = layoutIntervals(
      [
        { id: "in", start: 25, end: 50 },
        { id: "out", start: 200, end: 300 },
      ],
      { start: 0, end: 100 },
      200,
    );
    expect(result.placed).toHaveLength(1);
    expect(result.placed[0].x).toBe(50);
    expect(result.placed[0].w).toBe(50);
  });

  it("returns an empty layout for degenerate regions and widths", () => {
    expect(layoutIntervals([], { start: 0, end: 0 }, 100).placed).toEqual([]);
    expect(layoutIntervals([{ id: "a", start: 0, end: 1 }], { start: 0, end: 10 }, 0).placed).toEqual([]);
  });
});
