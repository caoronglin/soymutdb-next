// @vitest-environment jsdom
//
// REGRESSION — internal authorized search distinguishes public_id from internal_id.
//
// Invariant (DB-CORE identity contract): on the internal site the handwritten
// `internalSearch` client is called, each result row renders BOTH ids, and each
// copy control copies its own value (including the clipboard-absent fallback);
// on the external site the global path is unchanged and neither the internal
// token nor any internal control leaks into the DOM.
// Guards: the `internalSearch` client in @soymutdb/api-client and the internal
// result set / copy controls in SearchView.vue.
// Source (ablation): docs/dev/ablation/2026-09-26/frontend.md §3 「UI-02 internal
// 双 id」row + §4 GAP-UI02; README.md §3 G2; opt-c-internal-ui.md §2 「测试」and
// §3 RED (4 failed before the client + UI landed). Hardened by OPT-06 because
// the old `not.toContain("internal_id")` matched only the field name.
// If this is RED: internal users can no longer tell or copy the two identities,
// an internal id leaked onto the external site, or the copy fallback broke.
//
// Every id assertion is value-sensitive in BOTH directions (positive on the
// expected token AND negative on the other id), so swapping public_id <->
// internal_id or internal/external wiring flips the suite.
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
  return {
    ...actual,
    globalSearch: vi.fn(),
    internalSearch: vi.fn(),
    getReleaseId: () => "2026.09",
  };
});

import { globalSearch, internalSearch } from "@soymutdb/api-client";
import SearchView from "../views/SearchView.vue";

const mockedSearch = vi.mocked(globalSearch);
const mockedInternal = vi.mocked(internalSearch);

const PUBLIC_ID = "SM7QF3Z";
const INTERNAL_ID = "node-42";

const emptySearchResponse = {
  query: PUBLIC_ID,
  results: [],
  by_type: {},
  by_assembly: {},
  ambiguous: false,
  cursor: null,
  next_cursor: null,
  has_more: false,
  total_count: 0,
};

const writeText = vi.fn(async (_value: string) => {});

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

beforeEach(() => {
  vi.unstubAllEnvs();
  mockedSearch.mockReset();
  mockedInternal.mockReset();
  writeText.mockReset();
  writeText.mockResolvedValue(undefined);
  // jsdom ships no clipboard; install a spy so the copy control is exercised
  // against the same call the browser would receive.
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("ABLATION UI-02: internal search client + UI presence", () => {
  it("ships a handwritten internalSearch client (behind the module mock)", async () => {
    // `importActual` bypasses this file's mock so the assertion is about the
    // real package surface, not the test double.
    const actualClient =
      await vi.importActual<typeof import("@soymutdb/api-client")>("@soymutdb/api-client");
    // (`in` is used because a missing get on the vitest proxy throws.)
    expect("internalSearch" in actualClient).toBe(true);
    expect(typeof actualClient.internalSearch).toBe("function");
    // The generic wrapper still targets /search only.
    expect(typeof actualClient.globalSearch).toBe("function");
  });

  it("internal site: renders the internal result set with BOTH ids value-sensitively", async () => {
    vi.stubEnv("VITE_SITE_VARIANT", "internal");
    mockedSearch.mockResolvedValue(emptySearchResponse as never);
    mockedInternal.mockResolvedValue({
      query: PUBLIC_ID,
      mutants: [
        {
          entity_type: "mutant_line",
          public_id: PUBLIC_ID,
          internal_id: INTERNAL_ID,
          name: "line-A",
          matched_field: "public_id",
          match_type: "exact",
          is_public: true,
          url: "/mutants/SM7QF3Z",
        },
      ],
      genes: [],
      total_count: 1,
    } as never);

    const wrapper = await mountSearch({ q: PUBLIC_ID });

    expect(mockedInternal).toHaveBeenCalledTimes(1);
    expect(mockedInternal).toHaveBeenCalledWith(
      PUBLIC_ID,
      expect.objectContaining({ limit: 20 }),
    );

    const row = wrapper.find('[data-testid="search-internal-row"]');
    expect(row.exists()).toBe(true);

    const publicCell = row.find('[data-testid="internal-public-id"]');
    const internalCell = row.find('[data-testid="internal-internal-id"]');
    // Positive: each cell carries its own identifier.
    expect(publicCell.text()).toBe(PUBLIC_ID);
    expect(internalCell.text()).toBe(INTERNAL_ID);
    // Negative (value-sensitive): a swapped binding flips both of these.
    expect(publicCell.text()).not.toBe(INTERNAL_ID);
    expect(internalCell.text()).not.toBe(PUBLIC_ID);

    // A copy control per id, each wired to its own value.
    const copyPublic = row.find('[data-testid="copy-public-id"]');
    const copyInternal = row.find('[data-testid="copy-internal-id"]');
    expect(copyPublic.attributes("data-copy-value")).toBe(PUBLIC_ID);
    expect(copyInternal.attributes("data-copy-value")).toBe(INTERNAL_ID);
    expect(copyPublic.attributes("data-copy-value")).not.toBe(INTERNAL_ID);
    expect(copyInternal.attributes("data-copy-value")).not.toBe(PUBLIC_ID);

    // Clicking each control copies THAT id — also swap-sensitive.
    await copyInternal.trigger("click");
    await flushPromises();
    expect(writeText).toHaveBeenCalledWith(INTERNAL_ID);
    await copyPublic.trigger("click");
    await flushPromises();
    expect(writeText).toHaveBeenCalledWith(PUBLIC_ID);

    wrapper.unmount();
  });

  it("internal site: does not throw when navigator.clipboard is absent (jsdom fallback)", async () => {
    vi.stubEnv("VITE_SITE_VARIANT", "internal");
    // Remove the spy installed in beforeEach: the fallback path must survive.
    Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
    mockedSearch.mockResolvedValue(emptySearchResponse as never);
    mockedInternal.mockResolvedValue({
      query: PUBLIC_ID,
      mutants: [
        {
          entity_type: "mutant_line",
          public_id: PUBLIC_ID,
          internal_id: INTERNAL_ID,
          name: "line-A",
          matched_field: "public_id",
          match_type: "exact",
          is_public: true,
        },
      ],
      genes: [],
      total_count: 1,
    } as never);

    const wrapper = await mountSearch({ q: PUBLIC_ID });
    const copyInternal = wrapper.find('[data-testid="copy-internal-id"]');
    await copyInternal.trigger("click");
    await flushPromises();
    expect(copyInternal.exists()).toBe(true);
    wrapper.unmount();
  });

  it("external site: the global path is unchanged and no internal surface appears", async () => {
    // No stub -> resolveSiteVariant defaults to "external".
    mockedSearch.mockResolvedValue({
      ...emptySearchResponse,
      // The global payload may carry an internal token; the external row must
      // not leak it, and must not call the internal endpoint.
      results: [
        {
          id: PUBLIC_ID,
          type: "gene",
          name: PUBLIC_ID,
          url: "/genes/SM7QF3Z",
          internal_id: INTERNAL_ID,
        },
      ],
      total_count: 1,
    } as never);

    const wrapper = await mountSearch({ q: PUBLIC_ID });

    expect(mockedSearch).toHaveBeenCalledTimes(1);
    expect(mockedInternal).not.toHaveBeenCalled();

    const row = wrapper.find('[data-testid="search-result-row"]');
    expect(row.exists()).toBe(true);
    expect(row.attributes("data-url")).toBe("/genes/SM7QF3Z");
    // Public id visible, internal token absent from the rendered row.
    expect(row.text()).toContain(PUBLIC_ID);
    expect(row.text()).not.toContain(INTERNAL_ID);

    expect(wrapper.find('[data-testid="search-internal-results"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="copy-public-id"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="copy-internal-id"]').exists()).toBe(false);

    wrapper.unmount();
  });
});
