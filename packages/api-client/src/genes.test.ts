import { getGene, searchGenes } from "./genes";
import { afterEach, describe, expect, it, vi } from "vitest";

describe("gene client contract", () => {
  afterEach(() => vi.restoreAllMocks());

  it("maps the portal query and page parameters to the API contract", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [],
          page: 2,
          page_size: 20,
          total: 0,
          total_pages: 0,
          next_cursor: null,
          has_more: false,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    await searchGenes({ q: "Glyma.01G000100", cursor: "c1", limit: 20 });

    const [url] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    const parsed = new URL(url, "http://localhost");
    expect(parsed.searchParams.get("search")).toBe("Glyma.01G000100");
    expect(parsed.searchParams.get("cursor")).toBe("c1");
    expect(parsed.searchParams.get("limit")).toBe("20");
    expect(parsed.searchParams.has("q")).toBe(false);
  });
});

describe("gene detail sequence/evidence contract", () => {
  afterEach(() => vi.restoreAllMocks());

  it("keeps an unavailable molecule unavailable instead of defaulting it to a sequence", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          gene_id: "Glyma.01G000100",
          chromosome: "Chr01",
          start_pos: 1,
          end_pos: 100,
          strand: "+",
          sequences: [
            {
              molecule: "protein",
              availability: "unavailable",
              reason: "no_sequence_store:protein",
              length: null,
              checksum: null,
              sequence: null,
            },
          ],
          model_evidence: { kind: "predicted", source: "AUGUSTUS" },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    const detail = await getGene("Glyma.01G000100");
    expect(detail.sequences?.[0].availability).toBe("unavailable");
    expect(detail.sequences?.[0].sequence).toBeNull();
    expect(detail.model_evidence?.kind).toBe("predicted");
  });
});

describe("gene detail section contract", () => {
  afterEach(() => vi.restoreAllMocks());

  function detail(payload: Record<string, unknown>): void {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          gene_id: "Glyma.01G000100",
          chromosome: "Chr01",
          start_pos: 1,
          end_pos: 100,
          strand: "+",
          ...payload,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
  }

  it("keeps a section with no snapshot distinguishable from an empty one", async () => {
    detail({
      annotation_section: {
        status: {
          section: "annotation",
          state: "not_imported",
          count: null,
          evidence: null,
          reason: "annotation_set_missing",
        },
        terms: [],
        source_name: null,
        source_version: null,
        source_url: null,
      },
      expression_section: {
        status: { section: "expression", state: "empty", count: 0, evidence: null, reason: null },
        records: [],
      },
    });

    const gene = await getGene("Glyma.01G000100");
    // ``null`` (never 0) is what makes "we never imported it" readable.
    expect(gene.annotation_section?.status.state).toBe("not_imported");
    expect(gene.annotation_section?.status.count).toBeNull();
    expect(gene.expression_section?.status.state).toBe("empty");
    expect(gene.expression_section?.status.count).toBe(0);
  });

  it("carries each term's own evidence kind instead of the section's", async () => {
    detail({
      annotation_section: {
        status: {
          section: "annotation",
          state: "available",
          count: 2,
          evidence: { kind: "imported", source: "Synthetic GO fixture" },
          reason: null,
        },
        terms: [
          {
            ontology: "go",
            term_id: "GO:0008150",
            term_name: "biological process",
            evidence_code: "IDA",
            kind: "experimental",
            reference: "PMID:1",
            qualifier: null,
          },
          {
            ontology: "go",
            term_id: "GO:0003674",
            term_name: "molecular function",
            evidence_code: null,
            kind: "unknown",
            reference: null,
            qualifier: null,
          },
        ],
        source_name: "Synthetic GO fixture",
        source_version: "1",
        source_url: "https://example.org/go/v1",
      },
    });

    const gene = await getGene("Glyma.01G000100");
    expect(gene.annotation_section?.terms.map((term) => term.kind)).toEqual([
      "experimental",
      "unknown",
    ]);
  });

  it("never reports an unmeasured expression unit as zero", async () => {
    detail({
      expression_section: {
        status: { section: "expression", state: "available", count: 1, evidence: null, reason: null },
        records: [
          {
            library_id: "S1",
            library_name: "root control",
            tissue: "root",
            treatment: "control",
            stage: null,
            tpm: 12.5,
            fpkm: null,
            raw_count: null,
          },
        ],
      },
    });

    const gene = await getGene("Glyma.01G000100");
    const record = gene.expression_section?.records[0];
    expect(record?.tpm).toBe(12.5);
    expect(record?.fpkm).toBeNull();
    expect(record?.raw_count).toBeNull();
  });
});
