// @vitest-environment jsdom
/**
 * The gene detail page's assembly context.
 *
 * A deep link may carry the legacy genome-name spelling, but the endpoint only
 * accepts the catalogue's numeric `assembly_id`. Resolving here is not cosmetic:
 * v4/v5 share the name "Wm82", so a name-shaped parameter that is forwarded or
 * silently defaulted can read another coordinate namespace's record. These
 * cases pin the three outcomes the page must keep distinct — resolved (a
 * numeric id is sent), unknown, and ambiguous — plus the version-bearing label.
 */
import * as React from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const runtime = vi.hoisted(() => ({
  assembly: undefined as string | undefined,
  assembliesLoading: false,
  assembliesError: false,
}));

const api = vi.hoisted(() => ({
  getGene: vi.fn(),
  listTestDataPreviewMutationSitesForGene: vi.fn(),
  assemblies: [] as Array<Record<string, unknown>>,
  gene: null as unknown,
}));

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: Record<string, unknown>) => ({
    ...options,
    options,
    useParams: () => ({ geneId: "Glyma.01G000100" }),
    useSearch: () => ({ assembly: runtime.assembly }),
  }),
  Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a>,
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: { queryKey: unknown[]; queryFn?: () => unknown; enabled?: boolean }) => {
    const key = JSON.stringify(options.queryKey);
    if (key.includes('"assemblies"')) {
      const loading = runtime.assembliesLoading;
      const error = runtime.assembliesError;
      return {
        data: loading || error ? undefined : api.assemblies,
        isLoading: loading,
        isSuccess: !loading && !error,
        isError: error,
        refetch: vi.fn(),
      };
    }
    // A disabled query must report nothing, whatever data the double holds:
    // that is exactly the property under test when the context is blocked.
    if (options.enabled === false) {
      return { data: undefined, isLoading: false, isSuccess: false, isError: false, refetch: vi.fn() };
    }
    if (key.includes('"detail"')) {
      // The double stands in for the query observer, so it must run the
      // factory: the assertion is which request the page would send.
      void options.queryFn?.();
      return { data: api.gene, isLoading: false, isSuccess: true, isError: false, refetch: vi.fn() };
    }
    return { data: [], isLoading: false, isSuccess: true, isError: false, refetch: vi.fn() };
  },
}));

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);
vi.mock("../../lib/release-scope", () => ({ useReleaseId: () => "5" }));
vi.mock("../../lib/query-options", () => ({
  assembliesQueryOptions: () => ({ queryKey: ["assemblies"], queryFn: vi.fn() }),
}));
vi.mock("../../lib/site-variant", () => ({ SITE_VARIANT: "external" }));
vi.mock("@soymutdb/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@soymutdb/api-client")>()),
  getGene: api.getGene,
  listTestDataPreviewMutationSitesForGene: api.listTestDataPreviewMutationSitesForGene,
}));
vi.mock("../../components/gene-genome-view", () => ({ GeneGenomeView: () => null }));
vi.mock("../../components/gene-seed-request-entry", () => ({ GeneSeedRequestEntry: () => null }));

import { Route } from "../genes/$geneId";

const Page = (Route as unknown as { options: { component: React.ComponentType } }).options.component;

const V4 = { id: 4, name: "Wm82", version: "a4.v1", species: "Glycine max", is_default: false };
const V5 = { id: 5, name: "Wm82", version: "a5.v1", species: "Glycine max", is_default: true };

function gene(overrides: Record<string, unknown> = {}) {
  return {
    id: "internal-row-key",
    gene_id: "Glyma.01G000100",
    symbol: "GLYMA01G000100",
    name: null,
    biotype: "protein_coding",
    assembly_id: 5,
    assembly_name: "Wm82",
    chromosome: "Chr01",
    start_pos: 1000,
    end_pos: 2000,
    strand: "+",
    description: null,
    source: "soybase",
    extra: {},
    transcripts: [],
    annotations: [],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  runtime.assembly = undefined;
  runtime.assembliesLoading = false;
  runtime.assembliesError = false;
  api.assemblies = [V4, V5];
  api.gene = gene();
  api.listTestDataPreviewMutationSitesForGene.mockResolvedValue([]);
});
afterEach(cleanup);

const unavailable =
  "The requested assembly is unavailable; no query was sent.";

describe("gene detail assembly context", () => {
  it("sends the catalogue's numeric id for an id-shaped deep link", async () => {
    runtime.assembly = "5";
    render(<Page />);

    await waitFor(() => expect(api.getGene).toHaveBeenCalled());
    expect(api.getGene).toHaveBeenCalledWith("Glyma.01G000100", { assembly_id: "5" });
  });

  it("resolves a unique genome name to its id before requesting", async () => {
    runtime.assembly = "Wm82.a2.v1";
    api.assemblies = [
      { id: 9, name: "Wm82.a2.v1", version: "a2.v1", species: "Glycine max", is_default: true },
    ];
    api.gene = gene({ assembly_id: 9, assembly_name: "Wm82.a2.v1" });
    render(<Page />);

    await waitFor(() => expect(api.getGene).toHaveBeenCalled());
    expect(api.getGene).toHaveBeenCalledWith("Glyma.01G000100", { assembly_id: "9" });
  });

  it("refuses an ambiguous name instead of choosing one genome version", async () => {
    runtime.assembly = "Wm82";
    render(<Page />);

    expect((await screen.findByText(unavailable)).textContent).toBe(unavailable);
    expect(api.getGene).not.toHaveBeenCalled();
  });

  it("refuses an id that is not in this release's catalogue", async () => {
    runtime.assembly = "99";
    render(<Page />);

    expect((await screen.findByText(unavailable)).textContent).toBe(unavailable);
    expect(api.getGene).not.toHaveBeenCalled();
  });

  it("labels the record's assembly with its version", async () => {
    runtime.assembly = "5";
    render(<Page />);

    await waitFor(() =>
      expect(screen.getByTestId("gene-assembly").textContent).toBe("Wm82 a5.v1"),
    );
  });

  it("does not query while the catalogue is still loading", async () => {
    runtime.assembly = "5";
    runtime.assembliesLoading = true;
    render(<Page />);

    await waitFor(() => expect(screen.queryByTestId("gene-assembly")).toBeNull());
    expect(api.getGene).not.toHaveBeenCalled();
  });
});