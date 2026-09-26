import { http } from "./auth";
import {
  getAdminAnalyticsSummary,
  type AdminAnalyticsSummary,
} from "./admin-analytics";

vi.mock("./auth", () => ({
  http: { get: vi.fn() },
}));

const mockGet = vi.mocked(http.get);

const SUMMARY: AdminAnalyticsSummary = {
  total_events: 42,
  unique_sessions: 7,
  events_by_type: [{ label: "pageview", count: 40 }],
  top_pages: [{ label: "/search", count: 12 }],
  top_referrers: [{ label: "https://example.org", count: 3 }],
  top_searches: [{ label: "Glyma.01G000100", count: 5 }],
  events_by_day: [{ label: "2026-01-01", count: 9 }],
};

beforeEach(() => {
  mockGet.mockReset();
});

describe("admin analytics summary client", () => {
  it("requests the summary for the configured window", async () => {
    mockGet.mockResolvedValueOnce(SUMMARY);
    await expect(getAdminAnalyticsSummary({ days: 30 })).resolves.toEqual(SUMMARY);
    expect(mockGet).toHaveBeenCalledWith("/admin/analytics/summary", {
      params: { days: "30" },
    });
  });

  it("lets the server pick the default window when no days are given", async () => {
    mockGet.mockResolvedValueOnce(SUMMARY);
    await getAdminAnalyticsSummary();
    expect(mockGet).toHaveBeenCalledWith("/admin/analytics/summary", { params: {} });
  });
});
