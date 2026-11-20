/**
 * `/instances` is the one registry of deployed species databases.
 *
 * It replaces the weaker registry that used to be embedded in
 * `/table-templates` (that copy could only toggle and unregister; this page also
 * checks bounded health and switches the console's current instance). These are
 * the write-path regressions that moved out of `table-templates.test.tsx`: a
 * failed list must not read as "no instances", and a rejected unregister must
 * say so instead of leaving the row unchanged and silent.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InstanceContextProvider } from "../lib/instance-context-react";

vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);
vi.mock("@/lib/antd", async () => (await import("../test/antd-double")));

const api = vi.hoisted(() => ({
  listSpeciesInstances: vi.fn(),
  createSpeciesInstance: vi.fn(),
  updateSpeciesInstance: vi.fn(),
  deleteSpeciesInstance: vi.fn(),
  checkSpeciesInstanceHealth: vi.fn(),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    listSpeciesInstances: api.listSpeciesInstances,
    createSpeciesInstance: api.createSpeciesInstance,
    updateSpeciesInstance: api.updateSpeciesInstance,
    deleteSpeciesInstance: api.deleteSpeciesInstance,
    checkSpeciesInstanceHealth: api.checkSpeciesInstanceHealth,
  };
});

const SpeciesInstancesPage = (await import("./instances")).default;

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
  connection_state: "healthy",
  last_checked_at: null,
  last_error_at: null,
  is_stale: false,
  remote_management: "registration_only",
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};

beforeEach(() => {
  api.listSpeciesInstances.mockReset().mockResolvedValue({ items: [INSTANCE], total: 1 });
  api.createSpeciesInstance.mockReset().mockResolvedValue(INSTANCE);
  api.updateSpeciesInstance.mockReset().mockResolvedValue(INSTANCE);
  api.deleteSpeciesInstance.mockReset().mockResolvedValue(undefined);
  api.checkSpeciesInstanceHealth.mockReset().mockResolvedValue(INSTANCE);
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <InstanceContextProvider>
        <SpeciesInstancesPage />
      </InstanceContextProvider>
    </QueryClientProvider>,
  );
}

describe("species instance registry", () => {
  it("renders the registered deployments", async () => {
    renderPage();

    expect(await screen.findByTestId("instances-table")).toBeInTheDocument();
    expect(await screen.findByText("Soybean")).toBeInTheDocument();
    expect(api.listSpeciesInstances).toHaveBeenCalled();
  });

  it("reports a failed list as an error, not as an empty registry", async () => {
    api.listSpeciesInstances.mockRejectedValue(new Error("instances unavailable"));
    renderPage();

    const error = await screen.findByTestId("instances-load-error");
    expect(error).toHaveAttribute("role", "alert");
    expect(screen.queryByTestId("instances-empty")).toBeNull();
  });

  it("confirms before unregistering and reports a rejected unregister", async () => {
    api.deleteSpeciesInstance.mockRejectedValue(new Error("instance delete rejected"));
    renderPage();

    fireEvent.click(await screen.findByTestId("instance-delete-3"));
    expect(api.deleteSpeciesInstance).not.toHaveBeenCalled();
    expect(await screen.findByTestId("instance-delete-confirm")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("instance-delete-confirm-button"));

    await waitFor(() =>
      expect(api.deleteSpeciesInstance).toHaveBeenCalledWith(3, expect.anything()),
    );
    expect(await screen.findByTestId("instances-error")).toHaveTextContent(
      "admin.instances.deleteError",
    );
  });

  it("reports a failed health check instead of leaving the row looking checked", async () => {
    api.checkSpeciesInstanceHealth.mockRejectedValue(new Error("health unavailable"));
    renderPage();

    fireEvent.click(await screen.findByTestId("instance-check-3"));

    await waitFor(() =>
      expect(api.checkSpeciesInstanceHealth).toHaveBeenCalledWith(3, expect.anything()),
    );
    expect(await screen.findByTestId("instances-error")).toHaveTextContent(
      "admin.instances.healthError",
    );
  });
});