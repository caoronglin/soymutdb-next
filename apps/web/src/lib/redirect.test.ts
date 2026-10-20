import { describe, expect, it } from "vitest";

import { safeRedirect } from "./redirect";

describe("safeRedirect", () => {
  it("keeps same-site paths, including query and hash", () => {
    expect(safeRedirect("/genes?q=SoyZH13&assembly=Wm82.a5")).toBe(
      "/genes?q=SoyZH13&assembly=Wm82.a5",
    );
    expect(safeRedirect("/genes#results")).toBe("/genes#results");
  });

  it("rejects absolute and protocol-relative URLs", () => {
    expect(safeRedirect("https://evil.example/phish")).toBe("/");
    expect(safeRedirect("//evil.example/phish")).toBe("/");
    expect(safeRedirect("javascript:alert(1)")).toBe("/");
    expect(safeRedirect("data:text/html,<script>alert(1)</script>")).toBe("/");
  });

  it("rejects backslashes and control characters", () => {
    expect(safeRedirect("/\\evil.example")).toBe("/");
    expect(safeRedirect("/genes\u0000")).toBe("/");
  });

  it.each([0x1f, 0x7f, 0x80, 0x85, 0x9f])("rejects C0, DEL and C1 code point %i", (code) => {
    expect(safeRedirect(`/genes${String.fromCharCode(code)}`)).toBe("/");
  });

  it("falls back to the home path for missing or non-string values", () => {
    expect(safeRedirect(undefined)).toBe("/");
    expect(safeRedirect(null)).toBe("/");
    expect(safeRedirect(42)).toBe("/");
    expect(safeRedirect("relative/path")).toBe("/");
  });
});
