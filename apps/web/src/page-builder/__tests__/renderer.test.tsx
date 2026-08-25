// @vitest-environment jsdom
import * as React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import type { PageComponentNode, PageDefinition } from "@soymutdb/shared";

// Minimal i18n instance so useTranslation resolves keys without a full app.
void i18n.use(initReactI18next).init({
  lng: "en",
  fallbackLng: "en",
  resources: {
    en: {
      translation: {
        "common.retry": "Retry",
        "news.noNews": "No news",
        "news.homeUnavailable": "Unavailable",
        "search.genes.subtitle": "Find genes by gene ID",
        "search.location.subtitle": "Find variants in a region",
        "browser.subtitle": "Explore mutations",
        "blast.subtitle": "Search sequences",
        "search.primer.subtitle": "Design primers",
        "nav.browser": "Genome Browser",
        "nav.blast": "BLAST",
        "nav.search": "Search",
      },
    },
  },
  interpolation: { escapeValue: false },
});

function Wrapper({ children }: { children: React.ReactNode }) {
  const client = React.useMemo(() => new QueryClient(), []);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderWithProviders(ui: React.ReactElement) {
  return render(<Wrapper>{ui}</Wrapper>);
}

import { COMPONENT_TYPE_KEYS, isScriptLike, isPageDefinition } from "../types";

// Mock TanStack Router's Link — the renderer uses it for navigation/tool
// entries, and Link requires a full router context not present in unit tests.
vi.mock("@tanstack/react-router", () => ({
  Link: ({ to, children, ...rest }: { to: string; children?: React.ReactNode } & Record<string, unknown>) =>
    React.createElement("a", { href: to, ...rest }, children),
}));
import { hasRendererFor, REGISTERED_COMPONENT_TYPES } from "../registry";
import { HOME_DEFINITION, NAVIGATION_ORDER, TOOL_ENTRY_LABELS } from "../seed";
import { RenderNode, PageDefinitionRenderer } from "../renderer";

describe("page-builder renderer (shared DTO)", () => {
  it("registers a renderer for every allowlisted component type", () => {
    for (const key of COMPONENT_TYPE_KEYS) {
      expect(REGISTERED_COMPONENT_TYPES.has(key)).toBe(true);
    }
  });

  it("renders a columns node with news_list children without crashing", () => {
    const columns: PageComponentNode = {
      type: "columns",
      props: { columns: 1 },
      children: [{ type: "news_list", props: { limit: 5 } }],
    };
    const { container } = renderWithProviders(<RenderNode node={columns} />);
    expect(container.querySelector(".grid")).toBeTruthy();
  });

  it("rejects script-like values before reaching the DOM", () => {
    expect(isScriptLike("javascript:alert(1)")).toBe(true);
    expect(isScriptLike("JaVaScRiPt:foo")).toBe(true);
    expect(isScriptLike("/search/genes")).toBe(false);
  });

  it("drops an unknown component type instead of rendering raw data", () => {
    const bad = { type: "raw-script", props: {} } as unknown as PageComponentNode;
    expect(hasRendererFor(bad)).toBe(false);
  });

  it("recognises a full page definition shape", () => {
    expect(isPageDefinition(HOME_DEFINITION)).toBe(true);
    expect(isPageDefinition({ root: null })).toBe(false);
  });

  it("preserves the fixed five-item navigation order", () => {
    expect(NAVIGATION_ORDER.map((n) => n.label)).toEqual([
      "Home",
      "Search",
      "Tools",
      "Latest News",
      "Contact",
    ]);
  });

  it("defines the five home tool entries in the approved order", () => {
    expect(TOOL_ENTRY_LABELS).toEqual([
      "Gene ID",
      "Physical Location",
      "JBrowse 2",
      "BLAST",
      "Primer Design",
    ]);
  });

  it("home definition root is columns with navigation + tools + news + carousel + rich text", () => {
    const root = HOME_DEFINITION.root;
    expect(root.type).toBe("columns");
    if (root.type === "columns") {
      expect(root.children?.map((c) => c.type)).toEqual([
        "navigation",
        "tool_entries",
        "news_list",
        "media_carousel",
        "resource_cards",
        "rich_text",
      ]);
    }
  });

  it("renders a link node with noopener for http(s) targets", () => {
    const link: PageComponentNode = {
      type: "link",
      props: { label: "Docs", href: "https://example.com" },
    };
    const { container } = renderWithProviders(<RenderNode node={link} />);
    const anchor = container.querySelector("a");
    expect(anchor).toBeTruthy();
    expect(anchor?.getAttribute("rel")).toMatch(/noopener/);
    expect(anchor?.textContent).toContain("Docs");
  });

  it("renders editable resource cards in configured order with safe image and links", () => {
    const node: PageComponentNode = {
      type: "resource_cards",
      props: {
        heading: "Resource guide",
        cards: [
          { title: "First", description: "First description", image_url: "https://example.com/one.png", href: "/search/genes" },
          { title: "Second", href: "https://example.com/two" },
        ],
      },
    };
    const { container } = renderWithProviders(<RenderNode node={node} />);
    expect(screen.getByTestId("resource-cards")).toBeTruthy();
    expect(screen.getByText("Resource guide")).toBeTruthy();
    expect(Array.from(container.querySelectorAll("h3")).map((element) => element.textContent)).toEqual(["First", "Second"]);
    expect(container.querySelector("img")?.getAttribute("src")).toBe("https://example.com/one.png");
    const external = Array.from(container.querySelectorAll("a")).find((anchor) => anchor.getAttribute("href") === "https://example.com/two");
    expect(external?.getAttribute("rel")).toMatch(/noopener/);
  });

  it("does not render unsafe resource card image URLs", () => {
    const node: PageComponentNode = {
      type: "resource_cards",
      props: { cards: [{ title: "Unsafe", image_url: "javascript:alert(1)" }] },
    };
    const { container } = renderWithProviders(<RenderNode node={node} />);
    expect(container.querySelector("img")).toBeNull();
  });

  it("renders a rich_text node through DOMPurify (scripts and handlers stripped)", () => {
    const rt: PageComponentNode = {
      type: "rich_text",
      props: { content: '<p>Hi</p><script>alert(1)</script><img src="x" onerror="alert(1)">' },
    };
    const { container } = renderWithProviders(<RenderNode node={rt} />);
    expect(container.querySelector("script")).toBeNull();
    const img = container.querySelector("img");
    expect(img?.getAttribute("onerror")).toBeNull();
    expect(screen.getByText("Hi")).toBeTruthy();
  });

  it("renders a full home definition via PageDefinitionRenderer", () => {
    const definition: PageDefinition = HOME_DEFINITION;
    const { container } = renderWithProviders(<PageDefinitionRenderer definition={definition} />);
    // The navigation node and tool entries render links.
    expect(container.querySelectorAll("a").length).toBeGreaterThan(0);
  });
});
