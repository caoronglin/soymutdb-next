// @vitest-environment jsdom
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { GeneTranscript } from "@soymutdb/api-client";

import GeneModelPreview from "./GeneModelPreview.vue";

const transcripts: GeneTranscript[] = [
  {
    id: "tx-minus",
    gene_id: "Glyma.01G000100",
    name: "Glyma.01G000100.2",
    biotype: "protein_coding",
    start: 1050,
    end: 1900,
    strand: "-",
    is_canonical: false,
    exons: [
      { id: "exon-m2", start: 1700, end: 1800, order: 2 },
      { id: "exon-m1", start: 1100, end: 1200, order: 1 },
    ],
  },
  {
    id: "tx-plus",
    gene_id: "Glyma.01G000100",
    name: "Glyma.01G000100.1",
    biotype: "protein_coding",
    start: 1000,
    end: 2000,
    strand: "+",
    is_canonical: true,
    exons: [
      { id: "exon-p1", start: 1000, end: 1250, order: 1 },
      { id: "exon-p2", start: 1750, end: 2000, order: 2 },
    ],
  },
];

type PreviewOverrides = Partial<{
  geneId: string;
  assemblyId: string | number;
  assemblyName: string | null;
  chromosome: string;
  start: number;
  end: number;
  strand: string;
  transcripts: GeneTranscript[];
}>;

function mountPreview(overrides: PreviewOverrides = {}) {
  return mount(GeneModelPreview, {
    props: {
      geneId: "Glyma.01G000100",
      assemblyId: "5",
      assemblyName: "Wm82 v5",
      chromosome: "Chr01",
      start: 1000,
      end: 2000,
      strand: "+",
      transcripts,
      ...overrides,
    },
  });
}

describe("GeneModelPreview", () => {
  it("merges the gene span and transcript exons in one assembly-scoped view", () => {
    const wrapper = mountPreview();
    const svg = wrapper.get('[data-testid="gene-model-svg"]');

    expect(svg.attributes("aria-label")).toContain("Wm82 v5");
    expect(svg.attributes("aria-label")).toContain("Chr01:1000..2000");
    expect(wrapper.findAll('[data-testid="gene-model-exon"]')).toHaveLength(4);
    expect(wrapper.find('[data-testid="gene-model-transcript-tx-plus"]').attributes("data-strand")).toBe("+");
    expect(
      wrapper.find('[data-testid="gene-model-transcript-tx-minus"]').attributes("data-strand"),
    ).toBe("-");
    expect(wrapper.text()).toContain("Blocks mark exons; connecting lines show introns.");
    expect(wrapper.html()).toContain("1000..1250");
    expect(wrapper.text()).toContain("canonical");
    wrapper.unmount();
  });

  it("keeps invalid transcripts and out-of-transcript exons out of the drawing", () => {
    const wrapper = mountPreview({
      transcripts: [
        ...transcripts,
        {
          id: "invalid",
          gene_id: "Glyma.01G000100",
          name: null,
          biotype: null,
          start: 0,
          end: 100,
          strand: "+",
          is_canonical: false,
          exons: [],
        },
        {
          id: "bad-exon",
          gene_id: "Glyma.01G000100",
          name: null,
          biotype: null,
          start: 1200,
          end: 1300,
          strand: "+",
          is_canonical: false,
          exons: [{ id: "outside", start: 1301, end: 1310, order: 1 }],
        },
      ],
    });

    expect(wrapper.find('[data-testid="gene-model-transcript-invalid"]').exists()).toBe(false);
    expect(wrapper.findAll('[data-testid="gene-model-exon"]')).toHaveLength(4);
    expect(wrapper.html()).not.toContain('data-interval="1301..1310"');
    wrapper.unmount();
  });

  it("shows an explicit unavailable state for malformed gene coordinates", () => {
    const wrapper = mountPreview({ start: 0 });

    expect(wrapper.find('[data-testid="gene-model-svg"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="gene-model-unavailable"]').text()).toContain(
      "coordinates are invalid",
    );
    wrapper.unmount();
  });
});
