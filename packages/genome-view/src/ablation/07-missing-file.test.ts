import { describe, expect, it } from "vitest";
import {
  GenomeDataError,
  SequenceReader,
  VariantReader,
  isGenomeDataError,
  uriLocation,
} from "@soymutdb/genome-data";
import { ASSEMBLIES, memoryProvider } from "./support";

async function capture(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
    return undefined;
  } catch (error) {
    return error;
  }
}

describe("ablation scenario 7: missing file", () => {
  it("reader rejects with GenomeDataError code fetch when a file is absent", async () => {
    const empty = memoryProvider([]);

    const variant = new VariantReader({
      provider: empty,
      assembly: ASSEMBLIES[0],
      vcf: uriLocation("mem://variants.vcf.gz"),
      index: uriLocation("mem://variants.vcf.gz.tbi"),
      trackId: "variants",
    });
    const variantError = await capture(
      variant.getVariants({ assemblyKey: "v4", refName: "chr01", start: 0, end: 10 }),
    );
    expect(isGenomeDataError(variantError)).toBe(true);
    expect((variantError as GenomeDataError).code).toBe("fetch");

    const sequence = new SequenceReader({
      provider: empty,
      assembly: ASSEMBLIES[0],
      fasta: uriLocation("mem://reference.fa.gz"),
      fai: uriLocation("mem://reference.fa.gz.fai"),
      gzi: uriLocation("mem://reference.fa.gz.gzi"),
      trackId: "reference",
    });
    const sequenceError = await capture(
      sequence.getSequence({ assemblyKey: "v4", refName: "chr01", start: 0, end: 10 }),
    );
    expect(isGenomeDataError(sequenceError)).toBe(true);
    expect((sequenceError as GenomeDataError).code).toBe("fetch");
  });
});
