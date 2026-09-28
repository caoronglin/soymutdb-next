// @vitest-environment jsdom
//
// REGRESSION — SearchResult `match_type` / `cross_version` stay optional and the
// external result row consumes them defensively.
//
// Invariant: a payload WITH the new fields renders the match-type badge and a
// provenance-bearing cross-version link; an older payload WITHOUT them renders
// exactly as before and offers neither affordance. Because both fields are
// optional, old and new backends must both stay green.
// Guards: the external result row in SearchView.vue and the optional fields on
// `SearchResult` in @soymutdb/api-client.
// Source (ablation): docs/dev/ablation/2026-09-26/opt-c-internal-ui.md §2 「测试」
// and §3 RED (1 failed | 1 passed while the binding was absent);
// OPTIMIZATION-CHECKLIST.md OPT-06 records the W4 weak-assertion finding.
// If this is RED: the row stopped rendering an available affordance, or an older
// payload now crashes / renders extra chrome. The value-sensitive negative
// assertion (source id absent from the cross-version block) means a swapped
// binding cannot pass by matching a field name only.
import { mount, flushPromises } from "@vue/test-utils";
import { VueQueryPlugin, QueryClient } from "@tanstack/vue-query";
import { createPinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

const SOURCE_ID = "Glyma.01G000100";
const CROSS_ID = "Glyma.02G000200";

async function mountSearch() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/search", name: "search", component: SearchView }],
  });
  await router.push(`/search?q=${SOURCE_ID}`);
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
afterEach(() => vi.unstubAllEnvs());

describe("OPT-06: SearchResult match_type / cross_version are optional and defensive", () => {
  it("renders match_type and provenance-bearing cross-version links when present", async () => {
    mockedSearch.mockResolvedValue({
      query: SOURCE_ID,
      results: [
        {
          id: SOURCE_ID,
          type: "gene",
          name: SOURCE_ID,
          url: `/genes/${SOURCE_ID}`,
          match_type: "cross-version",
          cross_version: [
            {
              gene_accession: CROSS_ID,
              assembly_id: 2,
              assembly_name: "Wm82",
              assembly_version: "v5",
              relation_type: "alias",
              provenance_source: "gene_crosswalks",
              match_type: "cross-version",
            },
          ],
        },
      ],
      by_type: { gene: 1 },
      by_assembly: {},
      ambiguous: false,
      cursor: null,
      next_cursor: null,
      has_more: false,
      total_count: 1,
    } as never);

    const wrapper = await mountSearch();

    const badge = wrapper.find('[data-testid="search-result-match-type"]');
    expect(badge.exists()).toBe(true);
    expect(badge.text()).toBe("cross-version");

    const cross = wrapper.find('[data-testid="search-cross-version"]');
    expect(cross.exists()).toBe(true);
    // Positive on the linked accession, negative on the source row's id: a
    // swapped binding cannot satisfy both.
    expect(cross.text()).toContain(CROSS_ID);
    expect(cross.text()).not.toContain(SOURCE_ID);
    wrapper.unmount();
  });

  it("renders neither affordance when an older payload omits both fields", async () => {
    mockedSearch.mockResolvedValue({
      query: SOURCE_ID,
      results: [{ id: SOURCE_ID, type: "gene", name: SOURCE_ID, url: `/genes/${SOURCE_ID}` }],
      by_type: { gene: 1 },
      by_assembly: {},
      ambiguous: false,
      cursor: null,
      next_cursor: null,
      has_more: false,
      total_count: 1,
    } as never);

    const wrapper = await mountSearch();

    const row = wrapper.find('[data-testid="search-result-row"]');
    expect(row.exists()).toBe(true);
    expect(row.text()).toContain(SOURCE_ID);
    expect(wrapper.find('[data-testid="search-result-match-type"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="search-cross-version"]').exists()).toBe(false);
    wrapper.unmount();
  });
});
