// @vitest-environment jsdom
import { mount, flushPromises } from "@vue/test-utils";
import { VueQueryPlugin, QueryClient } from "@tanstack/vue-query";
import { createPinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@soymutdb/ui-vue", () => ({
  ConfigProvider: { template: "<div><slot /></div>" },
  Input: {
    template:
      "<input :value=\"modelValue\" @input=\"$emit('update:modelValue', $event.target.value)\" />",
    props: ["modelValue"],
  },
  Tag: { template: "<span><slot /></span>" },
  createThemeConfig: () => ({}),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, getReleaseId: () => "2026.09", searchVariants: vi.fn() };
});

import { searchVariants } from "@soymutdb/api-client";
import VariantsView from "./VariantsView.vue";

const mocked = vi.mocked(searchVariants);
beforeEach(() => mocked.mockReset());

async function mountView(query: Record<string, string> = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/variants", name: "variants", component: VariantsView }],
  });
  const qs = new URLSearchParams(query).toString();
  router.push(qs ? `/variants?${qs}` : "/variants");
  await router.isReady();
  return {
    router,
    wrapper: mount(VariantsView, {
      global: {
        plugins: [
          createPinia(),
          router,
          [VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }],
        ],
      },
    }),
  };
}

describe("VariantsView (Phase F, DB-CORE-3/4/6 + ADR-0006)", () => {
  it("renders public variant rows and shows the total when present", async () => {
    mocked.mockResolvedValue({
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
    });
    const { wrapper } = await mountView();
    await flushPromises();
    await flushPromises();

    const rows = wrapper.findAll('[data-testid="variant-row"]');
    expect(rows).toHaveLength(1);
    expect(wrapper.text()).toContain("v1");
    expect(wrapper.find('[data-testid="variants-total"]').text()).toContain("1 variants");
    expect(wrapper.html()).not.toContain("internal_id");
    wrapper.unmount();
  });

  it("binds every URL filter into the request and the cache key", async () => {
    mocked.mockResolvedValue({
      items: [],
      cursor: null,
      next_cursor: null,
      has_more: false,
      total_count: 0,
    });
    const { wrapper } = await mountView({
      chromosome: "Chr01",
      start: "1000",
      end: "2000",
      impact: "HIGH",
      assembly: "5",
    });
    await flushPromises();
    await flushPromises();

    // A shared/reloaded deep link must reproduce the same request, not drop
    // the region/impact filters.
    expect(mocked).toHaveBeenCalledWith(
      expect.objectContaining({
        assembly: "5",
        chromosome: "Chr01",
        start: 1000,
        end: 2000,
        impact: "HIGH",
        limit: 50,
      }),
    );
    wrapper.unmount();
  });

  it("commits an edited filter to the URL so reload and back/forward restore it", async () => {
    mocked.mockResolvedValue({
      items: [],
      cursor: null,
      next_cursor: null,
      has_more: false,
      total_count: 0,
    });
    const { router, wrapper } = await mountView();
    await flushPromises();

    const input = wrapper.find('[data-testid="chromosome-filter"]');
    await input.setValue("Chr02");
    await input.trigger("change");
    await flushPromises();

    expect(router.currentRoute.value.query.chromosome).toBe("Chr02");
    expect(mocked).toHaveBeenLastCalledWith(
      expect.objectContaining({ chromosome: "Chr02" }),
    );
    wrapper.unmount();
  });

  it("hides the total when the backend returns a null total_count (ADR-0006)", async () => {
    mocked.mockResolvedValue({ items: [], cursor: null, next_cursor: null, has_more: false, total_count: null });
    const { wrapper } = await mountView();
    await flushPromises();
    await flushPromises();
    expect(wrapper.find('[data-testid="variants-total"]').text()).toContain("total hidden");
    expect(wrapper.find('[data-testid="variants-empty"]').exists()).toBe(true);
    wrapper.unmount();
  });
});
