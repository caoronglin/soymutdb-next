import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppearanceSettingsForm } from "./appearance-form";

const { getMock, putMock, saveColorMock } = vi.hoisted(() => ({ getMock: vi.fn(), putMock: vi.fn(), saveColorMock: vi.fn() }));

vi.mock("@soymutdb/api-client", () => ({ http: { get: getMock, put: putMock } }));
vi.mock("@/lib/antd-theme", () => ({
  ANTD_PRIMARY_HEX: "#1677ff",
  isValidAdminPrimaryColor: (value: string) => /^#[0-9a-f]{6}$/i.test(value),
  readAdminPrimaryColor: () => "#1677ff",
  saveAdminPrimaryColor: saveColorMock,
}));
vi.mock("@/lib/antd", () => ({
  Card: ({ children }: any) => <section>{children}</section>,
  Typography: { Title: ({ children }: any) => <h2>{children}</h2>, Text: ({ children }: any) => <span>{children}</span> },
  Button: ({ children, onClick, disabled }: any) => <button disabled={disabled} onClick={onClick}>{children}</button>,
  ColorPicker: ({ value, onChangeComplete }: any) => <input aria-label="Primary color" value={value} onChange={(event) => onChangeComplete({ toHexString: () => event.target.value })} />,
}));

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><AppearanceSettingsForm /></QueryClientProvider>);
}

describe("AppearanceSettingsForm", () => {
  beforeEach(() => {
    getMock.mockReset();
    putMock.mockReset();
    saveColorMock.mockReset();
    getMock.mockResolvedValue({ siteName: "SoyMutDB", siteDescription: "Genome data", defaultLanguage: "en", defaultTheme: "light", primaryColor: "#123456" });
    putMock.mockResolvedValue({});
  });

  it("loads and saves only through the general settings contract while preserving existing values", async () => {
    renderForm();
    const color = await screen.findByLabelText("Primary color");
    expect(color).toHaveValue("#123456");
    fireEvent.change(color, { target: { value: "#654321" } });
    fireEvent.click(screen.getByRole("button", { name: /Save appearance/ }));
    await waitFor(() => expect(putMock).toHaveBeenCalledWith("/admin/settings/general", {
      json: { siteName: "SoyMutDB", siteDescription: "Genome data", defaultLanguage: "en", defaultTheme: "light", primaryColor: "#654321" },
    }));
    expect(saveColorMock).toHaveBeenCalledWith("#654321");
  });
});
