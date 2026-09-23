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

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, getNewsBySlug: vi.fn() };
});

import { getNewsBySlug } from "@soymutdb/api-client";
import NewsDetailView from "./NewsDetailView.vue";

const mockedDetail = vi.mocked(getNewsBySlug);
beforeEach(() => mockedDetail.mockReset());

function detail(overrides: Record<string, unknown> = {}) {
  return {
    id: "1",
    title_en: "First story",
    title_zh: "第一条",
    slug: "first-story",
    category: "news",
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
    content_en: "<p>Hello <strong>world</strong></p>",
    content_zh: "<p>你好</p>",
    ...overrides,
  };
}

async function mountView(query: Record<string, string> = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/news/:slug", name: "news-article", component: NewsDetailView },
      { path: "/:pathMatch(.*)*", component: { template: "<div />" } },
    ],
  });
  router.push({ path: "/news/first-story", query });
  await router.isReady();
  const wrapper = mount(NewsDetailView, {
    global: {
      plugins: [
        createPinia(),
        router,
        [VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }],
      ],
    },
  });
  return { wrapper, router };
}

describe("NewsDetailView (Phase 3 parity)", () => {
  it("renders the article title, date and body", async () => {
    mockedDetail.mockResolvedValue(detail() as never);

    const { wrapper } = await mountView();
    await flushPromises();
    await flushPromises();

    expect(mockedDetail).toHaveBeenCalledWith("first-story");
    expect(wrapper.find('[data-testid="news-detail-title"]').text()).toBe("First story");
    expect(wrapper.find('[data-testid="news-detail-date"]').text()).toBe("2026-09-01");
    expect(wrapper.find('[data-testid="news-detail-body"]').html()).toContain("Hello");
    wrapper.unmount();
  });

  it("sanitises CMS HTML before rendering it", async () => {
    mockedDetail.mockResolvedValue(
      detail({
        content_en:
          '<p>Safe</p><script>alert("xss")</script>' +
          '<img src="x" onerror="alert(1)">' +
          '<a href="javascript:alert(2)">link</a>',
      }) as never,
    );

    const { wrapper } = await mountView();
    await flushPromises();
    await flushPromises();

    const html = wrapper.find('[data-testid="news-detail-body"]').html();
    expect(html).toContain("Safe");
    expect(html).not.toContain("<script");
    expect(html).not.toContain("alert(");
    expect(html).not.toContain("onerror");
    expect(html).not.toContain("javascript:");
    wrapper.unmount();
  });

  it("renders the Chinese title and body when the URL asks for zh", async () => {
    mockedDetail.mockResolvedValue(detail() as never);

    const { wrapper } = await mountView({ lang: "zh" });
    await flushPromises();
    await flushPromises();

    expect(wrapper.find('[data-testid="news-detail-title"]').text()).toBe("第一条");
    expect(wrapper.find('[data-testid="news-detail-body"]').html()).toContain("你好");
    wrapper.unmount();
  });
});
