import { nextTick, watchEffect } from "vue";
import { describe, expect, it } from "vitest";
import type { Region } from "@soymutdb/genome-data";
import { useGenomeViewport } from "./viewport";

const initial: Region = { assemblyKey: "v5", refName: "chr1", start: 1000, end: 2000 };

describe("useGenomeViewport", () => {
  it("initialises from a Region", () => {
    const viewport = useGenomeViewport(initial);
    expect(viewport.assemblyKey).toBe("v5");
    expect(viewport.refName).toBe("chr1");
    expect(viewport.start).toBe(1000);
    expect(viewport.end).toBe(2000);
  });

  it("repairs an empty initial window to one base pair", () => {
    const viewport = useGenomeViewport({
      assemblyKey: "v4",
      refName: "chrX",
      start: 50,
      end: 50,
    });
    expect(viewport.start).toBe(50);
    expect(viewport.end).toBe(51);
  });

  it("pan shifts the window and preserves its span", () => {
    const viewport = useGenomeViewport(initial);
    viewport.pan(500);
    expect(viewport.start).toBe(1500);
    expect(viewport.end).toBe(2500);
  });

  it("pan clamps at coordinate 0", () => {
    const viewport = useGenomeViewport(initial);
    viewport.pan(-2000);
    expect(viewport.start).toBe(0);
    expect(viewport.end).toBe(1000);
  });

  it("zoom scales around the centre by default", () => {
    const viewport = useGenomeViewport(initial);
    viewport.zoom(2);
    expect(viewport.start).toBe(500);
    expect(viewport.end).toBe(2500);
  });

  it("zoom keeps an explicit anchor fixed", () => {
    const viewport = useGenomeViewport(initial);
    viewport.zoom(0.5, 1000);
    expect(viewport.start).toBe(1000);
    expect(viewport.end).toBe(1500);
  });

  it("zoom ignores non-positive or non-finite factors", () => {
    const viewport = useGenomeViewport(initial);
    viewport.zoom(0);
    viewport.zoom(-1);
    viewport.zoom(Number.NaN);
    expect(viewport.start).toBe(1000);
    expect(viewport.end).toBe(2000);
  });

  it("never zooms below one base pair", () => {
    const viewport = useGenomeViewport(initial);
    viewport.zoom(0.0001);
    expect(viewport.end - viewport.start).toBe(1);
  });

  it("gotoLocus switches the reference and normalises reversed ends", () => {
    const viewport = useGenomeViewport(initial);
    viewport.gotoLocus("chr2", 900, 300);
    expect(viewport.refName).toBe("chr2");
    expect(viewport.start).toBe(300);
    expect(viewport.end).toBe(900);
  });

  it("bpPerPx divides the span by the rendered width", () => {
    const viewport = useGenomeViewport(initial);
    expect(viewport.bpPerPx(500)).toBe(2);
    expect(viewport.bpPerPx(0)).toBe(0);
    expect(viewport.bpPerPx(-10)).toBe(0);
  });

  it("is reactive through its actions", async () => {
    const viewport = useGenomeViewport(initial);
    const seen: number[] = [];
    watchEffect(() => {
      seen.push(viewport.start);
    });
    viewport.pan(10);
    await nextTick();
    expect(seen).toEqual([1000, 1010]);
  });
});
