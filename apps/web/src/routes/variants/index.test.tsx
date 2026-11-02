import * as React from "react";
import { fireEvent, render, screen, cleanup, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const runtime = vi.hoisted(() => ({
  search: { assembly: "1", chromosome: "", variant_type: "", impact: "", mutant_line_public_id: "", cursor: undefined as string | undefined },
  navigate: vi.fn(),
  items: [] as Array<Record<string, unknown>>,
}));
vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: unknown) => ({ options, useSearch: () => runtime.search }),
  useNavigate: () => runtime.navigate,
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
vi.mock("@soymutdb/api-client", () => ({ getReleaseId: () => "1", searchVariants: vi.fn(), createVariantExport: vi.fn(), getAssemblies: vi.fn() }));
vi.mock("@tanstack/react-query", () => ({
  queryOptions: (options: unknown) => options,
  useQuery: (options: { queryKey: unknown[] }) => options.queryKey.includes("assemblies")
    ? { data: [{ id: 1, name: "Wm82.a4.v1", is_default: true }] }
    : { data: { items: runtime.items, has_more: true, next_cursor: runtime.search.cursor === "page-2" ? "page-3" : "page-2" } },
}));
import { Route } from "./index";
const Page = (Route.options as { component: React.ComponentType }).component;
afterEach(cleanup);
beforeEach(() => {
  runtime.search = { assembly: "1", chromosome: "", variant_type: "", impact: "", mutant_line_public_id: "", cursor: undefined };
  runtime.items = [];
  runtime.navigate.mockReset();
});

/**
 * The public variant id is the deterministic 64-bit digest the importer
 * mints, rendered as a decimal string: up to 20 characters. A truncated one
 * identifies nothing, so the table has to show it whole.
 */
const LONG_VARIANT_ID = "18446744073709551615";

function variantRow(extra: Record<string, unknown> = {}) {
  return {
    variant_id: LONG_VARIANT_ID,
    chromosome: "chr01",
    position: 1234,
    ref_allele: "A",
    alt_allele: "G",
    variant_type: "SNP",
    impact: "MODERATE",
    gene_symbol: "Glyma.01G000100",
    assembly: "Wm82.a4.v1",
    ...extra,
  };
}

describe("variant cursor history", () => {
  it("returns page 3 to page 2, then page 1 without skipping, and can advance again", () => {
    runtime.navigate.mockImplementation(({ search }: { search: typeof runtime.search }) => { runtime.search = search; });
    const view = render(<Page />);
    const click = (key: string) => { fireEvent.click(screen.getByRole("button", { name: new RegExp(key) })); view.rerender(<Page />); };
    expect((screen.getByRole("button", { name: /common.previous/ }) as HTMLButtonElement).disabled).toBe(true);
    click("common.next");
    expect(runtime.search.cursor).toBe("page-2");
    click("common.next");
    expect(runtime.search.cursor).toBe("page-3");
    click("common.previous");
    expect(runtime.search.cursor).toBe("page-2");
    click("common.previous");
    expect(runtime.search.cursor).toBeUndefined();
    click("common.next");
    expect(runtime.search.cursor).toBe("page-2");
  });
});

describe("variant identifier rendering", () => {
  it("shows the complete identifier and the assembly the row was read from", () => {
    runtime.items = [variantRow()];
    render(<Page />);

    const id = screen.getByTestId("variant-id");
    expect(id.textContent).toBe(LONG_VARIANT_ID);
    // The identifier wraps instead of being cut, so no ellipsis ever stands in
    // for the part that is missing.
    expect(id.textContent).not.toContain("…");
    expect(id.className).toContain("break-all");
    expect(screen.getByTestId("variant-assembly").textContent).toBe("Wm82.a4.v1");
  });

  it("keeps an internal identifier out of the rendered row", () => {
    runtime.items = [variantRow({ id: 987654321, internal_id: "internal-row-key" })];
    render(<Page />);

    const table = screen.getByRole("table");
    expect(table.textContent).toContain(LONG_VARIANT_ID);
    expect(table.textContent).not.toContain("internal-row-key");
    expect(table.textContent).not.toContain("987654321");
  });

  it("copies the complete identifier", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    runtime.items = [variantRow()];
    render(<Page />);

    fireEvent.click(screen.getByRole("button", { name: `common.copy ${LONG_VARIANT_ID}` }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(LONG_VARIANT_ID));
  });

  it("shows the pinned release scope and no invented source", () => {
    runtime.items = [variantRow()];
    render(<Page />);

    expect(screen.getByTestId("variant-release-scope").textContent).toBe("search.releaseLabel: 1");
  });

  it("lets a wide table scroll sideways instead of squeezing its columns", () => {
    runtime.items = [variantRow()];
    const { container } = render(<Page />);

    const table = container.querySelector("table");
    expect(table?.style.width).toBe("max-content");
  });

  it("exposes the result paging as a navigation landmark", () => {
    runtime.items = [variantRow()];
    render(<Page />);

    expect(screen.getByRole("navigation", { name: "common.pagination" })).toBeTruthy();
  });
});
