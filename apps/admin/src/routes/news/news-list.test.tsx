/**
 * Admin news list component tests (B3).
 *
 * Covers:
 * 1. request-parameter mapping — list form params (status/category/
 *    title_en/current/pageSize) are correctly forwarded to listAdminNews
 *    via buildAdminNewsQuery (pure-function unit tests) and through the
 *    rendered list request lifecycle (component test).
 * 2. error-state rendering — when listAdminNews rejects, the component
 *    shows the load-error toast and renders the empty state.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { App as AntdApp } from "../../lib/antd";
// Pulls in jest-dom matcher types (runtime registration is in setup.ts).
import "@testing-library/jest-dom/vitest";
import NewsListPage, { buildAdminNewsQuery } from "./index";
import { deleteNews, listAdminNews } from "@soymutdb/api-client";

// --- mocks ---------------------------------------------------------------

// The shared double keeps a stable `t` identity: an inline
// `() => ({ t: ... })` returns a new function per render and makes any
// component with `t` in an effect dependency loop forever. See test/mocks.ts.
vi.mock("react-i18next", async () => (await import("../../../test/mocks")).mockTranslation);

vi.mock("@tanstack/react-router", () => ({
  useRouter: () => ({ navigate: vi.fn() }),
}));

vi.mock("@soymutdb/api-client", () => ({
  deleteNews: vi.fn(),
  listAdminNews: vi.fn(),
}));

const listAdminNewsMock = vi.mocked(listAdminNews);
const deleteNewsMock = vi.mocked(deleteNews);

// --- helpers -------------------------------------------------------------

function makeArticle(overrides: Record<string, unknown> = {}) {
  return {
    id: "1",
    title_en: "Hello SoyMutDB",
    title_zh: null,
    slug: "hello-soymutdb",
    category: "news",
    status: "published",
    is_published: true,
    published_at: "2026-08-08T10:00:00Z",
    featured_sort: 0,
    carousel_group: null,
    carousel_sort: 0,
    cover_url: null,
    created_at: "2026-08-08T10:00:00Z",
    updated_at: "2026-08-08T10:00:00Z",
    ...overrides,
  } as unknown as import("@soymutdb/api-client").NewsSummary;
}

function renderPage() {
  return render(
    <AntdApp>
      <NewsListPage />
    </AntdApp>,
  );
}

beforeEach(() => {
  listAdminNewsMock.mockReset();
  deleteNewsMock.mockReset();
  listAdminNewsMock.mockResolvedValue({
    items: [makeArticle()],
    total: 1,
    page: 1,
    page_size: 10,
  });
});

// --- pure-function: request param mapping --------------------------------

describe("buildAdminNewsQuery", () => {
  it("maps defaults when no filters are present", () => {
    expect(buildAdminNewsQuery({})).toEqual({ page: 1, page_size: 10 });
  });

  it("maps current/pageSize to page/page_size", () => {
    expect(
      buildAdminNewsQuery({ current: 3, pageSize: 25 }),
    ).toEqual({ page: 3, page_size: 25 });
  });

  it("maps status select to status_filter", () => {
    expect(buildAdminNewsQuery({ status: "draft" })).toEqual({
      page: 1,
      page_size: 10,
      status_filter: "draft",
    });
  });

  it("maps title search to backend search param", () => {
    expect(buildAdminNewsQuery({ title_en: "EMS" })).toEqual({
      page: 1,
      page_size: 10,
      search: "EMS",
    });
  });

  it("maps category passthrough", () => {
    expect(buildAdminNewsQuery({ category: "news" })).toEqual({
      page: 1,
      page_size: 10,
      category: "news",
    });
  });

  it("combines all filters", () => {
    expect(
      buildAdminNewsQuery({
        current: 2,
        pageSize: 20,
        status: "archived",
        category: "updates",
        title_en: "genome",
      }),
    ).toEqual({
      page: 2,
      page_size: 20,
      status_filter: "archived",
      category: "updates",
      search: "genome",
    });
  });

  it("drops empty/undefined filter values", () => {
    expect(
      buildAdminNewsQuery({
        current: 1,
        pageSize: 10,
        status: undefined,
        category: "",
        title_en: "",
      }),
    ).toEqual({ page: 1, page_size: 10 });
  });
});

// --- component: request wiring + error state ------------------------------

describe("NewsListPage component", () => {
  it("calls listAdminNews on mount with default pagination", async () => {
    renderPage();
    await waitFor(() => {
      expect(listAdminNewsMock).toHaveBeenCalled();
    });
    expect(listAdminNewsMock).toHaveBeenCalledWith({
      page: 1,
      page_size: 10,
    });
  });

  it("renders rows from the API response", async () => {
    renderPage();
    expect(await screen.findByText("Hello SoyMutDB")).toBeTruthy();
  });

  it("shows the empty state when the API returns no rows", async () => {
    listAdminNewsMock.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 10,
    });
    renderPage();
    // emptyText is the raw i18n key because the translation hook is mocked.
    expect(await screen.findByText("admin.news.empty")).toBeTruthy();
  });

  it("shows load-error toast and the empty state when the request rejects", async () => {
    listAdminNewsMock.mockRejectedValue(new Error("boom"));
    renderPage();
    // The error toast message is rendered by AntD App message (async).
    expect(
      await screen.findByText(/admin\.news\.messages\.loadError.*boom/s),
    ).toBeTruthy();
    // Empty state renders after the failed request.
    expect(await screen.findByText("admin.news.empty")).toBeTruthy();
  });
});
