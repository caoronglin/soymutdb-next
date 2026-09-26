import { describe, expect, it } from "vitest";

import { InvalidCoordinateError } from "./index";
import {
  DEFAULT_MIN_BP,
  bpPerPx,
  clampViewport,
  clipInterval,
  panViewport,
  ticksFor,
  toBp,
  toScreenX,
  viewportSpan,
  zoomViewport,
  type Viewport,
} from "./viewport";

const bounds = { start: 1, end: 1000 };
const v = (start: number, end: number): Viewport => ({
  assemblyKey: "v4",
  refName: "chr01",
  start,
  end,
});

describe("viewport math", () => {
  it("measures inclusive span", () => {
    expect(viewportSpan(v(10, 10))).toBe(1);
    expect(viewportSpan(v(10, 20))).toBe(11);
  });

  it("rejects malformed viewports and widths", () => {
    expect(() => viewportSpan(v(20, 10))).toThrow(InvalidCoordinateError);
    expect(() => bpPerPx(v(1, 100), 0)).toThrow(InvalidCoordinateError);
    expect(() => toBp(0, v(1, 100), -1)).toThrow(InvalidCoordinateError);
  });

  it("clamps inside bounds while keeping width", () => {
    expect(clampViewport(v(900, 1100), bounds)).toEqual({
      assemblyKey: "v4",
      refName: "chr01",
      start: 800,
      end: 1000,
    });
  });

  it("enforces the minimum width, capped by the bounds span", () => {
    const clamped = clampViewport(v(10, 20), bounds);
    expect(viewportSpan(clamped)).toBe(DEFAULT_MIN_BP);
    const tiny = clampViewport(v(10, 20), { start: 1, end: 10 });
    expect(viewportSpan(tiny)).toBe(10);
  });

  it("zooms out around the centre and in around an anchor", () => {
    const out = zoomViewport(v(1, 100), 2);
    expect(viewportSpan(out)).toBe(200);
    const zoomedIn = zoomViewport(v(1, 100), 0.5, 50);
    expect(viewportSpan(zoomedIn)).toBe(50);
    expect(zoomedIn.start).toBeLessThanOrEqual(50);
    expect(zoomedIn.end).toBeGreaterThanOrEqual(50);
  });

  it("respects the min width and bounds on zoom", () => {
    const zoomed = zoomViewport(v(1, 50), 0.01, 25, bounds);
    expect(viewportSpan(zoomed)).toBe(DEFAULT_MIN_BP);
    const wide = zoomViewport(v(1, 100), 100, 500, { start: 1, end: 300 });
    expect(viewportSpan(wide)).toBe(300);
  });

  it("pans and clamps to bounds", () => {
    expect(panViewport(v(100, 200), 50)).toMatchObject({ start: 150, end: 250 });
    expect(panViewport(v(900, 1000), 500, bounds)).toMatchObject({ start: 900, end: 1000 });
    expect(panViewport(v(100, 200), -500).start).toBe(1);
  });

  it("converts between base positions and screen x", () => {
    expect(bpPerPx(v(1, 100), 100)).toBe(1);
    expect(toScreenX(1, v(1, 100), 100)).toBe(0);
    expect(toScreenX(101, v(1, 100), 100)).toBe(100);
    expect(toBp(0, v(1, 100), 100)).toBe(1);
    expect(toBp(50, v(1, 100), 100)).toBe(51);
    expect(toBp(999, v(1, 100), 100)).toBe(100);
  });

  it("clips intervals and rejects disjoint ones", () => {
    expect(clipInterval({ start: 10, end: 30 }, v(20, 25))).toEqual({ start: 20, end: 25 });
    expect(clipInterval({ start: 10, end: 19 }, v(20, 25))).toBeNull();
  });

  it("emits increasing nice ticks inside the viewport", () => {
    const ticks = ticksFor(v(1, 1000), 800, 80);
    expect(ticks.length).toBeGreaterThan(0);
    for (let i = 1; i < ticks.length; i += 1) {
      expect(ticks[i].x).toBeGreaterThan(ticks[i - 1].x);
      expect(ticks[i].bp).toBeGreaterThan(ticks[i - 1].bp);
    }
    expect(ticks[0].x).toBeGreaterThanOrEqual(0);
  });
});
