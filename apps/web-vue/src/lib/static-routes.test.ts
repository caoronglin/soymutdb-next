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

    expect(paths).toEqual(["/", "/downloads", "/mutants", "/search", "/variants"]);
    // Dynamic detail routes render from parameters; they never get a document.
    expect(paths).not.toContain("/genes/:geneId");
    expect(paths).not.toContain("/mutants/:publicId");
  });

  it("never lists the internal variant in the sitemap", () => {
    const external = deriveStaticRouteEntries(PORTAL_ROUTES, "external");
    const internal = deriveStaticRouteEntries(PORTAL_ROUTES, "internal");

    expect(external.every((entry) => entry.includeInSitemap)).toBe(true);
    expect(internal.some((entry) => entry.includeInSitemap)).toBe(false);
    // The document set itself is identical; only the indexing policy changes.
    expect(internal.map((entry) => entry.path)).toEqual(
      external.map((entry) => entry.path),
    );
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
