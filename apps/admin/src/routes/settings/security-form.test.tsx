import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SecuritySettingsForm } from "./security-form";

const { getMock, putMock } = vi.hoisted(() => ({ getMock: vi.fn(), putMock: vi.fn() }));

vi.mock("@soymutdb/api-client", () => ({ http: { get: getMock, put: putMock } }));
vi.mock("@/lib/antd", () => ({
  Card: ({ children }: any) => <section>{children}</section>,
  Typography: { Title: ({ children }: any) => <h2>{children}</h2>, Text: ({ children }: any) => <span>{children}</span> },
  Badge: ({ children }: any) => <span>{children}</span>,
  Button: ({ children, onClick, disabled }: any) => <button disabled={disabled} onClick={onClick}>{children}</button>,
  Input: ({ value, onChange }: any) => <input value={value} onChange={onChange} />,
}));

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><SecuritySettingsForm /></QueryClientProvider>);
}

describe("SecuritySettingsForm", () => {
  beforeEach(() => {
    getMock.mockReset();
    putMock.mockReset();
    getMock.mockResolvedValue({ sessionTimeoutMinutes: "60", maxLoginAttempts: "5", passwordMinLength: "8", requireTwoFactor: "false", untouchedPolicy: "preserve" });
    putMock.mockResolvedValue({});
  });

  it("saves the independent security section and preserves loaded payload values", async () => {
    renderForm();
    const timeout = await screen.findByDisplayValue("60");
    fireEvent.change(timeout, { target: { value: "90" } });
    fireEvent.click(screen.getByRole("button", { name: /Save security/ }));
    await waitFor(() => expect(putMock).toHaveBeenCalledWith("/admin/settings/security", {
      json: { sessionTimeoutMinutes: "90", maxLoginAttempts: "5", passwordMinLength: "8", requireTwoFactor: "false", untouchedPolicy: "preserve" },
    }));
  });
});
