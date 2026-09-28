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
  getSiteContent,
  getTableView,
  searchGenes,
} from "@soymutdb/api-client";
import SearchGenesView from "./SearchGenesView.vue";
import { setLanguage, t } from "../lib/i18n";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    getAssemblies: vi.fn(),
    getSiteBranding: vi.fn(),
    getSiteContent: vi.fn(),
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
  vi.mocked(getSiteContent).mockReset().mockResolvedValue({});
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

describe("gene search editable content", () => {
  it("renders the i18n title, assembly label and placeholder without overrides", async () => {
    const { wrapper } = await mountGenes({});

    expect(wrapper.get("h1").text()).toBe(t("search.genes.title"));
    expect(wrapper.get('[data-testid="search-genes-assembly"]').element.parentElement?.textContent)
      .toContain(t("search.genes.assembly"));
    expect(wrapper.get('[data-testid="search-genes-input"]').attributes("placeholder")).toBe(
      t("search.genes.geneIdPlaceholder"),
    );
    wrapper.unmount();
  });

  it("renders the operator override for the page title", async () => {
    vi.mocked(getSiteContent).mockResolvedValue({ "search.genes.title": "运营基因检索" } as never);

    const { wrapper } = await mountGenes({});

    expect(wrapper.get("h1").text()).toBe("运营基因检索");
    wrapper.unmount();
  });

  it("retitles a template column through its content key", async () => {
    vi.mocked(getTableView).mockResolvedValue({
      kind: "genes",
      species: "Glycine max",
      site_variant: "external",
      release_id: null,
      template_id: null,
      template_name: "builtin",
      is_builtin_default: true,
      columns: [
        { key: "assembly_name", label_zh: "基因组版本", label_en: "Genome version", visible: true },
      ],
      actions: { jbrowse: false, genome_preview: false },
    } as never);
    vi.mocked(getSiteContent).mockResolvedValue({ "search.genes.colAssembly": "运营版本" } as never);

    const { wrapper } = await mountGenes({ q: "SoyZH13", assembly: "5", run: "1" });

    expect(wrapper.get("thead th").text()).toBe("运营版本");
    wrapper.unmount();
  });

  it("uses the ui.errorRetry override when the result query fails", async () => {
    // The fallback is the catalog string (added in OPT5; it used to be a raw
    // key), and an operator override still wins over it.
    expect(t("search.genes.resultsRetry")).toBeTruthy();
    expect(t("search.genes.resultsRetry")).not.toBe("search.genes.resultsRetry");
    vi.mocked(getSiteContent).mockResolvedValue({ "ui.errorRetry": "运营重试" } as never);
    vi.mocked(searchGenes).mockRejectedValue(new Error("boom"));

    const { wrapper } = await mountGenes({ q: "SoyZH13", assembly: "5", run: "1" });

    expect(wrapper.get('[data-testid="search-genes-error"]').text()).toBe("运营重试");
    wrapper.unmount();
  });
});
