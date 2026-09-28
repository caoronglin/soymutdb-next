// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";

import { getAssemblies, getFeaturedNews, getPageDefinition, getSiteContent } from "@soymutdb/api-client";
import { mountPortalView } from "../test/mount-portal-view";
import { currentLanguage, setLanguage, t } from "../lib/i18n";
import { beforeEach, describe, expect, it, vi } from "vitest";
import HomeView from "./HomeView.vue";
import { useSiteContextStore } from "../stores/site-context";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    getAssemblies: vi.fn(),
    getFeaturedNews: vi.fn(),
    getSiteContent: vi.fn(),
    getPageDefinition: vi.fn(),
  };
});

const mockedAssemblies = vi.mocked(getAssemblies);
const mockedFeatured = vi.mocked(getFeaturedNews);
const mockedPageDefinition = vi.mocked(getPageDefinition);
const mockedSiteContent = vi.mocked(getSiteContent);

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
  mockedSiteContent.mockReset().mockResolvedValue({});
  // No published page definition by default: the built-in resource band renders.
  mockedPageDefinition.mockReset().mockRejectedValue(new Error("404: no published definition"));
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

    // Live React order: database entry points, then the news/carousel row,
    // then the research tools. The database block must never be displaced by
    // marketing content (AGENTS.md database-core contract).
    const database = wrapper.get('[data-testid="database-entrypoints"]').element;
    const tools = wrapper.get('[data-testid="task-entries"]').element;
    const news = wrapper.get('[data-testid="home-news-section"]').element;
    expect(database.compareDocumentPosition(news) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(news.compareDocumentPosition(tools) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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

describe("HomeView editable site content", () => {
  it("renders today's localized copy when no override is stored", async () => {
    setLanguage("zh");
    mockedSiteContent.mockResolvedValue({});

    const { wrapper } = await mountHome();
    expect(mockedSiteContent).toHaveBeenCalledWith("external", { onlyOverrides: true });
    expect(wrapper.get('[data-testid="home-hero"] h1').text()).toBe(t("home.heroTitle"));
    expect(wrapper.get('[data-testid="task-gene-search"]').text()).toContain(
      t("home.toolGeneLabel"),
    );
    wrapper.unmount();
  });

  it("keeps Chinese copy instead of the English default when the override map is empty", async () => {
    setLanguage("zh");
    mockedSiteContent.mockResolvedValue({});

    const { wrapper } = await mountHome();
    const title = wrapper.get('[data-testid="home-hero"] h1').text();
    expect(title).toBe(t("home.heroTitle"));
    expect(title).not.toBe("Explore the unknown frontier of multi-species mutations");
    wrapper.unmount();
  });

  it("renders a stored hero/tool override under both languages", async () => {
    mockedSiteContent.mockResolvedValue({
      "hero.title": "OVERRIDE",
      "tool.gene.label": "OVERRIDE TOOL",
    });

    setLanguage("en");
    const { wrapper } = await mountHome();
    expect(wrapper.get('[data-testid="home-hero"] h1').text()).toBe("OVERRIDE");
    expect(wrapper.get('[data-testid="task-gene-search"]').text()).toContain("OVERRIDE TOOL");

    setLanguage("zh");
    await flushPromises();
    expect(wrapper.get('[data-testid="home-hero"] h1').text()).toBe("OVERRIDE");
    wrapper.unmount();
  });

  it("uses the override for the hero search placeholder", async () => {
    mockedSiteContent.mockResolvedValue({ "hero.searchPlaceholder": "搜索运营词" });

    const { wrapper } = await mountHome();
    expect(wrapper.get('[data-testid="home-search-input"]').attributes("placeholder")).toBe(
      "搜索运营词",
    );
    wrapper.unmount();
  });
});

describe("HomeView CMS resource band (page definition)", () => {
  it("renders the published resource_cards node instead of the built-in band", async () => {
    mockedPageDefinition.mockResolvedValue({
      id: "v1",
      page_id: "p1",
      version: 1,
      status: "published",
      definition: {
        schema_version: 2,
        theme_id: "scientific-light",
        layouts: { mobile: {}, tablet: {}, desktop: {} },
        data_sources: [],
        root: {
          type: "columns",
          props: {},
          children: [
            {
              type: "resource_cards",
              props: {
                heading: "CMS 资源",
                cards: [
                  { title: "CMS 下载", description: "运营维护的下载入口", href: "/downloads" },
                  { title: "外部链接", description: "运营维护的外部入口", href: "https://example.org/x" },
                  { title: "不安全", description: "会被降级成普通卡片", href: "javascript:alert(1)" },
                ],
              },
            },
          ],
        },
      },
    } as never);

    const { wrapper } = await mountHome();

    const band = wrapper.get('[data-testid="resource-cards"]');
    expect(band.text()).toContain("CMS 资源");
    const cards = band.findAll('[data-testid="resource-card"]');
    expect(cards).toHaveLength(3);
    // Internal route -> router link; external -> real anchor; unsafe -> article.
    expect(cards[0].attributes("href")).toBe("/downloads");
    expect(cards[1].attributes("href")).toBe("https://example.org/x");
    expect(cards[1].attributes("rel")).toContain("noopener");
    expect(cards[2].attributes("href")).toBeUndefined();
    expect(cards[2].element.tagName.toLowerCase()).toBe("article");
    // The built-in band must not render twice.
    expect(wrapper.find('[data-testid="resource-guide"] ul').exists()).toBe(false);
    wrapper.unmount();
  });

  it("keeps the built-in band when the definition has no resource_cards node", async () => {
    mockedPageDefinition.mockResolvedValue({
      id: "v1",
      page_id: "p1",
      version: 1,
      status: "published",
      definition: {
        schema_version: 2,
        theme_id: "scientific-light",
        layouts: { mobile: {}, tablet: {}, desktop: {} },
        data_sources: [],
        root: { type: "rich_text", props: { content: "<p>nothing here</p>" } },
      },
    } as never);

    const { wrapper } = await mountHome();

    expect(wrapper.find('[data-testid="resource-cards"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="resource-guide"]').text()).toContain("Resource guide");
    wrapper.unmount();
  });
});

describe("HomeView operator-set hero image", () => {
  it("renders nothing by default", async () => {
    const { wrapper } = await mountHome();

    expect(wrapper.find('[data-testid="home-hero-image"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("renders an absolute http(s) image with the operator value", async () => {
    mockedSiteContent.mockResolvedValue({ "hero.image": "https://cdn.example.org/hero.png" });

    const { wrapper } = await mountHome();

    const figure = wrapper.get('[data-testid="home-hero-image"]');
    const img = figure.get("img");
    expect(img.attributes("src")).toBe("https://cdn.example.org/hero.png");
    // The image is decorative-adjacent: it reuses the hero title as alt text.
    expect(img.attributes("alt")).toBeTruthy();
    expect(img.attributes("loading")).toBe("lazy");
    wrapper.unmount();
  });

  it("drops script-like and protocol-relative image targets", async () => {
    for (const unsafe of ["javascript:alert(1)", "data:image/svg+xml,<svg/>", "//evil.example.org/x.png"]) {
      mockedSiteContent.mockResolvedValue({ "hero.image": unsafe });

      const { wrapper } = await mountHome();
      expect(wrapper.find('[data-testid="home-hero-image"]').exists()).toBe(false);
      wrapper.unmount();
    }
  });
});
