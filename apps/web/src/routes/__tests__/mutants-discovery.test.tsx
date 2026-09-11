// @vitest-environment jsdom
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const state = vi.hoisted(() => ({
  search: { mutagen: "EMS" },
  params: { id: "42" },
  navigate: vi.fn(),
  listMutantLines: vi.fn(),
  getMutantLine: vi.fn(),
  getMutantLinePhenotypes: vi.fn(),
  searchVariants: vi.fn(),
}));

vi.mock("@tanstack/react-router", async () => {
  const React = await import("react");
  return {
    createFileRoute: () => (options: Record<string, unknown>) => ({
      ...options,
      useSearch: () => state.search,
      useParams: () => state.params,
      useNavigate: () => state.navigate,
    }),
    Link: ({ children, to, params, search, ...props }: { children?: React.ReactNode; to: string; params?: { id?: string }; search?: Record<string, string | undefined> }) => {
      const query = search
        ? new URLSearchParams(Object.entries(search).filter(([, value]) => value != null) as Array<[string, string]>).toString()
        : "";
      const href = params?.id ? `/mutants/${params.id}` : query ? `${to}?${query}` : to;
      return React.createElement("a", { href, ...props }, children);
    },
  };
});

vi.mock("@soymutdb/api-client", () => ({
  listMutantLines: state.listMutantLines,
  getMutantLine: state.getMutantLine,
  getMutantLinePhenotypes: state.getMutantLinePhenotypes,
  searchVariants: state.searchVariants,
  isMutantLineId: (value: string) => {
    const trimmed = value.trim();
    return trimmed.length >= 3 && trimmed.length <= 32 && /^[A-Za-z0-9_-]+$/.test(trimmed);
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/components/route-motion", () => ({
  FadeUp: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/antd", async () => {
  const React = await import("react");
  type Column = { title?: React.ReactNode; dataIndex?: string; key?: React.Key; render?: (value: unknown, row: Record<string, unknown>) => React.ReactNode };
  return {
    Alert: ({ message }: { message?: React.ReactNode }) => <div role="alert">{message}</div>,
    Descriptions: ({ items }: { items: Array<{ key: React.Key; label: React.ReactNode; children: React.ReactNode }> }) => (
      <dl>{items.map((item) => <React.Fragment key={item.key}><dt>{item.label}</dt><dd>{item.children}</dd></React.Fragment>)}</dl>
    ),
    Button: ({ children, onClick, ...props }: { children?: React.ReactNode; onClick?: () => void }) => <button onClick={onClick} {...props}>{children}</button>,
    Empty: ({ description }: { description?: React.ReactNode }) => <div>{description}</div>,
    Input: ({ value, onChange, onPressEnter, ...props }: { value?: string; onChange?: React.ChangeEventHandler<HTMLInputElement>; onPressEnter?: () => void }) => <input value={value} onChange={onChange} onKeyDown={(event) => { if (event.key === "Enter") onPressEnter?.(); }} {...props} />,
    Skeleton: (props: React.HTMLAttributes<HTMLDivElement>) => <div {...props} />,
    Table: ({ columns, dataSource, locale }: { columns: Column[]; dataSource: Record<string, unknown>[]; locale?: { emptyText?: React.ReactNode } }) => (
      <table><thead><tr>{columns.map((column) => <th key={column.key}>{column.title}</th>)}</tr></thead><tbody>{dataSource.length ? dataSource.map((row, index) => (
        <tr key={String(row.id ?? index)}>{columns.map((column) => <td key={column.key}>{column.render ? column.render(column.dataIndex ? row[column.dataIndex] : undefined, row) : column.dataIndex ? row[column.dataIndex] as React.ReactNode : null}</td>)}</tr>
      )) : <tr><td>{locale?.emptyText}</td></tr>}</tbody></table>
    ),
    Typography: { Paragraph: ({ children }: { children?: React.ReactNode }) => <p>{children}</p> },
  };
});

import { Route as BrowseRoute } from "../mutants/index";
import { Route as DetailRoute } from "../mutants/$id";

function renderRoute(Route: unknown) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Component = (Route as { component: React.ComponentType }).component;
  return render(<QueryClientProvider client={queryClient}><Component /></QueryClientProvider>);
}

beforeEach(() => {
  state.search = { mutagen: "EMS" };
  state.params = { id: "SM7K3ZQ9P2A" };
  state.listMutantLines.mockResolvedValue([]);
  state.getMutantLine.mockResolvedValue(null);
  state.getMutantLinePhenotypes.mockResolvedValue([]);
  state.searchVariants.mockResolvedValue({ items: [], next_cursor: null, has_more: false, total_count: 0 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("mutant discovery public routes", () => {
  it("browses canonical mutant lines with the selected mutagen and exposes only server scientific fields and detail links", async () => {
    state.listMutantLines.mockResolvedValue([{
      public_id: "SM7K3ZQ9P2A", name: "EMS-42", cultivar: "Williams 82", mutagen: "EMS", variant_count: 17,
      description: "must not appear", species: "Glycine max", generation: "M2", phenotype_summary: "must not appear",
    }]);

    renderRoute(BrowseRoute);

    await waitFor(() => expect(state.listMutantLines).toHaveBeenCalledWith({ mutagen: "EMS", limit: 100 }));
    const row = (await screen.findByText("EMS-42")).closest("tr")!;
    expect(within(row).getByText("Williams 82")).toBeTruthy();
    expect(within(row).getByText("EMS")).toBeTruthy();
    expect(within(row).getByText("17")).toBeTruthy();
    expect(within(row).getByRole("link", { name: "EMS-42" }).getAttribute("href")).toBe("/mutants/SM7K3ZQ9P2A");
    expect(screen.queryByText("must not appear")).toBeNull();
  });

  it("applies an arbitrary mutagen rather than relying on values from a limited result page", async () => {
    state.search = { mutagen: "" };
    renderRoute(BrowseRoute);

    fireEvent.change(screen.getByLabelText("mutants.filter.label"), { target: { value: "Fast neutron" } });
    fireEvent.click(screen.getByRole("button", { name: "mutants.filter.apply" }));

    expect(state.navigate).toHaveBeenCalledWith({ to: "/mutants", search: { mutagen: "Fast neutron" } });
  });

  it("preserves the submitted exact mutagen query without normalization", async () => {
    state.search = { mutagen: "" };
    renderRoute(BrowseRoute);

    fireEvent.change(screen.getByLabelText("mutants.filter.label"), { target: { value: " EMS " } });
    fireEvent.click(screen.getByRole("button", { name: "mutants.filter.apply" }));

    expect(state.navigate).toHaveBeenCalledWith({ to: "/mutants", search: { mutagen: " EMS " } });
  });

  it("renders a clear filtered-empty state", async () => {
    state.listMutantLines.mockResolvedValue([]);
    renderRoute(BrowseRoute);

    expect(await screen.findByText("mutants.emptyFiltered")).toBeTruthy();
  });

  it("renders an actionable browse error without leaking backend detail", async () => {
    state.listMutantLines.mockRejectedValue(new Error("backend detail"));
    renderRoute(BrowseRoute);

    expect(await screen.findByText("mutants.error")).toBeTruthy();
    expect(screen.queryByText(/backend detail/i)).toBeNull();
  });

  it("loads the line before its phenotypes and renders the explicit ontology, environment, and protocol caveat", async () => {
    state.getMutantLine.mockResolvedValue({
      public_id: "SM7K3ZQ9P2A", name: "EMS-42", species: "Glycine max", cultivar: "Williams 82", mutagen: "EMS", generation: "M2", description: null, phenotype_summary: null, variant_count: 17,
    });
    state.getMutantLinePhenotypes.mockResolvedValue([{ id: "phenotype-1", trait_category: "Plant height", trait_name: "Height", trait_value: "30", unit: "cm", description: "Measured at flowering" }]);
    state.searchVariants.mockResolvedValue({
      items: [{ variant_id: "variant-1" }], next_cursor: null, has_more: false, total_count: 1,
    });

    renderRoute(DetailRoute);

    await waitFor(() => expect(state.getMutantLine).toHaveBeenCalledWith("SM7K3ZQ9P2A"));
    await waitFor(() => expect(state.getMutantLinePhenotypes).toHaveBeenCalledWith("SM7K3ZQ9P2A"));
    await waitFor(() => expect(state.searchVariants).toHaveBeenCalledWith({ mutant_line_id: "SM7K3ZQ9P2A", limit: 1 }));
    expect(state.getMutantLine.mock.invocationCallOrder[0]).toBeLessThan(state.getMutantLinePhenotypes.mock.invocationCallOrder[0]);
    expect(await screen.findByText("Height")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("mutants.phenotypes.boundary");
    const variantsHref = screen.getByRole("link", { name: "mutants.detail.viewVariants" }).getAttribute("href");
    const variantsUrl = new URL(variantsHref!, "https://soymutdb.example");
    expect(variantsUrl.pathname).toBe("/variants");
    expect(variantsUrl.searchParams.get("mutant_line_id")).toBe("SM7K3ZQ9P2A");
  });

  it("withholds the variant link when the active variant release has no matching record", async () => {
    state.getMutantLine.mockResolvedValue({
      public_id: "SM7K3ZQ9P2A", name: "Summary-only line", species: "Glycine max", cultivar: null, mutagen: null, generation: null, description: null, phenotype_summary: null, variant_count: 17,
    });
    renderRoute(DetailRoute);

    await waitFor(() => expect(state.searchVariants).toHaveBeenCalledWith({ mutant_line_id: "SM7K3ZQ9P2A", limit: 1 }));
    expect(await screen.findByText("Summary-only line")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "mutants.detail.viewVariants" })).toBeNull();
  });

  it("does not query unavailable noncanonical line IDs", async () => {
    state.params = { id: "line-42" };
    renderRoute(DetailRoute);

    expect(await screen.findByText("mutants.detail.notFound")).toBeTruthy();
    expect(state.getMutantLine).not.toHaveBeenCalled();
    expect(state.getMutantLinePhenotypes).not.toHaveBeenCalled();
  });

  it("uses a neutral unavailable-line message", async () => {
    state.getMutantLine.mockRejectedValue(new Error("not found"));

    renderRoute(DetailRoute);

    expect(await screen.findByText("mutants.detail.notFound")).toBeTruthy();
    expect(screen.queryByText(/not found/i)).toBeNull();
    expect(state.getMutantLinePhenotypes).not.toHaveBeenCalled();
  });
});
