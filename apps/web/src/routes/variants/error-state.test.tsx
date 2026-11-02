import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ searchVariants: vi.fn() }));
vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: unknown) => ({
    options,
    useSearch: () => ({ assembly: "1", chromosome: "", variant_type: "", impact: "", mutant_line_public_id: "", cursor: undefined }),
  }),
  useNavigate: () => vi.fn(),
}));
vi.mock("react-i18next", () => {
  // These boundary tests assert keys; keep their translator stable across renders.
  const translation = { t: (key: string) => key };
  return { useTranslation: () => translation };
});
vi.mock("../../lib/site-content-react", () => ({ useSiteContent: () => ({ get: (_key: string, fallback: string) => fallback }) }));
vi.mock("../../lib/session-context", () => ({ useSession: () => ({ sessionId: 1 }) }));
vi.mock("../../components/route-motion", () => ({ FadeUp: ({ children }: { children: React.ReactNode }) => children }));
vi.mock("../../lib/release-scope", () => ({
  // The pinned release is a React value, not a module read: the route
  // has to re-render when an operator publishes a new release.
  useReleaseId: () => "1",
}));
vi.mock("@soymutdb/api-client", () => ({
  getReleaseId: () => "1",
  getAssemblies: async () => [{ id: 1, name: "Wm82.a4.v1", is_default: true }],
  getAssemblyChromosomes: vi.fn(),
  searchVariants: api.searchVariants,
  createVariantExport: vi.fn(),
}));
import { Route } from "./index";
const Page = (Route.options as { component: React.ComponentType }).component;
const clients: QueryClient[] = [];
function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><Page /></QueryClientProvider>);
  return client;
}
beforeEach(() => { api.searchVariants.mockReset(); });
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });

it("shows a safe query failure, not no results, and retries the failed request", async () => {
  api.searchVariants.mockRejectedValueOnce(new Error("private database diagnostic"))
    .mockResolvedValueOnce({ items: [], has_more: false });
  const client = renderPage();

  expect((await screen.findByRole("alert")).textContent).toContain("variants.loadError");
  expect(screen.queryByText("variants.noResults")).toBeNull();
  expect(screen.queryByText("private database diagnostic")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "common.retry" }));

  await waitFor(() => expect(client.isFetching()).toBe(0));
  await screen.findByText("variants.noResults");
  expect(api.searchVariants).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole("alert")).toBeNull();
});

it("does not leave stale results or pagination looking authoritative after a failed refresh", async () => {
  api.searchVariants.mockResolvedValueOnce({ items: [], total_count: 42, has_more: true, next_cursor: "next-page" })
    .mockRejectedValueOnce(new Error("refresh unavailable"));
  const client = renderPage();
  await screen.findByText("variants.noResults");
  expect(await screen.findByText("variants.totalCount")).toBeTruthy();

  await client.invalidateQueries({ predicate: (query) => query.queryKey.includes("variants") });
  await screen.findByRole("alert");
  await waitFor(() => expect(screen.queryByText("variants.totalCount")).toBeNull());
  expect(screen.queryByRole("button", { name: /common.next/ })).toBeNull();
  expect(screen.queryByText("variants.noResults")).toBeNull();
});
