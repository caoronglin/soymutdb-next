import { describe, expect, it } from "vitest";

import { resolveSiteVariant } from "./site-variant";

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
