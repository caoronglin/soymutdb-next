// @vitest-environment jsdom
import * as React from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
// The shared double keeps `t`'s identity stable across renders, which the i18n
// contract in scripts/test_ci_job_contracts.py enforces.
import { stableT } from "@/test/mocks";

const runtime = vi.hoisted(() => ({
  search: {} as Record<string, unknown>,
  queries: [] as Array<{ queryKey: readonly unknown[]; enabled?: boolean }>,
  assemblies: [
    { id: 4, name: "v4", is_default: false },
    { id: 5, name: "v5", is_default: true },
  ],
  chromosomes: [{ name: "chr01" }],
}));

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: Record<string, unknown>) => ({
    options,
    useSearch: () => runtime.search,
  }),
  Link: "a",
  useRouter: () => ({ buildLocation: ({ to }: { to: string }) => ({ href: to }) }),
}));

vi.mock("@tanstack/react-query", () => ({
  // The route components now build their assembly reads through
  // `assembliesQueryOptions()`, which wraps the options object in the real
  // `queryOptions()` helper. Pass it through so the page under test hands this
  // mock the same `{ queryKey, enabled }` shape it always did.
  queryOptions: <T,>(options: T): T => options,
  infiniteQueryOptions: <T,>(options: T): T => options,
  useQuery: (options: { queryKey: readonly unknown[]; enabled?: boolean }) => {
    runtime.queries.push({ queryKey: options.queryKey, enabled: options.enabled });
    const key = options.queryKey;
    const data = key.includes("list") ? runtime.assemblies
      : key.includes("chromosomes") ? runtime.chromosomes
      : key.includes("search") ? { items: [], total: 0 }
      : [];
    return { data, isError: false, isLoading: false, isFetching: false };
  },
}));

vi.mock("react-i18next", () => ({
  // `t` must keep a stable identity across renders (see
  // scripts/test_ci_job_contracts.py): bind a module-level function.
  useTranslation: () => ({ t: stableT }),
}));
vi.mock("../../components/route-motion", () => ({
  FadeUp: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("../../lib/release-scope", () => ({
  // Search-page unit tests intentionally mount only the route, not the full
  // App provider tree. Stub the public reactive release hook explicitly.
  useReleaseId: () => null,
}));
vi.mock("../../lib/site-content-react", () => ({
  useSiteContent: () => ({ get: (_key: string, fallback: string) => fallback }),
}));

vi.mock("@/lib/antd", () => {
  const Wrapper = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  const Form = Object.assign(
    ({ children, onFinish }: { children?: React.ReactNode; onFinish?: () => void }) =>
      <form onSubmit={(event) => { event.preventDefault(); onFinish?.(); }}>{children}</form>,
    { Item: Wrapper },
  );
  const Input = (props: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} />;
  Input.TextArea = (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...props} />;
  const Select = ({ options = [], onChange, ...props }: {
    options?: Array<{ value: string; label: React.ReactNode }>;
    onChange?: (value: string) => void;
    value?: string;
  }) => <select value={props.value ?? ""} onChange={(event) => onChange?.(event.target.value)}>
    <option value="" />{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
  </select>;
  return {
    // antd 6 renamed `message` to `title` on Alert (`message` logs a deprecation
    // warning and is removed later); the stub follows the real API so these
    // assertions keep testing the pages rather than the stub.
    Alert: ({ title }: { title: React.ReactNode }) => <div role="alert">{title}</div>,
    Button: ({ children, disabled }: { children?: React.ReactNode; disabled?: boolean }) => <button disabled={disabled}>{children}</button>,
    Card: Wrapper,
    Empty: Wrapper,
    // The query bars lay their controls out with antd's `Flex` (nested:
    // `gap={8}` inside a field group, `gap={20}` between groups). `Space` is
    // kept because the pages still use it elsewhere.
    Flex: Wrapper,
    Form,
    Input,
    InputNumber: () => <input type="number" />,
    Select,
    // Superseded by `Flex` in the query bars, still used on other pages.
    Space: Wrapper,
    Table: () => <table />,
    Tag: Wrapper,
    Typography: { Text: Wrapper },
  };
});

import { Route as GeneRoute } from "./genes";
import { Route as LocationRoute } from "./location";

const GenePage = (GeneRoute as unknown as { options: { component: React.ComponentType } }).options.component;
const LocationPage = (LocationRoute as unknown as { options: { component: React.ComponentType } }).options.component;

beforeEach(() => {
  runtime.search = {};
  runtime.queries = [];
});
afterEach(() => cleanup());

describe("two active search tools", () => {
  it("does not run a gene query under the default genome when the deep link names an unknown one", () => {
    runtime.search = { q: "Glyma.01G000100", assembly: "missing", run: true };
    render(<GenePage />);
    expect(screen.getByRole("alert").textContent).toBe("search.assemblyUnavailable");
    expect(runtime.queries.find((item) => item.queryKey.includes("search"))?.enabled).toBe(false);
  });

  it("runs gene search with the explicitly selected v4, not the default v5", () => {
    runtime.search = { q: "Glyma.01G000100", assembly: "v4", run: true };
    render(<GenePage />);
    const query = runtime.queries.find((item) => item.queryKey.includes("search"));
    expect(query?.enabled).toBe(true);
    expect(query?.queryKey).toContain("4");
  });

  it("rejects an unknown location assembly without issuing a source-site query", async () => {
    runtime.search = { assembly: "missing", chromosome: "chr01", start: 1, end: 20, run: true };
    render(<LocationPage />);
    expect(screen.getByRole("alert").textContent).toBe("search.assemblyUnavailable");
    await waitFor(() => expect(runtime.queries.find((item) => item.queryKey.includes("search-region-preview-sites"))?.enabled).toBe(false));
  });

  it("rejects NaN coordinates in a deep link", async () => {
    runtime.search = { assembly: "v4", chromosome: "chr01", start: Number.NaN, end: 20, run: true };
    render(<LocationPage />);
    await waitFor(() => expect(runtime.queries.find((item) => item.queryKey.includes("search-region-preview-sites"))?.enabled).toBe(false));
  });
});
