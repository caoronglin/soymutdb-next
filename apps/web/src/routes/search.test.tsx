// @vitest-environment jsdom
import * as React from "react";
import { cleanup, render, screen } from "@testing-library/react";
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
  useQuery: () => runtime.query,
}));

vi.mock("react-i18next", () => ({
  // `t` must keep a stable identity across renders: pass the module-level
  // resolver straight through instead of wrapping it in a fresh closure.
  useTranslation: () => ({ t: resolveKey }),
}));

vi.mock("../components/route-motion", () => ({
  FadeUp: ({ children }: { children: React.ReactNode }) => children,
}));

import { Route } from "./search";

type RouteOptions = { component: React.ComponentType };
const SearchPage = (Route as unknown as { options: RouteOptions }).options.component;

afterEach(() => cleanup());

beforeEach(() => {
  runtime.language = "en";
  runtime.search = {};
  runtime.query = {
    data: undefined,
    isError: false,
    isFetching: false,
    isLoading: false,
    refetch: vi.fn(),
  };
  runtime.resources = { en: enCommon, zh: zhCommon };
  runtime.navigate.mockClear();
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
