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
  return { ...actual, getDownloadFiles: vi.fn() };
});

import { getDownloadFiles } from "@soymutdb/api-client";
import DownloadsView from "./DownloadsView.vue";

const mocked = vi.mocked(getDownloadFiles);
beforeEach(() => mocked.mockReset());

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
});
