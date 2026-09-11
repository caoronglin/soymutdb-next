import { describe, expect, it } from "vitest";

import { getFileKind, isTextKind } from "../format";

describe("file preview format dispatch", () => {
  it("keeps compressed bioinformatics files download-only until bounded decoding exists", () => {
    expect(getFileKind("reads.fa.gz")).toBe("binary");
    expect(getFileKind("variants.vcf.gz")).toBe("binary");
    expect(isTextKind(getFileKind("reads.fasta.gz"))).toBe(false);
  });

  it("uses a download-only fallback for unknown binary formats", () => {
    expect(getFileKind("archive.unknown")).toBe("binary");
    expect(getFileKind("notes.txt")).toBe("text");
    expect(getFileKind("reads.fasta")).toBe("fasta");
  });
});
