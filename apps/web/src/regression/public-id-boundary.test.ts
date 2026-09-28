// @vitest-environment jsdom
//
// REGRESSION — external mutant surfaces expose public_id and never the internal key.
//
// Invariant (DB-CORE identity contract): the external mutants list and detail
// render, link and key by `public_id`; the numeric internal persistence key
// (`id` / `internal_id`) must not leak into the row/detail DOM, and the detail
// request is keyed by the public id taken from the URL.
// Guards: MutantsListView.vue and MutantDetailView.vue.
// Source (ablation): docs/dev/ablation/2026-09-26/frontend.md §3 「UI-01 列表」and
// 「UI-01 详情」rows (GUARD-ACTIVE) + §6.B diff — swapping `line.public_id` ->
// `line.internal_id` in the two .vue files flipped these assertions
// (`expected "42" to be "SM7QF3Z"`).
// If this is RED: a public surface is showing or using the persistence key, and
// public URLs / links would stop matching the identity contract.
import { mount, flushPromises } from "@vue/test-utils";
import { VueQueryPlugin, QueryClient } from "@tanstack/vue-query";
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
  Input: {
    template:
      "<input :value=\"value\" @input=\"$emit('update:value', $event.target.value)\" />",
    props: ["value"],
  },
  Tag: { template: "<span><slot /></span>" },
  createThemeConfig: () => ({}),
}));

const RouterLink = { props: ["to"], template: "<a><slot /></a>" };

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    getReleaseId: () => "2026.09",
    listMutantLines: vi.fn(),
    getMutantLine: vi.fn(),
    getMutantLinePhenotypes: vi.fn(),
  };
});

import { getMutantLine, getMutantLinePhenotypes, listMutantLines } from "@soymutdb/api-client";
import MutantDetailView from "../views/MutantDetailView.vue";
import MutantsListView from "../views/MutantsListView.vue";

const mockedList = vi.mocked(listMutantLines);
const mockedDetail = vi.mocked(getMutantLine);
const mockedPhenotypes = vi.mocked(getMutantLinePhenotypes);

// The record deliberately carries every plausible internal key: a numeric
// `id`, a distinct `internal_id`, and `public_id`. Only `public_id` is public.
const RECORD_WITH_BOTH_IDS = {
  public_id: "SM7QF3Z",
  internal_id: "42",
  id: "42",
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
};

beforeEach(() => {
  mockedList.mockReset();
  mockedDetail.mockReset();
  mockedPhenotypes.mockReset();
  mockedPhenotypes.mockResolvedValue([]);
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
  const wrapper = mount(component as never, {
    global: {
      plugins: [
        createPinia(),
        router,
        [VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }],
      ],
      stubs: { RouterLink },
    },
  });
  return wrapper;
}

describe("ABLATION UI-01: external mutant surfaces render public_id, never the internal key", () => {
  it("list row renders the public id even when the payload also carries an internal id", async () => {
    mockedList.mockResolvedValue([RECORD_WITH_BOTH_IDS] as never);
    const wrapper = await mountComponent(MutantsListView, "/mutants");
    await flushPromises();
    await flushPromises();

    const row = wrapper.find('[data-testid="mutant-row"]');
    expect(row.exists()).toBe(true);
    // Public identity is what the row is keyed, linked and labelled by.
    expect(row.attributes("data-public-id")).toBe("SM7QF3Z");
    expect(row.text()).toContain("SM7QF3Z");
    // No numeric internal key leaks into the row's own markup.
    expect(row.html()).not.toContain("42");
    wrapper.unmount();
  });

  it("detail page renders the public id even when the payload also carries an internal id", async () => {
    mockedDetail.mockResolvedValue(RECORD_WITH_BOTH_IDS as never);
    const wrapper = await mountComponent(MutantDetailView, "/mutants/SM7QF3Z");
    await flushPromises();
    await flushPromises();

    expect(wrapper.find('[data-testid="mutant-public-id"]').text()).toBe("SM7QF3Z");
    expect(wrapper.find('[data-testid="mutant-public-id"]').text()).not.toBe("42");
    wrapper.unmount();
  });

  it("keys the detail request by the public id from the URL, not by the internal key", async () => {
    mockedDetail.mockResolvedValue(RECORD_WITH_BOTH_IDS as never);
    const wrapper = await mountComponent(MutantDetailView, "/mutants/SM7QF3Z");
    await flushPromises();
    await flushPromises();

    expect(mockedDetail).toHaveBeenCalledWith("SM7QF3Z");
    expect(mockedDetail).not.toHaveBeenCalledWith("42");
    wrapper.unmount();
  });
});
