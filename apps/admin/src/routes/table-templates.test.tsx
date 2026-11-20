/**
 * Table-view console contract.
 *
 * The instance enable/disable switch and the instance delete button called
 * the API directly and chained only a `then(...)`, so a rejected write became
 * an unhandled promise rejection: the operator saw the old value and no
 * message. Promoting and deleting a template fired on a single click, with no
 * confirmation, even though the screen's own comment says every row carries
 * its own write action.
 */
import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);
vi.mock("@/lib/antd", async () => (await import("../test/antd-double")));

const api = vi.hoisted(() => ({
  listTableViewTemplates: vi.fn(),
  listSpeciesInstances: vi.fn(),
  updateTableViewTemplate: vi.fn(),
  deleteTableViewTemplate: vi.fn(),
  updateSpeciesInstance: vi.fn(),
  deleteSpeciesInstance: vi.fn(),
  createTableViewTemplate: vi.fn(),
  createSpeciesInstance: vi.fn(),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    listTableViewTemplates: api.listTableViewTemplates,
    listSpeciesInstances: api.listSpeciesInstances,
    updateTableViewTemplate: api.updateTableViewTemplate,
    deleteTableViewTemplate: api.deleteTableViewTemplate,
    updateSpeciesInstance: api.updateSpeciesInstance,
    deleteSpeciesInstance: api.deleteSpeciesInstance,
    createTableViewTemplate: api.createTableViewTemplate,
    createSpeciesInstance: api.createSpeciesInstance,
  };
});

const TableViewsPage = (await import("./table-views")).default;

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

const INSTANCE = {
  id: 3,
  code: "soy",
  name: "Soybean",
  species: "Glycine max",
  api_base_url: "https://api.example.org",
  jbrowse_base_url: null,
  portal_base_url: null,
  site_url: null,
  is_enabled: true,
  is_local: false,
  notes: null,
};

/** The row buttons render the raw i18n key, because the call site has no
 *  `defaultValue`; the catalogue resolves it in the running application. */
const ROW_DELETE = "admin.tableViews.actionDelete";
const ROW_PROMOTE = "admin.tableViews.actionSetDefault";

beforeEach(() => {
  api.listTableViewTemplates.mockReset().mockResolvedValue({ items: [TEMPLATE], total: 1 });
  api.listSpeciesInstances.mockReset().mockResolvedValue({ items: [INSTANCE], total: 1 });
  api.updateTableViewTemplate.mockReset().mockRejectedValue(new Error("promote rejected"));
  api.deleteTableViewTemplate.mockReset().mockRejectedValue(new Error("template delete rejected"));
  api.updateSpeciesInstance.mockReset().mockRejectedValue(new Error("instance update rejected"));
  api.deleteSpeciesInstance.mockReset().mockRejectedValue(new Error("instance delete rejected"));
  api.createTableViewTemplate.mockReset().mockResolvedValue(TEMPLATE);
  api.createSpeciesInstance.mockReset().mockResolvedValue(INSTANCE);
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <TableViewsPage />
    </QueryClientProvider>,
  );
}

/** The template row's delete button is the first one; the instance row's is the second. */
async function deleteButtons() {
  return screen.findAllByRole("button", { name: ROW_DELETE });
}

describe("table-view write actions", () => {
  it("renders failed template and instance requests as errors, not empty lists", async () => {
    api.listTableViewTemplates.mockRejectedValue(new Error("templates unavailable"));
    api.listSpeciesInstances.mockRejectedValue(new Error("instances unavailable"));
    renderPage();
    expect(await screen.findByTestId("table-views-templates-error")).toHaveAttribute("role", "alert");
    expect(await screen.findByTestId("table-views-instances-error")).toHaveAttribute("role", "alert");
    expect(screen.queryByText("admin.tableViews.empty")).toBeNull();
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

  it("reports a rejected instance enable/disable instead of rejecting silently", async () => {
    renderPage();

    // Wait for the instance row: the template editor's own switches render
    // before the instance query resolves.
    await deleteButtons();
    const toggle = screen
      .getAllByRole("checkbox")
      .find((node) => node.closest("table") && (node as HTMLInputElement).checked);
    expect(toggle).toBeDefined();
    fireEvent.click(toggle!);

    await waitFor(() => expect(api.updateSpeciesInstance).toHaveBeenCalledTimes(1));
    const alert = await screen.findByTestId("table-views-action-error");
    expect(alert).toHaveAttribute("role", "alert");
    expect(alert).toHaveTextContent("Soybean");
    expect(alert).toHaveTextContent("instance update rejected");
  });

  it("confirms before unregistering an instance and reports a rejected unregister", async () => {
    renderPage();

    const buttons = await deleteButtons();
    const instanceDelete = buttons[buttons.length - 1];
    fireEvent.click(instanceDelete);

    expect(api.deleteSpeciesInstance).not.toHaveBeenCalled();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.deleteSpeciesInstance).toHaveBeenCalledWith(3));

    const error = await screen.findByTestId("table-views-instance-delete-error");
    expect(error.closest('[role="alert"]')).not.toBeNull();
    expect(error).toHaveTextContent("instance delete rejected");
  });
});
