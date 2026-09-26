// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mountAdminView } from "../test/support";

import {
  getAdminAnalyticsSummary,
  type AdminAnalyticsSummary,
} from "@soymutdb/api-client";
import AnalyticsSettingsView from "./AnalyticsSettingsView.vue";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, getAdminAnalyticsSummary: vi.fn() };
});

const SUMMARY: AdminAnalyticsSummary = {
  total_events: 1234,
  unique_sessions: 56,
  events_by_type: [{ label: "pageview", count: 1200 }],
  top_pages: [{ label: "/search", count: 90 }],
  top_referrers: [{ label: "https://example.org", count: 8 }],
  top_searches: [{ label: "Glyma.01G000100", count: 12 }],
  events_by_day: [{ label: "2026-01-01", count: 40 }],
};

beforeEach(() => {
  vi.mocked(getAdminAnalyticsSummary).mockReset().mockResolvedValue(SUMMARY);
});

describe("AnalyticsSettingsView", () => {
  it("renders the server summary instead of placeholder zeros", async () => {
    const { wrapper } = mountAdminView(AnalyticsSettingsView, { path: "/analytics-settings" });
    await flushPromises();

    expect(vi.mocked(getAdminAnalyticsSummary)).toHaveBeenCalledWith({ days: 7 });
    expect(wrapper.get('[data-testid="analytics-total-events"]').text()).toBe("1234");
    expect(wrapper.get('[data-testid="analytics-unique-sessions"]').text()).toBe("56");
    expect(wrapper.get('[data-testid="analytics-top-searches"]').text()).toContain(
      "Glyma.01G000100",
    );
    wrapper.unmount();
  });

  it("refetches when the operator widens the window", async () => {
    const { wrapper } = mountAdminView(AnalyticsSettingsView, { path: "/analytics-settings" });
    await flushPromises();

    await wrapper.get('[data-testid="analytics-days"]').setValue(30);
    await flushPromises();

    expect(vi.mocked(getAdminAnalyticsSummary)).toHaveBeenLastCalledWith({ days: 30 });
    wrapper.unmount();
  });

  it("states that the summary is unavailable when the endpoint fails", async () => {
    vi.mocked(getAdminAnalyticsSummary).mockRejectedValueOnce(new Error("clickhouse down"));
    const { wrapper } = mountAdminView(AnalyticsSettingsView, { path: "/analytics-settings" });
    await flushPromises();

    expect(wrapper.find('[data-testid="analytics-error"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="analytics-summary"]').exists()).toBe(false);
    wrapper.unmount();
  });
});
