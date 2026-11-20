import * as React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

/**
 * The database overview is release-scoped: its query key must carry the pinned
 * release and the site variant, or a release switch would leave the previous
 * release's counts on screen. These cases pin that contract and the number
 * rendering.
 */

const runtime = vi.hoisted(() => ({
  queries: [] as { queryKey: unknown[] }[],
  stats: {
    total_variants: 12_345,
    snp_count: 1,
    indel_count: 2,
    sv_count: 3,
    gene_count: 678,
    mutant_line_count: 90,
    release_count: 1,
    assembly_count: 2,
  },
}));

vi.mock("../portal-search-box", () => ({ PortalSearchBox: () => <div /> }));
vi.mock("../fluids/fluid-gradient", () => ({
  FluidGradient: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("../news-carousel", () => ({ NEWS_FEATURED_KEY: ["news-featured"] }));
vi.mock("../news-card", () => ({ pickNewsTitle: () => "title" }));
vi.mock("@tanstack/react-router", () => ({
  Link: ({
    to,
    children,
    search: _search,
    params: _params,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { to: string; search?: unknown; params?: unknown }) => (
    <a href={to} {...props}>{children}</a>
  ),
  useNavigate: () => vi.fn(),
}));
vi.mock("react-i18next", () => {
  // One shared value: a fresh `t` per render would defeat memoized children.
  const translation = {
    t: (key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? key,
    i18n: { language: "en" },
  };
  return { useTranslation: () => translation };
});
vi.mock("@/lib/site-content-react", () => ({
  useSiteContent: () => ({ get: (_key: string, fallback: string) => fallback }),
}));
vi.mock("@/lib/animation-context", () => ({
  useAnimation: () => ({ reduced: true }),
}));
vi.mock("../../lib/release-scope", () => ({ useReleaseId: () => "42" }));
vi.mock("../../lib/site-variant", () => ({ SITE_VARIANT: "external" }));
vi.mock("dompurify", () => ({ default: { sanitize: (html: string) => html } }));
vi.mock("@soymutdb/api-client", () => ({
  getFeaturedNews: async () => ({ featured: [] }),
  getSiteHome: async () => ({}),
  fetchHomepageStats: async () => runtime.stats,
}));
vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: { queryKey: unknown[] }) => {
    runtime.queries.push(options);
    if (options.queryKey[0] === "homepage-stats") {
      return { data: runtime.stats, isError: false, refetch: vi.fn() };
    }
    return { data: { featured: [] }, isPending: false, isError: false };
  },
}));
vi.mock("@/lib/antd", () => {
  const passthrough = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return {
    Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
      <button {...props}>{children}</button>
    ),
    Card: passthrough,
    Alert: ({ title }: { title?: React.ReactNode }) => <div role="alert">{title}</div>,
    Carousel: passthrough,
    Col: passthrough,
    Empty: passthrough,
    Row: passthrough,
    Skeleton: () => null,
    Typography: {
      Title: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
        <h2 {...props}>{children}</h2>
      ),
      Paragraph: ({ children, ...props }: React.HTMLAttributes<HTMLParagraphElement>) => (
        <p {...props}>{children}</p>
      ),
      Text: ({ children, ...props }: React.HTMLAttributes<HTMLSpanElement>) => (
        <span {...props}>{children}</span>
      ),
    },
  };
});

import { AntdHome } from "./antd-home";

beforeEach(() => {
  runtime.queries = [];
});

it("scopes the database overview to the pinned release and site variant", () => {
  render(<AntdHome />);
  const statsQuery = runtime.queries.find((query) => query.queryKey[0] === "homepage-stats");
  expect(statsQuery?.queryKey).toEqual(["homepage-stats", "42", "external"]);
});

it("renders the release counts with locale grouping", () => {
  render(<AntdHome />);
  expect(screen.getByTestId("home-stat-genes").textContent).toBe("678");
  expect(screen.getByTestId("home-stat-variants").textContent).toBe("12,345");
  expect(screen.getByTestId("home-stat-mutants").textContent).toBe("90");
  expect(screen.getByTestId("home-stat-assemblies").textContent).toBe("2");
});