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
      "/assemblies",
      "/blast",
      "/browser",
      "/comparative",
      "/compare",
      "/downloads",
      "/expression",
      "/genes",
      "/guide",
      "/help",
      "/login",
      "/mutants",
      "/news",
      "/phenotypes",
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
      "/tools/sequence",
      "/variants",
    ]);
    // A POST-form tool renders nothing without JS, so it gets no document of
    // its own: a titled shell with an empty body reads as "this page has no
    // content". The data-rendering tools keep theirs.
    expect(paths).not.toContain("/tools/ld");
    expect(paths).not.toContain("/tools/diversity");
    expect(paths).not.toContain("/tools/allelefreq");
    expect(paths).toContain("/tools/enrichment");
    expect(paths).toContain("/tools/seqfetch");
    expect(paths).toContain("/tools/exppattern");
    expect(paths).toContain("/tools/sequence");
    // Dynamic detail routes render from parameters; they never get a document.
    expect(paths).not.toContain("/genes/:geneId");
    expect(paths).not.toContain("/mutants/:publicId");
    expect(paths).not.toContain("/news/:slug");
    expect(paths).not.toContain("/comparative/:familyId");
    expect(paths).not.toContain("/assemblies/:assemblyId");
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

describe("injectPageHead shell fallback", () => {
  const shelf = '<html><head><title>Old</title></head>' +
    '<body><div id="root"></div><script src="/app.js"></script></body></html>';

  it("gives a prerendered shell a readable body beside its title", () => {
    const html = injectPageHead(shelf, {
      path: "/expression",
      title: "Expression — SoyMutDB",
      description: "Browse released expression libraries.",
      includeInSitemap: false,
    });

    // A crawler must not see a correct title over an empty document.
    expect(html).toContain("<title>Expression — SoyMutDB</title>");
    expect(html).toContain('class="soymutdb-shell-fallback"');
    expect(html).toContain("<h1>Expression — SoyMutDB</h1>");
    expect(html).toContain("<p>Browse released expression libraries.</p>");
    expect(html).toContain("<noscript>");
  });

  it("keeps the mount container empty so react can own it", () => {
    const html = injectPageHead(shelf, {
      path: "/expression",
      title: "Expression — SoyMutDB",
      includeInSitemap: false,
    });

    // The content-snapshot build only recognises an empty #root, and
    // createRoot clears it — anything written inside is markup nobody sees.
    expect(html).toContain('<div id="root"></div>');
    // The fallback is a sibling, and the boot script still comes last.
    expect(html).toContain('</div><div class="soymutdb-shell-fallback">');
    expect(html.indexOf("soymutdb-shell-fallback")).toBeLessThan(html.indexOf("<script"));
  });

  it("skips the fallback when the caller supplies a real body", () => {
    // The content-snapshot build calls this with a document that gets a real
    // <main>, so "enable JavaScript" must not appear in it.
    const html = injectPageHead(
      shelf,
      { path: "/about", title: "About", description: "About body.", includeInSitemap: true },
      undefined,
      "external",
      { shellFallback: false },
    );
    expect(html).toContain("<title>About</title>");
    expect(html).not.toContain("soymutdb-shell-fallback");
  });

  it("leaves a document with no mount container untouched", () => {
    const html = injectPageHead("<html><head><title>Old</title></head><body></body></html>", {
      path: "/about",
      title: "About",
      includeInSitemap: true,
    });
    expect(html).toContain("<title>About</title>");
    expect(html).not.toContain("soymutdb-shell-fallback");
  });

  it("escapes the title and description it writes into the body", () => {
    const html = injectPageHead(shelf, {
      path: "/about",
      title: 'A & "B"',
      description: "<script>x</script>",
      includeInSitemap: false,
    });
    expect(html).toContain("<h1>A &amp; &quot;B&quot;</h1>");
    expect(html).not.toContain("<p><script>");
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

  it("upgrades an existing robots meta instead of duplicating it", () => {
    const html = injectPageHead(
      '<html><head><title>x</title><meta name="robots" content="noindex,nofollow"></head><body></body></html>',
      { path: "/", title: "Home", description: undefined, includeInSitemap: false },
      undefined,
      "internal",
    );
    expect(html.match(/<meta name="robots"/gi)).toHaveLength(1);
    expect(html).toContain('<meta name="robots" content="noindex, nofollow, noarchive" />');
  });
});
