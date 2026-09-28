// @vitest-environment jsdom
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { computed } from "vue";
import { describe, expect, it, vi } from "vitest";

const useCurrentUser = vi.fn();
vi.mock("../lib/current-user", () => ({
  useCurrentUser: () => useCurrentUser(),
}));

const getAnalysis = vi
  .fn()
  .mockResolvedValue({ job_id: "j1", status: "succeeded", created_at: "2026-01-01T00:00:00Z" });
vi.mock("@soymutdb/api-client", () => ({
  getAnalysis: (...args: unknown[]) => getAnalysis(...args),
  getAnalysisDownload: vi.fn(),
  // The header mounts the notification bell, whose composable reads these
  // through the same module. A whole-module factory mock must satisfy it too.
  fetchUnreadCount: vi.fn().mockResolvedValue({ unread_count: 0 }),
  listNotifications: vi.fn().mockResolvedValue({ items: [], total: 0, unread_count: 0 }),
  markNotificationsRead: vi.fn().mockResolvedValue({ marked: 0 }),
}));

// Installs the @soymutdb/ui-vue stub also used by the other view tests.
import "../test/mount-portal-view";
import AnalysesJobView from "./AnalysesJobView.vue";

function setAuth(isResearcher: boolean) {
  useCurrentUser.mockReturnValue({
    user: computed(() => (isResearcher ? { role_name: "researcher" } : null)),
    isResearcher: computed(() => isResearcher),
    isLoading: computed(() => false),
  });
}

async function mountJobView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/analyses/:jobId", component: AnalysesJobView },
      { path: "/:pathMatch(.*)*", component: { template: "<div />" } },
    ],
  });
  await router.push("/analyses/j1");
  const wrapper = mount(AnalysesJobView, {
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
  return { wrapper };
}

describe("AnalysesJobView researcher gate", () => {
  it("shows the gate instead of the job detail for an anonymous session", () => {
    setAuth(false);

    return mountJobView().then(({ wrapper }) => {
      expect(wrapper.find('[data-testid="researcher-gate-denied"]').exists()).toBe(true);
      expect(wrapper.find('[data-testid="analysis-job-detail"]').exists()).toBe(false);
      wrapper.unmount();
    });
  });

  it("keeps its own job branch for a researcher", async () => {
    setAuth(true);

    const { wrapper } = await mountJobView();
    await flushPromises();

    expect(wrapper.find('[data-testid="researcher-gate-denied"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="analysis-job-detail"]').exists()).toBe(true);
    // The route param drives the fetch (defineProps was never wired).
    expect(getAnalysis).toHaveBeenCalledWith("j1");
    wrapper.unmount();
  });
});
