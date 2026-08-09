/**
 * Admin news list interaction tests (B3) — pagination, filtering, reset,
 * and loading state.
 *
 * These exercise the rendered ProTable with @testing-library/user-event:
 * - pagination: clicking a page triggers listAdminNews with the new page
 * - filter: typing in search fields + submitting maps params via
 *   buildAdminNewsQuery
 * - reset: resetting the search form restores default params
 * - loading: an unresolved request shows the AntD spin indicator
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { App as AntdApp } from "antd";
import "@testing-library/jest-dom/vitest";
import NewsListPage from "./index";
import { listAdminNews } from "@soymutdb/api-client";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@tanstack/react-router", () => ({
  useRouter: () => ({ navigate: vi.fn() }),
}));

vi.mock("@soymutdb/api-client", () => ({
  deleteNews: vi.fn(),
  listAdminNews: vi.fn(),
}));

const listAdminNewsMock = vi.mocked(listAdminNews);

function makeArticle(id: number | string, title: string) {
  return {
    id: String(id),
    title_en: title,
    title_zh: null,
    slug: `article-${id}`,
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
  } as unknown as import("@soymutdb/api-client").NewsSummary;
}

function renderPage() {
  return render(
    <AntdApp>
      <NewsListPage />
    </AntdApp>,
  );
}

/** ProTable search form submit button — AntD renders "查 询" (query). */
const QUERY_BTN = /查\s*询|quer/i;
/** ProTable search form reset button — AntD renders "重 置" (reset). */
const RESET_BTN = /重\s*置|reset/i;

beforeEach(() => {
  listAdminNewsMock.mockReset();
  listAdminNewsMock.mockResolvedValue({
    items: [makeArticle(1, "Article One")],
    total: 30,
    page: 1,
    page_size: 10,
  });
});

// --- pagination -----------------------------------------------------------

describe("NewsListPage pagination", () => {
  it("fetches page 2 when the next page is clicked", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Article One");

    // AntD Pagination page 2 button (aria label "page 2").
    const page2 = await screen.findByRole("listitem", { name: /2/i });
    await user.click(page2);

    await waitFor(() => {
      expect(listAdminNewsMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ page: 2 }),
      );
    });
  });
});

// --- filter / search ------------------------------------------------------

describe("NewsListPage filtering", () => {
  it("maps title search input to the backend search param on submit", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Article One");

    // ProTable search form: title_en field (label association via htmlFor).
    const titleInput = screen.getByLabelText("admin.news.columns.title");
    await user.type(titleInput, "EMS mutant");

    const submit = screen.getByRole("button", { name: QUERY_BTN });
    await user.click(submit);

    await waitFor(() => {
      expect(listAdminNewsMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ search: "EMS mutant" }),
      );
    });
  });

  it("maps category input to the category param on submit", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Article One");

    const categoryInput = screen.getByLabelText("admin.news.columns.category");
    await user.type(categoryInput, "updates");

    const submit = screen.getByRole("button", { name: QUERY_BTN });
    await user.click(submit);

    await waitFor(() => {
      expect(listAdminNewsMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ category: "updates" }),
      );
    });
  });
});

// --- reset ----------------------------------------------------------------

describe("NewsListPage reset", () => {
  it("restores default params after resetting the search form", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Article One");

    // Apply a filter first.
    const titleInput = screen.getByLabelText("admin.news.columns.title");
    await user.type(titleInput, "EMS");
    const submit = screen.getByRole("button", { name: QUERY_BTN });
    await user.click(submit);
    await waitFor(() => {
      expect(listAdminNewsMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ search: "EMS" }),
      );
    });

    // Reset button clears the form and re-fetches with defaults.
    const reset = screen.getByRole("button", { name: RESET_BTN });
    await user.click(reset);

    await waitFor(() => {
      expect(listAdminNewsMock).toHaveBeenLastCalledWith({
        page: 1,
        page_size: 10,
      });
    });
  });
});

// --- loading state --------------------------------------------------------

describe("NewsListPage loading state", () => {
  it("shows the AntD spinner while the request is pending", async () => {
    let resolveRequest: (
      value: import("@soymutdb/api-client").AdminNewsListResponse,
    ) => void = () => {};
    listAdminNewsMock.mockImplementation(
      () =>
        new Promise<
          import("@soymutdb/api-client").AdminNewsListResponse
        >((resolve) => {
          resolveRequest = resolve;
        }),
    );

    renderPage();
    // ProTable renders an antd Spin while loading (no ARIA role — the
    // loading wrapper carries .ant-spin / aria-busy on the table).
    await waitFor(() => {
      expect(document.querySelector(".ant-spin")).not.toBeNull();
    });
    const busyTable = document.querySelector("[aria-busy='true']");
    expect(busyTable).not.toBeNull();

    // Resolve the request to let the component settle (avoid act warnings).
    resolveRequest({
      items: [makeArticle(1, "Article One")],
      total: 1,
      page: 1,
      page_size: 10,
    });
    await screen.findByText("Article One");
  });
});
