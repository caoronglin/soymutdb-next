// @vitest-environment jsdom
//
// REGRESSION — every search result row carries assembly / release / source context.
//
// Invariant: an actioned row and a URL-less (disabled) row both render assembly,
// release_id and source; when no human assembly label is sent the numeric
// assembly_id is shown, so a version is never silently omitted (DB-CORE assembly
// scope). A bare gene name or coordinate must never be ambiguous across v4/v5.
// Guards: the `data-testid="search-result-meta"` span in SearchView.vue.
// Source (ablation): docs/dev/ablation/2026-09-26/frontend.md §3 「SRCH-CTX 结果
// 上下文」row (GUARD-ACTIVE) + §6.D — deleting the meta span flipped this harness
// to 3 failed while SearchView.test.ts stayed green, making this file the only
// guard against the scope being dropped.
// If this is RED: result rows lost their assembly/release/source scope, or the
// assembly_id fallback disappeared.
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

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, globalSearch: vi.fn(), getReleaseId: () => "2026.09" };
});

import { globalSearch } from "@soymutdb/api-client";
import SearchView from "../views/SearchView.vue";

const mockedSearch = vi.mocked(globalSearch);

async function mountSearch(query: Record<string, string>) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/search", name: "search", component: SearchView }],
  });
  await router.push(`/search?${new URLSearchParams(query).toString()}`);
  await router.isReady();
  const wrapper = mount(SearchView, {
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
  return wrapper;
}

beforeEach(() => mockedSearch.mockReset());

describe("ABLATION search-context: result rows carry assembly/release/source", () => {
  it("renders assembly, release and source on an actioned row", async () => {
    mockedSearch.mockResolvedValue({
      query: "Glyma.01G000100",
      results: [
        {
          id: "Glyma.01G000100",
          type: "gene",
          name: "Glyma.01G000100",
          url: "/genes/Glyma.01G000100?assembly=1",
          assembly: "Wm82 v4",
          release_id: 7,
          source: "internal",
        },
      ],
      by_type: { gene: 1 },
      by_assembly: { "1": 1 },
      ambiguous: false,
      cursor: null,
      next_cursor: null,
      has_more: false,
      total_count: 1,
    } as never);

    const wrapper = await mountSearch({ q: "Glyma.01G000100" });

    const meta = wrapper.find('[data-testid="search-result-meta"]');
    expect(meta.exists()).toBe(true);
    expect(meta.text()).toContain("Wm82 v4");
    expect(meta.text()).toContain("7");
    expect(meta.text()).toContain("internal");
    wrapper.unmount();
  });

  it("renders the same context on a URL-less (disabled) row", async () => {
    mockedSearch.mockResolvedValue({
      query: "Glyma.01G000100",
      results: [
        {
          id: "Glyma.01G000100",
          type: "gene",
          name: "no-url",
          assembly: "Wm82 v5",
          release_id: 8,
          source: "internal",
        },
      ],
      by_type: { gene: 1 },
      by_assembly: { "2": 1 },
      ambiguous: false,
      cursor: null,
      next_cursor: null,
      has_more: false,
      total_count: 1,
    } as never);

    const wrapper = await mountSearch({ q: "Glyma.01G000100" });

    const meta = wrapper.find('[data-testid="search-result-meta"]');
    expect(meta.exists()).toBe(true);
    expect(meta.text()).toContain("Wm82 v5");
    expect(meta.text()).toContain("8");
    wrapper.unmount();
  });

  it("falls back to the numeric assembly_id when no human label is sent", async () => {
    mockedSearch.mockResolvedValue({
      query: "x",
      results: [
        { id: "g", type: "gene", name: "g", url: "/genes/g", assembly_id: 4 },
      ],
      by_type: { gene: 1 },
      by_assembly: { "1": 1 },
      ambiguous: false,
      cursor: null,
      next_cursor: null,
      has_more: false,
      total_count: 1,
    } as never);

    const wrapper = await mountSearch({ q: "x" });

    // A version must never be silently omitted: the id is shown when the label
    // is absent (DB-CORE assembly contract).
    expect(wrapper.find('[data-testid="search-result-meta"]').text()).toContain("4");
    wrapper.unmount();
  });
});
