// @vitest-environment jsdom
// The mount helper is imported first: it registers the @soymutdb/ui-vue mock
// (Antdv Next does not resolve under vitest's node resolver — see
// packages/ui-vue/src/facade.test.ts) before the view module graph loads it.
import { flushPromises } from "@vue/test-utils";

import { mountPortalView } from "../test/mount-portal-view";

import { searchGenes, getSiteContent } from "@soymutdb/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setLanguage, t } from "../lib/i18n";
import GenesListView from "./GenesListView.vue";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, searchGenes: vi.fn(), getAssemblies: vi.fn(), getSiteContent: vi.fn() };
});

const mocked = vi.mocked(searchGenes);
const mockedSiteContent = vi.mocked(getSiteContent);

function row(geneId: string) {
  return {
    id: geneId,
    gene_id: geneId,
    symbol: `SYM-${geneId}`,
    name: geneId,
    biotype: "protein_coding",
    assembly_id: "5",
    assembly_name: "Wm82 v5",
    chromosome: "chr01",
    start_pos: 100,
    end_pos: 5000,
    strand: "+",
    description: null,
    variant_count: 3,
  };
}

beforeEach(() => {
  setLanguage("en");
  mockedSiteContent.mockReset().mockResolvedValue({});
  mocked.mockReset().mockResolvedValue({
    items: [row("Glyma.01G000100")],
    total: 1,
    next_cursor: null,
    has_more: false,
    page: 1,
    page_size: 20,
    total_pages: 1,
  });
});

describe("GenesListView", () => {
  it("renders released gene rows and links to the gene detail with its assembly", async () => {
    const { wrapper } = mountPortalView(GenesListView, { path: "/genes" });
    await flushPromises();

    expect(wrapper.get('[data-testid="gene-row"]').text()).toContain("Glyma.01G000100");
    const link = wrapper.get('[data-testid="gene-row"] a');
    expect(link.attributes("href")).toBe("/genes/Glyma.01G000100?assembly=5");
    wrapper.unmount();
  });

  it("keeps the filter state in the URL so a shared link restores the result set", async () => {
    mocked.mockResolvedValue({
      items: [],
      total: 0,
      next_cursor: null,
      has_more: false,
      page: 1,
      page_size: 20,
      total_pages: 0,
    });
    const { wrapper, router } = mountPortalView(GenesListView, { path: "/genes" });
    await flushPromises();

    await wrapper.get('[data-testid="genes-search"]').setValue("Glyma.02G");
    await wrapper.get('[data-testid="genes-filter-apply"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.query).toMatchObject({ q: "Glyma.02G" });
    expect(mocked).toHaveBeenLastCalledWith(
      expect.objectContaining({ q: "Glyma.02G", page: 1 }),
    );
    wrapper.unmount();
  });

  it("re-requests with the toggled sort direction", async () => {
    const { wrapper } = mountPortalView(GenesListView, { path: "/genes" });
    await flushPromises();
    mocked.mockClear();

    await wrapper.get('[data-testid="genes-sort-gene_id"]').trigger("click");
    await flushPromises();

    expect(mocked).toHaveBeenCalledWith(expect.objectContaining({ sort_by: "gene_id", sort_dir: "desc" }));
    wrapper.unmount();
  });

  it("reports an empty result set instead of inventing rows", async () => {
    mocked.mockResolvedValue({
      items: [],
      total: 0,
      next_cursor: null,
      has_more: false,
      page: 1,
      page_size: 20,
      total_pages: 0,
    });
    const { wrapper } = mountPortalView(GenesListView, { path: "/genes" });
    await flushPromises();

    expect(wrapper.find('[data-testid="genes-empty"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="gene-row"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("renders today's localized title/subtitle when no override is stored", async () => {
    const { wrapper } = mountPortalView(GenesListView, { path: "/genes" });
    await flushPromises();

    expect(wrapper.get(".eyebrow").text()).toBe(t("genes.title"));
    expect(wrapper.get("h1").text()).toBe(t("genes.subtitle"));
    wrapper.unmount();
  });

  it("keeps Chinese copy (not the English default) when the override map is empty", async () => {
    setLanguage("zh");
    const { wrapper } = mountPortalView(GenesListView, { path: "/genes" });
    await flushPromises();

    expect(wrapper.get(".eyebrow").text()).toBe(t("genes.title"));
    expect(wrapper.get("h1").text()).toBe(t("genes.subtitle"));
    expect(wrapper.get("h1").text()).not.toBe("Browse gene models, annotations and homologs");
    wrapper.unmount();
  });

  it("renders a stored title/subtitle override under the active language", async () => {
    mockedSiteContent.mockResolvedValue({
      "genes.title": "运营基因标题",
      "genes.subtitle": "运营基因副标题",
    });
    setLanguage("zh");
    const { wrapper } = mountPortalView(GenesListView, { path: "/genes" });
    await flushPromises();

    expect(wrapper.get(".eyebrow").text()).toBe("运营基因标题");
    expect(wrapper.get("h1").text()).toBe("运营基因副标题");
    wrapper.unmount();
  });
});
