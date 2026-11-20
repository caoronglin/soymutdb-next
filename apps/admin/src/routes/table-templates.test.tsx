/**
 * Table-template console contract.
 *
 * Promoting and deleting a template fired on a single click, with no
 * confirmation, even though the screen's own comment says every row carries its
 * own write action. Each write is now confirmed and a rejection is reported in
 * the dialog that asked for it.
 *
 * The species-instance registry that used to live on this page moved to
 * `/instances` (the only screen that owns those records); its write-path tests
 * live in `instances.test.tsx`.
 */
import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);
vi.mock("@/lib/antd", async () => (await import("../test/antd-double")));

const api = vi.hoisted(() => ({
  listTableViewTemplates: vi.fn(),
  updateTableViewTemplate: vi.fn(),
  deleteTableViewTemplate: vi.fn(),
  createTableViewTemplate: vi.fn(),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    listTableViewTemplates: api.listTableViewTemplates,
    updateTableViewTemplate: api.updateTableViewTemplate,
    deleteTableViewTemplate: api.deleteTableViewTemplate,
    createTableViewTemplate: api.createTableViewTemplate,
  };
});

const TableTemplatesPage = (await import("./table-templates")).default;

const TEMPLATE = {
  id: 7,
  name: "Mutation sites (with homologs)",
  kind: "mutation_sites",
  species: "Glycine max",
  site_variant: "external",
  release_id: null,
  columns: [{ key: "gene_id", label_zh: "基因 ID", label_en: "Gene ID", visible: true }],
  actions: { jbrowse: true, genome_preview: true },
  is_default: false,
};

/** The row buttons render the raw i18n key, because the call site has no
 *  `defaultValue`; the catalogue resolves it in the running application. */
const ROW_DELETE = "admin.tableViews.actionDelete";
const ROW_PROMOTE = "admin.tableViews.actionSetDefault";

beforeEach(() => {
  api.listTableViewTemplates.mockReset().mockResolvedValue({ items: [TEMPLATE], total: 1 });
  api.updateTableViewTemplate.mockReset().mockRejectedValue(new Error("promote rejected"));
  api.deleteTableViewTemplate.mockReset().mockRejectedValue(new Error("template delete rejected"));
  api.createTableViewTemplate.mockReset().mockResolvedValue(TEMPLATE);
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <TableTemplatesPage />
    </QueryClientProvider>,
  );
}

/** The template row's delete button labels itself with the row action key. */
async function deleteButtons() {
  return screen.findAllByRole("button", { name: ROW_DELETE });
}

describe("table-view write actions", () => {
  it("renders a failed template request as an error, not an empty list", async () => {
    api.listTableViewTemplates.mockRejectedValue(new Error("templates unavailable"));
    renderPage();
    expect(await screen.findByTestId("table-views-templates-error")).toHaveAttribute("role", "alert");
    expect(screen.queryByText("admin.tableViews.empty")).toBeNull();
  });

  it("no longer embeds the species-instance registry that /instances owns", async () => {
    renderPage();
    await deleteButtons();
    // One destination per record: the console registers and enables species
    // databases on /instances, not a second, weaker copy inside this page.
    expect(screen.queryByTestId("table-views-instances-error")).toBeNull();
    expect(screen.queryByText("admin.tableViews.instancesTitle")).toBeNull();
  });
  it("confirms before deleting a template and reports a rejected delete", async () => {
    renderPage();

    const [templateDelete] = await deleteButtons();
    fireEvent.click(templateDelete);

    expect(api.deleteTableViewTemplate).not.toHaveBeenCalled();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.deleteTableViewTemplate).toHaveBeenCalledWith(7));

    const error = await screen.findByTestId("table-views-delete-error");
    expect(error.closest('[role="alert"]')).not.toBeNull();
    expect(error).toHaveTextContent("template delete rejected");
  });

  it("confirms before promoting a template and reports a rejected promotion", async () => {
    renderPage();

    const promote = await screen.findByRole("button", { name: ROW_PROMOTE });
    fireEvent.click(promote);

    expect(api.updateTableViewTemplate).not.toHaveBeenCalled();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Set as default" }));
    await waitFor(() =>
      expect(api.updateTableViewTemplate).toHaveBeenCalledWith(7, { is_default: true }),
    );

    const error = await screen.findByTestId("table-views-promote-error");
    expect(error.closest('[role="alert"]')).not.toBeNull();
    expect(error).toHaveTextContent("promote rejected");
  });
});
