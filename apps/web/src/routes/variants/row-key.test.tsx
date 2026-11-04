import * as React from "react";
import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const runtime = vi.hoisted(() => ({
  search: {
    assembly: "1",
    chromosome: "",
    variant_type: "",
    impact: "",
    mutant_line_public_id: "",
    cursor: undefined as string | undefined,
  },
  items: [] as Array<Record<string, unknown>>,
}));
vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: unknown) => ({ options, useSearch: () => runtime.search }),
  useNavigate: () => vi.fn(),
}));
vi.mock("react-i18next", () => {
  const translation = { t: (key: string) => key };
  return { useTranslation: () => translation };
});
vi.mock("../../lib/site-content-react", () => ({
  useSiteContent: () => ({ get: (_key: string, fallback: string) => fallback }),
}));
vi.mock("../../lib/session-context", () => ({ useSession: () => ({ sessionId: 1 }) }));
vi.mock("../../components/route-motion", () => ({
  FadeUp: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("../../lib/release-scope", () => ({ useReleaseId: () => "1" }));
vi.mock("@soymutdb/api-client", () => ({
  getReleaseId: () => "1",
  searchVariants: vi.fn(),
  createVariantExport: vi.fn(),
  getAssemblies: vi.fn(),
}));
vi.mock("@tanstack/react-query", () => ({
  queryOptions: (options: unknown) => options,
  useQuery: (options: { queryKey: unknown[] }) =>
    options.queryKey.includes("assemblies")
      ? { data: [{ id: 1, name: "Wm82.a4.v1", is_default: true }] }
      : { data: { items: runtime.items, has_more: false, next_cursor: null } },
}));
import { Route } from "./index";

const Page = (Route.options as { component: React.ComponentType }).component;

afterEach(cleanup);
beforeEach(() => {
  runtime.items = [];
});

function variantRow(variantId: string, extra: Record<string, unknown> = {}) {
  return {
    variant_id: variantId,
    chromosome: "chr01",
    position: 1234,
    ref_allele: "A",
    alt_allele: "G",
    variant_type: "SNP",
    impact: "MODERATE",
    assembly: "Wm82.a4.v1",
    ...extra,
  };
}

function rowKeys(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll("tbody tr[data-row-key]")).map(
    (row) => row.getAttribute("data-row-key") ?? "",
  );
}

describe("variant row keys", () => {
  /**
   * `variant_id` is unique only inside one release, and the identifier column
   * already prints it: a page carrying the same variant from two assemblies
   * would collide on a bare `variant_id` and React would silently reuse a row.
   * The key therefore carries the assembly the row was read from.
   */
  it("gives every rendered row its own key across assemblies", () => {
    const shared = "18446744073709551615";
    runtime.items = [
      variantRow(shared, { assembly: "Wm82.a4.v1" }),
      variantRow(shared, { assembly: "Wm82.a5.v1" }),
    ];
    const { container } = render(<Page />);

    const keys = rowKeys(container);
    expect(keys).toHaveLength(2);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("renders duplicate identifiers without a React duplicate-key warning", () => {
    const shared = "18446744073709551615";
    runtime.items = [
      variantRow(shared, { assembly: "Wm82.a4.v1" }),
      variantRow(shared, { assembly: "Wm82.a5.v1" }),
    ];
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      render(<Page />);
      const complaints = errors.mock.calls
        .map((call) => call.map((part) => String(part)).join(" "))
        .filter((line) => /same key|duplicate key/i.test(line));
      expect(complaints).toEqual([]);
      expect(screen.getAllByTestId("variant-row")).toHaveLength(2);
    } finally {
      errors.mockRestore();
    }
  });
});
