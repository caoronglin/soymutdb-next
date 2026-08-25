// @vitest-environment jsdom
import * as React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { PageDefinitionV2 } from "@soymutdb/shared";

const state = vi.hoisted(() => ({ definition: null as PageDefinitionV2 | null }));

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: unknown) => options,
  Link: ({ to, children, ...rest }: { to: string; children?: React.ReactNode } & Record<string, unknown>) =>
    <a href={to} {...rest}>{children}</a>,
  useNavigate: () => vi.fn(),
}));

vi.mock("../../page-builder/loader", () => ({
  usePageDefinition: () => ({ definition: state.definition }),
}));

vi.mock("../../components/home/antd-home", () => ({
  AntdHome: ({ resourceCards }: { resourceCards?: { props?: Record<string, unknown> } }) => (
    <div data-testid="actual-home">
      {resourceCards ? (
        <div data-testid="published-resource-cards">
          {String(resourceCards.props?.heading ?? "")}
          {(resourceCards.props?.cards as Array<{ title: string; image_url?: string; href?: string }> ?? []).map((card) => (
            <article key={card.title}>
              <span>{card.title}</span>
              {card.image_url ? <img src={card.image_url} alt="" /> : null}
              {card.href ? <a href={card.href}>open</a> : null}
            </article>
          ))}
        </div>
      ) : <div data-testid="resource-cards-fallback">legacy fallback</div>}
    </div>
  ),
}));

import { Route } from "../index";
const HomeComponent = (Route as unknown as { component: React.ComponentType }).component;

function definitionWith(root: PageDefinitionV2["root"]): PageDefinitionV2 {
  return {
    schema_version: 2,
    root,
    data_sources: [],
    theme_id: "scientific-light",
    layouts: { desktop: {}, tablet: {}, mobile: {} },
  };
}

afterEach(cleanup);

describe("home published PageDefinition binding", () => {
  it("passes a custom published resource_cards node, including text/image/href and configured order, into actual home", () => {
    state.definition = definitionWith({
      type: "columns", props: { columns: 1 }, children: [{
        type: "columns", props: { columns: 1 }, children: [{
          type: "resource_cards",
          props: {
            heading: "Published resource directory",
            cards: [
              { title: "Third becomes first", description: "custom", image_url: "https://cdn.example.test/first.png", href: "/guide" },
              { title: "Second card", image_url: "https://cdn.example.test/second.png", href: "https://docs.example.test/resource" },
            ],
          },
        }],
      }],
    });

    render(<HomeComponent />);

    expect(screen.getByTestId("actual-home")).toBeTruthy();
    expect(screen.getByTestId("published-resource-cards").textContent).toContain("Published resource directory");
    expect(Array.from(screen.getAllByRole("article")).map((node) => node.textContent)).toEqual([
      "Third becomes firstopen", "Second cardopen",
    ]);
    expect(Array.from(screen.getByTestId("published-resource-cards").querySelectorAll("img")).map((image) => image.getAttribute("src"))).toEqual([
      "https://cdn.example.test/first.png", "https://cdn.example.test/second.png",
    ]);
    expect(screen.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
      "/guide", "https://docs.example.test/resource",
    ]);
  });

  it("uses the old-definition fallback when no resource_cards component is published", () => {
    state.definition = definitionWith({ type: "columns", props: { columns: 1 }, children: [{ type: "rich_text", props: { content: "old" } }] });
    render(<HomeComponent />);
    expect(screen.getByTestId("resource-cards-fallback").textContent).toContain("legacy fallback");
    expect(screen.queryByTestId("published-resource-cards")).toBeNull();
  });
});
