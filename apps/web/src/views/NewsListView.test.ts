// @vitest-environment jsdom
import { mount, flushPromises } from "@vue/test-utils";
import { VueQueryPlugin, QueryClient } from "@tanstack/vue-query";
import { createPinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@soymutdb/ui-vue", () => ({
  ConfigProvider: { template: "<div><slot /></div>" },
  Tag: { template: "<span><slot /></span>" },
  createThemeConfig: () => ({}),
}));

// The portal shell is exercised by its own coverage; stub it so these
// assertions stay focused on the view and do not need pinia/header wiring.
vi.mock("../components/PortalLayout.vue", () => ({
  default: { template: "<div><slot /></div>" },
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, listNews: vi.fn() };
});

import { listNews } from "@soymutdb/api-client";
import NewsListView from "./NewsListView.vue";

const mockedList = vi.mocked(listNews);
beforeEach(() => mockedList.mockReset());

function article(id: string, title: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    title_en: title,
    title_zh: `${title} (zh)`,
    slug: `slug-${id}`,
    category: "update",
    cover_url: null,
    cover_asset_id: null,
    cover_alt_text: null,
    featured_sort: 0,
    carousel_group: null,
    carousel_sort: 0,
    status: "published",
    is_published: true,
    published_at: "2026-09-01T00:00:00Z",
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    ...overrides,
  };
}

async function mountView(query: Record<string, string> = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/news", name: "news", component: NewsListView },
      // Catch-all for the row/home links the view renders.
      { path: "/:pathMatch(.*)*", component: { template: "<div />" } },
    ],
  });
  router.push({ path: "/news", query });
  await router.isReady();
  const wrapper = mount(NewsListView, {
    global: {
      plugins: [
        createPinia(),
        router,
        [VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }],
      ],
    },
  });
  return { router, wrapper };
}

describe("NewsListView (Phase 3 parity)", () => {
  it("renders articles from the URL-scoped query", async () => {
    mockedList.mockResolvedValue({
      items: [article("1", "First story"), article("2", "Second story")],
      total: 2,
      page: 1,
      page_size: 10,
    } as never);

    const { wrapper } = await mountView();
    await flushPromises();
    await flushPromises();

    expect(mockedList).toHaveBeenCalledWith(undefined, 1, 10);
    expect(wrapper.findAll('[data-testid="news-row"]')).toHaveLength(2);
    expect(wrapper.text()).toContain("First story");
    expect(wrapper.find('[data-testid="news-total"]').text()).toContain("2 articles");
    wrapper.unmount();
  });

  it("commits a category change to the URL and refetches with it", async () => {
    mockedList.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 10 } as never);

    const { router, wrapper } = await mountView();
    await flushPromises();
    await wrapper.find('[data-testid="news-category-update"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.query.category).toBe("update");
    expect(mockedList).toHaveBeenLastCalledWith("update", 1, 10);
    wrapper.unmount();
  });

  it("paginates through the URL and keeps the category", async () => {
    mockedList.mockResolvedValue({
      items: [article("1", "First story")],
      total: 25,
      page: 1,
      page_size: 10,
    } as never);

    const { router, wrapper } = await mountView({ category: "news" });
    await flushPromises();
    await flushPromises();

    expect(wrapper.find('[data-testid="news-page"]').text()).toContain("Page 1 of 3");
    await wrapper.find('[data-testid="news-next"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.query.page).toBe("2");
    expect(router.currentRoute.value.query.category).toBe("news");
    expect(mockedList).toHaveBeenLastCalledWith("news", 2, 10);
    wrapper.unmount();
  });

  it("renders the Chinese title when the URL asks for zh", async () => {
    mockedList.mockResolvedValue({
      items: [article("1", "First story")],
      total: 1,
      page: 1,
      page_size: 10,
    } as never);

    const { wrapper } = await mountView({ lang: "zh" });
    await flushPromises();
    await flushPromises();

    expect(wrapper.text()).toContain("First story (zh)");
    wrapper.unmount();
  });
});
