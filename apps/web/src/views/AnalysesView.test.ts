// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";
import { computed } from "vue";
import { describe, expect, it, vi } from "vitest";

const useCurrentUser = vi.fn();
vi.mock("../lib/current-user", () => ({
  useCurrentUser: () => useCurrentUser(),
}));

vi.mock("@soymutdb/api-client", () => ({
  getAnalysis: vi.fn().mockResolvedValue({ job_id: "j1", status: "succeeded" }),
  // The header mounts the notification bell, whose composable reads these
  // through the same module. A whole-module factory mock must satisfy it too.
  fetchUnreadCount: vi.fn().mockResolvedValue({ unread_count: 0 }),
  listNotifications: vi.fn().mockResolvedValue({ items: [], total: 0, unread_count: 0 }),
  markNotificationsRead: vi.fn().mockResolvedValue({ marked: 0 }),
}));

vi.mock("@soymutdb/shared/analyses-local", () => ({
  readRecentJobs: () => [],
  forgetRecentJob: vi.fn(),
}));

import { mountPortalView } from "../test/mount-portal-view";
import AnalysesView from "./AnalysesView.vue";

function setAuth(isResearcher: boolean) {
  useCurrentUser.mockReturnValue({
    user: computed(() => (isResearcher ? { role_name: "researcher" } : null)),
    isResearcher: computed(() => isResearcher),
    isLoading: computed(() => false),
  });
}

describe("AnalysesView researcher gate", () => {
  it("shows the gate instead of the jobs list for an anonymous session", async () => {
    setAuth(false);

    const { wrapper } = mountPortalView(AnalysesView, { path: "/analyses" });

    expect(wrapper.find('[data-testid="researcher-gate-denied"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="researcher-gate-sign-in"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="analyses-table"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("keeps its own empty branch for a researcher", async () => {
    setAuth(true);

    const { wrapper } = mountPortalView(AnalysesView, { path: "/analyses" });
    await flushPromises();

    expect(wrapper.find('[data-testid="researcher-gate-denied"]').exists()).toBe(false);
    // The view's own loading/empty branch is not swallowed by the gate.
    expect(wrapper.find('[data-testid="analyses-empty"]').exists()).toBe(true);
    wrapper.unmount();
  });
});
