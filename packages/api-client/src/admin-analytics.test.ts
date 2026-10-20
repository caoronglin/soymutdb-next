import { http } from "./auth";
import {
  getAdminAnalyticsSummary,
  type AdminAnalyticsSummary,
} from "./admin-analytics";

vi.mock("./auth", () => ({
  http: { get: vi.fn() },
}));

const mockGet = vi.mocked(http.get);

/** Labels the server can actually emit; the mock may not show anything else. */
const CANONICAL_PAGE_TEMPLATES = new Set([
  "/search",
  "/mutants/:publicId",
  "/other",
]);
const REFERRER_CATEGORIES = new Set(["direct", "search", "social", "other"]);
const EVENT_TYPES = new Set(["pageview", "click", "search", "widget", "other"]);
const DAY_LABEL = /^\d{4}-\d{2}-\d{2}$/;

/**
 * A response the real endpoint could produce: canonical labels only, no raw
 * gene id, no URL, and no search term.
 */
const SUMMARY: AdminAnalyticsSummary = {
  total_events: 42,
  unique_sessions: 7,
  events_by_type: [{ label: "pageview", count: 40 }],
  top_pages: [
    { label: "/search", count: 12 },
    { label: "/mutants/:publicId", count: 9 },
  ],
  top_referrers: [{ label: "direct", count: 20 }],
  top_searches: [],
  events_by_day: [{ label: "2026-01-01", count: 9 }],
  total_events_available: true,
  unique_sessions_available: true,
  events_by_type_available: true,
  top_pages_available: true,
  top_referrers_available: true,
  top_searches_available: false,
  events_by_day_available: true,
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

  it("passes every availability flag through so an unavailable store is not zero traffic", async () => {
    mockGet.mockResolvedValueOnce(SUMMARY);
    const summary = await getAdminAnalyticsSummary();
    expect(summary.top_pages_available).toBe(true);
    expect(summary.top_referrers_available).toBe(true);
    expect(summary.top_searches_available).toBe(false);
  });

  it("keeps the mock response inside the labels the server can emit", () => {
    // A fixture that reintroduces a raw gene id, a full referrer URL or a
    // search term would document behaviour the API cannot have.
    for (const item of SUMMARY.top_pages) {
      expect(CANONICAL_PAGE_TEMPLATES.has(item.label)).toBe(true);
    }
    for (const item of SUMMARY.top_referrers) {
      expect(REFERRER_CATEGORIES.has(item.label)).toBe(true);
    }
    for (const item of SUMMARY.events_by_type) {
      expect(EVENT_TYPES.has(item.label)).toBe(true);
    }
    for (const item of SUMMARY.events_by_day) {
      expect(DAY_LABEL.test(item.label)).toBe(true);
    }
    expect(SUMMARY.top_searches).toEqual([]);
  });
});