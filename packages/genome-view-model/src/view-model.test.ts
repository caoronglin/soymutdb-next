import { describe, expect, it } from "vitest";
import {
  AssemblyMismatchError,
  InvalidCoordinateError,
  clipToWindow,
  contains,
  length,
  normalizeInterval,
  overlaps,
  packRows,
  sameAssembly,
  sortByPosition,
  sortForStrandView,
} from "./index";

const on = (assemblyKey: string) => (start: number, end: number) => ({
  assemblyKey,
  start,
  end,
});

describe("1-based inclusive coordinates", () => {
  it("measures length inclusively", () => {
    expect(length({ assemblyKey: "v5", start: 10, end: 10 })).toBe(1);
    expect(length({ assemblyKey: "v5", start: 10, end: 20 })).toBe(11);
  });

  it("treats adjacent-but-contiguous intervals as non-overlapping", () => {
    expect(overlaps(on("v5")(1, 5), on("v5")(6, 10))).toBe(false);
    expect(overlaps(on("v5")(1, 5), on("v5")(5, 10))).toBe(true); // share base 5
  });

  it("handles single-base intervals", () => {
    expect(overlaps(on("v4")(5, 5), on("v4")(5, 5))).toBe(true);
    expect(overlaps(on("v4")(5, 5), on("v4")(6, 6))).toBe(false);
    expect(overlaps(on("v4")(5, 5), on("v4")(1, 10))).toBe(true);
  });

  it("normalizes reversed ends and rejects non-positive coords", () => {
    expect(normalizeInterval({ assemblyKey: "v5", start: 9, end: 4 })).toEqual({
      assemblyKey: "v5",
      start: 4,
      end: 9,
    });
    expect(() => normalizeInterval({ assemblyKey: "v5", start: 0, end: 4 })).toThrow(
      InvalidCoordinateError,
    );
    expect(() => length({ assemblyKey: "v5", start: 4, end: 3 })).toThrow(
      InvalidCoordinateError,
    );
  });
});

describe("assembly scoping (DB-CORE-3 / H04)", () => {
  it("never collapses across assemblies and refuses comparison", () => {
    expect(sameAssembly(on("v4")(1, 2), on("v5")(1, 2))).toBe(false);
    expect(() => overlaps(on("v4")(1, 10), on("v5")(5, 6))).toThrow(AssemblyMismatchError);
    expect(() => contains(on("v4")(1, 100), on("v5")(2, 3))).toThrow(AssemblyMismatchError);
  });

  it("packRows refuses a mixed-assembly set", () => {
    expect(() => packRows([on("v4")(1, 4), on("v5")(2, 5)])).toThrow(AssemblyMismatchError);
  });

  it("keeps identically-coordinated v4 and v5 as separate rows per assembly", () => {
    const v4 = packRows([on("v4")(1, 4)]);
    const v5 = packRows([on("v5")(1, 4)]);
    expect(v4).toHaveLength(1);
    expect(v5).toHaveLength(1);
    expect(v4[0][0].item.assemblyKey).toBe("v4");
    expect(v5[0][0].item.assemblyKey).toBe("v5");
  });
});

describe("containment + clipping", () => {
  it("detects containment within an assembly", () => {
    expect(contains(on("v5")(1, 100), on("v5")(10, 20))).toBe(true);
    expect(contains(on("v5")(1, 100), on("v5")(100, 101))).toBe(false);
  });

  it("clips to a window or returns null when disjoint", () => {
    expect(clipToWindow(on("v5")(8, 40), 10, 20)).toEqual({ assemblyKey: "v5", start: 10, end: 20 });
    expect(clipToWindow(on("v5")(1, 5), 10, 20)).toBeNull();
    expect(clipToWindow(on("v5")(1, 100), 10, 20)).toEqual({
      assemblyKey: "v5",
      start: 10,
      end: 20,
    });
  });
});

describe("packRows greedy packing", () => {
  it("packs overlapping intervals onto separate rows and reuses free rows", () => {
    const items = [on("v5")(1, 4), on("v5")(2, 5), on("v5")(6, 9), on("v5")(7, 8)];
    const rows = packRows(items);
    expect(rows).toHaveLength(2);
    expect(rows[0].map((p) => p.item.start)).toEqual([1, 6]);
    expect(rows[1].map((p) => p.item.start)).toEqual([2, 7]);
    expect(rows.flat().every((p) => typeof p.row === "number")).toBe(true);
  });

  it("gives every non-overlapping interval the same row", () => {
    const rows = packRows([on("v5")(1, 2), on("v5")(3, 4), on("v5")(5, 6)]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveLength(3);
  });
});

describe("ordering", () => {
  it("sorts by start then end", () => {
    const sorted = sortByPosition([on("v5")(20, 30), on("v5")(10, 12), on("v5")(10, 18)]);
    expect(sorted.map((i) => `${i.start}-${i.end}`)).toEqual(["10-12", "10-18", "20-30"]);
  });

  it("sorts strand-first then by position", () => {
    const sorted = sortForStrandView([
      { assemblyKey: "v5", start: 5, end: 6, strand: "+" as const },
      { assemblyKey: "v5", start: 5, end: 6, strand: "-" as const },
      { assemblyKey: "v5", start: 1, end: 2, strand: "-" as const },
    ]);
    expect(sorted.map((i) => `${i.strand}:${i.start}`)).toEqual(["+:5", "-:1", "-:5"]);
  });
});
