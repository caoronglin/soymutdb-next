import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const runtime = vi.hoisted(() => ({
  search: { assembly: "5", chromosome: "Gm01", start: 100, end: 200, run: true },
  navigate: vi.fn(),
  chromosomes: vi.fn(),
  sites: vi.fn(),
  assemblies: [
    { id: 4, name: "Wm82", version: "v4", species: "Glycine max", is_default: false },
    { id: 5, name: "Wm82", version: "v5", species: "Glycine max", is_default: true },
  ],
}));
vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: unknown) => ({ options, useSearch: () => runtime.search }),
  useRouter: () => ({ navigate: runtime.navigate }),
  Link: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("react-i18next", () => {
  // Preserve the key/matches assertions without replacing `t` on every render.
  const translation = {
    t: (key: string, options?: { matches?: string }) => options?.matches ? `${key}: ${options.matches}` : key,
  };
  return { useTranslation: () => translation };
});
vi.mock("../../lib/site-content-react", () => ({ useSiteContent: () => ({ get: (_key: string, fallback: string) => fallback }) }));
vi.mock("../../components/route-motion", () => ({ FadeUp: ({ children }: { children: React.ReactNode }) => children }));
vi.mock("../../lib/release-scope", () => ({ useReleaseId: () => "7" }));
vi.mock("@soymutdb/api-client", () => ({
  getReleaseId: () => "7",
  getAssemblies: async () => runtime.assemblies,
  getAssemblyChromosomes: runtime.chromosomes,
  isTestDataPreviewAssembly: () => false,
  searchTestDataPreviewMutationSites: runtime.sites,
}));

import { Route } from "./location";
const Page = (Route.options as { component: React.ComponentType }).component;
const clients: QueryClient[] = [];
function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><Page /></QueryClientProvider>);
}
beforeEach(() => {
  runtime.search = { assembly: "5", chromosome: "Gm01", start: 100, end: 200, run: true };
  runtime.assemblies = [
    { id: 4, name: "Wm82", version: "v4", species: "Glycine max", is_default: false },
    { id: 5, name: "Wm82", version: "v5", species: "Glycine max", is_default: true },
  ];
  runtime.navigate.mockReset();
  runtime.chromosomes.mockReset().mockResolvedValue([{ name: "Gm01", length: 10000 }]);
  runtime.sites.mockReset().mockResolvedValue({ items: [] });
});
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });

it.each(["4", "5"])("keeps namespace %s and writes its stable id into a shareable URL", async (assemblyId) => {
  runtime.search.assembly = assemblyId;
  renderPage();
  const submit = screen.getByTestId("location-submit");
  await waitFor(() => expect((submit as HTMLButtonElement).disabled).toBe(false));
  await waitFor(() => expect(runtime.chromosomes).toHaveBeenCalledWith(assemblyId));
  expect(runtime.chromosomes).not.toHaveBeenCalledWith(assemblyId === "4" ? "5" : "4");
  expect(screen.getByText(`Wm82 v${assemblyId}`)).toBeTruthy();
  fireEvent.click(submit);
  expect(runtime.navigate).toHaveBeenCalledWith({
    to: "/search/location",
    search: { assembly: assemblyId, chromosome: "Gm01", start: 100, end: 200, run: true },
  });
});

it("labels an ambiguous legacy name with both versions and makes no scoped data request", async () => {
  runtime.search.assembly = "Wm82";
  renderPage();
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain("search.ambiguousAssembly");
  expect(alert.textContent).toContain("Wm82 v4");
  expect(alert.textContent).toContain("Wm82 v5");
  expect((screen.getByTestId("location-submit") as HTMLButtonElement).disabled).toBe(true);
  expect(runtime.chromosomes).not.toHaveBeenCalled();
  expect(runtime.sites).not.toHaveBeenCalled();
  expect(screen.queryByRole("region", { name: "search.location.resultsAria" })).toBeNull();
});

it.each([false, true])("reports an unknown assembly without falling back (empty catalog: %s)", async (empty) => {
  runtime.search.assembly = "unavailable";
  if (empty) runtime.assemblies = [];
  renderPage();
  expect((await screen.findByRole("alert")).textContent).toContain("search.assemblyUnavailable");
  expect(runtime.chromosomes).not.toHaveBeenCalled();
  expect(runtime.sites).not.toHaveBeenCalled();
  expect((screen.getByTestId("location-submit") as HTMLButtonElement).disabled).toBe(true);
});

it("accepts a unique legacy name but emits an id on the next submission", async () => {
  runtime.assemblies[1]!.name = "Wm82-a5";
  runtime.search.assembly = "Wm82-a5";
  renderPage();
  const submit = screen.getByTestId("location-submit");
  await waitFor(() => expect((submit as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(submit);
  expect(runtime.navigate).toHaveBeenCalledWith(expect.objectContaining({
    search: expect.objectContaining({ assembly: "5" }),
  }));
});
