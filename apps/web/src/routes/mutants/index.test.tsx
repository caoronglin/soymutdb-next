// @vitest-environment jsdom
import * as React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const runtime = vi.hoisted(() => ({
  search: { q: "", mutagen: "", page: 1 },
  release: "4",
  navigate: vi.fn(),
  refetch: vi.fn(),
  queryOptions: {} as Record<string, unknown>,
  data: [] as { public_id: string; name: string }[],
  isError: false,
  // The scroll configuration the table was rendered with; `undefined` until a
  // table is rendered.
  tableScroll: undefined as { x?: number | string | true } | undefined,
}));
vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: Record<string, unknown>) => ({
    ...options, options,
    useSearch: () => runtime.search,
    useNavigate: () => runtime.navigate,
  }),
  Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a>,
}));
vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: Record<string, unknown>) => {
    runtime.queryOptions = options;
    return { data: runtime.isError ? undefined : runtime.data, isLoading: false,
      isFetching: false, isError: runtime.isError, refetch: runtime.refetch };
  },
}));
vi.mock("@soymutdb/api-client", () => ({ listMutantLines: vi.fn() }));
vi.mock("../../lib/release-scope", () => ({ useReleaseId: () => runtime.release }));
vi.mock("../../components/route-motion", () => ({
  FadeUp: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("react-i18next", () => {
  // These boundary tests assert keys; keep their translator stable across renders.
  const translation = { t: (key: string) => key };
  return { useTranslation: () => translation };
});
vi.mock("@/lib/antd", () => ({
  Button: ({ children, loading: _loading, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean }) => <button {...props}>{children}</button>,
  Empty: ({ description }: { description: React.ReactNode }) => <div>{description}</div>,
  Input: ({ onPressEnter, allowClear: _clear, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { onPressEnter?: () => void; allowClear?: boolean }) => <input {...props} onKeyDown={(event) => { if (event.key === "Enter") onPressEnter?.(); }} />,
  Skeleton: () => null,
  Typography: { Paragraph: ({ children }: { children: React.ReactNode }) => <p>{children}</p>, Text: ({ children }: { children: React.ReactNode }) => <span>{children}</span> },
  Table: ({ dataSource, scroll }: { dataSource: { public_id: string }[]; scroll?: { x?: number | string | true } }) => {
    runtime.tableScroll = scroll;
    return <div>{dataSource.map((row) => <div key={row.public_id}>{row.public_id}</div>)}</div>;
  },
}));
import { listMutantLines } from "@soymutdb/api-client";
import { Route } from "./index";
const Page = (Route as unknown as { options: { component: React.ComponentType } }).options.component;
afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  runtime.search = { q: "", mutagen: "", page: 1 };
  runtime.release = "4";
  runtime.isError = false;
  runtime.data = [];
  runtime.tableScroll = undefined;
});

it("uses URL filters and a one-row look-ahead without displaying that extra row", () => {
  runtime.search = { q: "leaf", mutagen: "EMS", page: 3 };
  runtime.data = Array.from({ length: 51 }, (_, i) => ({ public_id: `SM${i}`, name: `Line ${i}` }));
  render(<Page />);
  (runtime.queryOptions.queryFn as () => unknown)();
  expect(listMutantLines).toHaveBeenCalledWith({ q: "leaf", mutagen: "EMS", limit: 51, offset: 100 });
  expect(screen.queryByText("SM50")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "common.next" }));
  expect(runtime.navigate).toHaveBeenCalledWith({ to: "/mutants", search: { q: "leaf", mutagen: "EMS", page: 4 } });
  fireEvent.click(screen.getByRole("button", { name: "common.previous" }));
  expect(runtime.navigate).toHaveBeenLastCalledWith({ to: "/mutants", search: { q: "leaf", mutagen: "EMS", page: 2 } });
});
it("disables previous on the first page and next on a full final page", () => {
  runtime.data = Array.from({ length: 50 }, (_, i) => ({ public_id: `SM${i}`, name: "Line" }));
  render(<Page />);
  expect((screen.getByRole("button", { name: "common.previous" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "common.next" }) as HTMLButtonElement).disabled).toBe(true);
});
it("resets the page when applying free text and retains exact mutagen", () => {
  runtime.search = { q: "old", mutagen: "EMS", page: 3 };
  render(<Page />);
  fireEvent.change(screen.getByLabelText("mutants.filter.label"), { target: { value: "Jack" } });
  fireEvent.click(screen.getByRole("button", { name: "mutants.filter.apply" }));
  expect(runtime.navigate).toHaveBeenCalledWith({ to: "/mutants", search: { q: "Jack", mutagen: "EMS", page: 1 } });
});
it("offers a retry after a request fails", () => {
  runtime.isError = true;
  render(<Page />);
  fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
  expect(runtime.refetch).toHaveBeenCalledOnce();
});
it("keys results by reactive release and resets paging on release changes", () => {
  runtime.search.page = 3;
  const view = render(<Page />);
  const first = runtime.queryOptions.queryKey;
  runtime.release = "9";
  view.rerender(<Page />);
  expect(runtime.queryOptions.queryKey).not.toEqual(first);
  expect(runtime.queryOptions.queryKey).toContain("9");
  expect(runtime.navigate).toHaveBeenCalledWith({ to: "/mutants", search: { q: "", mutagen: "", page: 1 } });
});
it("rejects malformed or unbounded page values", () => {
  const validate = (Route as unknown as { options: { validateSearch: (s: Record<string, unknown>) => { page: number } } }).options.validateSearch;
  for (const page of ["Infinity", "NaN", -1, 1.5, 1e20]) expect(validate({ page }).page).toBe(1);
  expect(validate({ page: "3" }).page).toBe(3);
});
it("scrolls a wide table sideways on a narrow screen instead of squeezing it", () => {
  runtime.data = [{ public_id: "SM7K3ZQ9P2AX", name: "Line" }];
  render(<Page />);
  expect(runtime.tableScroll).toEqual({ x: "max-content" });
});
