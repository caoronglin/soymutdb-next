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
    template:
      '<button :type="htmlType ?? type ?? \'button\'" :disabled="disabled" @click="$emit(\'click\', $event)"><slot /></button>',
  },
  Tag: { template: "<span><slot /></span>" },
  createThemeConfig: () => ({}),
}));

import { getAssemblies, getSiteBranding, getSiteContent, searchVariants } from "@soymutdb/api-client";
import VariantsView from "./VariantsView.vue";
import { setLanguage, t } from "../lib/i18n";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    getAssemblies: vi.fn(),
    getSiteBranding: vi.fn(),
    getSiteContent: vi.fn(),
    getReleaseId: () => "2026.09",
    searchVariants: vi.fn(),
  };
});

const ASSEMBLIES = [
  { id: 4, name: "Wm82", version: "a4.v1", species: "Glycine max", is_default: false },
  { id: 5, name: "Wm82", version: "a5", species: "Glycine max", is_default: true },
];

const EMPTY_PAGE = {
  items: [],
  cursor: null,
  next_cursor: null,
  has_more: false,
  total_count: 0,
};

const mockedSearch = vi.mocked(searchVariants);
const mockedSiteContent = vi.mocked(getSiteContent);

beforeEach(() => {
  setLanguage("en");
  mockedSearch.mockReset().mockResolvedValue(EMPTY_PAGE as never);
  mockedSiteContent.mockReset().mockResolvedValue({});
  vi.mocked(getAssemblies).mockReset().mockResolvedValue(ASSEMBLIES as never);
  vi.mocked(getSiteBranding).mockReset().mockResolvedValue({
    variant: "external",
    name_zh: "SoyMutDB",
    name_en: "SoyMutDB",
    icon_url: null,
  });
});

async function mountView(query: Record<string, string> = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/variants", name: "variants", component: VariantsView }],
  });
  const qs = new URLSearchParams(query).toString();
  await router.push(qs ? `/variants?${qs}` : "/variants");
  await router.isReady();
  const wrapper = mount(VariantsView, {
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

describe("VariantsView (Phase F, DB-CORE-3/4/6 + ADR-0006)", () => {
  it("renders public variant rows and shows the total when present", async () => {
    mockedSearch.mockResolvedValue({
      items: [
        {
          variant_id: "v1",
          chromosome: "Chr01",
          position: 123,
          ref_allele: "A",
          alt_allele: "G",
          variant_type: "SNP",
          gene_id: "Glyma.01G000100",
          gene_symbol: "Gm01",
          impact: "MODERATE",
        },
      ],
      cursor: null,
      next_cursor: null,
      has_more: false,
      total_count: 1,
    } as never);
    const { wrapper } = await mountView();

    const rows = wrapper.findAll('[data-testid="variant-row"]');
    expect(rows).toHaveLength(1);
    expect(wrapper.text()).toContain("v1");
    expect(wrapper.get('[data-testid="variants-total"]').text()).toContain("1");
    expect(wrapper.html()).not.toContain("internal_id");
    wrapper.unmount();
  });

  it("binds every URL filter into the request and sends the resolved assembly label", async () => {
    const { wrapper } = await mountView({
      assembly: "5",
      chromosome: "Chr01",
      start: "1000",
      end: "2000",
      impact: "HIGH",
      variant_type: "SNP",
      mutant_line_id: "SM7QF3Z",
    });

    // The URL carries the stable id; the label-based API receives the name.
    expect(mockedSearch).toHaveBeenCalledWith(
      expect.objectContaining({
        assembly: "Wm82",
        chromosome: "Chr01",
        start: 1000,
        end: 2000,
        impact: "HIGH",
        variant_type: "SNP",
        mutant_line_public_id: "SM7QF3Z",
        limit: 50,
      }),
    );
    wrapper.unmount();
  });

  it("shows the version in the assembly select so v4 and v5 are distinguishable", async () => {
    const { wrapper } = await mountView();

    const options = wrapper.get('[data-testid="assembly-filter"]').findAll("option");
    const labels = options.map((option) => option.text());
    expect(labels).toContain("Wm82 a4.v1");
    expect(labels).toContain("Wm82 a5");
    wrapper.unmount();
  });

  it("commits an edited filter to the URL so reload and back/forward restore it", async () => {
    const { router, wrapper } = await mountView();

    await wrapper.get('[data-testid="chromosome-filter"]').setValue("Chr02");
    await wrapper.get('[data-testid="chromosome-filter"]').trigger("change");
    await flushPromises();

    expect(router.currentRoute.value.query.chromosome).toBe("Chr02");
    expect(mockedSearch).toHaveBeenLastCalledWith(
      expect.objectContaining({ chromosome: "Chr02" }),
    );
    wrapper.unmount();
  });

  it("hides the total when the backend returns a null total_count (ADR-0006)", async () => {
    mockedSearch.mockResolvedValue({ ...EMPTY_PAGE, total_count: null } as never);
    const { wrapper } = await mountView();

    expect(wrapper.get('[data-testid="variants-total"]').text()).toContain("total hidden");
    expect(wrapper.find('[data-testid="variants-empty"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it("reports an unknown assembly id instead of querying a different namespace", async () => {
    const { wrapper } = await mountView({ assembly: "99" });

    expect(wrapper.find('[data-testid="variants-unknown-assembly"]').exists()).toBe(true);
    expect(mockedSearch).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("reports a shared assembly name as ambiguous and requires the id", async () => {
    const { wrapper } = await mountView({ assembly: "Wm82" });

    expect(wrapper.get('[data-testid="variants-unknown-assembly"]').text()).toContain(
      "matches several versions",
    );
    expect(mockedSearch).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("pages forward and back with the cursor, never replaying page one", async () => {
    mockedSearch
      .mockResolvedValueOnce({
        ...EMPTY_PAGE,
        items: [],
        has_more: true,
        next_cursor: "cursor-2",
        total_count: null,
      } as never)
      .mockResolvedValueOnce({
        ...EMPTY_PAGE,
        items: [],
        has_more: false,
        next_cursor: null,
        total_count: null,
      } as never);
    const { router, wrapper } = await mountView();
    await flushPromises();

    await wrapper.get('[data-testid="variants-next"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.query.cursor).toBe("cursor-2");
    expect(mockedSearch).toHaveBeenLastCalledWith(
      expect.objectContaining({ cursor: "cursor-2", limit: 50 }),
    );

    await wrapper.get('[data-testid="variants-previous"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.query.cursor).toBeUndefined();
    wrapper.unmount();
  });

  it("labels every row's assembly when All genome versions is selected (P1-05)", async () => {
    mockedSearch.mockResolvedValue({
      items: [
        { variant_id: "v4-1", chromosome: "Chr01", position: 1, ref_allele: "A", alt_allele: "G", variant_type: "SNP", assembly: "a4.v1" },
        { variant_id: "v5-1", chromosome: "Chr01", position: 1, ref_allele: "A", alt_allele: "G", variant_type: "SNP", assembly: "a5" },
      ],
      cursor: null,
      next_cursor: null,
      has_more: false,
      total_count: 2,
    } as never);
    const { wrapper } = await mountView();

    expect(wrapper.find('[data-testid="variants-assembly-column"]').exists()).toBe(true);
    const labels = wrapper
      .findAll('[data-testid="variant-assembly"]')
      .map((node) => node.text());
    expect(labels).toHaveLength(2);
    expect(labels.join(" ")).toContain("Wm82 a4.v1");
    expect(labels.join(" ")).toContain("Wm82 a5");
    wrapper.unmount();
  });

  it("hides the assembly column when a single assembly is selected", async () => {
    const { wrapper } = await mountView({ assembly: "5" });

    expect(wrapper.find('[data-testid="variants-assembly-column"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("renders today's localized title/subtitle when no override is stored", async () => {
    const { wrapper } = await mountView();

    expect(wrapper.get(".eyebrow").text()).toBe(t("variants.title"));
    expect(wrapper.get("h1").text()).toBe(t("variants.subtitle"));
    wrapper.unmount();
  });

  it("keeps Chinese copy (not the English default) when the override map is empty", async () => {
    setLanguage("zh");
    const { wrapper } = await mountView();

    expect(wrapper.get(".eyebrow").text()).toBe(t("variants.title"));
    expect(wrapper.get("h1").text()).toBe(t("variants.subtitle"));
    expect(wrapper.get("h1").text()).not.toBe("Search and explore genomic variant information");
    wrapper.unmount();
  });

  it("renders a stored title/subtitle override under the active language", async () => {
    mockedSiteContent.mockResolvedValue({
      "variants.title": "运营变异标题",
      "variants.subtitle": "运营变异副标题",
    });
    setLanguage("zh");
    const { wrapper } = await mountView();

    expect(wrapper.get(".eyebrow").text()).toBe("运营变异标题");
    expect(wrapper.get("h1").text()).toBe("运营变异副标题");
    wrapper.unmount();
  });
});
