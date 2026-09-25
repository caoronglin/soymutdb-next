import { describe, expect, it } from "vitest";

import { normalizeBasePath } from "./base-path";

describe("normalizeBasePath (Vite base + router history base)", () => {
  it("keeps a root deployment at /", () => {
    expect(normalizeBasePath("/")).toBe("/");
    expect(normalizeBasePath("")).toBe("/");
    expect(normalizeBasePath(undefined)).toBe("/");
    expect(normalizeBasePath("   ")).toBe("/");
  });

  it("normalizes a subpath deployment to Vite's /subpath/ form", () => {
    expect(normalizeBasePath("soymutdb-next")).toBe("/soymutdb-next/");
    expect(normalizeBasePath("/soymutdb-next")).toBe("/soymutdb-next/");
    expect(normalizeBasePath("/soymutdb-next/")).toBe("/soymutdb-next/");
    expect(normalizeBasePath("///nested///")).toBe("/nested/");
  });
});
