import { describe, expect, it } from "vitest";

import {
  normalizeBasePath,
  resolveInitialReleaseId,
  resolveJbrowseBaseUrl,
  resolveSiteVariant,
} from "./deployment";

describe("resolveSiteVariant (DB-CORE-5)", () => {
  it("accepts exactly the two deployment variants", () => {
    expect(resolveSiteVariant("external")).toBe("external");
    expect(resolveSiteVariant("internal")).toBe("internal");
  });

  it("defaults to external only when the input is absent or empty", () => {
    expect(resolveSiteVariant(undefined)).toBe("external");
    expect(resolveSiteVariant(null)).toBe("external");
    expect(resolveSiteVariant("")).toBe("external");
  });

  it("fails closed on a typo instead of creating a third variant", () => {
    for (const bad of ["External", " external", "internal ", "public", "EXTERNAL", 1, {}]) {
      expect(() => resolveSiteVariant(bad)).toThrow(/VITE_SITE_VARIANT/);
    }
  });
});

describe("release pin", () => {
  it("trims the release id and treats empty as unpinned", () => {
    expect(resolveInitialReleaseId(" 2026.09 ")).toBe("2026.09");
    expect(resolveInitialReleaseId("")).toBeNull();
    expect(resolveInitialReleaseId(undefined)).toBeNull();
    expect(resolveInitialReleaseId(42)).toBeNull();
  });
});

describe("resolveJbrowseBaseUrl", () => {
  it("uses the canonical origin and strips trailing slashes", () => {
    expect(resolveJbrowseBaseUrl("https://jbrowse.example.org/")).toBe(
      "https://jbrowse.example.org",
    );
    expect(resolveJbrowseBaseUrl("/jbrowse/")).toBe("/jbrowse");
  });

  it("falls back to the same-origin /jbrowse path", () => {
    expect(resolveJbrowseBaseUrl(undefined)).toBe("/jbrowse");
    expect(resolveJbrowseBaseUrl("   ")).toBe("/jbrowse");
  });
});

describe("normalizeBasePath", () => {
  it("normalizes the deployment subpath for Vite and the router", () => {
    expect(normalizeBasePath("/")).toBe("/");
    expect(normalizeBasePath("")).toBe("/");
    expect(normalizeBasePath("soymutdb-next")).toBe("/soymutdb-next/");
    expect(normalizeBasePath("/soymutdb-next/")).toBe("/soymutdb-next/");
    expect(normalizeBasePath("///nested///")).toBe("/nested/");
  });
});
