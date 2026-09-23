import { describe, expect, it } from "vitest";
import { cn } from "@soymutdb/shared/cn";

describe("web-vue shell consumes the framework-neutral seam", () => {
  it("merges classes via the shared cn utility", () => {
    // Keep the falsy input in a typed variable: a literal `false && "b"` is a
    // constant binary expression and eslint no-constant-binary-expression
    // rejects it. The assertion still covers the boolean branch of ClassValue.
    const disabled: string | false = false;
    expect(cn("a", disabled && "b", "c")).toBe("a c");
  });
});
