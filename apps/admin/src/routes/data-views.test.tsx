/**
 * Multi-dimensional data views: one saved view, one table.
 *
 * The table is also the field configuration, so the page's contract is:
 * (1) rows come from the shared public API client and never from a second query
 * path, (2) each column header writes exactly one partial `PUT` for the switch
 * it toggles, applied optimistically, and (3) a rejected write puts the cached
 * view back instead of leaving the UI claiming a change the server never took.
 *
 * The client double below keeps the saved view as state: a patch is echoed back
 * the way the API does, so a test that asserts on the rendered column set is
 * asserting the same convergence the page gets after its post-write refetch.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { messageCalls } from "../test/antd-double";

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
  source: "genes" as const,
  view_type: "grid" as "grid" | "kanban" | "gallery",
  visible_fields: ["gene_id", "symbol"],
  searchable_fields: [] as string[],
  filters: {} as Record<string, string>,
  sort_field: null as string | null,
  sort_dir: null as "asc" | "desc" | null,
  group_field: null as string | null,
  title_field: null as string | null,
  page_size: 25,
  is_default: true,
  notes: null as string | null,
  visibility: "visible" as "visible" | "hidden",
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};

/** The saved view as the server currently holds it. */
let savedView = { ...VIEW };

function replyToPatch(_id: number, patch: Record<string, unknown>) {
  savedView = { ...savedView, ...patch };
  return Promise.resolve(savedView);
}

const ROW_PAGE = {
  items: [
    { gene_id: "Glyma.01G000100", symbol: "Gm01" },
    { gene_id: "Glyma.02G000200", symbol: "Alpha" },
  ],
  total: 2,
  nextCursor: null,
  hasMore: false,
};

beforeEach(() => {
  savedView = { ...VIEW };
  messageCalls.length = 0;
  api.listDataViewSources.mockReset().mockResolvedValue(SOURCES);
  api.listAdminDataViews
    .mockReset()
    .mockImplementation(() => Promise.resolve({ items: [savedView], total: 1 }));
  api.fetchDataViewRows.mockReset().mockResolvedValue(ROW_PAGE);
  api.createAdminDataView.mockReset().mockResolvedValue({ ...VIEW, id: 9, name: "New view" });
  api.updateAdminDataView.mockReset().mockImplementation(replyToPatch);
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

describe("data-view table", () => {
  it("renders one column per visible field and the rows through the public client", async () => {
    renderPage();

    expect(await screen.findByText("Genes by chromosome")).toBeInTheDocument();
    expect(await screen.findByText("Glyma.01G000100")).toBeInTheDocument();
    expect(screen.getByTestId("field-header-gene_id")).toBeInTheDocument();
    expect(screen.getByTestId("field-header-symbol")).toBeInTheDocument();
    // A field that is not in `visible_fields` has no column.
    expect(screen.queryByTestId("field-header-chromosome")).toBeNull();
    expect(api.listAdminDataViews).toHaveBeenCalledWith({ source: "genes" });
    expect(api.fetchDataViewRows).toHaveBeenCalledWith(VIEW, { page: 1 });
  });

  it("keeps the toolbar above the table and out of a card", async () => {
    renderPage();
    await screen.findByText("Genes by chromosome");

    const toolbar = screen.getByTestId("data-views-toolbar");
    const table = screen.getByTestId("data-views-table");
    expect(toolbar.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(toolbar).getByTestId("data-views-summary")).toHaveTextContent(
      "admin.dataViews.summary",
    );
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

    const error = await screen.findByTestId("data-views-rows-error");
    expect(error).toHaveAttribute("role", "alert");
  });

  it("marks a field searchable with one partial patch and shows it immediately", async () => {
    // Never settles, so the assertion sees the optimistic state rather than the
    // server's echo of it.
    api.updateAdminDataView.mockReset().mockImplementation(() => new Promise(() => undefined));
    renderPage();
    await screen.findByText("Glyma.01G000100");

    fireEvent.click(screen.getByTestId("field-symbol-searchable"));

    await waitFor(() => expect(screen.getByTestId("field-symbol-searchable")).toBeChecked());
    expect(api.updateAdminDataView).toHaveBeenCalledWith(5, { searchable_fields: ["symbol"] });
    // The search box appears from the new state, not from a refetch.
    expect(screen.getByTestId("data-views-search")).toBeInTheDocument();
  });

  it("rolls the searchable switch back when the patch is rejected", async () => {
    api.updateAdminDataView.mockReset().mockRejectedValue(new Error("patch rejected"));
    renderPage();
    await screen.findByText("Glyma.01G000100");

    fireEvent.click(screen.getByTestId("field-symbol-searchable"));

    await waitFor(() => expect(screen.getByTestId("field-symbol-searchable")).not.toBeChecked());
    expect(screen.queryByTestId("data-views-search")).toBeNull();
    expect(messageCalls.some((call) => call.level === "error")).toBe(true);
  });

  it("hides a column with one partial patch", async () => {
    renderPage();
    await screen.findByText("Glyma.01G000100");

    fireEvent.click(screen.getByTestId("field-symbol-visible"));

    await waitFor(() =>
      expect(api.updateAdminDataView).toHaveBeenCalledWith(5, {
        visible_fields: ["gene_id"],
      }),
    );
    await waitFor(() => expect(screen.queryByTestId("field-header-symbol")).toBeNull());
    // The row identity column survives: one field always stays visible.
    expect(screen.getByTestId("field-header-gene_id")).toBeInTheDocument();
  });

  it("refuses to hide the last visible column", async () => {
    savedView = { ...VIEW, visible_fields: ["gene_id"] };
    renderPage();
    await screen.findByText("Glyma.01G000100");

    const lastSwitch = screen.getByTestId("field-gene_id-visible");
    expect(lastSwitch).toBeDisabled();
    fireEvent.click(lastSwitch);
    expect(api.updateAdminDataView).not.toHaveBeenCalled();
  });

  it("adds a field that is not a column yet", async () => {
    renderPage();
    await screen.findByText("Glyma.01G000100");

    fireEvent.change(screen.getByTestId("data-views-add-field"), {
      target: { value: "chromosome" },
    });

    await waitFor(() =>
      expect(api.updateAdminDataView).toHaveBeenCalledWith(5, {
        visible_fields: ["gene_id", "symbol", "chromosome"],
      }),
    );
    await waitFor(() => expect(screen.getByTestId("field-header-chromosome")).toBeInTheDocument());
  });

  it("moves a column with the keyboard reorder buttons", async () => {
    renderPage();
    await screen.findByText("Glyma.01G000100");

    const header = screen.getByTestId("field-header-gene_id");
    fireEvent.click(
      within(header).getByRole("button", { name: "admin.dataViews.field.moveRightAria" }),
    );

    await waitFor(() =>
      expect(api.updateAdminDataView).toHaveBeenCalledWith(5, {
        visible_fields: ["symbol", "gene_id"],
      }),
    );
  });

  it("shows no search box when the view declares no searchable fields", async () => {
    renderPage();
    await screen.findByText("Genes by chromosome");

    expect(screen.queryByTestId("data-views-search")).toBeNull();
  });

  it("filters the loaded rows through the view's searchable fields only", async () => {
    savedView = { ...VIEW, searchable_fields: ["symbol"] };
    renderPage();

    const search = await screen.findByTestId("data-views-search");
    fireEvent.change(search, { target: { value: "alpha" } });

    await waitFor(() => expect(screen.queryByText("Glyma.01G000100")).toBeNull());
    expect(screen.getByText("Glyma.02G000200")).toBeInTheDocument();
  });

  it("creates a view from the source's default columns", async () => {
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
          searchable_fields: [],
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

  it("saves the visibility chosen in the drawer", async () => {
    renderPage();
    await screen.findByText("Genes by chromosome");

    fireEvent.click(screen.getByRole("button", { name: "admin.dataViews.newView" }));
    fireEvent.change(await screen.findByTestId("data-views-name"), {
      target: { value: "Hidden genes" },
    });
    fireEvent.change(screen.getByTestId("data-views-visibility"), {
      target: { value: "hidden" },
    });
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));

    await waitFor(() =>
      expect(api.createAdminDataView).toHaveBeenCalledWith(
        expect.objectContaining({ visibility: "hidden" }),
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

  it("presents a view saved as a board as a table and says so", async () => {
    savedView = { ...VIEW, view_type: "kanban", group_field: "symbol" };
    renderPage();

    expect(await screen.findByTestId("data-views-layout-note")).toHaveTextContent(
      "admin.dataViews.layoutNote.kanban",
    );
    expect(screen.getByTestId("data-views-table")).toBeInTheDocument();
    expect(screen.getByTestId("field-header-symbol")).toBeInTheDocument();
  });

  it("confirms before deleting and reports a rejected delete", async () => {
    api.deleteAdminDataView.mockRejectedValue(new Error("delete rejected"));
    renderPage();
    await screen.findByText("Glyma.01G000100");

    // The toolbar action is disabled until a view is active, so the click has to
    // wait for the saved-view list rather than for the button to exist.
    fireEvent.click(screen.getByTestId("data-views-delete"));
    expect(api.deleteAdminDataView).not.toHaveBeenCalled();

    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "common.delete" }));

    await waitFor(() => expect(api.deleteAdminDataView).toHaveBeenCalledWith(5));
    const error = await screen.findByTestId("data-views-delete-error");
    expect(error.closest('[role="alert"]')).not.toBeNull();
    expect(error).toHaveTextContent("delete rejected");
  });
});