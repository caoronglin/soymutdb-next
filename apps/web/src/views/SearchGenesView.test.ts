// @vitest-environment jsdom
import { flushPromises, mount } from "@vue/test-utils";
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { createPinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@soymutdb/ui-vue", () => ({
  ConfigProvider: { template: "<div><slot /></div>" },
  Button: {
    props: ["disabled", "type", "htmlType", "size"],
    emits: ["click"],
    template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
  },
  createThemeConfig: () => ({}),
}));

import {
  getAssemblies,
  getSiteBranding,
  getTableView,
  searchGenes,
} from "@soymutdb/api-client";
import SearchGenesView from "./SearchGenesView.vue";
import { setLanguage } from "../lib/i18n";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    getAssemblies: vi.fn(),
    getSiteBranding: vi.fn(),
    getTableView: vi.fn(),
    searchGenes: vi.fn(),
  };
});

const ASSEMBLIES = [
  { id: 4, name: "Wm82", version: "a4.v1", species: "Glycine max", is_default: false },
  { id: 5, name: "Wm82", version: "a5", species: "Glycine max", is_default: true },
];

beforeEach(() => {
  setLanguage("en");
  vi.mocked(getAssemblies).mockReset().mockResolvedValue(ASSEMBLIES as never);
  vi.mocked(searchGenes).mockReset().mockResolvedValue({ items: [], total: 0 } as never);
  vi.mocked(getSiteBranding).mockReset().mockResolvedValue({
    variant: "external",
    name_zh: "SoyMutDB",
    name_en: "SoyMutDB",
    icon_url: null,
  });
  vi.mocked(getTableView).mockReset().mockResolvedValue({
    kind: "genes",
    species: "Glycine max",
    site_variant: "external",
    release_id: null,
    template_id: null,
    template_name: "builtin",
    is_builtin_default: true,
    columns: [],
    actions: { jbrowse: false, genome_preview: false },
  } as never);
});

async function mountGenes(query: Record<string, string>) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/search/genes", name: "search-genes", component: SearchGenesView }],
  });
  const qs = new URLSearchParams(query).toString();
  await router.push(qs ? `/search/genes?${qs}` : "/search/genes");
  await router.isReady();
  const wrapper = mount(SearchGenesView, {
    attachTo: document.body,
    global: {
      plugins: [
        createPinia(),
        router,
        [VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }],
      ],
    },
  });
  await flushPromises();
  await flushPromises();
  return { wrapper, router };
}

describe("gene search assembly deep links", () => {
  it("reports an unknown assembly id instead of falling back to the default", async () => {
    const { wrapper } = await mountGenes({ q: "SoyZH13", assembly: "99", run: "1" });

    expect(wrapper.get('[data-testid="search-genes-unknown-assembly"]').text()).toContain(
      "not available",
    );
    expect(vi.mocked(searchGenes)).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("reports a name shared by v4 and v5 as ambiguous", async () => {
    const { wrapper } = await mountGenes({ q: "SoyZH13", assembly: "Wm82", run: "1" });

    expect(wrapper.get('[data-testid="search-genes-unknown-assembly"]').text()).toContain(
      "matches several versions",
    );
    expect(vi.mocked(searchGenes)).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("runs a deep link against the stable id", async () => {
    const { wrapper } = await mountGenes({ q: "SoyZH13", assembly: "5", run: "1" });

    expect(vi.mocked(searchGenes)).toHaveBeenCalledWith(
      expect.objectContaining({ q: "SoyZH13", assembly_id: "5" }),
    );
    wrapper.unmount();
  });
});
