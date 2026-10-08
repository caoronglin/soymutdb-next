import { describe, expect, it } from "vitest";

import { PORTAL_ROUTES } from "../router/routes";
import {
  deriveStaticRouteEntries,
  directoryIndexPath,
  escapeHtml,
  injectPageHead,
  renderRobots,
  renderSitemap,
} from "./static-routes";

describe("deriveStaticRouteEntries", () => {
  it("prerenders the stable routes and skips dynamic ones", () => {
    const entries = deriveStaticRouteEntries(PORTAL_ROUTES, "external");
    const paths = entries.map((entry) => entry.path);

    expect(paths).toEqual([
      "/",
      "/about",
      "/analyses",
      "/analytics",
      "/blast",
      "/browser",
      "/compare",
      "/downloads",
      "/genes",
      "/guide",
      "/help",
      "/login",
      "/mutants",
      "/news",
      "/publications",
      "/search",
      "/search/gbrowse",
      "/search/genes",
      "/search/location",
      "/search/primer",
      "/search/tools",
      "/seed-request",
      "/sra",
      "/tools",
      "/tools/enrichment",
      "/tools/exppattern",
      "/tools/seqfetch",
      "/variants",
    ]);
    // Dynamic detail routes render from parameters; they never get a document.
    expect(paths).not.toContain("/genes/:geneId");
    expect(paths).not.toContain("/mutants/:publicId");
    expect(paths).not.toContain("/news/:slug");
  });

  it("never lists the internal variant in the sitemap", () => {
    const external = deriveStaticRouteEntries(PORTAL_ROUTES, "external");
    const internal = deriveStaticRouteEntries(PORTAL_ROUTES, "internal");

    // The document set itself is identical; only the indexing policy changes.
    expect(internal.map((entry) => entry.path)).toEqual(
      external.map((entry) => entry.path),
    );
    // Internal is never indexable, whatever the route metadata says.
    expect(internal.some((entry) => entry.includeInSitemap)).toBe(false);
    // External indexes the public content pages, but never the private-entry
    // routes (login, seed request, SRA, tool-with-form pages).
    const externalIndexed = external.filter((entry) => entry.includeInSitemap);
    expect(externalIndexed.map((entry) => entry.path)).toContain("/");
    expect(externalIndexed.map((entry) => entry.path)).not.toContain("/login");
    expect(externalIndexed.map((entry) => entry.path)).not.toContain("/seed-request");
  });

  it("skips a dynamic path even if metadata says prerender", () => {
    const entries = deriveStaticRouteEntries(
      [{ path: "/genes/:id", meta: { prerender: true, title: "Gene" } }],
      "external",
    );
    expect(entries).toEqual([]);
  });
});

describe("directoryIndexPath", () => {
  it("maps routes to their static document path", () => {
    expect(directoryIndexPath("/")).toBe("index.html");
    expect(directoryIndexPath("/search")).toBe("search/index.html");
    expect(directoryIndexPath("/search/")).toBe("search/index.html");
  });
});

describe("injectPageHead", () => {
  it("replaces the title and appends description + canonical", () => {
    const html = "<html><head><title>SoyMutDB</title></head><body></body></html>";
    const output = injectPageHead(
      html,
      {
        path: "/search",
        title: "Search — SoyMutDB",
        description: 'Search <genes> & "variants"',
        includeInSitemap: true,
      },
      "https://soymutdb.org",
    );

    expect(output).toContain("<title>Search — SoyMutDB</title>");
    expect(output).toContain(
      '<meta name="description" content="Search &lt;genes&gt; &amp; &quot;variants&quot;" />',
    );
    expect(output).toContain('<link rel="canonical" href="https://soymutdb.org/search" />');
    expect(output).not.toContain("<title>SoyMutDB</title>");
  });

  it("leaves the document without an origin free of canonical tags", () => {
    const html = "<html><head><title>old</title></head></html>";
    const output = injectPageHead(html, {
      path: "/",
      title: "Home",
      includeInSitemap: false,
    });
    expect(output).toContain("<title>Home</title>");
    expect(output).not.toContain("canonical");
  });
});

describe("renderSitemap", () => {
  it("lists only sitemap entries with absolute URLs", () => {
    const sitemap = renderSitemap(
      [
        { path: "/", title: "Home", includeInSitemap: true },
        { path: "/genes/:id", title: "Gene", includeInSitemap: false },
      ],
      "https://soymutdb.org",
    );
    expect(sitemap).toContain("<loc>https://soymutdb.org/</loc>");
    expect(sitemap).not.toContain("/genes/");
    expect(sitemap).toContain('xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"');
  });
});

describe("renderRobots", () => {
  it("disallows everything on the internal variant", () => {
    expect(renderRobots("internal", "https://internal.example.org")).toBe(
      "User-agent: *\nDisallow: /\n",
    );
  });

  it("marks every internal static document as noindex", () => {
    const html = injectPageHead(
      "<html><head><title>Old</title></head><body></body></html>",
      { path: "/tools", title: "Tools", includeInSitemap: false },
      "https://internal.example.org",
      "internal",
    );
    expect(html).toContain('<meta name="robots" content="noindex, nofollow, noarchive" />');
  });

  it("allows crawling and points at the sitemap for the external variant", () => {
    const robots = renderRobots("external", "https://soymutdb.org");
    expect(robots).toContain("Allow: /");
    expect(robots).toContain("Sitemap: https://soymutdb.org/sitemap.xml");
  });
});

describe("escapeHtml", () => {
  it("escapes the five document characters", () => {
    expect(escapeHtml(`<a href="x">&'`)).toBe("&lt;a href=&quot;x&quot;&gt;&amp;&#39;");
  });
});
