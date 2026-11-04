/**
 * Gene-detail section blocks.
 *
 * The contract these tests defend is "a section never prints a number it does
 * not have". A `SectionStatus` carries `count: null` when the release holds no
 * snapshot, and every state below is asserted by its rendered sentence rather
 * than by colour or layout, because the sentence is what a researcher reads.
 *
 * i18n resolves through the shared English catalog (`mockTranslation`), so a
 * missing key surfaces as the key itself instead of silently becoming prose.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  GeneAnnotationSection,
  GeneExpressionSection,
  GeneHomologSection,
  GeneLiteratureSection,
  GenePhenotypeSection,
  GeneSectionStatus,
  GeneVariantSection,
} from "@soymutdb/api-client";

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);

import {
  GeneAnnotationSectionCard,
  GeneExpressionSectionCard,
  GeneHomologSectionCard,
  GeneLiteratureSectionCard,
  GenePhenotypeSectionCard,
  GeneVariantSectionCard,
} from "./index";

afterEach(cleanup);

function status(
  section: GeneSectionStatus["section"],
  state: GeneSectionStatus["state"],
  count: number | null,
  reason: string | null = null,
): GeneSectionStatus {
  return {
    section,
    state,
    count,
    evidence: count === null ? null : { kind: "imported", source: "go_snapshot" },
    reason,
  };
}

/** `0` as a standalone token: "0", "0.00", "0 items" — but not "10" or "0.5". */
function hasBareZero(root: HTMLElement): boolean {
  return /(^|\D)0(\.0+)?(\D|$)/.test(root.textContent ?? "");
}

describe("section states", () => {
  it("renders rows when the section is available", () => {
    render(<GeneVariantSectionCard section={availableVariantSection()} />);
    const card = screen.getByTestId("gene-variant-section");
    expect(card).toBeTruthy();
    // One row per counted consequence class, and the total as stated.
    const rows = within(card).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(screen.getByTestId("gene-variant-total").textContent).toBe("7");
  });

  it("says the gene has none — not an error — when the section is empty", () => {
    const section: GeneVariantSection = { status: status("variants", "empty", 0), total: 0, by_impact: {} };
    render(<GeneVariantSectionCard section={section} />);
    expect(screen.getByTestId("gene-section-empty")).toBeTruthy();
    expect(screen.queryByTestId("gene-section-not-imported")).toBeNull();
    expect(screen.getByText("This gene has no variants in this release.")).toBeTruthy();
  });

  it("says the release never imported it, with the keyed reason, when not imported", () => {
    const section: GeneAnnotationSection = {
      status: status("annotation", "not_imported", null, "annotation_set_missing"),
      terms: [],
      source_name: null,
      source_version: null,
      source_url: null,
    };
    render(<GeneAnnotationSectionCard section={section} />);
    const notice = screen.getByTestId("gene-section-not-imported");
    expect(within(notice).getByText(/GO \/ KEGG annotation was not imported for this release\./)).toBeTruthy();
    expect(screen.getByTestId("gene-section-reason").textContent).toContain("annotation_set_missing");
    // "not imported" is a statement about the release, never about the gene.
    expect(screen.queryByText(/This gene has no GO or KEGG terms/)).toBeNull();
  });
});

describe("count === null", () => {
  it("never prints a zero for any section whose source is absent", () => {
    // Every not-imported block mounted at once: literature is the live case
    // (`gene_literature_link_missing`), the rest guard the same rule.
    const { container } = render(
      <>
        <GeneAnnotationSectionCard
          section={{
            status: status("annotation", "not_imported", null, "annotation_set_missing"),
            terms: [],
            source_name: null,
            source_version: null,
            source_url: null,
          }}
        />
        <GeneExpressionSectionCard section={{ status: status("expression", "not_imported", null), records: [] }} />
        <GeneHomologSectionCard section={{ status: status("homolog", "not_imported", null), records: [] }} />
        <GenePhenotypeSectionCard section={{ status: status("phenotype", "not_imported", null), records: [] }} />
        <GeneLiteratureSectionCard
          section={{ status: status("literature", "not_imported", null, "gene_literature_link_missing"), records: [] }}
        />
      </>,
    );
    expect(screen.getAllByTestId("gene-section-not-imported")).toHaveLength(5);
    expect(hasBareZero(container)).toBe(false);
    // Nor is the count smuggled in as a translated label.
    expect(container.textContent).not.toMatch(/\b0\b/);
  });

  it("keeps an absent measurement out of the expression table", () => {
    // tpm present, fpkm not measured: the cell is an em dash, not 0.00.
    const section: GeneExpressionSection = {
      status: status("expression", "available", 1),
      records: [
        {
          library_id: "lib-1",
          library_name: "root_L1",
          tissue: "root",
          treatment: null,
          stage: null,
          tpm: 12.5,
          fpkm: null,
          raw_count: null,
        },
      ],
    };
    render(<GeneExpressionSectionCard section={section} />);
    const card = screen.getByTestId("gene-expression-section");
    expect(within(card).getByText("12.50")).toBeTruthy();
    expect(within(card).getByText("—")).toBeTruthy();
    expect(hasBareZero(card)).toBe(false);
  });
});

describe("available rows carry their evidence", () => {
  it("shows the GO evidence code verbatim next to the derived kind badge", () => {
    const section: GeneAnnotationSection = {
      status: status("annotation", "available", 2),
      terms: [
        {
          ontology: "go",
          term_id: "GO:0009733",
          term_name: "response to auxin",
          evidence_code: "IDA",
          kind: "experimental",
          reference: "PMID:1234",
          qualifier: null,
        },
        {
          ontology: "go",
          term_id: "GO:0006355",
          term_name: "regulation of DNA-templated transcription",
          evidence_code: null,
          kind: "unknown",
          reference: null,
          qualifier: null,
        },
      ],
      source_name: "soybase_go",
      source_version: "2026-01",
      source_url: null,
    };
    render(<GeneAnnotationSectionCard section={section} />);
    const card = screen.getByTestId("gene-annotation-section");
    const table = within(card).getByRole("table");
    expect(within(table).getAllByRole("row").slice(1)).toHaveLength(2);
    // The source's code is not rewritten into the coarse class.
    expect(within(card).getByText("IDA")).toBeTruthy();
    const kinds = within(card).getAllByTestId("annotation-evidence-kind");
    expect(kinds.map((node) => node.querySelector("[data-evidence-kind]")?.getAttribute("data-evidence-kind"))).toEqual([
      "experimental",
      "unknown",
    ]);
    // An absent code stays absent rather than borrowing the row above.
    expect(within(card).getAllByTestId("annotation-evidence-code")[1].textContent).toBe("—");
  });

  it("marks every homolog row as transferred, never as a measurement of this gene", () => {
    const section: GeneHomologSection = {
      // The API sets `transferred` on the status; the card must render that
      // class, not the `imported` used by the other sections' fixtures.
      status: {
        ...status("homolog", "available", 1),
        evidence: { kind: "transferred", source: "inparanoid" },
      },
      records: [
        {
          homolog_species: "Arabidopsis thaliana",
          homolog_gene_id: "AT1G01010",
          homolog_type: "ortholog",
          method: null,
          source: "inparanoid",
          kind: "transferred",
          confidence: null,
        },
      ],
    };
    render(<GeneHomologSectionCard section={section} />);
    const card = screen.getByTestId("gene-homolog-section");
    expect(within(card).getAllByRole("row").slice(1)).toHaveLength(1);
    expect(within(card).getByText("AT1G01010")).toBeTruthy();
    expect(within(card).getByText("Transferred by orthology")).toBeTruthy();
  });

  it("identifies a phenotype by the mutant's public id only", () => {
    const section: GenePhenotypeSection = {
      status: status("phenotype", "available", 1),
      records: [
        {
          mutant_public_id: "SM0001",
          mutant_name: "W82-ems-17",
          trait_category: "morphology",
          trait_name: "plant height",
          trait_value: "42",
          unit: "cm",
          measurement_method: "ruler",
        },
      ],
    };
    render(<GenePhenotypeSectionCard section={section} />);
    const card = screen.getByTestId("gene-phenotype-section");
    expect(screen.getByTestId("phenotype-mutant").textContent).toBe("SM0001");
    expect(within(card).getByText("42 cm")).toBeTruthy();
    // No internal row key exists on the record, and none may be synthesised.
    expect(card.textContent).not.toMatch(/\b\d{6,}\b/);
  });

  it("renders literature rows with their identifier when the relation lands", () => {
    const section: GeneLiteratureSection = {
      status: status("literature", "available", 1),
      records: [
        {
          title: "A soybean gene atlas",
          authors: "Li et al.",
          journal: "Plant Cell",
          year: 2024,
          doi: "10.1105/tpc.001",
          pmid: null,
        },
      ],
    };
    render(<GeneLiteratureSectionCard section={section} />);
    const card = screen.getByTestId("gene-literature-section");
    expect(within(card).getAllByRole("row").slice(1)).toHaveLength(1);
    expect(within(card).getByText("10.1105/tpc.001", { exact: false })).toBeTruthy();
  });
});

describe("a block missing from the response", () => {
  it("does not claim the gene has none", () => {
    render(<GeneLiteratureSectionCard section={null} />);
    const missing = screen.getByTestId("gene-section-unreported");
    expect(missing.textContent).toContain("nothing reported by this API build");
    expect(hasBareZero(missing)).toBe(false);
  });
});

function availableVariantSection(): GeneVariantSection {
  return {
    status: status("variants", "available", 7),
    total: 7,
    // A class absent from the map was not measured; it must not become a 0 row.
    by_impact: { HIGH: 4, MODERATE: 3 },
  };
}
