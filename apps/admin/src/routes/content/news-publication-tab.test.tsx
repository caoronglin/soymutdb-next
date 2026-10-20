import * as React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);
vi.mock("@/lib/antd", async () => (await import("../../test/antd-double")));
vi.mock("@tanstack/react-router", () => ({ useNavigate: () => vi.fn() }));
const api = vi.hoisted(() => ({ get: vi.fn(), delete: vi.fn() }));
vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, http: { ...actual.http, get: api.get, delete: api.delete } };
});
const { NewsPublicationTab } = await import("./news-publication-tab");

function renderTab(type: "news" | "publication") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><NewsPublicationTab type={type} /></QueryClientProvider>);
}

beforeEach(() => {
  api.get.mockReset().mockResolvedValue({ items: [{ id: "item-1", title_en: "News title", title: "Publication title", slug: "news", status: "draft", authors: "Author", created_at: "2026-01-01", updated_at: "2026-01-01" }], total: 1 });
  api.delete.mockReset().mockRejectedValue(new Error("delete refused"));
});

describe.each(["news", "publication"] as const)("%s list failure feedback", (type) => {
  it("does not display an empty success while pending or after a failed request", async () => {
    let rejectRequest!: (error: Error) => void;
    api.get.mockImplementation(() => new Promise((_resolve, reject) => { rejectRequest = reject; }));
    renderTab(type);
    expect(screen.queryByText(/No .* content/)).toBeNull();
    rejectRequest(new Error("list unavailable"));
    expect(await screen.findByTestId("content-list-load-error")).toHaveAttribute("role", "alert");
    expect(screen.queryByText(/No .* content/)).toBeNull();
  });

  it("confirms deletion and retains the rejection in the open dialog", async () => {
    renderTab(type);
    fireEvent.click(await screen.findByRole("button", { name: "Delete content" }));
    expect(api.delete).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(type === "news" ? "/admin/news/item-1" : "/admin/publications/item-1"));
    expect(await screen.findByRole("alert")).toHaveTextContent("delete refused");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
