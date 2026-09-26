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
  getAssemblyChromosomes,
  getSiteBranding,
  getTableView,
  searchRegionVariants,
} from "@soymutdb/api-client";
import SearchLocationView from "./SearchLocationView.vue";
import { setLanguage } from "../lib/i18n";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    getAssemblies: vi.fn(),
    getAssemblyChromosomes: vi.fn(),
    getSiteBranding: vi.fn(),
    getTableView: vi.fn(),
    searchRegionVariants: vi.fn(),
  };
});

const ASSEMBLIES = [
  { id: 4, name: "Wm82", version: "a4.v1", species: "Glycine max", is_default: false },
  { id: 5, name: "Wm82", version: "a5", species: "Glycine max", is_default: true },
  { id: 6, name: "ZH13", version: "v1", species: "Glycine max", is_default: false },
];

beforeEach(() => {
  setLanguage("en");
  vi.mocked(getAssemblies).mockReset().mockResolvedValue(ASSEMBLIES as never);
  vi.mocked(getAssemblyChromosomes).mockReset().mockResolvedValue([
    { id: 1, assembly_id: 5, name: "Chr01", length: 1000, order: 1 },
  ] as never);
  vi.mocked(getSiteBranding).mockReset().mockResolvedValue({
    variant: "external",
    name_zh: "SoyMutDB",
    name_en: "SoyMutDB",
    icon_url: null,
  });
  vi.mocked(getTableView).mockReset().mockResolvedValue({
    kind: "variants",
    species: "Glycine max",
    site_variant: "external",
    release_id: null,
    template_id: null,
    template_name: "builtin",
    is_builtin_default: true,
    columns: [],
    actions: { jbrowse: false, genome_preview: false },
  } as never);
  vi.mocked(searchRegionVariants).mockReset().mockResolvedValue([] as never);
});

async function mountLocation(query: Record<string, string>) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/search/location", name: "search-location", component: SearchLocationView }],
  });
  const qs = new URLSearchParams(query).toString();
  await router.push(qs ? `/search/location?${qs}` : "/search/location");
  await router.isReady();
  const wrapper = mount(SearchLocationView, {
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
  await flushPromises();
  return { wrapper, router };
}

describe("region search assembly deep links", () => {
  it("reports an unknown assembly id instead of querying another namespace", async () => {
    const { wrapper } = await mountLocation({
      assembly: "99",
      chromosome: "Chr01",
      start: "1",
      end: "2",
      run: "1",
    });

    expect(wrapper.get('[data-testid="location-unknown-assembly"]').text()).toContain(
      "not available",
    );
    expect(vi.mocked(searchRegionVariants)).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("reports a name shared by v4 and v5 as ambiguous", async () => {
    const { wrapper } = await mountLocation({
      assembly: "Wm82",
      chromosome: "Chr01",
      start: "1",
      end: "2",
      run: "1",
    });

    expect(wrapper.get('[data-testid="location-unknown-assembly"]').text()).toContain(
      "matches several versions",
    );
    expect(vi.mocked(searchRegionVariants)).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("runs a deep link by id and sends the resolved assembly label", async () => {
    const { wrapper } = await mountLocation({
      assembly: "5",
      chromosome: "Chr01",
      start: "1",
      end: "2000",
      run: "1",
    });

    expect(vi.mocked(searchRegionVariants)).toHaveBeenCalledWith(
      expect.objectContaining({
        assembly: "Wm82",
        chromosome: "Chr01",
        start: 1,
        end: 2000,
      }),
    );
    wrapper.unmount();
  });

  it("canonicalizes a unique legacy name to the stable id", async () => {
    const { router } = await mountLocation({
      assembly: "ZH13",
      chromosome: "Chr01",
      start: "1",
      end: "2",
      run: "1",
    });
    await flushPromises();

    expect(router.currentRoute.value.query.assembly).toBe("6");
  });
});
