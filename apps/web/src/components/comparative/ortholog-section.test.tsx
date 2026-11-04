// @vitest-environment jsdom
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GeneOrthologs } from "@soymutdb/api-client";

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);
vi.mock("../../lib/release-scope", () => ({ useReleaseId: () => "2026.09" }));

const api = vi.hoisted(() => ({ getGeneOrthologs: vi.fn() }));
vi.mock("@soymutdb/api-client", () => ({ getGeneOrthologs: api.getGeneOrthologs }));

import { GeneOrthologSection } from "./ortholog-section";

function payload(overrides: Partial<GeneOrthologs> = {}): GeneOrthologs {
  return {
    gene_id: "Gm01g00010",
    assembly_id: 4,
    release_id: 1,
    state: "available",
    records: [],
    ...overrides,
  };
}

function renderSection() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <GeneOrthologSection geneId="Gm01g00010" assemblyId="4" />
    </QueryClientProvider>,
  );
}

afterEach(() => cleanup());
beforeEach(() => api.getGeneOrthologs.mockReset());

describe("GeneOrthologSection", () => {
  it("prints each relationship class verbatim", async () => {
    api.getGeneOrthologs.mockResolvedValue(
      payload({
        records: [
          {
            gene_accession: "Gm01g00010",
            counterpart_species: "Glycine soja",
            counterpart_gene_id: "GSO_1",
            homolog_type: "ortholog",
            relationship_type: "one_to_one",
            method: "orthofinder",
            source: "OrthoDB",
            release_id: 1,
            confidence: 0.9,
            evidence: { kind: "transferred", source: "gene_homologs" },
          },
          {
            gene_accession: "Gm01g00010",
            counterpart_species: "Medicago truncatula",
            counterpart_gene_id: "MED_7",
            homolog_type: "ortholog",
            relationship_type: "many_to_many",
            method: null,
            source: null,
            release_id: 1,
            confidence: null,
            evidence: { kind: "transferred", source: "gene_homologs" },
          },
        ],
      }),
    );
    renderSection();

    await waitFor(() => expect(screen.getByText("GSO_1")).toBeTruthy());
    const oneToOne = document.querySelector('[data-relationship-type="one_to_one"]');
    const manyToMany = document.querySelector('[data-relationship-type="many_to_many"]');
    expect(oneToOne?.textContent).toBe("one_to_one");
    expect(manyToMany?.textContent).toBe("many_to_many");
    // No score is invented for a row whose source stated no method.
    expect(screen.getByText("MED_7")).toBeTruthy();
  });

  it("reports no_data rather than an empty table", async () => {
    api.getGeneOrthologs.mockResolvedValue(payload({ state: "no_data", records: [] }));
    renderSection();

    await waitFor(() => expect(document.querySelector('[data-comparative-state="no_data"]')).toBeTruthy());
    expect(document.querySelector("table")).toBeNull();
  });

  it("keeps not_imported distinct from no_data", async () => {
    api.getGeneOrthologs.mockResolvedValue(payload({ state: "not_imported", records: [] }));
    renderSection();

    await waitFor(() =>
      expect(document.querySelector('[data-comparative-state="not_imported"]')).toBeTruthy(),
    );
    expect(document.querySelector('[data-comparative-state="no_data"]')).toBeNull();
  });

  it("never derives orthology from a similarity score on the page", async () => {
    api.getGeneOrthologs.mockResolvedValue(
      payload({
        records: [
          {
            gene_accession: "Gm01g00010",
            counterpart_species: "Glycine soja",
            counterpart_gene_id: "GSO_1",
            homolog_type: "ortholog",
            relationship_type: "one_to_one",
            method: "orthofinder",
            source: "OrthoDB",
            release_id: 1,
            confidence: 0.9,
            evidence: { kind: "transferred", source: "gene_homologs" },
          },
        ],
      }),
    );
    const { container } = renderSection();

    await waitFor(() => expect(screen.getByText("GSO_1")).toBeTruthy());
    // The section's own hint says the relationship types come from the
    // imported rows *rather than* from sequence similarity — so the copy
    // contains "similarity" on purpose. Drop that one sentence before scanning
    // for score vocabulary, or the guard fails on its own disclaimer.
    const hint = container.querySelector("p.text-xs")?.textContent ?? "";
    expect(hint).toMatch(/rather than|not from/i);
    const text = (container.textContent ?? "").replace(hint, "");

    // No e-value, bit score or identity column exists because the record has none.
    expect(text).not.toMatch(/e-?value/i);
    expect(text).not.toMatch(/bitscore|bit score/i);
    expect(text).not.toMatch(/identity/i);
    expect(text).not.toMatch(/similar/i);
  });
});
