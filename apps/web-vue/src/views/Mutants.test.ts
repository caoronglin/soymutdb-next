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

// Stub RouterLink so the list/detail tests do not need real navigation.
const RouterLink = {
  props: ["to"],
  template: '<a><slot /></a>',
};

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    getReleaseId: () => "2026.09",
    listMutantLines: vi.fn(),
    getMutantLine: vi.fn(),
  };
});

import { getMutantLine, listMutantLines } from "@soymutdb/api-client";
import MutantDetailView from "./MutantDetailView.vue";
import MutantsListView from "./MutantsListView.vue";

const mockedList = vi.mocked(listMutantLines);
const mockedDetail = vi.mocked(getMutantLine);

beforeEach(() => {
  mockedList.mockReset();
  mockedDetail.mockReset();
});

async function mountComponent(component: unknown, url: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/mutants", name: "mutants", component: MutantsListView },
      { path: "/mutants/:publicId", name: "mutant", component: MutantDetailView },
    ],
  });
  router.push(url);
  await router.isReady();
  return { router, wrapper: mount(component as never, {
    global: {
      plugins: [
        createPinia(),
        router,
        [VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }],
      ],
      stubs: { RouterLink },
    },
  }) };
}

describe("Mutant pages (Phase F, DB-CORE-2 public_id)", () => {
  it("lists mutant lines by public id and never leaks an internal id", async () => {
    mockedList.mockResolvedValue([
      { public_id: "SM7QF3Z", name: "line-A", mutagen: "EMS", cultivar: "W82", variant_count: 3 },
    ]);
    const { wrapper } = await mountComponent(MutantsListView, "/mutants");
    await flushPromises();
    await flushPromises();

    const row = wrapper.find('[data-testid="mutant-row"]');
    expect(row.exists()).toBe(true);
    expect(row.attributes("data-public-id")).toBe("SM7QF3Z");
    expect(wrapper.html()).toContain("SM7QF3Z"); // public id rendered
    expect(wrapper.html()).not.toContain("internal_id"); // private id absent
    wrapper.unmount();
  });

  it("binds the URL mutagen deep link into the request", async () => {
    mockedList.mockResolvedValue([]);
    const { wrapper } = await mountComponent(MutantsListView, "/mutants?mutagen=EMS");
    await flushPromises();
    await flushPromises();

    // A shared/reloaded deep link must reproduce the same filtered request.
    expect(mockedList).toHaveBeenCalledWith({ mutagen: "EMS", limit: 50 });
    const input = wrapper.find('[data-testid="mutagen-filter"]');
    expect((input.element as HTMLInputElement).value).toBe("EMS");
    wrapper.unmount();
  });

  it("commits an edited mutagen to the URL so reload and back/forward restore it", async () => {
    mockedList.mockResolvedValue([]);
    const { router, wrapper } = await mountComponent(MutantsListView, "/mutants");
    await flushPromises();

    const input = wrapper.find('[data-testid="mutagen-filter"]');
    await input.setValue("gamma");
    await input.trigger("change");
    await flushPromises();

    expect(router.currentRoute.value.query.mutagen).toBe("gamma");
    expect(mockedList).toHaveBeenLastCalledWith({ mutagen: "gamma", limit: 50 });
    wrapper.unmount();
  });

  it("renders a mutant detail by public id with no internal identifier", async () => {
    mockedDetail.mockResolvedValue({
      public_id: "SM7QF3Z",
      name: "line-A",
      mutagen: "EMS",
      cultivar: "W82",
      variant_count: 3,
      species: "Glycine max",
      description: null,
      generation: "M3",
      phenotype_summary: null,
      is_public: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    const { wrapper } = await mountComponent(MutantDetailView, "/mutants/SM7QF3Z");
    await flushPromises();
    await flushPromises();

    expect(wrapper.find('[data-testid="mutant-public-id"]').text()).toBe("SM7QF3Z");
    expect(wrapper.find('[data-testid="mutant-name"]').text()).toBe("line-A");
    expect(wrapper.html()).not.toContain("internal_id");
    // An unknown public id surfaces no internal record (DB-CORE-2).
    wrapper.unmount();
  });

  it("shows no detail for an unknown public id", async () => {
    mockedDetail.mockResolvedValue(undefined as never);
    const { wrapper } = await mountComponent(MutantDetailView, "/mutants/DOESNOTEXIST");
    await flushPromises();
    await flushPromises();
    expect(wrapper.find('[data-testid="mutant-detail"]').exists()).toBe(false);
    wrapper.unmount();
  });
});
