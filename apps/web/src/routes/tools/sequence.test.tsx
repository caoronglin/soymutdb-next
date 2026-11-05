// @vitest-environment jsdom
/**
 * Behavioural tests for the sequence toolkit page.
 *
 * The page is mostly a form, so these assert the parts that are easy to break
 * without noticing: an absent kernel must read as "not deployed" (not as a
 * rejected input), a kernel rejection must name the code, and the operation
 * switch must drive the right endpoint.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: Record<string, unknown>) => ({ ...options, options }),
  Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a>,
}));

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);

const api = vi.hoisted(() => ({
  capabilities: vi.fn(),
  reverseComplement: vi.fn(),
  match: vi.fn(),
  stats: vi.fn(),
  translate: vi.fn(),
  kmers: vi.fn(),
  orfs: vi.fn(),
  align: vi.fn(),
  inspect: vi.fn(),
  sequenceKernelCode: vi.fn(),
  isKernelUnavailable: vi.fn(),
  countSequenceCharacters: vi.fn(),
}));

vi.mock("@soymutdb/api-client", async () => {
  const actual = await vi.importActual<typeof import("@soymutdb/api-client")>("@soymutdb/api-client");
  return {
    ...actual,
    sequenceApi: {
      capabilities: api.capabilities,
      reverseComplement: api.reverseComplement,
      match: api.match,
      stats: api.stats,
      translate: api.translate,
      kmers: api.kmers,
      orfs: api.orfs,
      align: api.align,
      inspect: api.inspect,
    },
  };
});

import { Route } from "./sequence";

type RouteOptions = { component: React.ComponentType };
function componentOf(route: unknown): React.ComponentType {
  return (route as { options: RouteOptions }).options.component;
}
const SequenceTool = componentOf(Route);

const CAPABILITIES = {
  available: true,
  engine: "bio-core",
  engine_version: "0.1.2",
  reason: null,
  max_inline_sequence: 1_048_576,
  max_pattern: 256,
  max_hits: 1000,
  k_range: [1, 32],
  genetic_codes: [1],
  coordinate_system_internal: "0-based-half-open",
  coordinate_system_public: "1-based-inclusive",
  programs: ["reverse-complement", "match", "align", "stats", "orfs", "translate", "kmers"],
  formats: ["fasta", "fastq", "bed"],
};

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <SequenceTool />
    </QueryClientProvider>,
  );
}

describe("sequence tool page", () => {
  beforeEach(() => {
    api.capabilities.mockResolvedValue(CAPABILITIES);
    api.reverseComplement.mockResolvedValue({
      sequence: "GCAT",
      length: 4,
      alphabet: "dna",
      engine: { engine: "bio-core", engine_version: "0.1.2", request_id: null },
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("disables Run until a sequence is entered", async () => {
    renderPage();
    const run = await screen.findByRole("button", { name: /Run/i });
    await waitFor(() => expect((run as HTMLButtonElement).disabled).toBe(true));

    const box = screen.getAllByRole("textbox")[0] as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "ATGC" } });
    await waitFor(() => expect((run as HTMLButtonElement).disabled).toBe(false));
  });

  it("calls reverseComplement and renders the result", async () => {
    renderPage();
    const box = await screen.findByPlaceholderText(/Paste a nucleotide sequence/i);
    fireEvent.change(box, { target: { value: "ATGC" } });
    fireEvent.click(screen.getByRole("button", { name: /Run/i }));

    await waitFor(() => expect(api.reverseComplement).toHaveBeenCalledWith({ sequence: "ATGC" }));
    await screen.findByText("GCAT");
  });

  it("reports an absent kernel as a deployment gap, not a rejected input", async () => {
    api.capabilities.mockResolvedValue({
      ...CAPABILITIES,
      available: false,
      engine_version: null,
      reason: "wheel not installed",
    });
    renderPage();
    // Both the Tag and the Alert render "unavailable" copy; assert the Alert
    // title explicitly so the deployment-gap wording is actually pinned.
    await screen.findByText("Sequence kernel unavailable");
    const run = screen.getByRole("button", { name: /Run/i });
    await waitFor(() => expect((run as HTMLButtonElement).disabled).toBe(true));
  });

  it("keeps the operation switch wired to the right endpoint", async () => {
    api.stats.mockResolvedValue({
      length: 4,
      gc_count: 2,
      at_count: 2,
      ambiguous_count: 0,
      a: 1,
      c: 1,
      g: 1,
      t: 1,
      denominator: 4,
      gc_fraction: 0.5,
      engine: { engine: "bio-core", engine_version: "0.1.2", request_id: null },
    });

    renderPage();
    const box = await screen.findByPlaceholderText(/Paste a nucleotide sequence/i);
    fireEvent.change(box, { target: { value: "ATGC" } });

    fireEvent.click(screen.getByText(/Base composition/i));
    fireEvent.click(screen.getByRole("button", { name: /Run/i }));

    await waitFor(() => expect(api.stats).toHaveBeenCalledWith({ sequence: "ATGC" }));
    expect(api.reverseComplement).not.toHaveBeenCalled();
  });

  it("exposes the format-inspect operation and drives the /inspect endpoint", async () => {
    api.inspect.mockResolvedValue({
      fmt: "fasta",
      valid: true,
      record_count: 1,
      truncated: false,
      records: [{ header: "seq1" }],
      engine: { engine: "bio-core", engine_version: "0.1.2", request_id: null },
    });

    renderPage();
    // Wait for capabilities to resolve: the page shows a Skeleton until then,
    // so the Segmented (and its tabs) is not mounted on first paint.
    await screen.findByRole("button", { name: /Run/i });
    // The inspect tab is only reachable when it is registered in OPERATIONS;
    // otherwise its whole branch is dead code and typecheck rejects it.
    fireEvent.click(screen.getByText(/Format validation/i));

    const box = await screen.findByPlaceholderText(/Paste FASTA content/i);
    fireEvent.change(box, { target: { value: ">seq1\nATGC\n" } });
    fireEvent.click(screen.getByRole("button", { name: /Run/i }));

    await waitFor(() =>
      expect(api.inspect).toHaveBeenCalledWith("fasta", btoa(">seq1\nATGC\n")),
    );
    expect(api.reverseComplement).not.toHaveBeenCalled();
    await screen.findByText(/1 records/i);
  });
});
