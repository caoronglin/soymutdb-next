// @vitest-environment jsdom
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@soymutdb/ui-vue", () => ({
  ConfigProvider: { template: "<div><slot /></div>" },
  createThemeConfig: () => ({}),
}));

// The portal shell is exercised by its own coverage; stub it so these
// assertions stay focused on the view and do not need pinia/header wiring.
vi.mock("../components/PortalLayout.vue", () => ({
  default: { template: "<div><slot /></div>" },
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    getAssemblies: vi.fn(),
    runEnrichment: vi.fn(),
  };
});

import { getAssemblies, runEnrichment } from "@soymutdb/api-client";
import EnrichmentView from "./EnrichmentView.vue";

const mockedAssemblies = vi.mocked(getAssemblies);
const mockedRunEnrichment = vi.mocked(runEnrichment);

function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/tools/enrichment", component: EnrichmentView }],
  });
  router.push("/tools/enrichment");
  return mount(EnrichmentView, {
    // jsdom only dispatches `submit` for a form that is part of the document.
    attachTo: document.body,
    global: {
      plugins: [
        router,
        [VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }],
      ],
    },
  });
}

beforeEach(() => {
  mockedAssemblies.mockReset().mockResolvedValue([
    { id: 5, name: "Wm82.v5", species: "Glycine max", version: "v5", is_default: true },
  ]);
  mockedRunEnrichment.mockReset().mockResolvedValue({
    mode: "ora",
    assembly_id: 5,
    release_id: 7,
    assembly_name: "Wm82.v5",
    assembly_version: "v5",
    annotation_source: {
      name: "Synthetic GO fixture",
      version: "1",
      url: "https://example.org/go/v1",
      sha256: "a".repeat(64),
      imported_at: "2026-09-24T00:00:00Z",
    },
    ontology: "go",
    input_genes: 2,
    background_genes: 100,
    terms: [
      { id: "GO:0008150", name: "biological process", p_value: 0.001, q_value: 0.01, gene_count: 2, genes: ["G1", "G2"] },
    ],
    message: null,
  });
});

describe("EnrichmentView", () => {
  it("submits an assembly-scoped gene list and renders the result context", async () => {
    const wrapper = mountView();
    await flushPromises();
    await wrapper.get('[data-testid="enrichment-genes"]').setValue("G1, G2 G1");
    await wrapper.get('[data-testid="enrichment-submit"]').trigger("click");
    await flushPromises();

    expect(mockedRunEnrichment).toHaveBeenCalledWith({
      assembly_id: 5,
      genes: ["G1", "G2"],
      mode: "ora",
      ontology: "go",
      p_threshold: 0.05,
      max_terms: 50,
      min_genes: 5,
    });
    expect(wrapper.get('[data-testid="enrichment-summary"]').text()).toContain("Wm82.v5 · v5");
    expect(wrapper.get('[data-testid="enrichment-summary"]').text()).toContain("Release 7");
    expect(wrapper.get('[data-testid="enrichment-provenance"]').text()).toContain(
      "Synthetic GO fixture · 1",
    );
    expect(wrapper.get('[data-testid="enrichment-plot"]').text()).toContain("GO:0008150");
    wrapper.unmount();
  });

  it("validates ranked GSEA input before requesting the API", async () => {
    const wrapper = mountView();
    await flushPromises();
    await wrapper.get('[data-testid="enrichment-mode-gsea"]').trigger("click");
    await wrapper.get('[data-testid="enrichment-submit"]').trigger("click");

    expect(mockedRunEnrichment).not.toHaveBeenCalled();
    expect(wrapper.get('[role="alert"]').text()).toContain("ranked genes");
    wrapper.unmount();
  });
});
