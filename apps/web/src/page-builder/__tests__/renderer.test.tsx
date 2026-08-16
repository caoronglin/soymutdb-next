// @vitest-environment jsdom
import * as React from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

// Minimal i18n instance so useTranslation resolves keys without a full app.
void i18n.use(initReactI18next).init({
  lng: "en",
  fallbackLng: "en",
  resources: {
    en: { translation: { "common.retry": "Retry", "news.noNews": "No news", "news.homeUnavailable": "Unavailable" } },
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

import { COMPONENT_TYPE_KEYS, isScriptLike, type PageComponent } from "../types";
import { hasRendererFor, REGISTERED_COMPONENT_TYPES } from "../registry";
import { HOME_DEFINITION, NAVIGATION_ORDER, HOME_TOOL_ENTRIES } from "../seed";
import { RenderNode } from "../renderer";

describe("page-builder renderer", () => {
  it("registers a renderer for every allowlisted component type", () => {
    for (const key of COMPONENT_TYPE_KEYS) {
      expect(REGISTERED_COMPONENT_TYPES.has(key)).toBe(true);
    }
  });

  it("renders a columns node containing news and carousel children without crashing", () => {
    const columns: PageComponent = {
      type: "columns",
      id: "test-columns",
      props: {
        ratio: "2fr_3fr",
        children: [
          { type: "latest-news", id: "news", props: { max: 5 } },
          { type: "featured-carousel", id: "carousel" },
        ],
      },
    };
    const { container } = renderWithProviders(<RenderNode node={columns} />);
    // The 2:3 grid is applied; children mount (loading/empty states are not
    // fatal and never render fake data).
    expect(container.querySelector(".lg\\:grid-cols-\\[2fr_3fr\\]")).toBeTruthy();
  });

  it("rejects script-like values before reaching the DOM", () => {
    expect(isScriptLike("javascript:alert(1)")).toBe(true);
    expect(isScriptLike("JaVaScRiPt:foo")).toBe(true);
    expect(isScriptLike("/search/genes")).toBe(false);
  });

  it("drops an unknown component type instead of rendering raw data", () => {
    // Cast through unknown to simulate a bad definition from the wire.
    const bad = { type: "raw-script", id: "x" } as unknown as PageComponent;
    expect(hasRendererFor(bad)).toBe(false);
  });

  it("preserves the fixed five-item navigation order", () => {
    expect(NAVIGATION_ORDER.map((n) => n.labelKey)).toEqual([
      "nav.home",
      "nav.search",
      "nav.tools",
      "nav.latestNews",
      "nav.contact",
    ]);
  });

  it("defines the five home tool entries in the approved order", () => {
    expect(HOME_TOOL_ENTRIES.map((e) => (e as { props: { target: string } }).props.target)).toEqual([
      "gene-id",
      "physical-location",
      "jbrowse-2",
      "blast",
      "primer-design",
    ]);
  });

  it("home definition renders a 2:3 split with a max-five news list", () => {
    const top = HOME_DEFINITION.sections[0];
    const columns = top.components[0];
    expect(columns.type).toBe("columns");
    if (columns.type === "columns") {
      expect(columns.props.ratio).toBe("2fr_3fr");
      expect(columns.props.children[0].type).toBe("latest-news");
      if (columns.props.children[0].type === "latest-news") {
        expect(columns.props.children[0].props?.max).toBe(5);
      }
    }
  });

  it("renders a safe link node with noopener attributes", () => {
    const link: PageComponent = {
      type: "link",
      id: "l",
      props: { labelKey: "nav.home", to: "/", newTab: true },
    };
    const { container } = renderWithProviders(<RenderNode node={link} />);
    const anchor = container.querySelector("a");
    expect(anchor).toBeTruthy();
    expect(anchor?.getAttribute("rel")).toMatch(/noopener/);
  });

  it("renders a rich-text node through DOMPurify (scripts and handlers stripped)", () => {
    const rt: PageComponent = {
      type: "rich-text",
      id: "rt",
      props: { html: '<p>Hi</p><script>alert(1)</script><img src="x" onerror="alert(1)">' },
    };
    const { container } = renderWithProviders(<RenderNode node={rt} />);
    // DOMPurify removes the <script> element entirely and strips inline
    // event handlers from any surviving elements.
    expect(container.querySelector("script")).toBeNull();
    const img = container.querySelector("img");
    expect(img?.getAttribute("onerror")).toBeNull();
    expect(screen.getByText("Hi")).toBeTruthy();
  });
});
