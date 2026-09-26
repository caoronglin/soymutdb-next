// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mountAdminView } from "../test/support";

import {
  getAdminAnalyticsSummary,
  getReleases,
  type AdminAnalyticsSummary,
  type ReleaseSummary,
} from "@soymutdb/api-client";
import DashboardView from "./DashboardView.vue";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, getReleases: vi.fn(), getAdminAnalyticsSummary: vi.fn() };
});

const RELEASE: ReleaseSummary = {
  id: "rel-1",
  name: "2026-01",
  assembly_id: "asm-1",
  assembly_name: "Glyma.Wm82.a2.v1",
  status: "published",
  variant_count: 12,
  gene_count: 3,
  mutant_line_count: 4,
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

const SUMMARY: AdminAnalyticsSummary = {
  total_events: 1234,
  unique_sessions: 56,
  events_by_type: [{ label: "pageview", count: 1200 }],
  top_pages: [{ label: "/search", count: 90 }],
  top_referrers: [],
  top_searches: [{ label: "Glyma.01G000100", count: 12 }],
  events_by_day: [],
};

beforeEach(() => {
  vi.mocked(getReleases).mockReset().mockResolvedValue([RELEASE]);
  vi.mocked(getAdminAnalyticsSummary).mockReset().mockResolvedValue(SUMMARY);
});

describe("DashboardView", () => {
  it("renders the active release aggregate and the analytics summary", async () => {
    const { wrapper } = mountAdminView(DashboardView, { path: "/" });
    await flushPromises();

    expect(vi.mocked(getReleases)).toHaveBeenCalledWith({ page: 1, page_size: 50 });
    expect(vi.mocked(getAdminAnalyticsSummary)).toHaveBeenCalledWith({ days: 7 });
    expect(wrapper.get('[data-testid="dashboard-release-id"]').text()).toBe("rel-1");
    expect(wrapper.get('[data-testid="dashboard-variants"]').text()).toBe("12");
    expect(wrapper.get('[data-testid="dashboard-analytics-total-events"]').text()).toBe("1234");
    expect(wrapper.get('[data-testid="dashboard-analytics-unique-sessions"]').text()).toBe("56");
    wrapper.unmount();
  });

  it("states the releases and analytics empty states explicitly", async () => {
    vi.mocked(getReleases).mockResolvedValueOnce([]);
    vi.mocked(getAdminAnalyticsSummary).mockResolvedValueOnce({
      ...SUMMARY,
      total_events: 0,
      unique_sessions: 0,
      top_pages: [],
    });

    const { wrapper } = mountAdminView(DashboardView, { path: "/" });
    await flushPromises();

    expect(wrapper.find('[data-testid="dashboard-no-active"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="dashboard-releases-empty"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="dashboard-analytics-empty"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="dashboard-analytics-summary"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("keeps the analytics section independent when releases fail", async () => {
    vi.mocked(getReleases).mockRejectedValueOnce(new Error("api down"));
    const { wrapper } = mountAdminView(DashboardView, { path: "/" });
    await flushPromises();

    expect(wrapper.find('[data-testid="dashboard-error"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="dashboard-analytics-summary"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it("says analytics is unavailable when the summary endpoint fails", async () => {
    vi.mocked(getAdminAnalyticsSummary).mockRejectedValueOnce(new Error("clickhouse down"));
    const { wrapper } = mountAdminView(DashboardView, { path: "/" });
    await flushPromises();

    expect(wrapper.find('[data-testid="dashboard-analytics-error"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="dashboard-analytics-summary"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("refetches the summary when the operator widens the window", async () => {
    const { wrapper } = mountAdminView(DashboardView, { path: "/" });
    await flushPromises();

    await wrapper.get('[data-testid="dashboard-analytics-days"]').setValue(30);
    await flushPromises();

    expect(vi.mocked(getAdminAnalyticsSummary)).toHaveBeenLastCalledWith({ days: 30 });
    wrapper.unmount();
  });
});
