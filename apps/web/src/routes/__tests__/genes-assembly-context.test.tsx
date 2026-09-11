// @vitest-environment jsdom
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const state = vi.hoisted(() => ({
  search: {
    q: "Glyma.02G000100",
    assembly: "alt-assembly",
    run: true,
  },
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
      buildLocation: ({ to }: { to: string }) => ({ href: to }),
    }),
  };
});

vi.mock("@soymutdb/api-client", () => ({
  getAssemblies: state.getAssemblies,
  searchGenes: state.searchGenes,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

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
    <QueryClientProvider client={queryClient}>
      <Component />
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
