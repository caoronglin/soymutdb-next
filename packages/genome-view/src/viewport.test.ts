import { describe, expect, it } from "vitest";

import {
  bpPerPx,
  bpToPx,
  createViewport,
  gotoViewport,
  panViewport,
  viewportKey,
  zoomViewport,
} from "./viewport";

const region = { assemblyKey: "Gmax_880_v6.0", refName: "Gm01", start: 1000, end: 2000 };

describe("createViewport", () => {
  it("normalises the initial region", () => {
    expect(createViewport(region)).toEqual({
      assemblyKey: "Gmax_880_v6.0",
      refName: "Gm01",
      start: 1000,
      end: 2000,
    });
  });

  it("never yields a zero-width window", () => {
    const viewport = createViewport({ ...region, start: 500, end: 500 });
    expect(viewport.end).toBeGreaterThan(viewport.start);
  });

  it("rejects non-finite coordinates", () => {
    const viewport = createViewport({ ...region, start: Number.NaN, end: Number.NaN });
    expect(viewport.start).toBe(0);
    expect(viewport.end).toBeGreaterThan(0);
  });
});

describe("panViewport", () => {
  it("keeps the span and clamps the start at zero", () => {
    const panned = panViewport(createViewport(region), -5000);
    expect(panned.start).toBe(0);
    expect(panned.end).toBe(1000);
  });

  it("returns the same value for a non-finite delta", () => {
    const viewport = createViewport(region);
    expect(panViewport(viewport, Number.NaN)).toBe(viewport);
  });
});

describe("zoomViewport", () => {
  it("scales the span about the centre by default", () => {
    const zoomed = zoomViewport(createViewport(region), 0.5);
    expect(zoomed.end - zoomed.start).toBe(500);
    expect(zoomed.start).toBe(1250);
  });

  it("holds an explicit anchor fixed", () => {
    const zoomed = zoomViewport(createViewport(region), 0.5, 1000);
    expect(zoomed.start).toBe(1000);
    expect(zoomed.end).toBe(1500);
  });

  it("ignores a non-positive factor", () => {
    const viewport = createViewport(region);
    expect(zoomViewport(viewport, 0)).toBe(viewport);
  });
});

describe("gotoViewport", () => {
  it("normalises reversed ends", () => {
    const moved = gotoViewport(createViewport(region), "Gm02", 5000, 3000);
    expect(moved.refName).toBe("Gm02");
    expect(moved.start).toBe(3000);
    expect(moved.end).toBe(5000);
  });
});

describe("scale helpers", () => {
  it("derives base pairs per pixel", () => {
    expect(bpPerPx(createViewport(region), 1000)).toBe(1);
    expect(bpPerPx(createViewport(region), 0)).toBe(0);
  });

  it("maps a base pair onto the track", () => {
    expect(bpToPx(createViewport(region), 1500, 1000)).toBe(500);
    expect(bpToPx(createViewport(region), 1500, 0)).toBe(0);
  });
});

describe("viewportKey", () => {
  it("is stable and window-specific", () => {
    const viewport = createViewport(region);
    expect(viewportKey(viewport)).toBe("Gmax_880_v6.0:Gm01:1000-2000");
    expect(viewportKey(zoomViewport(viewport, 0.5))).not.toBe(viewportKey(viewport));
  });
});
