// @vitest-environment jsdom
import { mount, flushPromises } from "@vue/test-utils";
import { VueQueryPlugin, QueryClient } from "@tanstack/vue-query";
import { createPinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@soymutdb/ui-vue", () => ({
  ConfigProvider: { template: "<div><slot /></div>" },
  Tag: { template: "<span><slot /></span>" },
  createThemeConfig: () => ({}),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, getGene: vi.fn(), getReleaseId: () => "2026.09" };
});

import { getGene } from "@soymutdb/api-client";
import GeneView from "./GeneView.vue";
import { useSiteContextStore } from "../stores/site-context";

const mockedGetGene = vi.mocked(getGene);

const GENE_RESPONSE = {
  id: "gene-1",
  gene_id: "Glyma.01G000100",
  symbol: "Gm01",
  name: "example gene",
  biotype: "protein_coding",
  assembly_id: "5",
  assembly_name: "Wm82 v5",
  chromosome: "Chr01",
  start_pos: 1000,
  end_pos: 2000,
  strand: "-",
  description: null,
  variant_count: 12,
  high_impact_variants: 3,
  source: "test",
  extra: {},
  transcripts: [],
  annotations: [],
};

async function mountGene(geneId: string, query: Record<string, string> = {}) {
  const qs = new URLSearchParams(query).toString();
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/genes/:geneId", name: "gene", component: GeneView }],
  });
  router.push(`/genes/${geneId}${qs ? `?${qs}` : ""}`);
  await router.isReady();
  const pinia = createPinia();
  const wrapper = mount(GeneView, {
    global: {
      plugins: [
        pinia,
        router,
        [VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }],
      ],
    },
  });
  return { wrapper, pinia };
}

beforeEach(() => mockedGetGene.mockReset());

describe("GeneView (Phase F, DB-CORE-3/4/7)", () => {
  it("renders the assembly-scoped coordinate context and never a private id", async () => {
    mockedGetGene.mockResolvedValue(GENE_RESPONSE);

    const { wrapper } = await mountGene("Glyma.01G000100", { assembly: "5" });
    await flushPromises();
    await flushPromises();

    expect(wrapper.find('[data-testid="gene-id"]').text()).toBe("Glyma.01G000100");
    // Assembly version context is visible (DB-CORE-3/5).
    expect(wrapper.find('[data-testid="gene-assembly"]').text()).toContain("Wm82 v5");
    // 1-based inclusive length from the neutral view-model: 2000-1000+1 = 1001.
    expect(wrapper.find('[data-testid="gene-coords"]').text()).toContain("1001 bp");
    expect(wrapper.find('[data-testid="gene-coords"]').text()).toContain("-");
    // getGene was bound to the requested assembly.
    expect(mockedGetGene).toHaveBeenCalledWith("Glyma.01G000100", { assembly_id: "5" });
    // The public page never renders a private internal identifier.
    expect(wrapper.html()).not.toContain("internal_id");
    // A JBrowse deep link carrying the assembly context is offered.
    expect(wrapper.find('[data-testid="gene-jbrowse"]').attributes("href")).toContain("assembly=5");
    wrapper.unmount();
  });

  it("renders no detail for an absent gene", async () => {
    mockedGetGene.mockResolvedValue(undefined as never);
    const { wrapper } = await mountGene("Glyma.XX");
    await flushPromises();
    await flushPromises();
    // The detail section must not render for an absent record (empty/404).
    expect(wrapper.find('[data-testid="gene-detail"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("refetches when the pinned release changes", async () => {
    mockedGetGene.mockResolvedValue(GENE_RESPONSE);
    const { wrapper, pinia } = await mountGene("Glyma.01G000100");
    await flushPromises();
    await flushPromises();
    expect(mockedGetGene).toHaveBeenCalledTimes(1);

    // The request header and the cache key both carry the release: switching it
    // must not reuse the previous release's cached detail.
    useSiteContextStore(pinia).setRelease("2026.10");
    await flushPromises();
    await flushPromises();
    expect(mockedGetGene).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it("renders transcript rows with coordinates and the canonical marker", async () => {
    mockedGetGene.mockResolvedValue({
      ...GENE_RESPONSE,
      transcripts: [
        {
          id: "tx1",
          gene_id: "Glyma.01G000100",
          name: "Glyma.01G000100.1",
          biotype: "protein_coding",
          start: 1000,
          end: 2000,
          strand: "-",
          is_canonical: true,
          exons: [
            { id: "e1", start: 1000, end: 1200, order: 1 },
            { id: "e2", start: 1800, end: 2000, order: 2 },
          ],
        },
        {
          id: "tx2",
          gene_id: "Glyma.01G000100",
          name: null,
          biotype: null,
          start: 1000,
          end: 1500,
          strand: "-",
          is_canonical: false,
          exons: [],
        },
      ],
    });

    const { wrapper } = await mountGene("Glyma.01G000100", { assembly: "5" });
    await flushPromises();
    await flushPromises();

    const rows = wrapper.findAll('[data-testid="transcript-row"]');
    expect(rows).toHaveLength(2);
    expect(wrapper.text()).toContain("Glyma.01G000100.1");
    expect(wrapper.text()).toContain("canonical");
    expect(wrapper.text()).toContain("1000..2000");
    // A missing name falls back to the transcript id, never an empty cell.
    expect(rows[1].text()).toContain("tx2");
    expect(wrapper.html()).not.toContain("internal_id");
    wrapper.unmount();
  });

  it("links to the canonical VITE_JBROWSE_BASE_URL origin", async () => {
    vi.stubEnv("VITE_JBROWSE_BASE_URL", "https://jbrowse.example.org/");
    try {
      mockedGetGene.mockResolvedValue(GENE_RESPONSE);
      const { wrapper } = await mountGene("Glyma.01G000100", { assembly: "5" });
      await flushPromises();
      await flushPromises();
      const href = wrapper.find('[data-testid="gene-jbrowse"]').attributes("href");
      expect(href).toMatch(/^https:\/\/jbrowse\.example\.org\?/);
      expect(href).not.toContain("VITE_JBROWSE_URL");
      wrapper.unmount();
    } finally {
      vi.unstubAllEnvs();
    }
  });
});
