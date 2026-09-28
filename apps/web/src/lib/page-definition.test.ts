// @vitest-environment node
import { describe, expect, it } from "vitest";

import type { PageComponentNode } from "@soymutdb/shared";

import { findResourceCards, isSafePageHref } from "./page-definition";

/**
 * The page builder is operator-editable, so every value reaching the DOM is
 * untrusted. These cases pin the two guards the React renderer had — a
 * depth-first search for the one node type the home page consumes, and an href
 * allowlist — because a regression here is a script-injection or an open
 * redirect, not a cosmetic bug.
 */
describe("findResourceCards", () => {
  it("finds the node nested anywhere in the tree", () => {
    const root: PageComponentNode = {
      type: "columns",
      props: {},
      children: [
        { type: "rich_text", props: { content: "<p>x</p>" } },
        {
          type: "columns",
          props: {},
          children: [
            {
              type: "resource_cards",
              props: { heading: "CMS 资源", cards: [{ title: "下载", href: "/downloads" }] },
            },
          ],
        },
      ],
    };

    expect(findResourceCards(root)).toEqual({
      heading: "CMS 资源",
      cards: [{ title: "下载", href: "/downloads" }],
    });
  });

  it("returns null when the tree has no resource_cards node", () => {
    expect(findResourceCards({ type: "rich_text", props: {} })).toBeNull();
    expect(findResourceCards(undefined)).toBeNull();
  });

  it("normalises a malformed node instead of trusting its props", () => {
    const node = {
      type: "resource_cards",
      props: { heading: 42, cards: "not-an-array" },
    } as unknown as PageComponentNode;

    expect(findResourceCards(node)).toEqual({ heading: "", cards: [] });
  });
});

describe("isSafePageHref", () => {
  it("keeps internal routes and absolute http(s)/mailto/tel targets", () => {
    expect(isSafePageHref("/downloads")).toBe(true);
    expect(isSafePageHref("https://example.org/x")).toBe(true);
    expect(isSafePageHref("mailto:ops@example.org")).toBe(true);
    expect(isSafePageHref("tel:+8610000000")).toBe(true);
  });

  it("rejects script-like, protocol-relative, scheme-less-host and backslash values", () => {
    expect(isSafePageHref("javascript:alert(1)")).toBe(false);
    expect(isSafePageHref("java\nscript:alert(1)")).toBe(false);
    expect(isSafePageHref("data:text/html,<script>alert(1)</script>")).toBe(false);
    expect(isSafePageHref("//evil.example.org")).toBe(false);
    expect(isSafePageHref("/safe\\..\\..\\etc")).toBe(false);
    expect(isSafePageHref(undefined)).toBe(false);
  });
});
