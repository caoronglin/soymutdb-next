import { describe, expect, it } from "vitest";
import { cn } from "@soymutdb/shared/cn";

describe("web-vue shell consumes the framework-neutral seam", () => {
  it("merges classes via the shared cn utility", () => {
    expect(cn("a", false && "b", "c")).toBe("a c");
  });
});
