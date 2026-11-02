// @vitest-environment jsdom
import * as React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import enCommon from "@soymutdb/i18n-core/locales/en/common.json";
import zhCommon from "@soymutdb/i18n-core/locales/zh/common.json";

const runtime = vi.hoisted(() => ({
  language: "en",
  search: {} as Record<string, unknown>,
  navigate: vi.fn(),
  query: {} as Record<string, unknown>,
  resources: {} as Record<string, Record<string, unknown>>,
  pathname: "/search",
  release: "4",
  variant: "external",
  queryOptions: {} as Record<string, unknown>,
  // The release-scoped assembly catalogue the route resolves a URL assembly
  // parameter against (DB-CORE-3: v4/v5 are distinct namespaces).
  assemblies: [] as Array<{ id: number; name: string; species: string; version: string; is_default: boolean }>,
  assembliesQuery: {} as Record<string, unknown>,
  assembliesOptions: {} as Record<string, unknown>,
}));

function resolveKey(key: string, options?: Record<string, unknown>) {
  let value: unknown = runtime.resources[runtime.language];
  for (const part of key.split(".")) {
    value = value && typeof value === "object" ? (value as Record<string, unknown>)[part] : undefined;
  }
  if (typeof value !== "string") return key;
  return value.replace(/\{\{(\w+)\}\}/g, (_match, name: string) => String(options?.[name] ?? ""));
}

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: Record<string, unknown>) => ({
    ...options,
    options,
    useSearch: () => runtime.search,
  }),
  Link: "a",
  Outlet: () => null,
  useNavigate: () => runtime.navigate,
  // The portal hero renders only on `/search` itself; child routes such as
  // `/search/genes` are standalone pages. Default to the portal path so these
  // localization assertions keep exercising the portal view. The real hook
  // applies `select`, so the mock must too — returning the raw state would hand
  // the component an object where it expects a pathname string.
  useRouterState: (options?: { select?: (state: { location: { pathname: string } }) => unknown }) => {
    const state = { location: { pathname: runtime.pathname } };
    return options?.select ? options.select(state) : state;
  },
}));

vi.mock("@tanstack/react-query", () => ({
  // `queryOptions` is a pass-through factory used by the shared assembly
  // query options module.
  queryOptions: (options: Record<string, unknown>) => options,
  useQuery: (options: Record<string, unknown>) => {
    const key = Array.isArray(options.queryKey) ? options.queryKey.join("|") : "";
    // The assembly catalogue is a second query on this route; the search
    // query keeps the `queryOptions` slot the assertions below rely on.
    if (key.includes("assemblies")) {
      runtime.assembliesOptions = options;
      return runtime.assembliesQuery;
    }
    runtime.queryOptions = options;
    return runtime.query;
  },
}));
vi.mock("../lib/release-scope", () => ({ useReleaseId: () => runtime.release }));
vi.mock("../lib/site-variant", () => ({ get SITE_VARIANT() { return runtime.variant; } }));
vi.mock("@soymutdb/api-client", () => ({ globalSearch: vi.fn(), internalSearch: vi.fn() }));

vi.mock("react-i18next", () => ({
  // `t` must keep a stable identity across renders: pass the module-level
  // resolver straight through instead of wrapping it in a fresh closure.
  useTranslation: () => ({ t: resolveKey }),
}));

vi.mock("../components/route-motion", () => ({
  FadeUp: ({ children }: { children: React.ReactNode }) => children,
}));

import { Route } from "./search";
import { globalSearch, internalSearch } from "@soymutdb/api-client";

type RouteOptions = { component: React.ComponentType };
const SearchPage = (Route as unknown as { options: RouteOptions }).options.component;

afterEach(() => cleanup());

beforeEach(() => {
  runtime.language = "en";
  runtime.search = {};
  runtime.release = "4";
  runtime.variant = "external";
  runtime.pathname = "/search";
  vi.clearAllMocks();
  runtime.query = {
    data: undefined,
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  };
  runtime.resources = { en: enCommon, zh: zhCommon };
  runtime.navigate.mockClear();
  // v4 and v5 deliberately share the name "Wm82" (the ambiguous case the
  // resolver must report instead of collapsing), while "Wm82.a4.v1" stays
  // unique (the legacy unique-name deep link that must keep working).
  runtime.assemblies = [
    { id: 7, name: "Wm82", species: "Glycine max", version: "v4.0", is_default: true },
    { id: 8, name: "Wm82", species: "Glycine max", version: "v5.0", is_default: false },
    { id: 9, name: "Wm82.a4.v1", species: "Glycine max", version: "v4.0.1", is_default: false },
  ];
  runtime.assembliesQuery = {
    data: runtime.assemblies,
    isLoading: false,
    isSuccess: true,
    isError: false,
    isFetching: false,
    refetch: vi.fn(),
  };
});

function catalogue(next: string | null = null) {
  runtime.search = { q: "leaf", assembly: "7" };
  runtime.query = { ...runtime.query, data: { results: [], total_count: 0, next_cursor: next, has_more: Boolean(next) } };
}
function lastNavigation() {
  return runtime.navigate.mock.lastCall?.[0] as { search: Record<string, unknown> };
}

describe("global search pagination and filters", () => {
  it("shows five types, filters by URL and clears a cursor on selection", () => {
    catalogue();
    runtime.search.cursor = "old";
    const view = render(<SearchPage />);
    expect(screen.getAllByRole("checkbox")).toHaveLength(5);
    fireEvent.click(screen.getByRole("checkbox", { name: "Genes" }));
    expect(lastNavigation().search).toMatchObject({ types: ["gene"], cursor: undefined, assembly: "7" });
    runtime.search = lastNavigation().search;
    view.rerender(<SearchPage />);
    (runtime.queryOptions.queryFn as () => unknown)();
    expect(globalSearch).toHaveBeenLastCalledWith(expect.objectContaining({ types: ["gene"], cursor: undefined }));
    fireEvent.click(screen.getByRole("button", { name: "All types" }));
    expect(lastNavigation().search.types).toBeUndefined();
  });
  it("navigates multiple cursors forward and back to the first page", () => {
    catalogue("page2");
    const view = render(<SearchPage />);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(lastNavigation().search.cursor).toBe("page2");
    runtime.search = lastNavigation().search;
    runtime.query = { ...runtime.query, data: { results: [], next_cursor: "page3", has_more: true } };
    view.rerender(<SearchPage />);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(lastNavigation().search.cursor).toBe("page3");
    runtime.search = lastNavigation().search;
    view.rerender(<SearchPage />);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(lastNavigation().search.cursor).toBe("page2");
    runtime.search = lastNavigation().search;
    view.rerender(<SearchPage />);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(lastNavigation().search.cursor).toBeUndefined();
  });
  it("preserves filters on query submit and ignores unknown result types", () => {
    catalogue();
    runtime.search.types = ["gene", "unknown", "gene"];
    render(<SearchPage />);
    (runtime.queryOptions.queryFn as () => unknown)();
    expect(globalSearch).toHaveBeenLastCalledWith(expect.objectContaining({ types: ["gene"] }));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "new query" } });
    fireEvent.keyDown(screen.getByRole("searchbox"), { key: "Enter", keyCode: 13 });
    expect(lastNavigation().search).toMatchObject({ q: "new query", types: ["gene"], assembly: "7", cursor: undefined });
  });
  it("disables pagination while fetching and offers request recovery", () => {
    catalogue("page2");
    runtime.search.cursor = "current";
    runtime.query = { ...runtime.query, isFetching: true, isError: true };
    render(<SearchPage />);
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(runtime.query.refetch).toHaveBeenCalledOnce();
  });
  it("disables next on the last page", () => {
    catalogue();
    render(<SearchPage />);
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
  });
  it("retains initial cursor deep links and offers first page without invented history", () => {
    catalogue();
    runtime.search.cursor = "deep-link";
    render(<SearchPage />);
    (runtime.queryOptions.queryFn as () => unknown)();
    expect(globalSearch).toHaveBeenCalledWith(expect.objectContaining({ cursor: "deep-link" }));
    fireEvent.click(screen.getByRole("button", { name: "First" }));
    expect(lastNavigation().search.cursor).toBeUndefined();
  });
  it.each(["q", "assembly", "types", "release"])("resets stale cursor when %s changes", (dimension) => {
    catalogue();
    runtime.search.cursor = "old";
    const view = render(<SearchPage />);
    if (dimension === "release") runtime.release = "9";
    // "assembly" switches to another *resolvable* assembly: an unresolvable
    // one blocks the request instead (see the assembly-scope suite below).
    else runtime.search = { ...runtime.search, [dimension]: dimension === "types" ? ["gene"] : dimension === "assembly" ? "8" : "changed" };
    view.rerender(<SearchPage />);
    (runtime.queryOptions.queryFn as () => unknown)();
    expect(globalSearch).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: undefined }));
    expect(lastNavigation().search.cursor).toBeUndefined();
  });
  it("never resurrects a stale release cursor while URL clearing is pending", () => {
    catalogue("next-release-page");
    runtime.search.cursor = "old-release-cursor";
    const view = render(<SearchPage />);
    runtime.release = "9";
    view.rerender(<SearchPage />);
    // Deliberately do not apply the URL navigation yet.
    fireEvent.click(screen.getByRole("checkbox", { name: "Genes" }));
    view.rerender(<SearchPage />);
    (runtime.queryOptions.queryFn as () => unknown)();
    expect(globalSearch).toHaveBeenLastCalledWith(expect.objectContaining({ release_id: 9, cursor: undefined }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    view.rerender(<SearchPage />);
    (runtime.queryOptions.queryFn as () => unknown)();
    expect(globalSearch).toHaveBeenLastCalledWith(expect.objectContaining({ release_id: 9, cursor: undefined }));
  });
  it("does not redirect standalone child tools when the release changes", () => {
    runtime.pathname = "/search/genes";
    runtime.search = { q: "leaf", cursor: "parent-cursor" };
    const view = render(<SearchPage />);
    runtime.release = "9";
    view.rerender(<SearchPage />);
    expect(runtime.navigate).not.toHaveBeenCalled();
    expect(runtime.queryOptions.enabled).toBe(false);
    expect(screen.queryByRole("searchbox")).toBeNull();
  });
  it("does not invent pagination or type controls for the internal directory", () => {
    runtime.variant = "internal";
    runtime.search = { q: "leaf", cursor: "ignored" };
    runtime.query = { ...runtime.query, data: { genes: [], mutants: [], total_count: 0 } };
    render(<SearchPage />);
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByText("Internal directory results are not paginated.")).toBeTruthy();
    (runtime.queryOptions.queryFn as () => unknown)();
    expect(internalSearch).toHaveBeenCalledWith("leaf", { limit: 20 });
  });
});

/**
 * DB-CORE-3: v4 and v5 are distinct coordinate/identifier namespaces. An
 * unscoped query may be issued, but its hits must carry the assembly identity
 * and an ambiguous match must be reported instead of silently collapsed onto a
 * default version.
 */
describe("global search assembly scope", () => {
  const crossAssemblyResponse = {
    results: [
      {
        type: "gene",
        id: "Glyma.01G000100",
        name: "Gene A",
        assembly_id: 7,
        assembly: "Wm82 v4.0",
        url: "/genes/Glyma.01G000100",
      },
      {
        type: "gene",
        id: "Glyma.01G000101",
        name: "Gene B",
        assembly_id: 8,
        assembly: "Wm82 v5.0",
        url: "/genes/Glyma.01G000101",
      },
    ],
    total_count: 5,
    by_assembly: { "7": 3, "8": 2 },
    ambiguous: true,
  };

  it("offers assembly scopes without presenting distribution counts as result totals", () => {
    runtime.search = { q: "leaf", types: ["variant"] };
    runtime.query = { ...runtime.query, data: crossAssemblyResponse };
    render(<SearchPage />);

    const v4 = screen.getByTestId("search-assembly-option-7");
    const v5 = screen.getByTestId("search-assembly-option-8");
    expect(v4.textContent).toBe("Wm82 v4.0");
    expect(v5.textContent).toBe("Wm82 v5.0");
    fireEvent.click(v5);
    expect(lastNavigation().search).toMatchObject({ assembly: "8", cursor: undefined });
  });

  it("scopes the request to the numeric assembly id from the URL", () => {
    runtime.search = { q: "leaf", assembly: "8" };
    render(<SearchPage />);
    (runtime.queryOptions.queryFn as () => unknown)();
    expect(globalSearch).toHaveBeenLastCalledWith(expect.objectContaining({ assembly_id: 8 }));
  });

  it("resolves a legacy unique assembly name to the canonical id instead of NaN", () => {
    runtime.search = { q: "leaf", assembly: "Wm82.a4.v1" };
    render(<SearchPage />);
    (runtime.queryOptions.queryFn as () => unknown)();
    expect(globalSearch).toHaveBeenLastCalledWith(expect.objectContaining({ assembly_id: 9 }));
    // The old `Number(assembly)` conversion produced NaN for a name and the
    // API rejected the request with 422.
    expect(globalSearch).not.toHaveBeenLastCalledWith(expect.objectContaining({ assembly_id: NaN }));
  });

  it("runs an unscoped discovery query without an assembly id", () => {
    runtime.search = { q: "leaf" };
    render(<SearchPage />);
    (runtime.queryOptions.queryFn as () => unknown)();
    expect(globalSearch).toHaveBeenLastCalledWith(expect.objectContaining({ assembly_id: undefined }));
  });

  it("does not send a request for an unknown assembly and offers a recoverable prompt", async () => {
    runtime.search = { q: "leaf", assembly: "no-such-assembly" };
    render(<SearchPage />);
    expect(runtime.queryOptions.enabled).toBe(false);
    await expect((runtime.queryOptions.queryFn as () => Promise<unknown>)()).rejects.toThrow();
    expect(globalSearch).not.toHaveBeenCalled();
    expect(screen.getByTestId("search-assembly-blocked")).toBeTruthy();
    expect(screen.getByText("The requested assembly is unavailable; no query was sent.")).toBeTruthy();
    // The picker stays available so the user can recover without editing the URL.
    expect(screen.getByTestId("search-assembly-select")).toBeTruthy();
  });

  it("reports an ambiguous assembly name and sends no request", async () => {
    runtime.search = { q: "leaf", assembly: "Wm82" };
    render(<SearchPage />);
    expect(runtime.queryOptions.enabled).toBe(false);
    await expect((runtime.queryOptions.queryFn as () => Promise<unknown>)()).rejects.toThrow();
    expect(globalSearch).not.toHaveBeenCalled();
    expect(screen.getByTestId("search-assembly-blocked")).toBeTruthy();
    expect(screen.getByText(/Assembly name matches several versions/)).toBeTruthy();
  });

  it("waits for the assembly catalogue before it decides", async () => {
    runtime.assembliesQuery = {
      data: undefined,
      isLoading: true,
      isSuccess: false,
      isError: false,
      isFetching: true,
      refetch: vi.fn(),
    };
    runtime.search = { q: "leaf", assembly: "7" };
    render(<SearchPage />);
    expect(runtime.queryOptions.enabled).toBe(false);
    await expect((runtime.queryOptions.queryFn as () => Promise<unknown>)()).rejects.toThrow();
    expect(globalSearch).not.toHaveBeenCalled();
    // A catalogue that has not arrived yet is not an "unknown" assembly.
    expect(screen.queryByTestId("search-assembly-blocked")).toBeNull();
  });

  it("flags a cross-assembly match and labels every hit with its assembly", () => {
    runtime.search = { q: "leaf" };
    runtime.query = { ...runtime.query, data: crossAssemblyResponse };
    render(<SearchPage />);
    expect(screen.getByTestId("search-ambiguous-notice")).toBeTruthy();
    expect(
      screen.getByText("This query matches more than one genome version. Choose a version to disambiguate."),
    ).toBeTruthy();
    const labels = screen.getAllByTestId("search-result-assembly").map((node) => node.textContent);
    expect(labels).toEqual(["Wm82 v4.0", "Wm82 v5.0"]);
    expect(screen.getByTestId("search-assembly-select")).toBeTruthy();
    expect(screen.getByTestId("search-assembly-option-7")).toBeTruthy();
    expect(screen.getByTestId("search-assembly-option-8")).toBeTruthy();
  });

  it("writes the canonical assembly id to the URL and clears the cursor", () => {
    runtime.search = { q: "leaf", cursor: "old" };
    runtime.query = { ...runtime.query, data: crossAssemblyResponse };
    render(<SearchPage />);
    fireEvent.click(screen.getByTestId("search-assembly-option-8"));
    expect(lastNavigation().search).toMatchObject({ assembly: "8", cursor: undefined, q: "leaf" });
  });

  it("the version picker writes the canonical assembly id to the URL and clears the cursor", () => {
    runtime.search = { q: "leaf", cursor: "old" };
    runtime.query = { ...runtime.query, data: crossAssemblyResponse };
    render(<SearchPage />);
    // The picker is labelled, and its options carry the version so v4 and v5
    // stay distinguishable.
    fireEvent.mouseDown(screen.getByLabelText("Genome version"));
    fireEvent.click(screen.getByTitle("Wm82 v5.0"));
    expect(lastNavigation().search).toMatchObject({ assembly: "8", cursor: undefined, q: "leaf" });
  });

  it("never renders an internal identifier on the external site", () => {
    runtime.variant = "external";
    runtime.search = { q: "leaf" };
    runtime.query = {
      ...runtime.query,
      data: {
        results: [
          {
            type: "mutant_line",
            id: "M-001",
            public_id: "M-001",
            internal_id: "SENTINEL-INTERNAL-9f3a",
            name: "Line",
            url: "/mutants/M-001",
          },
        ],
        total_count: 1,
      },
    };
    render(<SearchPage />);
    expect(screen.queryByTestId("search-internal-id")).toBeNull();
    expect(document.body.textContent).not.toContain("SENTINEL-INTERNAL-9f3a");
  });

  it("keeps the internal directory free of an assembly scope", () => {
    runtime.variant = "internal";
    runtime.search = { q: "leaf" };
    runtime.query = { ...runtime.query, data: { genes: [], mutants: [], total_count: 0 } };
    render(<SearchPage />);
    // The internal directory has no assembly dimension: no picker, and the
    // assembly catalogue is not even requested.
    expect(screen.queryByTestId("search-assembly-select")).toBeNull();
    expect(runtime.assembliesOptions.enabled).toBe(false);
    (runtime.queryOptions.queryFn as () => unknown)();
    expect(globalSearch).not.toHaveBeenCalled();
    expect(internalSearch).toHaveBeenCalledWith("leaf", { limit: 20 });
  });

  it("renders the internal identifier only for an authorized internal result", () => {
    runtime.variant = "internal";
    runtime.search = { q: "leaf" };
    runtime.query = {
      ...runtime.query,
      data: {
        genes: [],
        mutants: [
          {
            public_id: "M-001",
            internal_id: "SENTINEL-INTERNAL-9f3a",
            name: "Line",
            matched_field: "internal_id",
            match_type: "exact",
          },
        ],
        total_count: 1,
      },
    };
    render(<SearchPage />);
    expect(screen.getByText("SENTINEL-INTERNAL-9f3a")).toBeTruthy();
  });
});

describe("global search localization", () => {
  it("renders the search form and empty prompt in Chinese", () => {
    runtime.language = "zh";
    render(<SearchPage />);

    expect(screen.getByRole("heading", { level: 1, name: "探索 SoyMutDB" })).toBeTruthy();
    expect(screen.getByRole("searchbox", { name: "搜索" })).toBeTruthy();
    // The external-source (federated) toggle was retired permanently, so the
    // portal search box must not offer it any more.
    expect(screen.queryByTestId("external-source-toggle")).toBeNull();
    expect(screen.getByText("输入关键词开始搜索")).toBeTruthy();
    expect(screen.getByText("输入基因、变异或论文信息以探索数据库。")).toBeTruthy();
  });

  it("localizes result summaries and no-match guidance in Chinese", () => {
    runtime.language = "zh";
    runtime.search = { q: "Glyma.01G000100" };
    runtime.query = {
      data: { results: [], total_count: 0 },
      isError: false,
      isFetching: false,
      isLoading: false,
      refetch: vi.fn(),
    };
    render(<SearchPage />);

    const results = screen.getByRole("region", { name: "搜索结果" });
    expect(results.textContent).toContain("搜索结果：");
    expect(screen.getByText("0 条结果")).toBeTruthy();
    expect(screen.getByText("未找到结果")).toBeTruthy();
    expect(screen.getByText("没有记录匹配此查询，请尝试更宽泛的关键词。")).toBeTruthy();
  });
});
