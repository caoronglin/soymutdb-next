// @vitest-environment jsdom
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { mount, flushPromises } from "@vue/test-utils";
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
    seqFetchGenes: vi.fn(),
    seqFetchRegion: vi.fn(),
  };
});

import { getAssemblies, seqFetchGenes, seqFetchRegion } from "@soymutdb/api-client";
import SeqFetchView from "./SeqFetchView.vue";
import { setLanguage } from "../lib/i18n";

const mockedAssemblies = vi.mocked(getAssemblies);
const mockedSeqFetchGenes = vi.mocked(seqFetchGenes);
const mockedSeqFetchRegion = vi.mocked(seqFetchRegion);

const ASSEMBLIES = [
  { id: "4", name: "Wm82 v4", species: "Glycine max", version: "v4", is_default: false },
  { id: "5", name: "Wm82 v5", species: "Glycine max", version: "v5", is_default: true },
];

function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/tools/seqfetch", component: SeqFetchView }],
  });
  router.push("/tools/seqfetch");
  return mount(SeqFetchView, {
    // jsdom only dispatches `submit` for a form that is part of the document.
    attachTo: document.body,
    global: {
      plugins: [
        router,
        [
          VueQueryPlugin,
          { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
        ],
      ],
    },
  });
}

beforeEach(() => {
  setLanguage("en");
  mockedAssemblies.mockReset().mockResolvedValue(ASSEMBLIES);
  mockedSeqFetchGenes.mockReset();
  mockedSeqFetchRegion.mockReset();
});

describe("SeqFetchView", () => {
  it("extracts a deduplicated gene list inside the selected assembly", async () => {
    mockedSeqFetchGenes.mockResolvedValue({
      format: "fasta",
      sequence: ">Glyma.01G000100\nACGT\n",
      count: 1,
      truncated: false,
      missing: ["Glyma.99G999999"],
      download_url: null,
      expires_in: null,
    });
    const wrapper = mountView();
    await flushPromises();
    await wrapper.get('[data-testid="seqfetch-genes"]').setValue(
      "Glyma.01G000100, Glyma.99G999999; Glyma.01G000100",
    );
    await wrapper.get('[data-testid="seqfetch-submit"]').trigger("click");
    await flushPromises();
    await flushPromises();

    expect(mockedSeqFetchGenes).toHaveBeenCalledWith("Wm82 v5", [
      "Glyma.01G000100",
      "Glyma.99G999999",
    ]);
    expect(wrapper.get('[data-testid="seqfetch-fasta-preview"]').text()).toContain(
      ">Glyma.01G000100",
    );
    expect(wrapper.text()).toContain("Accessions not found in Wm82 v5");
    wrapper.unmount();
  });

  it("validates and extracts a bounded 1-based region in the chosen assembly", async () => {
    mockedSeqFetchRegion.mockResolvedValue({
      format: "fasta",
      sequence: ">Wm82 v4:Chr01:100-109\nACGTACGTAC\n",
      count: 1,
      truncated: false,
      missing: [],
      download_url: null,
      expires_in: null,
    });
    const wrapper = mountView();
    await flushPromises();
    await wrapper.get('[data-testid="seqfetch-mode-region"]').trigger("click");
    await wrapper.get("#seqfetch-assembly").setValue("Wm82 v4");
    await wrapper.get("#seqfetch-chromosome").setValue("Chr01");
    await wrapper.get('[data-testid="seqfetch-start"]').setValue("100");
    await wrapper.get('[data-testid="seqfetch-end"]').setValue("109");
    await wrapper.get('[data-testid="seqfetch-submit"]').trigger("click");
    await flushPromises();
    await flushPromises();

    expect(mockedSeqFetchRegion).toHaveBeenCalledWith("Wm82 v4", "Chr01:100-109");
    expect(wrapper.text()).toContain("Wm82 v4 · 1 sequence");
    wrapper.unmount();
  });

  it("rejects invalid or oversized regions before making a request", async () => {
    const wrapper = mountView();
    await flushPromises();
    await wrapper.get('[data-testid="seqfetch-mode-region"]').trigger("click");
    await wrapper.get("#seqfetch-chromosome").setValue("Chr01");
    await wrapper.get('[data-testid="seqfetch-start"]').setValue("1");
    await wrapper.get('[data-testid="seqfetch-end"]').setValue("1000001");
    await wrapper.get('[data-testid="seqfetch-submit"]').trigger("click");

    expect(mockedSeqFetchRegion).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("may not exceed 1,000,000 bp");
    wrapper.unmount();
  });
});
