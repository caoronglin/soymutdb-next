/**
 * Footer navigation document contract (mirror of
 * `apps/api/app/core/footer_content.py`).
 *
 * The editor must not invent a shape the API rejects: the parser has to reject a
 * document it cannot round-trip, and the serializer has to hand the server the
 * bounded, contiguous-order form the registry canonicalizes.
 */
import { describe, expect, it } from "vitest";

import {
  FOOTER_NAVIGATION_SCHEMA_VERSION,
  MAX_FOOTER_GROUPS,
  MAX_FOOTER_LINKS,
  countFooterLinks,
  isFooterSlug,
  parseFooterNavigationJson,
  reindexFooterNavigation,
  serializeFooterNavigation,
  type FooterNavDocument,
} from "./site-footer";

function document(): FooterNavDocument {
  return {
    schema_version: FOOTER_NAVIGATION_SCHEMA_VERSION,
    groups: [
      {
        id: "explore",
        title_en: "Explore",
        title_zh: "浏览",
        enabled: true,
        order: 0,
        links: [
          { id: "genes", label_en: "Genes", label_zh: "基因", target: "internal", href: "/genes", enabled: true, order: 0 },
          { id: "blast", label_en: "BLAST", label_zh: "BLAST", target: "internal", href: "/blast", enabled: false, order: 1 },
        ],
      },
    ],
  };
}

describe("footer navigation document", () => {
  it("round-trips a document through serialize and parse", () => {
    const parsed = parseFooterNavigationJson(serializeFooterNavigation(document()));
    expect(parsed).toEqual(document());
  });

  it("rejects a stored value it cannot edit, so the editor falls back instead of rendering blanks", () => {
    expect(parseFooterNavigationJson("")).toBeNull();
    expect(parseFooterNavigationJson("not json")).toBeNull();
    expect(parseFooterNavigationJson(JSON.stringify({ schema_version: 2, groups: [] }))).toBeNull();
    expect(parseFooterNavigationJson(JSON.stringify({ schema_version: 1 }))).toBeNull();
  });

  it("defaults a missing enabled flag to true rather than hiding a link", () => {
    const parsed = parseFooterNavigationJson(
      JSON.stringify({
        schema_version: 1,
        groups: [{ id: "explore", title_en: "Explore", title_zh: "浏览", links: [{ id: "genes", label_en: "Genes", label_zh: "基因", href: "/genes" }] }],
      }),
    );
    expect(parsed?.groups[0].enabled).toBe(true);
    expect(parsed?.groups[0].links[0].enabled).toBe(true);
    expect(parsed?.groups[0].links[0].target).toBe("internal");
  });

  it("rewrites order values from array position, which is what the operator sees", () => {
    const moved = reindexFooterNavigation({
      schema_version: 1,
      groups: [
        { ...document().groups[0], order: 7, links: [...document().groups[0].links].reverse() },
      ],
    });
    expect(moved.groups[0].order).toBe(0);
    expect(moved.groups[0].links.map((link) => [link.id, link.order])).toEqual([
      ["blast", 0],
      ["genes", 1],
    ]);
  });

  it("counts links across groups so the editor can show the footer budget", () => {
    expect(countFooterLinks(document())).toBe(2);
    expect(MAX_FOOTER_LINKS).toBe(32);
    expect(MAX_FOOTER_GROUPS).toBe(6);
  });

  it("accepts only the slug form the server accepts for ids", () => {
    expect(isFooterSlug("explore")).toBe(true);
    expect(isFooterSlug("all-tools")).toBe(true);
    expect(isFooterSlug("Explore")).toBe(false);
    expect(isFooterSlug("all_tools")).toBe(false);
    expect(isFooterSlug("-tools")).toBe(false);
  });
});