import { describe, expect, it } from "vitest";

import { resolveFeatureFlag, resolveInitialReleaseId, resolveJbrowseBaseUrl } from "./deployment";

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

describe("resolveFeatureFlag", () => {
  it("keeps a service enabled when the flag is absent or unrecognized", () => {
    expect(resolveFeatureFlag(undefined)).toBe(true);
    expect(resolveFeatureFlag("")).toBe(true);
    expect(resolveFeatureFlag("maybe")).toBe(true);
  });

  it("disables only on an explicit off-token", () => {
    for (const value of ["0", "false", "off", "no", " FALSE "]) {
      expect(resolveFeatureFlag(value)).toBe(false);
    }
    for (const value of ["1", "true", "on", "yes"]) {
      expect(resolveFeatureFlag(value)).toBe(true);
    }
  });
});
