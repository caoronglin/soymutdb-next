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

/**
 * These fixtures are hand-built rows, not a snapshot of what `alembic upgrade
 * head` can return. `variant_id` is minted by `compute_variant_id` from
 * `release_id + assembly + chromosome + position + ref + alt`, so in a real
 * database one `variant_id` can never appear under two assemblies in the same
 * release — the importer has already folded the assembly into the digest.
 * What is under test here is the key function's correctness, not a shape
 * Postgres will hand back.
 */
describe("variant row keys", () => {
  /**
   * The key is derived, so a whole class of mutations keeps it unique by
   * accident: the rows differ in `assembly`, so any distinct-suffix rule
   * separates them. Bucketing the keys asserts the actual contract — two rows
   * sharing an identifier but differing in assembly land in different buckets,
   * and nothing else collapses into one.
   */
  const bucketsOf = (keys: string[]) => {
    const buckets = new Map<string, number>();
    for (const key of keys) buckets.set(key, (buckets.get(key) ?? 0) + 1);
    return [...buckets.values()].sort();
  };

  it("separates rows that share an identifier and differ in assembly", () => {
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

  /**
   * A `?? ""` fallback looks equivalent to `?? null` until a row actually
   * carries `assembly: ""`. This fixture forces that collision: `null` and `""`
   * must stay different values, so the shared identifier must split three ways
   * rather than collapsing the empty and absent assembly into one key.
   */
  it("separates an absent assembly from an empty one under a shared identifier", () => {
    const shared = "18446744073709551615";
    runtime.items = [
      variantRow(shared, { assembly: "Wm82.a4.v1" }),
      variantRow(shared, { assembly: null }),
      variantRow(shared, { assembly: "" }),
    ];
    const { container } = render(<Page />);

    const keys = rowKeys(container);
    expect(keys).toHaveLength(3);
    expect(new Set(keys).size).toBe(3);
    expect(bucketsOf(keys)).toEqual([1, 1, 1]);
  });

  /**
   * Two rows that agree on both identifier and assembly are the same row said
   * twice; they must NOT be split, so a key carrying extra noise (an index, a
   * timestamp) would show up here as three buckets.
   */
  it("keeps rows that agree on identifier and assembly in one bucket", () => {
    const shared = "18446744073709551615";
    runtime.items = [
      variantRow(shared, { assembly: "Wm82.a4.v1" }),
      variantRow(shared, { assembly: "Wm82.a4.v1" }),
      variantRow(shared, { assembly: null }),
    ];
    const { container } = render(<Page />);

    expect(bucketsOf(rowKeys(container))).toEqual([1, 2]);
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
