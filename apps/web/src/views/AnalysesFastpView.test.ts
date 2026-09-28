// @vitest-environment jsdom
import { computed } from "vue";
import { describe, expect, it, vi } from "vitest";

const useCurrentUser = vi.fn();
vi.mock("../lib/current-user", () => ({
  useCurrentUser: () => useCurrentUser(),
}));

vi.mock("@soymutdb/api-client", () => ({
  submitAnalysisFiles: vi.fn(),
  // The header mounts the notification bell, whose composable reads these
  // through the same module. A whole-module factory mock must satisfy it too.
  fetchUnreadCount: vi.fn().mockResolvedValue({ unread_count: 0 }),
  listNotifications: vi.fn().mockResolvedValue({ items: [], total: 0, unread_count: 0 }),
  markNotificationsRead: vi.fn().mockResolvedValue({ marked: 0 }),
}));

import { mountPortalView } from "../test/mount-portal-view";
import AnalysesFastpView from "./AnalysesFastpView.vue";

function setAuth(isResearcher: boolean) {
  useCurrentUser.mockReturnValue({
    user: computed(() => (isResearcher ? { role_name: "researcher" } : null)),
    isResearcher: computed(() => isResearcher),
    isLoading: computed(() => false),
  });
}

describe("AnalysesFastpView researcher gate", () => {
  it("hides the submission form from an anonymous session", () => {
    setAuth(false);

    const { wrapper } = mountPortalView(AnalysesFastpView, { path: "/analyses/fastp" });

    expect(wrapper.find('[data-testid="researcher-gate-denied"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="fastp-submit"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("renders the form for a researcher", () => {
    setAuth(true);

    const { wrapper } = mountPortalView(AnalysesFastpView, { path: "/analyses/fastp" });

    expect(wrapper.find('[data-testid="researcher-gate-denied"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="fastp-submit"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="fastp-files"]').exists()).toBe(true);
    wrapper.unmount();
  });
});
