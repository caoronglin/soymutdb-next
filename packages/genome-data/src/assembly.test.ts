import { describe, expect, it } from "vitest";

import { assertAssembly, resolveRefName, type AssemblyContext } from "./assembly";
import { GenomeDataError } from "./errors";

const assembly: AssemblyContext = {
  key: "v4.0",
  name: "Wm82v4.0",
  aliases: ["Wm82 v4.0"],
  refNames: ["chr01", "chr02"],
  refNameAliases: { "1": "chr01" },
};

describe("resolveRefName", () => {
  it("accepts a canonical reference name", () => {
    expect(resolveRefName(assembly, "chr02")).toBe("chr02");
  });

  it("resolves an alias to its canonical name", () => {
    expect(resolveRefName(assembly, "1")).toBe("chr01");
  });

  it("trims surrounding whitespace", () => {
    expect(resolveRefName(assembly, " chr01 ")).toBe("chr01");
  });

  it("rejects an unknown reference with assembly-mismatch", () => {
    try {
      resolveRefName(assembly, "chr99");
      throw new Error("expected resolveRefName to throw");
    } catch (error) {
      expect(error).toBeInstanceOf(GenomeDataError);
      expect((error as GenomeDataError).code).toBe("assembly-mismatch");
    }
  });

  it("rejects an empty reference", () => {
    expect(() => resolveRefName(assembly, "   ")).toThrow(GenomeDataError);
  });
});

describe("assertAssembly", () => {
  it("accepts a matching key", () => {
    expect(() => assertAssembly(assembly, "v4.0")).not.toThrow();
  });

  it("rejects a cross-assembly record", () => {
    try {
      assertAssembly(assembly, "v5.0");
      throw new Error("expected assertAssembly to throw");
    } catch (error) {
      expect(error).toBeInstanceOf(GenomeDataError);
      expect((error as GenomeDataError).code).toBe("assembly-mismatch");
    }
  });
});
