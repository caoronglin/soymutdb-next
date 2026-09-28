// @vitest-environment jsdom
//
// REGRESSION — React-owned context gates and public-boundary helpers.
//
// Invariants guarded here (all React, not the legacy Vue views):
//   1. /browser fails closed without an explicit assembly AND release. The
//      retired behaviour substituted `Wm82.a4.v1`, which rendered the v4
//      namespace for a context-free or unknown-v5 deep link (DB-CORE assembly
//      scope: v4 and v5 are distinct coordinate namespaces).
//   2. `returnTo` stays a same-site path (no open redirect / scheme smuggling).
//   3. `jbrowseUrl()` never fabricates an assembly for a caller that has no
//      assembly context — it returns an empty href so the link is inert.
//
// If this is RED: a React surface is inventing release/assembly context or
// accepting an off-site return target, and links can silently change namespace.
import { describe, expect, it, vi } from "vitest";

import { browserContextMissing, safeReturnTo } from "../routes/browser";
import { jbrowseUrl } from "../lib/format";

describe("browser deep-link context gate", () => {
  it("requires both an explicit assembly and a release", () => {
    expect(browserContextMissing({ assembly: "Wm82v4.0", release: "2026.09" })).toBe(false);
    expect(browserContextMissing({ assembly: "Wm82v4.0", release: null })).toBe(true);
    expect(browserContextMissing({ assembly: null, release: "2026.09" })).toBe(true);
    expect(browserContextMissing({})).toBe(true);
    // Blank/whitespace values are not context.
    expect(browserContextMissing({ assembly: "   ", release: "2026.09" })).toBe(true);
    expect(browserContextMissing({ assembly: "Wm82v5.0", release: " " })).toBe(true);
  });

  it("never treats a version label as an implicit v4/v5 default", () => {
    // The gate is purely about presence: an unknown-but-explicit assembly name
    // is allowed through here and rejected later by the release-scoped API,
    // which is the only component that can resolve a canonical assembly.
    expect(browserContextMissing({ assembly: "UnknownAsm", release: "2026.09" })).toBe(false);
  });
});

describe("safeReturnTo", () => {
  it("keeps same-site absolute paths", () => {
    expect(safeReturnTo("/genes/Glyma.01G000100")).toBe("/genes/Glyma.01G000100");
  });

  it("rejects off-site, protocol-relative, backslash and scheme targets", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    try {
      for (const unsafe of [
        "//evil.example/collect",
        "/\\evil.example/collect",
        "javascript:alert(1)",
        "https://evil.example/",
        "genes/relative",
      ]) {
        expect(safeReturnTo(unsafe)).toBeUndefined();
      }
    } finally {
      warn.mockRestore();
    }
    expect(safeReturnTo(undefined)).toBeUndefined();
  });
});

describe("jbrowseUrl requires explicit assembly context", () => {
  it("returns an empty href instead of an implicit v4 default", () => {
    expect(jbrowseUrl({ chromosome: "chr01" })).toBe("");
    expect(jbrowseUrl({ chromosome: "chr01" }, "")).toBe("");
    expect(jbrowseUrl({ chromosome: "chr01" }, undefined)).toBe("");
  });

  it("builds the locus link only from the caller's assembly", () => {
    const href = jbrowseUrl({ chromosome: "chr01", start: 1, end: 1000 }, "Wm82v5.0");
    expect(href).toContain("assembly=Wm82v5.0");
    expect(href).not.toContain("Wm82.a4.v1");
  });
});
