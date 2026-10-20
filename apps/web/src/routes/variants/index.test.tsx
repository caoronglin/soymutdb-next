import * as React from "react";
import { fireEvent, render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const runtime = vi.hoisted(() => ({
  search: { assembly: "1", chromosome: "", variant_type: "", impact: "", mutant_line_public_id: "", cursor: undefined as string | undefined },
  navigate: vi.fn(),
}));
vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: unknown) => ({ options, useSearch: () => runtime.search }),
  useNavigate: () => runtime.navigate,
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../../lib/site-content-react", () => ({ useSiteContent: () => ({ get: (_key: string, fallback: string) => fallback }) }));
vi.mock("../../components/route-motion", () => ({ FadeUp: ({ children }: { children: React.ReactNode }) => children }));
vi.mock("@soymutdb/api-client", () => ({ getReleaseId: () => "1", searchVariants: vi.fn(), createVariantExport: vi.fn(), getAssemblies: vi.fn() }));
vi.mock("@tanstack/react-query", () => ({
  queryOptions: (options: unknown) => options,
  useQuery: (options: { queryKey: unknown[] }) => options.queryKey.includes("assemblies")
    ? { data: [{ id: 1, name: "Wm82.a4.v1", is_default: true }] }
    : { data: { items: [], has_more: true, next_cursor: runtime.search.cursor === "page-2" ? "page-3" : "page-2" } },
}));
import { Route } from "./index";
const Page = (Route.options as { component: React.ComponentType }).component;
afterEach(cleanup);

describe("variant cursor history", () => {
  it("returns page 3 to page 2, then page 1 without skipping, and can advance again", () => {
    runtime.search.cursor = undefined;
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
