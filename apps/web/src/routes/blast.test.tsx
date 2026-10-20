import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const runtime = vi.hoisted(() => ({ navigate: vi.fn(), assembly: "Wm82.a4.v1" as string | undefined, hits: vi.fn() }));
vi.mock("@tanstack/react-router", () => ({ createFileRoute: () => (options: unknown) => ({ options }), useNavigate: () => runtime.navigate }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../lib/site-content-react", () => ({ useSiteContent: () => ({ get: (_key: string, fallback: string) => fallback }) }));
vi.mock("../components/route-motion", () => ({ FadeUp: ({ children }: { children: React.ReactNode }) => children }));
vi.mock("../lib/use-current-user", () => ({ useCurrentUser: () => ({ user: { email: "user@example.org" }, isLoading: false }) }));
vi.mock("@soymutdb/api-client", () => ({
  BLAST_PROGRAMS: [{ value: "blastp", label: "BLASTP" }], apiBaseUrl: "/api/v1", getAccessToken: () => null,
  getBlastDatabases: async () => [{ id: 1, name: "protein-v4", is_active: true, assembly_name: runtime.assembly }],
  getBlastJobs: async () => ({ items: [{ id: "job", status: "completed", program: "blastp", database: "protein-v4", query_sequence: ">query\nMKVLAAGIVGLNLGGK" }] }),
  getBlastHits: runtime.hits,
  submitBlastJob: vi.fn(),
}));
import { Route } from "./blast";
const Page = (Route.options as { component: React.ComponentType }).component;
beforeEach(() => {
  runtime.assembly = "Wm82.a4.v1";
  runtime.hits.mockReset().mockResolvedValue({ items: [{ subject_id: "Glyma.01G000100", subject_start: 1, subject_end: 100 }] });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it.each(["Wm82.a4.v1", undefined])("keeps gene search assembly-scoped (%s)", async (assembly) => {
  runtime.assembly = assembly;
  runtime.navigate.mockClear();
  vi.stubGlobal("EventSource", class { addEventListener() {} close() {} });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><Page /></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", { name: /blast.viewResults/ }));
  const geneButton = await screen.findByRole("button", { name: "Glyma.01G000100" });
  if (assembly) {
    fireEvent.click(geneButton);
    await waitFor(() => expect(runtime.navigate).toHaveBeenCalledWith({ to: "/search/genes", search: { q: "Glyma.01G000100", assembly, run: true } }));
  } else {
    expect((geneButton as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(geneButton);
    expect(runtime.navigate).not.toHaveBeenCalled();
  }
  client.clear();
});

it("distinguishes a failed hits query from no hits and recovers on retry", async () => {
  runtime.hits.mockRejectedValueOnce(new Error("private database diagnostic"))
    .mockResolvedValueOnce({ items: [] });
  vi.stubGlobal("EventSource", class { addEventListener() {} close() {} });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  try {
    render(<QueryClientProvider client={client}><Page /></QueryClientProvider>);
    fireEvent.click(await screen.findByRole("button", { name: /blast.viewResults/ }));
    expect((await screen.findByRole("alert")).textContent).toContain("blast.hitsLoadError");
    expect(screen.queryByText("blast.noHits")).toBeNull();
    expect(screen.queryByText("private database diagnostic")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    await waitFor(() => expect(client.isFetching()).toBe(0));
    await screen.findByText("blast.noHits");
    expect(runtime.hits).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).toBeNull();
  } finally {
    cleanup();
    client.clear();
  }
});
