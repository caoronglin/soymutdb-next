import { describe, expect, it } from "vitest";

import { resolveInitialReleaseId, resolveJbrowseBaseUrl } from "./deployment";

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
