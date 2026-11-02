import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const runtime = vi.hoisted(() => ({
  navigate: vi.fn(),
  /** The assembly of the *active* release (the currently listed databases). */
  activeAssembly: "Wm82.a6.v1" as string | undefined,
  /** The assembly the job's own database belongs to (its provenance). */
  jobAssembly: "Wm82.a4.v1" as string | undefined,
  /** The release the job was computed against (its provenance). */
  jobRelease: 4 as number | null,
  hits: vi.fn(),
  resolveTarget: vi.fn(),
  currentRelease: "9",
  currentUser: { email: "user@example.org", is_superuser: false, effective_roles: ["researcher"] as string[] } as { email: string; is_superuser: boolean; effective_roles: string[] } | null,
  submit: vi.fn(),
}));
vi.mock("@tanstack/react-router", () => ({ createFileRoute: () => (options: unknown) => ({ options }), useNavigate: () => runtime.navigate }));
vi.mock("react-i18next", () => {
  // These boundary tests assert keys; keep their translator stable across renders.
  const translation = { t: (key: string) => key };
  return { useTranslation: () => translation };
});
vi.mock("../lib/site-content-react", () => ({ useSiteContent: () => ({ get: (_key: string, fallback: string) => fallback }) }));
vi.mock("../components/route-motion", () => ({ FadeUp: ({ children }: { children: React.ReactNode }) => children }));
vi.mock("../lib/release-scope", () => ({ useReleaseId: () => runtime.currentRelease }));
vi.mock("../lib/use-current-user", () => ({
  useCurrentUser: () => ({ user: runtime.currentUser, isLoading: false }),
  grantsResearcher: (user: { is_superuser?: boolean; effective_roles?: string[] }) => user.is_superuser === true || user.effective_roles?.includes("researcher") === true,
}));
vi.mock("@soymutdb/api-client", () => ({
  BLAST_PROGRAMS: [{ value: "blastp", label: "BLASTP" }], apiBaseUrl: "/api/v1", getAccessToken: () => null,
  // The database list belongs to the ACTIVE release (release 9) — it must
  // never be used to re-label a job that was computed against another one.
  getBlastDatabases: async () => [
    { id: 1, name: "protein-v4", is_active: true, assembly_name: runtime.activeAssembly, release_id: 9 },
  ],
  getBlastJobs: async () => ({
    items: [{
      id: "job",
      status: "completed",
      program: "blastp",
      database: "protein-v4",
      query_sequence: ">query\nMKVLAAGIVGLNLGGK",
      release_id: runtime.jobRelease,
      assembly_name: runtime.jobAssembly,
    }],
  }),
  getBlastHits: runtime.hits,
  resolveBlastHitGenomeTarget: runtime.resolveTarget,
  submitBlastJob: runtime.submit,
}));
import { Route } from "./blast";
const Page = (Route.options as { component: React.ComponentType }).component;
beforeEach(() => {
  runtime.activeAssembly = "Wm82.a6.v1";
  runtime.jobAssembly = "Wm82.a4.v1";
  runtime.jobRelease = 4;
  runtime.currentRelease = "9";
  runtime.navigate.mockReset();
  runtime.submit.mockReset();
  runtime.currentUser = { email: "user@example.org", is_superuser: false, effective_roles: ["researcher"] };
  vi.stubGlobal("EventSource", class { addEventListener() {} close() {} });
  runtime.resolveTarget.mockReset().mockImplementation(async (job: { release_id: number; assembly_name: string }) => ({ release: String(job.release_id), assembly: job.assembly_name, locus: "chr01:12000-15000" }));
  runtime.hits.mockReset().mockResolvedValue({ items: [{ subject_id: "Glyma.01G000100", subject_start: 1, subject_end: 100 }] });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

/** Render the page and open the (single) completed job's hits table. */
async function renderHits(): Promise<QueryClient> {
  vi.stubGlobal("EventSource", class { addEventListener() {} close() {} });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><Page /></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", { name: /blast.viewResults/ }));
  return client;
}

it("keeps the form public while preventing anonymous submission", async () => {
  runtime.currentUser = null;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><Page /></QueryClientProvider>);
  const submit = await screen.findByTestId("blast-submit");
  expect((submit as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText("blast.submitRequiresLogin")).toBeTruthy();
  expect(runtime.submit).not.toHaveBeenCalled();
  client.clear();
});

it("keeps submission restricted to researcher-capable sessions", async () => {
  runtime.currentUser = { email: "viewer@example.org", is_superuser: false, effective_roles: ["viewer"] };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><Page /></QueryClientProvider>);
  const submit = await screen.findByTestId("blast-submit");
  expect((submit as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText("blast.submitRequiresResearcher")).toBeTruthy();
  expect(runtime.submit).not.toHaveBeenCalled();
  client.clear();
});

it.each(["Wm82.a4.v1", undefined])("keeps gene search assembly-scoped (%s)", async (assembly) => {
  runtime.jobAssembly = assembly;
  runtime.jobRelease = 9;
  runtime.navigate.mockClear();
  const client = await renderHits();
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

it("pins the genome-browser link to the job's own release and assembly", async () => {
  const client = await renderHits();
  const link = await screen.findByTestId("blast-gbrowse-link");
  expect(runtime.resolveTarget).not.toHaveBeenCalled();
  fireEvent.click(link);
  await waitFor(() => expect(runtime.navigate).toHaveBeenCalledWith({ to: "/browser", search: { release: "4", assembly: "Wm82.a4.v1", locus: "chr01:12000-15000" } }));
  expect(runtime.resolveTarget).toHaveBeenCalledWith(expect.objectContaining({ release_id: 4, assembly_name: "Wm82.a4.v1" }), "Glyma.01G000100");
  client.clear();
});

it("keeps the genome-browser link release-scoped when the job matches the active release", async () => {
  runtime.jobRelease = 9;
  runtime.jobAssembly = "Wm82.a6.v1";
  const client = await renderHits();
  const link = await screen.findByTestId("blast-gbrowse-link");
  fireEvent.click(link);
  await waitFor(() => expect(runtime.navigate).toHaveBeenCalledWith({ to: "/browser", search: { release: "9", assembly: "Wm82.a6.v1", locus: "chr01:12000-15000" } }));
  client.clear();
});

it("offers no genome-browser link when the job states no release context", async () => {
  runtime.jobRelease = null;
  runtime.jobAssembly = undefined;
  const client = await renderHits();
  const link = await screen.findByTestId("blast-gbrowse-link");
  // No clickable link: an unknown context must not fall back to the active
  // release, whose coordinates would be shown under the old job.
  expect(link.getAttribute("href")).toBeNull();
  expect(link.hasAttribute("disabled")).toBe(true);
  // The reason is stated instead of the link being silently dropped.
  expect(screen.getByText("browser.contextMissingTitle")).toBeTruthy();
  client.clear();
});

it("resolves a genomic interval even when protein alignment coordinates are missing", async () => {
  runtime.hits.mockResolvedValue({ items: [{ subject_id: "Glyma.01G000100" }] });
  const client = await renderHits();
  const link = await screen.findByTestId("blast-gbrowse-link");
  fireEvent.click(link);
  await waitFor(() => expect(runtime.navigate).toHaveBeenCalledWith(expect.objectContaining({ to: "/browser" })));
  // Protein alignment coordinates are not needed for the authoritative lookup.
  expect(screen.queryByText("browser.contextMissingTitle")).toBeNull();
  client.clear();
});

it("does not silently search a different portal release for an old job", async () => {
  const client = await renderHits();
  const geneButton = await screen.findByRole("button", { name: "Glyma.01G000100" });
  expect((geneButton as HTMLButtonElement).disabled).toBe(true);
  expect(geneButton.getAttribute("title")).toBe("blast.geneSearchReleaseMismatch");
  fireEvent.click(geneButton);
  expect(runtime.navigate).not.toHaveBeenCalled();
  client.clear();
});

it("shows an unmapped subject rather than fabricating a genome locus", async () => {
  runtime.resolveTarget.mockResolvedValue(null);
  const client = await renderHits();
  fireEvent.click(await screen.findByTestId("blast-gbrowse-link"));
  expect(await screen.findByText("blast.jbrowse.unavailable")).toBeTruthy();
  expect(runtime.navigate).not.toHaveBeenCalled();
  client.clear();
});

it("recovers on another click after genomic lookup fails without exposing diagnostics", async () => {
  runtime.resolveTarget.mockRejectedValueOnce(new Error("private diagnostic"));
  const client = await renderHits();
  const button = await screen.findByTestId("blast-gbrowse-link");
  fireEvent.click(button);
  expect(await screen.findByText("blast.jbrowse.resolveFailed")).toBeTruthy();
  expect(screen.queryByText("private diagnostic")).toBeNull();
  fireEvent.click(button);
  await waitFor(() => expect(runtime.navigate).toHaveBeenCalledWith(expect.objectContaining({ to: "/browser" })));
  expect(runtime.resolveTarget).toHaveBeenCalledTimes(2);
  client.clear();
});

it("does not navigate after the user has left the results page", async () => {
  let resolve!: (value: { release: string; assembly: string; locus: string }) => void;
  runtime.resolveTarget.mockReturnValue(new Promise((done) => { resolve = done; }));
  const client = await renderHits();
  fireEvent.click(await screen.findByTestId("blast-gbrowse-link"));
  cleanup();
  await act(async () => resolve({ release: "4", assembly: "Wm82.a4.v1", locus: "chr01:12000-15000" }));
  expect(runtime.navigate).not.toHaveBeenCalled();
  client.clear();
});

it("disables duplicate lookup actions while resolving", async () => {
  runtime.resolveTarget.mockReturnValue(new Promise(() => {}));
  const client = await renderHits();
  const button = await screen.findByTestId("blast-gbrowse-link");
  fireEvent.click(button);
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(button.textContent).toContain("blast.jbrowse.resolving");
  fireEvent.click(button);
  expect(runtime.resolveTarget).toHaveBeenCalledOnce();
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
