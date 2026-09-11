// @vitest-environment jsdom
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SiteContentProvider } from "@/lib/site-content";

const state = vi.hoisted(() => ({
  // URL search params restored by the route. Each field is optional: a test
  // clears them to exercise the pristine (no deep link) form state.
  search: {
    q: "Glyma.02G000100",
    assembly: "alt-assembly",
    run: true,
  } as { q?: string; assembly?: string; run?: boolean },
  getAssemblies: vi.fn(),
  searchGenes: vi.fn(),
}));

vi.mock("@tanstack/react-router", async () => {
  const React = await import("react");

  return {
    createFileRoute: () => (options: Record<string, unknown>) => ({
      ...options,
      useSearch: () => state.search,
    }),
    Link: ({
      children,
      params: _params,
      search,
      to,
      ...props
    }: {
      children?: React.ReactNode;
      params?: unknown;
      search?: Record<string, unknown>;
      to: string;
    }) => {
      const query = search
        ? new URLSearchParams(
            Object.entries(search)
              .filter(([, value]) => value != null)
              .map(([key, value]) => [key, String(value)]),
          )
        : null;
      return React.createElement(
        "a",
        { href: query && query.toString() ? `${to}?${query}` : to, ...props },
        children,
      );
    },
    useRouter: () => ({
      // Mirror the router contract: `to` + `search` produce a URL with the
      // search params applied, so a regression that drops `q`/`assembly`/`run`
      // is observable here.
      buildLocation: ({ to, search }: { to: string; search?: Record<string, unknown> }) => {
        const params = new URLSearchParams(
          Object.entries(search ?? {})
            .filter(([, value]) => value != null)
            .map(([key, value]) => [key, String(value)]),
        );
        const query = params.toString();
        return { href: query ? `${to}?${query}` : to };
      },
    }),
  };
});

vi.mock("@soymutdb/api-client", () => ({
  getAssemblies: state.getAssemblies,
  searchGenes: state.searchGenes,
  // The route stamps the active release onto its API calls; no release is
  // pinned in this test, so the anonymous default (`null`) applies.
  getReleaseId: () => null,
}));

// The shared double keeps a stable `t` identity: an inline
// `() => ({ t: (key) => key })` returns a new function per render, which
// makes any component with `t` in an effect dependency loop forever.
// See src/test/mocks.ts.
vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);

vi.mock("@ant-design/icons", () => ({
  SearchOutlined: () => null,
}));

vi.mock("@/lib/antd", async () => {
  const React = await import("react");

  const Form = Object.assign(
    ({ children, onFinish, ...props }: { children?: React.ReactNode; onFinish?: () => void }) =>
      React.createElement(
        "form",
        {
          ...props,
          onSubmit: (event: React.FormEvent) => {
            event.preventDefault();
            onFinish?.();
          },
        },
        children,
      ),
    {
      Item: ({ children, label }: { children?: React.ReactNode; label?: React.ReactNode }) =>
        React.createElement("label", null, label, children),
    },
  );

  return {
    Button: ({
      children,
      disabled,
      href,
      htmlType,
      icon: _icon,
      loading: _loading,
      type: _type,
      ...props
    }: {
      children?: React.ReactNode;
      disabled?: boolean;
      href?: string;
      htmlType?: "button" | "submit" | "reset";
      icon?: React.ReactNode;
      loading?: boolean;
      type?: string;
    }) =>
      href
        ? React.createElement("a", { href, ...props }, children)
        : React.createElement("button", { disabled, type: htmlType, ...props }, children),
    Card: ({ children, ...props }: { children?: React.ReactNode }) =>
      React.createElement("section", props, children),
    Empty: ({ description }: { description?: React.ReactNode }) =>
      React.createElement("div", null, description),
    Form,
    Input: {
      TextArea: ({ ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) =>
        React.createElement("textarea", props),
    },
    Select: ({ options, value }: { options?: Array<{ label: React.ReactNode; value: string }>; value?: string }) => {
      const selected = options?.find((option) => option.value === value);
      return React.createElement("div", { "data-testid": "assembly-select" }, selected?.label);
    },
    Table: ({
      columns,
      dataSource,
    }: {
      columns: Array<{
        dataIndex?: string;
        key?: React.Key;
        render?: (value: unknown, row: Record<string, unknown>) => React.ReactNode;
      }>;
      dataSource: Array<Record<string, unknown>>;
    }) =>
      React.createElement(
        "table",
        null,
        React.createElement(
          "tbody",
          null,
          dataSource.map((row) =>
            React.createElement(
              "tr",
              { key: String(row.gene_id) },
              columns.map((column) =>
                React.createElement(
                  "td",
                  { key: column.key },
                  column.render?.(column.dataIndex ? row[column.dataIndex] : undefined, row),
                ),
              ),
            ),
          ),
        ),
      ),
    Tag: ({ children }: { children?: React.ReactNode }) => React.createElement("span", null, children),
    Typography: {
      Text: ({ children, ...props }: { children?: React.ReactNode }) =>
        React.createElement("span", props, children),
    },
  };
});

import { Route } from "../search/genes";

const defaultAssembly = {
  id: "default-assembly",
  name: "Glycine max Wm82.a2.v1",
  species: "Glycine max",
  version: "a2.v1",
  is_default: true,
};

const alternateAssembly = {
  id: "alt-assembly",
  name: "Glycine max Wm82.a4.v1",
  species: "Glycine max",
  version: "a4.v1",
  is_default: false,
};

function renderRoute() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  const Component = (Route as unknown as { component: React.ComponentType }).component;

  return render(
    // The gene route reads site copy through the provider; without it the
    // component throws instead of rendering the assembly context.
    <QueryClientProvider client={queryClient}>
      <SiteContentProvider>
        <Component />
      </SiteContentProvider>
    </QueryClientProvider>,
  );
}

describe("gene search assembly context", () => {
  beforeEach(() => {
    state.search = {
      q: "Glyma.02G000100",
      assembly: "alt-assembly",
      run: true,
    };
    state.getAssemblies.mockResolvedValue([defaultAssembly, alternateAssembly]);
    state.searchGenes.mockResolvedValue({
      items: [
        {
          id: "gene-1",
          gene_id: "Glyma.02G000100",
          symbol: null,
          name: null,
          biotype: "protein_coding",
          chromosome: "Chr02",
          start_pos: 100,
          end_pos: 200,
          strand: "+",
          description: null,
        },
      ],
      next_cursor: null,
      has_more: false,
      page: 1,
      page_size: 20,
      total: 1,
      total_pages: 1,
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("keeps a non-default deep link request, visible result context, and JBrowse link on one assembly", async () => {
    renderRoute();

    await waitFor(() => {
      expect(state.searchGenes).toHaveBeenCalledWith(
        expect.objectContaining({
          q: "Glyma.02G000100",
          assembly_id: alternateAssembly.id,
        }),
      );
    });

    expect(screen.getByTestId("assembly-select").textContent).toContain(alternateAssembly.name);

    const results = await screen.findByRole("region", { name: "Gene ID search results" });
    expect(within(results).getByText(alternateAssembly.name)).toBeTruthy();
    const browserHref = within(results).getByRole("link", { name: "search.genes.openBrowser" }).getAttribute("href");
    expect(new URL(browserHref ?? "", "https://portal.example.invalid").searchParams.get("assembly")).toBe(
      alternateAssembly.name,
    );
    const geneHref = within(results)
      .getByRole("link", { name: /search.genes.openGene/ })
      .getAttribute("href");
    expect(new URL(geneHref ?? "", "https://portal.example.invalid").searchParams.get("assembly")).toBe(
      alternateAssembly.id,
    );
  });

  it("disables submit until a genome-version context is resolved", async () => {
    let resolveAssemblies: (value: unknown) => void = () => {};
    state.getAssemblies.mockReturnValue(
      new Promise((resolve) => {
        resolveAssemblies = resolve;
      }),
    );

    renderRoute();

    // No assembly list yet → the submit control must not silently discard the
    // request; it reports that the genome-version context is unresolved.
    const submit = screen.getByText("search.genes.submit") as HTMLButtonElement;
    expect(submit.tagName).toBe("BUTTON");
    expect(submit.disabled).toBe(true);

    resolveAssemblies([defaultAssembly]);

    await waitFor(() => {
      expect((screen.getByText("search.genes.submit") as HTMLButtonElement).disabled).toBe(false);
    });
  });

  it("opens a parameterized result view once the assembly context is available", async () => {
    state.search = { q: undefined, assembly: undefined, run: false };
    const opened: string[] = [];
    const originalOpen = window.open;
    window.open = ((url?: string | URL) => {
      opened.push(String(url));
      return null;
    }) as typeof window.open;

    try {
      renderRoute();

      const input = screen.getByRole("textbox", { name: "search.genes.geneId" });
      const { fireEvent } = await import("@testing-library/react");
      fireEvent.change(input, { target: { value: "Glyma.01G000100" } });

      const submit = screen.getByText("search.genes.submit") as HTMLButtonElement;
      await waitFor(() => {
        expect(submit.disabled).toBe(false);
      });
      fireEvent.click(submit);

      expect(opened).toHaveLength(1);
      const url = new URL(opened[0] ?? "", "https://portal.example.invalid");
      expect(url.searchParams.get("q")).toBe("Glyma.01G000100");
      expect(url.searchParams.get("assembly")).toBe(defaultAssembly.id);
      expect(url.searchParams.get("run")).toBe("true");
    } finally {
      window.open = originalOpen;
    }
  });

  it("preselects an assembly-only deep link without starting a gene search", async () => {
    state.search = {
      q: "",
      assembly: alternateAssembly.id,
      run: false,
    };

    renderRoute();

    await waitFor(() => {
      expect(screen.getByTestId("assembly-select").textContent).toContain(alternateAssembly.name);
    });
    expect(state.searchGenes).not.toHaveBeenCalled();
  });
});
