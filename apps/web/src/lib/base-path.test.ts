import { describe, expect, it } from "vitest";

import { normalizeBasePath } from "./base-path";

describe("normalizeBasePath", () => {
  it("normalizes a missing value to the root", () => {
    expect(normalizeBasePath(undefined)).toBe("/");
    expect(normalizeBasePath("")).toBe("/");
    expect(normalizeBasePath("   ")).toBe("/");
  });

  it("adds and strips deployment slashes", () => {
    expect(normalizeBasePath("/soymutdb-next/")).toBe("/soymutdb-next/");
    expect(normalizeBasePath("soymutdb-next")).toBe("/soymutdb-next/");
  });
});
