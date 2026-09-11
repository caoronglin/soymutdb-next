// @vitest-environment jsdom
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

vi.mock("@tanstack/react-router", () => ({
  Link: ({
    to,
    children,
    params: _params,
    search: _search,
    ...props
  }: {
    to: string;
    children?: React.ReactNode;
    params?: unknown;
    search?: unknown;
  }) => (
    <a href={to} {...props}>
      {children}
    </a>
  ),
  useNavigate: () => vi.fn(),
}));
vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ isPending: false, isError: false, data: { featured: [] } }),
}));
// The shared double keeps a stable `t` identity: a per-render `t` makes any
// component with `t` in an effect dependency loop forever. See src/test/mocks.ts.
vi.mock("react-i18next", async () => (await import("../../../test/mocks")).mockTranslation);
vi.mock("@/lib/site-content", () => ({
  useSiteContent: () => ({ get: (_key: string, fallback: string) => fallback }),
}));
vi.mock("@/lib/animation-context", () => ({
  useAnimation: () => ({ reduced: true }),
}));
vi.mock("../../fluids/fluid-gradient", () => ({
  FluidGradient: ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));
vi.mock("../../../page-builder/renderer", () => ({ RenderNode: () => null }));
vi.mock("../../news-carousel", () => ({ NEWS_FEATURED_KEY: ["news"] }));
vi.mock("../../news-card", () => ({ pickNewsTitle: () => "News" }));
vi.mock("@soymutdb/api-client", () => ({ getFeaturedNews: vi.fn() }));
vi.mock("@ant-design/icons", () => new Proxy({}, { get: () => () => null }));
vi.mock("@/lib/format", () => ({ formatDate: () => "" }));
vi.mock("@/lib/antd", () => {
  const passthrough = ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  );
  const Input = () => <input />;
  return {
    Alert: passthrough,
    Button: passthrough,
    Card: passthrough,
    Carousel: passthrough,
    Col: passthrough,
    Empty: passthrough,
    Input,
    List: passthrough,
    Row: passthrough,
    Typography: { Title: passthrough, Paragraph: passthrough, Text: passthrough },
  };
});

import { AntdHome } from "../antd-home";

afterEach(cleanup);

describe("home database entrypoints", () => {
  it("renders public search and entity catalog links", () => {
    render(<AntdHome />);
    const section = screen.getByTestId("database-entrypoints");
    expect(within(section).getByText("生物信息学数据库")).toBeTruthy();
    expect(
      within(section).getByRole("link", { name: /查询数据库/ }).getAttribute("href"),
    ).toBe("/search");
    expect(
      within(section).getByRole("link", { name: /突变体/ }).getAttribute("href"),
    ).toBe("/mutants");
    expect(
      within(section).getByRole("link", { name: /基因/ }).getAttribute("href"),
    ).toBe("/genes");
    expect(
      within(section).getByRole("link", { name: /变异/ }).getAttribute("href"),
    ).toBe("/variants");
  });
});
