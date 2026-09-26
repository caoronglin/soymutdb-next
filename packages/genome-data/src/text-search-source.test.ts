import { describe, expect, it } from "vitest";

import type { AssemblyContext } from "./assembly";
import { GenomeDataError } from "./errors";
import { createTextSearchDataSource, type TextSearchAdapterConfig } from "./factory";
import { TextSearchReader } from "./readers/trix";
import { fixtureProvider } from "./readers/test-fixtures";

const assembly: AssemblyContext = {
  key: "v5.0",
  name: "Wm82v5.0",
  refNames: ["chr01", "chr02"],
};

function adapter(overrides: Partial<TextSearchAdapterConfig> = {}): TextSearchAdapterConfig {
  return {
    textSearchAdapterId: "gene_index",
    ixFilePath: { uri: "memory://genes.ix", locationType: "UriLocation" },
    ixxFilePath: { uri: "memory://genes.ixx", locationType: "UriLocation" },
    assemblyNames: ["v5.0"],
    ...overrides,
  };
}

const provider = () => fixtureProvider(["genes.ix", "genes.ixx"]);

describe("createTextSearchDataSource", () => {
  it("binds a Trix reader to the adapter's assembly and searches it", async () => {
    const source = createTextSearchDataSource(adapter(), {
      provider: provider(),
      assemblies: [assembly],
    });
    expect(source.sourceId).toBe("gene_index");
    expect(source.assemblyKey).toBe("v5.0");
    expect(source.reader).toBeInstanceOf(TextSearchReader);

    const hits = await source.reader.search("at1", 1);
    expect(hits).toEqual([{ id: "at1g01010", label: "chr01:1..60|gene:AT1G01010|AT1G01010" }]);
  });

  it("accepts bare URI strings as locations", () => {
    const source = createTextSearchDataSource(
      adapter({ ixFilePath: "memory://genes.ix", ixxFilePath: "memory://genes.ixx" }),
      { provider: provider(), assemblies: [assembly] },
    );
    expect(source.assemblyKey).toBe("v5.0");
  });

  it("resolves the assembly by display name", () => {
    const source = createTextSearchDataSource(adapter({ assemblyNames: ["Wm82v5.0"] }), {
      provider: provider(),
      assemblies: [assembly],
    });
    expect(source.assemblyKey).toBe("v5.0");
  });

  it("rejects an adapter bound to an unknown assembly", () => {
    try {
      createTextSearchDataSource(adapter({ assemblyNames: ["v9.0"] }), {
        provider: provider(),
        assemblies: [assembly],
      });
      throw new Error("expected createTextSearchDataSource to throw");
    } catch (error) {
      expect(error).toBeInstanceOf(GenomeDataError);
      expect((error as GenomeDataError).code).toBe("assembly-mismatch");
    }
  });

  it("rejects an adapter that names no assembly", () => {
    expect(() =>
      createTextSearchDataSource(adapter({ assemblyNames: [] }), {
        provider: provider(),
        assemblies: [assembly],
      }),
    ).toThrow(GenomeDataError);
  });
});
