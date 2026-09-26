// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";

import { getAssemblies, getFeaturedNews } from "@soymutdb/api-client";
import { mountPortalView } from "../test/mount-portal-view";
import { currentLanguage, setLanguage } from "../lib/i18n";
import { beforeEach, describe, expect, it, vi } from "vitest";
import HomeView from "./HomeView.vue";
import { useSiteContextStore } from "../stores/site-context";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, getAssemblies: vi.fn(), getFeaturedNews: vi.fn() };
});

const mockedAssemblies = vi.mocked(getAssemblies);
const mockedFeatured = vi.mocked(getFeaturedNews);

const ASSEMBLIES = [
  { id: 5, name: "Wm82", version: "v5", species: "Glycine max", is_default: true },
  { id: 4, name: "Wm82", version: "v4", species: "Glycine max", is_default: false },
];

function article(overrides: Record<string, unknown> = {}) {
  return {
    id: "news-1",
    title_en: "First story",
    title_zh: "第一条动态",
    slug: "first-story",
    category: "update",
    cover_url: null,
    cover_asset_id: null,
    cover_alt_text: null,
    featured_sort: 1,
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

function featured(items: ReturnType<typeof article>[] = []) {
  return { featured: items, carousel: [] } as never;
}

beforeEach(() => {
  setLanguage("en");
  mockedAssemblies.mockReset().mockResolvedValue(ASSEMBLIES as never);
  mockedFeatured.mockReset().mockResolvedValue(featured());
});

async function mountHome() {
  const result = mountPortalView(HomeView, { path: "/" });
  await flushPromises();
  await flushPromises();
  return result;
}

describe("HomeView database entry point", () => {
  it("puts public database directories before tools and news", async () => {
    const { wrapper } = await mountHome();

    expect(wrapper.find('[data-testid="home-search-input"]').exists()).toBe(true);
    expect(wrapper.findAll('[data-testid="database-entry-list"] li')).toHaveLength(3);
    expect(wrapper.findAll('[data-testid="task-entries"] > li')).toHaveLength(5);
    expect(wrapper.find('[data-testid="database-genes"]').attributes("href")).toBe("/genes");
    expect(wrapper.find('[data-testid="database-variants"]').attributes("href")).toBe("/variants");
    expect(wrapper.find('[data-testid="database-mutants"]').attributes("href")).toBe("/mutants");

    const database = wrapper.get('[data-testid="database-entrypoints"]').element;
    const tools = wrapper.get('[data-testid="task-entries"]').element;
    const news = wrapper.get('[data-testid="home-news-section"]').element;
    expect(database.compareDocumentPosition(tools) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(tools.compareDocumentPosition(news) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    wrapper.unmount();
  });

  it("uses the assembly ID for selection and carries it into global search", async () => {
    const { wrapper, router, pinia } = await mountHome();

    await wrapper.get('[data-testid="assembly-select-4"]').trigger("click");
    expect(useSiteContextStore(pinia).assemblyKey).toBe("4");
    expect(wrapper.get('[data-testid="home-context"]').text()).toContain("Wm82 v4");

    await wrapper.get('[data-testid="home-search-input"]').setValue("Glyma.01G000100");
    await wrapper.get('[data-testid="home-search-submit"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query).toMatchObject({ q: "Glyma.01G000100", assembly: "4" });
    wrapper.unmount();
  });

  it("renders assemblies with versioned identity and the default marker", async () => {
    const { wrapper } = await mountHome();

    expect(wrapper.findAll('[data-testid="assemblies-list"] li')).toHaveLength(2);
    expect(wrapper.text()).toContain("Wm82 v5");
    expect(wrapper.text()).toContain("Wm82 v4");
    expect(wrapper.text()).toContain("Default");
    expect(wrapper.find('[data-testid="portal-context"]').text()).toContain("external");
    wrapper.unmount();
  });

  it("keeps homepage news in loading, error, and empty states distinct", async () => {
    let finishLoading!: (value: never) => void;
    mockedFeatured.mockReturnValueOnce(new Promise((resolve) => (finishLoading = resolve)) as never);
    const loading = mountPortalView(HomeView, { path: "/" });
    expect(loading.wrapper.find('[data-testid="home-news-loading"]').exists()).toBe(true);
    finishLoading(featured());
    await flushPromises();
    await flushPromises();
    loading.wrapper.unmount();

    mockedFeatured.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(featured());
    const failed = await mountHome();
    expect(failed.wrapper.find('[data-testid="home-news-error"]').exists()).toBe(true);
    await failed.wrapper.get('[data-testid="home-news-error"] button').trigger("click");
    await flushPromises();
    await flushPromises();
    expect(mockedFeatured).toHaveBeenCalledTimes(3);
    expect(failed.wrapper.find('[data-testid="home-news-empty"]').exists()).toBe(true);
    failed.wrapper.unmount();
  });

  it("uses the selected language and marks a missing Chinese title", async () => {
    setLanguage("zh");
    mockedFeatured.mockResolvedValueOnce(featured([article({ title_zh: null })]));

    const { wrapper } = await mountHome();
    expect(currentLanguage.value).toBe("zh");
    expect(wrapper.get('[data-testid="home-news-first-story"]').text()).toContain("First story");
    expect(wrapper.get('[data-testid="home-news-first-story"]').text()).toContain("暂无中文标题");
    wrapper.unmount();
  });
});

describe("HomeView core-only deployment (JBrowse optional)", () => {
  it("hides the JBrowse entry card when VITE_JBROWSE_ENABLED=0", async () => {
    vi.stubEnv("VITE_JBROWSE_ENABLED", "0");
    const { wrapper } = await mountHome();

    expect(wrapper.find('[data-testid="task-jbrowse"]').exists()).toBe(false);
    expect(wrapper.findAll('[data-testid="task-entries"] > li')).toHaveLength(4);
    expect(wrapper.find('[data-testid="task-gene-search"]').exists()).toBe(true);
    vi.unstubAllEnvs();
    wrapper.unmount();
  });

  it("keeps the JBrowse entry card by default", async () => {
    vi.stubEnv("VITE_JBROWSE_ENABLED", "1");
    const { wrapper } = await mountHome();

    expect(wrapper.find('[data-testid="task-jbrowse"]').exists()).toBe(true);
    vi.unstubAllEnvs();
    wrapper.unmount();
  });
});
