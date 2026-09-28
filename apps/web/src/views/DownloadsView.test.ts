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
  return {
    ...actual,
    getDownloadFiles: vi.fn(),
    getDownloadUrl: vi.fn(),
    getSiteContent: vi.fn(),
  };
});

import { getDownloadFiles, getDownloadUrl, getSiteContent } from "@soymutdb/api-client";
import { setLanguage, t } from "../lib/i18n";
import DownloadsView from "./DownloadsView.vue";

const mocked = vi.mocked(getDownloadFiles);
const mockedUrl = vi.mocked(getDownloadUrl);
const mockedSiteContent = vi.mocked(getSiteContent);
beforeEach(() => {
  setLanguage("en");
  mocked.mockReset();
  mockedUrl.mockReset();
  mockedSiteContent.mockReset().mockResolvedValue({});
});

function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/downloads", name: "downloads", component: DownloadsView }],
  });
  router.push("/downloads");
  return mount(DownloadsView, {
    global: {
      plugins: [
        createPinia(),
        router,
        [VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }],
      ],
    },
  });
}

describe("DownloadsView (Phase F)", () => {
  it("renders download files with a human size and no leaked direct URLs", async () => {
    mocked.mockResolvedValue([
      {
        id: "f1",
        name: "variants-v5.tsv.gz",
        description: "Variant facts",
        file_url: "https://minio.internal/bucket/key?sig=SECRET",
        file_size: 1536,
        category: "variants",
        download_count: 10,
        created_at: "2026-01-01T00:00:00Z",
      },
    ]);
    const wrapper = mountView();
    await flushPromises();
    await flushPromises();

    const rows = wrapper.findAll('[data-testid="download-row"]');
    expect(rows).toHaveLength(1);
    expect(wrapper.text()).toContain("variants-v5.tsv.gz");
    expect(wrapper.text()).toContain("1.5 KB");
    // The presigned/direct object URL must never be rendered into the DOM.
    expect(wrapper.html()).not.toContain("SECRET");
    expect(wrapper.html()).not.toContain("minio.internal");
    // A real download control exists: metadata alone is not a download page.
    expect(wrapper.find('[data-testid="download-action"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it("resolves a presigned URL on demand and opens it, not the raw object URL", async () => {
    mocked.mockResolvedValue([
      {
        id: "f1",
        name: "variants-v5.tsv.gz",
        description: null,
        file_url: "https://minio.internal/bucket/key?sig=SECRET",
        file_size: 1024,
        category: "variants",
        download_count: 1,
        created_at: "2026-01-01T00:00:00Z",
      },
    ]);
    mockedUrl.mockResolvedValue({
      url: "https://minio.internal/bucket/key?sig=PRESIGNED",
      expires_in: 300,
    });
    const open = vi.spyOn(window, "open").mockImplementation(() => null);

    const wrapper = mountView();
    await flushPromises();
    await flushPromises();
    await wrapper.find('[data-testid="download-action"]').trigger("click");
    await flushPromises();

    expect(mockedUrl).toHaveBeenCalledWith("f1");
    expect(open).toHaveBeenCalledWith(
      "https://minio.internal/bucket/key?sig=PRESIGNED",
      "_blank",
      "noopener,noreferrer",
    );
    open.mockRestore();
    wrapper.unmount();
  });

  it("falls back to the catalogue URL when presigning fails", async () => {
    mocked.mockResolvedValue([
      {
        id: "f1",
        name: "variants-v5.tsv.gz",
        description: null,
        file_url: "https://minio.internal/bucket/key?sig=SECRET",
        file_size: 1024,
        category: "variants",
        download_count: 1,
        created_at: "2026-01-01T00:00:00Z",
      },
    ]);
    mockedUrl.mockRejectedValue(new Error("presign unavailable"));
    const open = vi.spyOn(window, "open").mockImplementation(() => null);

    const wrapper = mountView();
    await flushPromises();
    await flushPromises();
    await wrapper.find('[data-testid="download-action"]').trigger("click");
    await flushPromises();

    expect(open).toHaveBeenCalledWith(
      "https://minio.internal/bucket/key?sig=SECRET",
      "_blank",
      "noopener,noreferrer",
    );
    open.mockRestore();
    wrapper.unmount();
  });

  it("shows an empty state when there are no downloads", async () => {
    mocked.mockResolvedValue([]);
    const wrapper = mountView();
    await flushPromises();
    await flushPromises();
    expect(wrapper.find('[data-testid="downloads-empty"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it("renders today's localized title/subtitle when no override is stored", async () => {
    mocked.mockResolvedValue([]);
    const wrapper = mountView();
    await flushPromises();
    await flushPromises();

    expect(wrapper.get("h1").text()).toBe(t("downloads.title"));
    expect(wrapper.text()).toContain(t("downloads.subtitle"));
    wrapper.unmount();
  });

  it("renders a stored title/subtitle override", async () => {
    mockedSiteContent.mockResolvedValue({
      "downloads.title": "运营下载标题",
      "downloads.subtitle": "运营下载副标题",
    });
    mocked.mockResolvedValue([]);
    const wrapper = mountView();
    await flushPromises();
    await flushPromises();

    expect(wrapper.get("h1").text()).toBe("运营下载标题");
    expect(wrapper.text()).toContain("运营下载副标题");
    wrapper.unmount();
  });
});
