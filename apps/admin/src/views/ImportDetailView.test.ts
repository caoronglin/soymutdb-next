// @vitest-environment jsdom
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";

import { adminImportsApi } from "@soymutdb/api-client";

import ImportDetailView from "./ImportDetailView.vue";

vi.mock("@soymutdb/ui-vue", () => ({
  ConfigProvider: { template: "<div><slot /></div>" },
  createThemeConfig: () => ({}),
  Button: {
    props: ["disabled", "type", "htmlType", "size"],
    emits: ["click"],
    template:
      '<button :disabled="disabled" @click="$emit(\'click\', $event)"><slot /></button>',
  },
  Tag: { props: ["color"], template: "<span><slot /></span>" },
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    adminImportsApi: {
      ...actual.adminImportsApi,
      get: vi.fn(),
      status: vi.fn(),
      retry: vi.fn(),
      cancel: vi.fn(),
    },
  };
});

const TASK = {
  id: 42,
  filename: "variants.vcf",
  type: "vcf",
  status: "failed",
  progress: 40,
  total_records: 100,
  processed_records: 40,
  submitted_by: "admin",
  file_path: "s3://bucket/variants.vcf",
  error_message: "conversion failed",
  submitted_at: "2026-09-25T00:00:00Z",
  completed_at: null,
};

const STATUS = {
  id: 42,
  status: "failed",
  celery_status: "FAILURE",
  progress: 40,
  processed_records: 40,
  total_records: 100,
  error_message: "conversion failed",
};

async function mountDetail() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/imports/:taskId", name: "import-detail", component: ImportDetailView },
      { path: "/imports", name: "imports", component: { template: "<div />" } },
    ],
  });
  await router.push("/imports/42");
  await router.isReady();
  const wrapper = mount(ImportDetailView, {
    attachTo: document.body,
    global: {
      plugins: [
        createPinia(),
        router,
        [
          VueQueryPlugin,
          { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
        ],
      ],
    },
  });
  await flushPromises();
  await flushPromises();
  return { wrapper, router };
}

beforeEach(() => {
  vi.mocked(adminImportsApi.get).mockReset().mockResolvedValue(TASK as never);
  vi.mocked(adminImportsApi.status).mockReset().mockResolvedValue(STATUS as never);
  vi.mocked(adminImportsApi.retry).mockReset().mockResolvedValue(TASK as never);
  vi.mocked(adminImportsApi.cancel).mockReset().mockResolvedValue(undefined as never);
});

describe("ImportDetailView (P1-06)", () => {
  it("shows the task, live status and offers retry for a failed task", async () => {
    const { wrapper } = await mountDetail();

    expect(vi.mocked(adminImportsApi.get)).toHaveBeenCalledWith(42);
    expect(vi.mocked(adminImportsApi.status)).toHaveBeenCalledWith(42);
    expect(wrapper.get('[data-testid="import-detail-status"]').text()).toContain("failed");
    expect(wrapper.get('[data-testid="import-detail-error-message"]').text()).toContain(
      "conversion failed",
    );
    expect(wrapper.find('[data-testid="import-detail-retry"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="import-detail-cancel"]').exists()).toBe(false);

    await wrapper.get('[data-testid="import-detail-retry"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(adminImportsApi.retry)).toHaveBeenCalledWith(42);
    wrapper.unmount();
  });

  it("offers cancel for an active task and calls the cancel endpoint", async () => {
    vi.mocked(adminImportsApi.get).mockResolvedValue({
      ...TASK,
      status: "running",
      error_message: null,
    } as never);
    vi.mocked(adminImportsApi.status).mockResolvedValue({
      ...STATUS,
      status: "running",
      celery_status: "STARTED",
      error_message: null,
    } as never);

    const { wrapper } = await mountDetail();

    expect(wrapper.find('[data-testid="import-detail-retry"]').exists()).toBe(false);
    await wrapper.get('[data-testid="import-detail-cancel"]').trigger("click");
    await flushPromises();
    expect(vi.mocked(adminImportsApi.cancel)).toHaveBeenCalledWith(42);
    wrapper.unmount();
  });
});
