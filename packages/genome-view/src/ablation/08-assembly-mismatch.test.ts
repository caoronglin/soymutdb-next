import { describe, expect, it } from "vitest";
import {
  GenomeDataError,
  VariantReader,
  createTrackDataSource,
  isGenomeDataError,
  uriLocation,
} from "@soymutdb/genome-data";
import { ASSEMBLIES, VARIANT_FILES, memoryProvider, variantTrack } from "./support";

async function capture(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
    return undefined;
  } catch (error) {
    return error;
  }
}

describe("ablation scenario 8: assembly mismatch", () => {
  it("factory rejects a track that references an unconfigured assembly", () => {
    const track = { ...variantTrack(), assemblyNames: ["v9"] };
    let error: unknown;
    try {
      createTrackDataSource(track, {
        provider: memoryProvider(VARIANT_FILES),
        assemblies: ASSEMBLIES,
      });
    } catch (caught) {
      error = caught;
    }
    expect(isGenomeDataError(error)).toBe(true);
    expect((error as GenomeDataError).code).toBe("assembly-mismatch");
  });

  it("reader rejects a foreign assemblyKey or an unknown reference name", async () => {
    const reader = new VariantReader({
      provider: memoryProvider(VARIANT_FILES),
      assembly: ASSEMBLIES[0],
      vcf: uriLocation("mem://variants.vcf.gz"),
      index: uriLocation("mem://variants.vcf.gz.tbi"),
      trackId: "variants",
    });

    const foreign = await capture(
      reader.getVariants({ assemblyKey: "v5", refName: "chr01", start: 0, end: 10 }),
    );
    expect(isGenomeDataError(foreign)).toBe(true);
    expect((foreign as GenomeDataError).code).toBe("assembly-mismatch");

    const unknownRef = await capture(
      reader.getVariants({ assemblyKey: "v4", refName: "chrZ", start: 0, end: 10 }),
    );
    expect(isGenomeDataError(unknownRef)).toBe(true);
    expect((unknownRef as GenomeDataError).code).toBe("assembly-mismatch");
  });
});
