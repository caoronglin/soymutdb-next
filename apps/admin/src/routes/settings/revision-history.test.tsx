import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SettingsRevisionHistory } from "./revision-history";

const { historyMock, rollbackMock } = vi.hoisted(() => ({ historyMock: vi.fn(), rollbackMock: vi.fn() }));

vi.mock("@soymutdb/api-client", () => ({
  adminSettingsApi: { history: historyMock, rollback: rollbackMock },
}));

vi.mock("@/components/confirm-dialog", () => ({
  ConfirmDialog: ({ children, onConfirm, title }: any) => (
    <div role="dialog"><p>{title}</p>{children}<button onClick={onConfirm}>Restore revision</button></div>
  ),
}));

function renderHistory() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><SettingsRevisionHistory sections={[{ id: "security", label: "Security" }]} /></QueryClientProvider>);
}

describe("SettingsRevisionHistory", () => {
  beforeEach(() => {
    historyMock.mockReset();
    rollbackMock.mockReset();
    historyMock.mockResolvedValue({
      section: "security",
      current_version: 3,
      items: [
        { version: 3, action: "patch", values: {}, changes: {}, actor_id: null, created_at: "2026-01-02T12:00:00Z", rollback_from_version: null, reason: null },
        { version: 2, action: "patch", values: {}, changes: {}, actor_id: null, created_at: "2026-01-01T12:00:00Z", rollback_from_version: null, reason: "previous policy" },
      ],
    });
    rollbackMock.mockResolvedValue({ section: "security", version: 4, values: {} });
  });

  it("loads history and restores a non-current revision with the required audit reason", async () => {
    renderHistory();
    expect(await screen.findByText("v2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restore v3" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Restore v2" }));
    fireEvent.change(screen.getByPlaceholderText("Required audit reason"), { target: { value: "Restore reviewed policy" } });
    fireEvent.click(screen.getByRole("button", { name: "Restore revision" }));
    await waitFor(() => expect(rollbackMock).toHaveBeenCalledWith("security", {
      expected_version: 3,
      target_version: 2,
      reason: "Restore reviewed policy",
    }));
  });
});
