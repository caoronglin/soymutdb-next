/**
 * Regression cover for the gene-detail payload guard.
 *
 * The offline E2E fixture exposed the failure mode: a 200 response with the
 * search-list envelope (`{items: [...], total: 0}`) reached the detail page,
 * typecheck could not see it, and the genome view crashed on
 * `undefined.toLocaleString()` while rendering coordinates. The guard makes
 * that payload render the empty state instead of throwing.
 */
import { describe, expect, it } from "vitest";

import { isGeneDetailRecord, isMutantLineDetailRecord, isNewsDetailRecord } from "./api-contract-guards";

const VALID_GENE = {
  gene_id: "Glyma.01G000100",
  chromosome: "chr01",
  start_pos: 1,
  end_pos: 2000,
  biotype: "protein_coding",
  transcripts: [],
};

describe("isGeneDetailRecord", () => {
  it("accepts a minimal gene detail record", () => {
    expect(isGeneDetailRecord(VALID_GENE)).toBe(true);
  });

  it("rejects the search-list envelope that caused the crash", () => {
    expect(isGeneDetailRecord({ items: [], next_cursor: null, page: 1 })).toBe(false);
    expect(isGeneDetailRecord({ items: [{ gene_id: "Glyma.01G000100" }] })).toBe(false);
  });

  it("rejects a record without usable coordinates", () => {
    expect(isGeneDetailRecord({ ...VALID_GENE, start_pos: undefined })).toBe(false);
    expect(isGeneDetailRecord({ ...VALID_GENE, end_pos: null })).toBe(false);
    expect(isGeneDetailRecord({ ...VALID_GENE, start_pos: Number.NaN })).toBe(false);
    expect(isGeneDetailRecord({ ...VALID_GENE, start_pos: 100, end_pos: 50 })).toBe(false);
  });

  it("rejects non-objects, arrays and empty identifiers", () => {
    for (const value of [null, undefined, "gene", 7, [], {}, { gene_id: "" }]) {
      expect(isGeneDetailRecord(value), JSON.stringify(value)).toBe(false);
    }
  });
});

describe("isMutantLineDetailRecord", () => {
  const valid = { public_id: "SM7K3ZQ9P2A", name: "Williams 82 mutant", species: "Glycine max" };

  it("accepts a minimal mutant-line detail", () => {
    expect(isMutantLineDetailRecord(valid)).toBe(true);
  });

  it("rejects list envelopes and error bodies", () => {
    expect(isMutantLineDetailRecord({ items: [valid], total: 1 })).toBe(false);
    expect(isMutantLineDetailRecord({ error: { code: "NOT_FOUND" } })).toBe(false);
    expect(isMutantLineDetailRecord({ ...valid, public_id: "" })).toBe(false);
    expect(isMutantLineDetailRecord(null)).toBe(false);
  });
});

describe("isNewsDetailRecord", () => {
  const valid = { slug: "release-notes", title_en: "Release notes", content_en: "<p>body</p>" };

  it("accepts a minimal news detail", () => {
    expect(isNewsDetailRecord(valid)).toBe(true);
  });

  it("rejects list envelopes and records without a body", () => {
    expect(isNewsDetailRecord({ items: [valid], total: 1 })).toBe(false);
    expect(isNewsDetailRecord({ ...valid, content_en: undefined })).toBe(false);
    expect(isNewsDetailRecord({ ...valid, slug: "" })).toBe(false);
    expect(isNewsDetailRecord([])).toBe(false);
  });
});
