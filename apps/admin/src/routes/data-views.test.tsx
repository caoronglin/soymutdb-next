/**
 * Multi-dimensional data-view console.
 *
 * The workspace persists presentation only, so the page's contract is that it
 * reads rows through the shared public API client, never invents a source, and
 * reports failures per region instead of showing an empty grid that reads as
 * "no records exist".
 */
import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);
vi.mock("@/lib/antd", async () => (await import("../test/antd-double")));

const api = vi.hoisted(() => ({
  listDataViewSources: vi.fn(),
  listAdminDataViews: vi.fn(),
  createAdminDataView: vi.fn(),
  updateAdminDataView: vi.fn(),
  deleteAdminDataView: vi.fn(),
  fetchDataViewRows: vi.fn(),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    listDataViewSources: api.listDataViewSources,
    listAdminDataViews: api.listAdminDataViews,
    createAdminDataView: api.createAdminDataView,
    updateAdminDataView: api.updateAdminDataView,
    deleteAdminDataView: api.deleteAdminDataView,
    fetchDataViewRows: api.fetchDataViewRows,
  };
});

const DataViewsPage = (await import("./data-views")).default;

const SOURCES = {
  items: [
    {
      source: "genes",
      fields: ["gene_id", "symbol", "chromosome", "start_pos"],
      filter_fields: ["q", "chromosome"],
      default_fields: ["gene_id", "symbol"],
    },
    {
      source: "variants",
      fields: ["variant_id", "chromosome", "impact"],
      filter_fields: ["chromosome", "impact"],
      default_fields: ["variant_id"],
    },
    {
      source: "mutant_lines",
      fields: ["public_id", "name"],
      filter_fields: ["q"],
      default_fields: ["public_id"],
    },
  ],
};

const VIEW = {
  id: 5,
  name: "Genes by chromosome",
  source: "genes",
  view_type: "grid",
  visible_fields: ["gene_id", "symbol"],
  searchable_fields: [] as string[],
  filters: {},
  sort_field: null,
  sort_dir: null,
  group_field: null,
  title_field: null,
  page_size: 25,
  is_default: true,
  notes: null,
  visibility: "visible" as "visible" | "hidden",
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};

const ROW_PAGE = {
  items: [{ gene_id: "Glyma.01G000100", symbol: "Gm01" }],
  total: 1,
  nextCursor: null,
  hasMore: false,
};

beforeEach(() => {
  api.listDataViewSources.mockReset().mockResolvedValue(SOURCES);
  api.listAdminDataViews.mockReset().mockResolvedValue({ items: [VIEW], total: 1 });
  api.fetchDataViewRows.mockReset().mockResolvedValue(ROW_PAGE);
  api.createAdminDataView.mockReset().mockResolvedValue({ ...VIEW, id: 9, name: "New view" });
  api.updateAdminDataView.mockReset().mockResolvedValue(VIEW);
  api.deleteAdminDataView.mockReset().mockResolvedValue(undefined);
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <DataViewsPage />
    </QueryClientProvider>,
  );
}

describe("data-view workspace", () => {
  it("renders the saved view and fetches rows through the public client", async () => {
    renderPage();

    expect(await screen.findByText("Genes by chromosome")).toBeInTheDocument();
    expect(await screen.findByText("Glyma.01G000100")).toBeInTheDocument();
    expect(screen.getByText("Gm01")).toBeInTheDocument();
    expect(api.listAdminDataViews).toHaveBeenCalledWith({ source: "genes" });
    expect(api.fetchDataViewRows).toHaveBeenCalledWith(VIEW, { page: 1 });
  });

  it("reports a failed view list instead of rendering an empty workspace", async () => {
    api.listAdminDataViews.mockRejectedValue(new Error("views unavailable"));
    renderPage();

    const error = await screen.findByTestId("data-views-list-error");
    expect(error).toHaveAttribute("role", "alert");
    expect(screen.queryByText("admin.dataViews.empty")).toBeNull();
  });

  it("reports failed rows separately from the saved-view list", async () => {
    api.fetchDataViewRows.mockRejectedValue(new Error("rows unavailable"));
    renderPage();

    expect(await screen.findByText("Genes by chromosome")).toBeInTheDocument();
    const error = await screen.findByTestId("data-views-rows-error");
    expect(error).toHaveAttribute("role", "alert");
  });

  it("creates a view for the active source with its default visible fields", async () => {
    renderPage();
    await screen.findByText("Genes by chromosome");

    fireEvent.click(screen.getByRole("button", { name: "admin.dataViews.newView" }));
    fireEvent.change(await screen.findByTestId("data-views-name"), {
      target: { value: "My gene view" },
    });
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));

    await waitFor(() =>
      expect(api.createAdminDataView).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "My gene view",
          source: "genes",
          visible_fields: ["gene_id", "symbol"],
          filters: {},
        }),
      ),
    );
  });

  it("blocks saving a nameless view and explains why", async () => {
    renderPage();
    await screen.findByText("Genes by chromosome");

    fireEvent.click(screen.getByRole("button", { name: "admin.dataViews.newView" }));

    expect(await screen.findByTestId("data-views-draft-issue")).toHaveTextContent(
      "admin.dataViews.issue.name",
    );
    expect(screen.getByRole("button", { name: "common.save" })).toBeDisabled();
    expect(api.createAdminDataView).not.toHaveBeenCalled();
  });

  it("groups rows into kanban columns using the saved group field", async () => {
    api.listAdminDataViews.mockResolvedValue({
      items: [{ ...VIEW, view_type: "kanban", group_field: "chromosome" }],
      total: 1,
    });
    api.fetchDataViewRows.mockResolvedValue({
      items: [
        { gene_id: "G1", symbol: "A", chromosome: "01" },
        { gene_id: "G2", symbol: "B", chromosome: "02" },
      ],
      total: 2,
      nextCursor: null,
      hasMore: false,
    });
    renderPage();

    const board = await screen.findByTestId("data-views-kanban");
    expect(board).toHaveTextContent("01");
    expect(board).toHaveTextContent("02");
    expect(board).toHaveTextContent("G1");
    expect(board).toHaveTextContent("G2");
  });

  it("renders the gallery layout with every visible field", async () => {
    api.listAdminDataViews.mockResolvedValue({
      items: [{ ...VIEW, view_type: "gallery" }],
      total: 1,
    });
    renderPage();

    const gallery = await screen.findByTestId("data-views-gallery");
    expect(gallery).toHaveTextContent("Glyma.01G000100");
    expect(gallery).toHaveTextContent("symbol");
  });

  it("shows no search box when the view declares no searchable fields", async () => {
    renderPage();
    await screen.findByText("Genes by chromosome");

    expect(screen.queryByTestId("data-views-search")).toBeNull();
  });

  it("filters the loaded rows through the view's searchable fields only", async () => {
    api.listAdminDataViews.mockResolvedValue({
      items: [{ ...VIEW, searchable_fields: ["symbol"] }],
      total: 1,
    });
    api.fetchDataViewRows.mockResolvedValue({
      items: [
        { gene_id: "Glyma.01G000100", symbol: "Alpha" },
        { gene_id: "Glyma.02G000200", symbol: "Beta" },
      ],
      total: 2,
      nextCursor: null,
      hasMore: false,
    });
    renderPage();

    const search = await screen.findByTestId("data-views-search");
    fireEvent.change(search, { target: { value: "beta" } });

    await waitFor(() => expect(screen.queryByText("Alpha")).toBeNull());
    expect(screen.getByText("Beta")).toBeInTheDocument();
  });

  it("saves the searchable fields and visibility chosen in the editor", async () => {
    renderPage();
    await screen.findByText("Genes by chromosome");

    fireEvent.click(screen.getByRole("button", { name: "admin.dataViews.newView" }));
    fireEvent.change(await screen.findByTestId("data-views-name"), {
      target: { value: "Searchable genes" },
    });
    fireEvent.click(screen.getByTestId("data-views-searchable-symbol"));
    fireEvent.change(screen.getByTestId("data-views-visibility"), {
      target: { value: "hidden" },
    });
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));

    await waitFor(() =>
      expect(api.createAdminDataView).toHaveBeenCalledWith(
        expect.objectContaining({
          searchable_fields: ["symbol"],
          visibility: "hidden",
        }),
      ),
    );
  });

  it("asks the API for hidden views only when the operator enables them", async () => {
    renderPage();
    await screen.findByText("Genes by chromosome");
    expect(api.listAdminDataViews).toHaveBeenCalledWith({ source: "genes" });

    fireEvent.click(screen.getByTestId("data-views-show-hidden"));

    await waitFor(() =>
      expect(api.listAdminDataViews).toHaveBeenCalledWith({
        source: "genes",
        includeHidden: true,
      }),
    );
  });

  it("confirms before deleting and reports a rejected delete", async () => {
    api.deleteAdminDataView.mockRejectedValue(new Error("delete rejected"));
    renderPage();

    const [rowDelete] = await screen.findAllByRole("button", { name: "common.delete" });
    fireEvent.click(rowDelete);
    expect(api.deleteAdminDataView).not.toHaveBeenCalled();

    const buttons = await screen.findAllByRole("button", { name: "common.delete" });
    fireEvent.click(buttons[buttons.length - 1]);

    await waitFor(() => expect(api.deleteAdminDataView).toHaveBeenCalledWith(5));
    const error = await screen.findByTestId("data-views-delete-error");
    expect(error.closest('[role="alert"]')).not.toBeNull();
    expect(error).toHaveTextContent("delete rejected");
  });
});