import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  databases: vi.fn(), submit: vi.fn(), job: vi.fn(), results: vi.fn(),
}));
vi.mock("@tanstack/react-router", () => ({ createFileRoute: () => (options: unknown) => ({ options }), Link: ({ children }: { children: React.ReactNode }) => <a href="/blast">{children}</a> }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../../lib/site-content-react", () => ({ useSiteContent: () => ({ get: (_key: string, fallback: string) => fallback }) }));
vi.mock("../../lib/release-scope", () => ({ useReleaseId: () => "9" }));
vi.mock("@soymutdb/api-client", () => ({
  getPublicBlastDatabases: api.databases,
  submitPublicBlastJob: api.submit,
  getPublicBlastJob: api.job,
  getPublicBlastResults: api.results,
}));
import { Route } from "./blast";
const Page = (Route.options as { component: React.ComponentType }).component;

const database = { id: 1, name: "protein-v4", db_type: "prot", assembly_id: 7, is_active: true };
const completed = { id: "public-job", program: "blastp", database: "protein-v4", status: "completed", query_sequence: null, parameters: {}, hit_count: 1, submitted_at: "2030-01-01T00:00:00Z" };

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><Page /></QueryClientProvider>);
  return client;
}

beforeEach(() => {
  api.databases.mockResolvedValue([database]);
  api.submit.mockReset();
  api.job.mockReset();
  api.results.mockReset();
});
afterEach(() => cleanup());

it("executes through public endpoints and renders the raw download", async () => {
  api.submit.mockResolvedValue({ job: completed, access_token: "memory-only-token", expires_at: "2999-01-01T00:00:00Z" });
  api.results.mockResolvedValue({ job_id: "public-job", status: "completed", items: [{ subject_id: "Glyma.01G000100", hsp_num: 1, percent_identity: 99, alignment_length: 100, evalue: 1e-20, bit_score: 120 }], total: 1, download_url: "https://objects.example/raw.tsv" });
  renderPage();
  await screen.findByText("protein-v4");
  fireEvent.change(screen.getByPlaceholderText("blastPublic.sequencePlaceholder"), { target: { value: "MKKLLLLLLLL" } });
  fireEvent.click(screen.getByRole("button", { name: "blastPublic.submit" }));
  await waitFor(() => expect(api.submit).toHaveBeenCalledOnce());
  expect(api.job).not.toHaveBeenCalled();
  expect(await screen.findByText("Glyma.01G000100")).toBeTruthy();
  expect(screen.getByRole("link", { name: /blastPublic.download/ }).getAttribute("href")).toBe("https://objects.example/raw.tsv");
});

it("uses server pagination offsets without putting the capability in the query key", async () => {
  api.submit.mockResolvedValue({ job: completed, access_token: "memory-only-token", expires_at: "2999-01-01T00:00:00Z" });
  api.results.mockResolvedValue({ job_id: "public-job", status: "completed", items: [{ subject_id: "gene-26", hsp_num: 1, percent_identity: 90, alignment_length: 100, evalue: 1e-10, bit_score: 80 }], total: 26, download_url: null });
  renderPage();
  await screen.findByText("protein-v4");
  fireEvent.change(screen.getByPlaceholderText("blastPublic.sequencePlaceholder"), { target: { value: "MKKLLLLLLLL" } });
  fireEvent.click(screen.getByRole("button", { name: "blastPublic.submit" }));
  await screen.findByText("gene-26");
  fireEvent.click(screen.getByTitle("2"));
  await waitFor(() => expect(api.results).toHaveBeenLastCalledWith("public-job", "memory-only-token", { limit: 25, offset: 25 }));
});

it("polls a running public job before loading completed results", async () => {
  api.submit.mockResolvedValue({ job: { ...completed, status: "running" }, access_token: "memory-only-token", expires_at: "2999-01-01T00:00:00Z" });
  api.job.mockResolvedValue({ ...completed, status: "completed" });
  api.results.mockResolvedValue({ job_id: "public-job", status: "completed", items: [], total: 0, download_url: null });
  renderPage();
  await screen.findByText("protein-v4");
  fireEvent.change(screen.getByPlaceholderText("blastPublic.sequencePlaceholder"), { target: { value: "MKKLLLLLLLL" } });
  fireEvent.click(screen.getByRole("button", { name: "blastPublic.submit" }));
  await waitFor(() => expect(api.job).toHaveBeenCalledWith("public-job", "memory-only-token"));
  await waitFor(() => expect(api.results).toHaveBeenCalledWith("public-job", "memory-only-token", { limit: 25, offset: 0 }));
});

it("shows invalid-token errors without calling private endpoints", async () => {
  api.submit.mockResolvedValue({ job: { ...completed, status: "running" }, access_token: "memory-only-token", expires_at: "2999-01-01T00:00:00Z" });
  api.job.mockRejectedValue(new Error("invalid token"));
  renderPage();
  await screen.findByText("protein-v4");
  fireEvent.change(screen.getByPlaceholderText("blastPublic.sequencePlaceholder"), { target: { value: "MKKLLLLLLLL" } });
  fireEvent.click(screen.getByRole("button", { name: "blastPublic.submit" }));
  await waitFor(() => expect(screen.getByText("blastPublic.accessFailed")).toBeTruthy());
  expect(api.results).not.toHaveBeenCalled();
});

it("renders an expired public job as recoverable state", async () => {
  api.submit.mockResolvedValue({ job: { ...completed, status: "expired" }, access_token: "memory-only-token", expires_at: "2000-01-01T00:00:00Z" });
  renderPage();
  await screen.findByText("protein-v4");
  fireEvent.change(screen.getByPlaceholderText("blastPublic.sequencePlaceholder"), { target: { value: "MKKLLLLLLLL" } });
  fireEvent.click(screen.getByRole("button", { name: "blastPublic.submit" }));
  await waitFor(() => expect(screen.getByText("blastPublic.expired")).toBeTruthy());
  expect(api.results).not.toHaveBeenCalled();
});
