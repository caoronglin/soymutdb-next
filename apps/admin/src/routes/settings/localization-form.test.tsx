import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LocalizationSettingsForm } from "./localization-form";

const { getMock, putMock } = vi.hoisted(() => ({ getMock: vi.fn(), putMock: vi.fn() }));

vi.mock("@soymutdb/api-client", () => ({ http: { get: getMock, put: putMock } }));
vi.mock("@/lib/antd", () => ({
  Card: ({ children }: any) => <section>{children}</section>,
  Typography: { Title: ({ children }: any) => <h2>{children}</h2>, Text: ({ children }: any) => <span>{children}</span> },
  Button: ({ children, onClick, disabled }: any) => <button disabled={disabled} onClick={onClick}>{children}</button>,
  Select: Object.assign(({ value, onChange, children }: any) => <select aria-label="Default Language" value={value} onChange={(event) => onChange(event.target.value)}>{children}</select>, { Option: ({ value, children }: any) => <option value={value}>{children}</option> }),
}));

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><LocalizationSettingsForm /></QueryClientProvider>);
}

describe("LocalizationSettingsForm", () => {
  beforeEach(() => {
    getMock.mockReset();
    putMock.mockReset();
    getMock.mockResolvedValue({ siteName: "SoyMutDB", defaultLanguage: "en", defaultTheme: "light", primaryColor: "#123456" });
    putMock.mockResolvedValue({});
  });

  it("saves default language through general settings while preserving the full payload", async () => {
    renderForm();
    const language = await screen.findByLabelText("Default Language");
    fireEvent.change(language, { target: { value: "zh" } });
    fireEvent.click(screen.getByRole("button", { name: /Save localization/ }));
    await waitFor(() => expect(putMock).toHaveBeenCalledWith("/admin/settings/general", {
      json: { siteName: "SoyMutDB", defaultLanguage: "zh", defaultTheme: "light", primaryColor: "#123456" },
    }));
  });
});
