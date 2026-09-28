// @vitest-environment jsdom
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { defineComponent, h, type Component } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getSiteContent } from "@soymutdb/api-client";
import { useSiteContent, type SiteContentState } from "./site-content";
import type { SiteVariant } from "../stores/site-context";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, getSiteContent: vi.fn() };
});

const mockedGetSiteContent = vi.mocked(getSiteContent);

beforeEach(() => {
  mockedGetSiteContent.mockReset().mockResolvedValue({});
});

interface Harness {
  state: SiteContentState;
  queryClient: QueryClient;
  wrapper: ReturnType<typeof mount>;
  unmount: () => void;
}

/** Mount the composable in a real component so Vue Query/Pinia are installed. */
function mountSiteContent(variant?: SiteVariant): Harness {
  let state!: SiteContentState;
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Host: Component = defineComponent({
    setup() {
      state = useSiteContent(variant);
      return () => h("div");
    },
  });
  const wrapper = mount(Host, {
    global: {
      plugins: [createPinia(), [VueQueryPlugin, { queryClient }]],
    },
  });
  return { state, queryClient, wrapper, unmount: () => wrapper.unmount() };
}

describe("useSiteContent", () => {
  it("returns the caller fallback while no override is stored", async () => {
    mockedGetSiteContent.mockResolvedValue({});
    const { state, unmount } = mountSiteContent();
    await flushPromises();

    expect(state.get("hero.title", "默认标题")).toBe("默认标题");
    expect(state.get("missing.key", "fallback")).toBe("fallback");
    unmount();
  });

  it("prefers a stored override over the fallback", async () => {
    mockedGetSiteContent.mockResolvedValue({ "hero.title": "运营标题" });
    const { state, unmount } = mountSiteContent();
    await flushPromises();

    expect(state.get("hero.title", "默认标题")).toBe("运营标题");
    unmount();
  });

  it("returns an empty string when the fallback is omitted", async () => {
    mockedGetSiteContent.mockResolvedValue({});
    const { state, unmount } = mountSiteContent();
    await flushPromises();

    expect(state.get("hero.title")).toBe("");
    expect(state.get("hero.title")).not.toBeUndefined();
    unmount();
  });

  it("degrades to fallbacks when the request fails without throwing", async () => {
    mockedGetSiteContent.mockRejectedValue(new Error("401"));
    const { state, unmount } = mountSiteContent();
    await flushPromises();

    expect(state.get("nav.home", "首页")).toBe("首页");
    unmount();
  });

  it("does not share cached overrides between the external and internal variants", async () => {
    mockedGetSiteContent.mockImplementation(async (variant) =>
      variant === "internal" ? { "hero.title": "内部标题" } : { "hero.title": "外部标题" },
    );

    let external!: SiteContentState;
    let internal!: SiteContentState;
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const Host: Component = defineComponent({
      setup() {
        external = useSiteContent("external");
        internal = useSiteContent("internal");
        return () => h("div");
      },
    });
    const wrapper = mount(Host, {
      global: { plugins: [createPinia(), [VueQueryPlugin, { queryClient }]] },
    });
    await flushPromises();

    expect(external.get("hero.title", "fallback")).toBe("外部标题");
    expect(internal.get("hero.title", "fallback")).toBe("内部标题");

    const keys = queryClient
      .getQueryCache()
      .getAll()
      .map((query) => query.queryKey)
      .sort();
    expect(keys).toEqual(
      expect.arrayContaining([
        ["site", "content", "external"],
        ["site", "content", "internal"],
      ]),
    );
    wrapper.unmount();
  });

  it("always requests stored-only overrides for the store's variant", async () => {
    const { unmount } = mountSiteContent();
    await flushPromises();

    expect(mockedGetSiteContent).toHaveBeenCalledWith("external", { onlyOverrides: true });
    unmount();
  });
});
