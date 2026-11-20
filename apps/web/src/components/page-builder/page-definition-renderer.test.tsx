import * as React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PageDefinitionV2 } from "@soymutdb/shared";
import { PageDefinitionRenderer, safeHref } from "./page-definition-renderer";

vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => vi.fn(),
}));

vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);

vi.mock("@soymutdb/api-client", () => ({
  listNews: vi.fn(async () => ({ items: [], total: 0, page: 1, page_size: 6 })),
  ontologyApi: { relationshipGraph: vi.fn() },
}));

vi.mock("../../lib/release-scope", () => ({ useReleaseId: () => "42" }));
vi.mock("../../lib/site-variant", () => ({ SITE_VARIANT: "external" }));
vi.mock("../../lib/query-options", () => ({
  assemblyStatisticsQueryOptions: () => ({}),
}));

vi.mock("@/lib/antd", () => {
  const passthrough = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  const Title = passthrough;
  const Text = passthrough;
  const Paragraph = passthrough;
  return {
    Alert: ({ message }: { message?: React.ReactNode }) => <div>{message}</div>,
    Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
      <button {...props}>{children}</button>
    ),
    Card: Object.assign(passthrough, { Meta: passthrough }),
    Carousel: passthrough,
    Col: passthrough,
    Divider: () => <hr />,
    Empty: passthrough,
    Input: passthrough,
    Row: passthrough,
    Select: passthrough,
    Skeleton: Object.assign(passthrough, { Input: passthrough, active: null }),
    Space: Object.assign(passthrough, { Compact: passthrough }),
    Table: passthrough,
    Tabs: passthrough,
    Typography: { Title, Text, Paragraph },
  };
});

function definition(root: PageDefinitionV2["root"]): PageDefinitionV2 {
  return {
    schema_version: 2,
    root,
    data_sources: [],
    theme_id: "scientific-light",
    layouts: { desktop: {}, tablet: {}, mobile: {} },
  };
}

describe("safeHref", () => {
  it.each([
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
    "",
    "relative/path",
  ])("rejects %s", (value) => {
    expect(safeHref(value)).toBeNull();
  });

  it.each(["/search", "/news/a-slug", "https://example.org", "mailto:a@example.org", "tel:+1"])(
    "accepts %s",
    (value) => {
      expect(safeHref(value)).toBe(value);
    },
  );

  it("ignores non-string values", () => {
    expect(safeHref(undefined)).toBeNull();
    expect(safeHref(42)).toBeNull();
  });
});

describe("PageDefinitionRenderer", () => {
  it("sanitises rich text before insertion", () => {
    const { container } = render(
      <PageDefinitionRenderer
        definition={definition({
          type: "rich_text",
          props: {
            content: '<p>Hello</p><script>alert("x")</script><img src="x" onerror="alert(1)">',
          },
        })}
      />,
    );
    expect(screen.getByText("Hello")).toBeTruthy();
    expect(container.querySelector("script")).toBeNull();
    expect(container.innerHTML).not.toContain("onerror");
  });

  it("drops navigation entries whose route is not a safe URL", () => {
    render(
      <PageDefinitionRenderer
        definition={definition({
          type: "navigation",
          props: {
            title: "Links",
            items: [
              { label: "Safe", route: "/search" },
              { label: "Unsafe", route: "javascript:alert(1)" },
            ],
          },
        })}
      />,
    );
    expect(screen.getByText("Safe").closest("a")?.getAttribute("href")).toBe("/search");
    expect(screen.getByText("Unsafe").closest("a")).toBeNull();
  });

  it("renders nothing for an unknown component type", () => {
    const { container } = render(
      <PageDefinitionRenderer
        definition={definition({
          type: "future_component" as never,
          props: {},
        })}
      />,
    );
    expect(container.textContent).toBe("");
    expect(container.querySelector("a")).toBeNull();
  });

  it("never treats notice content as HTML", () => {
    const { container } = render(
      <PageDefinitionRenderer
        definition={definition({
          type: "notice",
          props: { kind: "info", content: "<b>bold</b>" },
        })}
      />,
    );
    expect(container.querySelector("b")).toBeNull();
    expect(container.textContent).toContain("<b>bold</b>");
  });
});