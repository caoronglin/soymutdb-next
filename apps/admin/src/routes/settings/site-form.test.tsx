import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SiteSettingsForm } from "./site-form";

const { getMock, putMock } = vi.hoisted(() => ({ getMock: vi.fn(), putMock: vi.fn() }));

vi.mock("@soymutdb/api-client", () => ({ http: { get: getMock, put: putMock } }));
vi.mock("@/lib/antd", () => ({
  Card: ({ children }: any) => <section>{children}</section>,
  Typography: { Title: ({ children }: any) => <h2>{children}</h2>, Text: ({ children }: any) => <span>{children}</span> },
  Button: ({ children, onClick, disabled }: any) => <button disabled={disabled} onClick={onClick}>{children}</button>,
  Input: Object.assign(({ value, onChange }: any) => <input value={value} onChange={onChange} />, { TextArea: ({ value, onChange }: any) => <textarea value={value} onChange={onChange} /> }),
  Select: Object.assign(({ value, onChange, children }: any) => <select value={value} onChange={(event) => onChange(event.target.value)}>{children}</select>, { Option: ({ value, children }: any) => <option value={value}>{children}</option> }),
}));

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><SiteSettingsForm /></QueryClientProvider>);
}

describe("SiteSettingsForm", () => {
  beforeEach(() => {
    getMock.mockReset();
    putMock.mockReset();
    getMock.mockResolvedValue({ siteName: "SoyMutDB", siteDescription: "Genome data", defaultLanguage: "en", defaultTheme: "light", primaryColor: "#123456" });
    putMock.mockResolvedValue({});
  });

  it("loads site fields and preserves full general settings when saving", async () => {
    renderForm();
    const siteName = await screen.findByDisplayValue("SoyMutDB");
    fireEvent.change(siteName, { target: { value: "SoyMutDB vNext" } });
    fireEvent.click(screen.getByRole("button", { name: /Save site information/ }));
    await waitFor(() => expect(putMock).toHaveBeenCalledWith("/admin/settings/general", {
      json: { siteName: "SoyMutDB vNext", siteDescription: "Genome data", defaultLanguage: "en", defaultTheme: "light", primaryColor: "#123456" },
    }));
  });
});
