/* global process, Buffer, URL, console */

/**
 * Minimal static server for LOCAL public-artifact Playwright tests.
 *
 * Serves `apps/web/dist` mounted at `/soymutdb-next` (mirrors the gh-pages
 * sub-path the build bakes into dynamic-import chunk paths), with:
 *   - SPA fallback to index.html for unknown extensionless paths
 *     (mirrors GitHub Pages 404.html behaviour);
 *   - a real 404 for /assets/* and API-shaped paths (like GitHub Pages
 *     when the API_BASE_URL secret is unset);
 *   - a mocked `POST /api/v1/auth/login` endpoint for deterministic
 *     authentication; it accepts only documented test credentials and returns
 *     a deliberately non-user-facing message for invalid attempts;
 *   - a mocked `POST /api/v1/tools/seqfetch` returning a fixed FASTA
 *     sequence, so the "from genome" primer mode is testable offline
 *     without a backend. The FASTA contains a GC-balanced 300 bp block
 *     that yields valid primer pairs;
 *   - an OPT-IN gene fixture: only with `GENES_JBROWSE_FIXTURE=1` and only for
 *     the fixture query does gene search return one row, so the JBrowse 2
 *     deep-link assertion in tests/genes.spec.ts can run offline. The default
 *     remains an empty result (never fabricated rows).
 *
 * Usage:  node static-server.mjs [root] [port] [prefix]
 *   root  : dist directory (default ../apps/web/dist)
 *   port  : listen port (default 4173)
 *   prefix: mount prefix (default /soymutdb-next)
 */

import { createServer } from "node:http";
import { createReadStream, existsSync, statSync } from "node:fs";
import { extname, join, normalize } from "node:path";

const ROOT = process.argv[2] ?? join(import.meta.dirname, "..", "apps", "web", "dist");
const PORT = Number(process.argv[3] ?? 4173);
// Mount prefix, normalised to either "" (origin root) or "/segment" with no
// trailing slash. Keeping "" for the root mount matters: every mock below is
// built as `${PREFIX}/api/v1/...`, and a raw "/" would produce "//api/v1/...",
// which silently 404s every mocked endpoint.
const PREFIX_RAW = process.argv[4] ?? "/soymutdb-next";
const PREFIX = PREFIX_RAW === "/" ? "" : PREFIX_RAW.replace(/\/+$/, "");

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
  ".xml": "application/xml",
  ".gz": "application/gzip",
  ".webmanifest": "application/manifest+json",
  ".ico": "image/x-icon",
};

/** GC-balanced 300 bp mock template (15 × ACGTACGTACGTACGTACGT). */
const MOCK_SEQ =
  "ACGTACGTACGTACGTACGT".repeat(15);

/**
 * Opt-in deterministic gene fixture for the JBrowse deep-link E2E.
 *
 * With GENES_JBROWSE_FIXTURE=1, a search for GENE_JBROWSE_FIXTURE_QUERY returns
 * exactly this one row. Every other query (and every run without the env flag)
 * keeps the long-standing empty envelope, so the empty-state assertions still
 * see no rows and the server never invents data by default.
 */
const GENE_JBROWSE_FIXTURE_QUERY = "SMDB-E2E-GENE-1";
const GENE_JBROWSE_FIXTURE_ROW = Object.freeze({
  id: "e2e-fixture-gene-1",
  gene_id: GENE_JBROWSE_FIXTURE_QUERY,
  symbol: "E2E1",
  name: "E2E fixture gene",
  biotype: "protein_coding",
  assembly_id: "1",
  assembly_name: "Wm82.a4.v1",
  chromosome: "chr01",
  position: 12345,
  start_pos: 12300,
  end_pos: 12400,
  strand: "+",
  description: null,
  variant_count: 1,
});

const LOGIN_TEST_CREDENTIALS = Object.freeze({
  email: "researcher@example.org",
  password: "correct-horse-battery-staple",
});

// Kept for reference: the historical 404 rule also matched bare route names
// (`/genes/...`), which shadows the SPA's own detail routes. The fallback now
// keys on the `/api/` sub-path instead — see the fallback block below.
const API_PATH_RE =
  /^\/(api|auth|stats|genes|variants|news|site|blast|tools|analyses|gwas|notifications|seed-requests|content|expression|homolog|releases|sra|downloads|mutants|health|admin|widget)\//;

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf-8");
}

function gzipSibling(req, file) {
  const accepted = String(req.headers["accept-encoding"] ?? "").toLowerCase();
  if (!accepted.includes("gzip")) return null;
  const candidate = `${file}.gz`;
  return existsSync(candidate) ? candidate : null;
}

/**
 * Serve one file, preferring the build's `.gz` sibling when the client
 * negotiated gzip.
 *
 * The artifact carries a `.gz` next to every compressible file
 * (`apps/web/scripts/gzip-compress.ts`), exactly as the nginx `gzip_static`
 * deployment consumes them. Answering `Accept-Encoding: gzip` with the sibling
 * is what makes these suites measure the delivery a real host gives; leaving it
 * out served the uncompressed bytes to every request and hid a missing
 * `Content-Encoding` from every gate.
 */
function sendFile(req, res, file) {
  const gz = gzipSibling(req, file);
  if (gz) {
    res.writeHead(200, {
      "Content-Type": MIME[extname(file)] ?? "application/octet-stream",
      "Content-Encoding": "gzip",
      Vary: "Accept-Encoding",
    });
    createReadStream(gz).pipe(res);
    return;
  }
  // Resource Timing needs a body length to report static asset sizes. This is
  // also what a production static host normally sends for immutable artifacts.
  // (A pre-compressed body is streamed without a length: the `Content-Length`
  // of the `.gz` is not the length of the representation.)
  res.writeHead(200, {
    "Content-Type": MIME[extname(file)] ?? "application/octet-stream",
    "Content-Length": statSync(file).size,
    Vary: "Accept-Encoding",
  });
  createReadStream(file).pipe(res);
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);
  let pathname = decodeURIComponent(url.pathname);

  // `@soymutdb/api-client` falls back to a RELATIVE `/api/v1` base when the
  // injected `VITE_API_BASE_URL` is not visible to the workspace package. A
  // relative base resolves against the origin root, so those requests arrive as
  // `/api/v1/...` while every mock route below is keyed on the mount prefix.
  // Normalise before matching, otherwise the whole portal 404s offline and the
  // suites report "assemblies could not be loaded" instead of exercising a page.
  if (PREFIX !== "" && pathname.startsWith("/api/v1")) {
    pathname = `${PREFIX}${pathname}`;
  }

  // Mock login: POST /<prefix>/api/v1/auth/login. This exercises the emitted
  // browser request rather than a route-level stub. Keep the test principal
  // local to this static server; it is not a real account or a test fixture
  // for API integration.
  if (req.method === "POST" && pathname === `${PREFIX}/api/v1/auth/login`) {
    let body = null;
    try {
      body = JSON.parse(await readBody(req));
    } catch {
      /* invalid JSON is an invalid credential attempt for this test server */
    }

    // The public portal posts `{email, password}`; the admin console posts
    // `{username, password}`. Both are one test principal here.
    const identifier = body?.email ?? body?.username;
    const valid =
      identifier === LOGIN_TEST_CREDENTIALS.email &&
      body?.password === LOGIN_TEST_CREDENTIALS.password;

    if (valid) {
      res.writeHead(200, {
        "Content-Type": "application/json",
        // Mirrors the shape of the production session handoff without
        // persisting a real secret in the repository.
        "Set-Cookie": "soymutdb_e2e_refresh=mock; Path=/; HttpOnly; SameSite=Lax",
      });
      res.end(JSON.stringify({ access_token: "e2e-access-token", expires_in: 900 }));
      return;
    }

    res.writeHead(401, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        error: {
          code: "INVALID_CREDENTIALS",
          message: "Mock authentication detail must not be rendered to users.",
        },
      }),
    );
    return;
  }

  // Mock seqfetch: POST /<prefix>/api/v1/tools/seqfetch → fixed FASTA.
  if (
    req.method === "POST" &&
    pathname.startsWith(`${PREFIX}/api/v1/tools/seqfetch`)
  ) {
    let body = {};
    try {
      body = JSON.parse(await readBody(req));
    } catch {
      /* empty */
    }
    const { assembly, region } = body;
    const seq = MOCK_SEQ;
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        format: "fasta",
        sequence: `>${assembly ?? "mock"} ${region ?? "chr01:1-300"}\n${seq}`,
        count: 1,
        truncated: false,
        missing: [],
      }),
    );
    return;
  }

  // Mock genomes metadata: GET /<prefix>/api/v1/genes/assemblies → one
  // default assembly, and /genes/assemblies/{id}/chromosomes → chr01..chr03.
  // Enables the Gene ID / Physical Location search forms to be exercised
  // offline (the submit path requires a selected assembly).
  if (
    req.method === "GET" &&
    pathname.startsWith(`${PREFIX}/api/v1/genes/assemblies`)
  ) {
    const rest = pathname.slice(`${PREFIX}/api/v1/genes/assemblies`.length);
    if (rest === "" || rest === "/") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify([
          {
            id: "1",
            name: "Wm82.a4.v1",
            species: "Glycine max",
            version: "a4.v1",
            is_default: true,
          },
          {
            // Independent unpublished source-preview namespace, opt-in by
            // explicit user selection; the default released assembly stays v4.
            id: "6",
            name: "Gmax_880_v6.0",
            species: "Glycine max",
            version: "v6.0",
            is_default: false,
          },
        ]),
      );
    } else {
      // /genes/assemblies/{id}/chromosomes
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify([
          { id: "1", assembly_id: "1", name: "chr01", length: 100000, order: 0 },
          { id: "2", assembly_id: "1", name: "chr02", length: 100000, order: 1 },
          { id: "3", assembly_id: "1", name: "chr03", length: 100000, order: 2 },
        ]),
      );
    }
    return;
  }

  // Mock table-view templates: the portal asks the API which columns to render
  // (see docs/dev/configurable-table-views.md). Offline it must still get an
  // ordered, non-empty column set — the built-in default — or a table would
  // render with no headers at all.
  if (
    req.method === "GET" &&
    new RegExp(`^${PREFIX}/api/v1/table-views/[a-z_]+$`).test(pathname)
  ) {
    const builtin = {
      mutation_sites: [
        ["mutant_line_name", "Mutant line"],
        ["mutation_system", "Mutation system"],
        ["chromosome", "Chromosome"],
        ["position", "Position"],
        ["confidence", "Confidence"],
        ["gene_id", "Gene ID"],
        ["feature", "Feature"],
        ["available", "Available"],
      ],
      variants: [
        ["variant_id", "Variant ID"],
        ["chromosome", "Chromosome"],
        ["position", "Position"],
        ["ref", "Ref"],
        ["alt", "Alt"],
        ["variant_type", "Type"],
        ["impact", "Impact"],
        ["gene_id", "Gene ID"],
      ],
      // Mirrors BUILTIN_DEFAULT_COLUMNS in
      // apps/api/app/services/table_views_service.py — the approved
      // search-result order. `apps/api/tests/test_table_views.py` asserts the
      // server-side list; keep this copy in step with it.
      genes: [
        ["assembly_name", "Genome version"],
        ["chromosome", "Chromosome"],
        ["position", "Position"],
        ["variant_count", "Mutation feature"],
        ["gene_id", "Gene ID"],
      ],
      mutant_lines: [
        ["public_id", "Mutant line"],
        ["name", "Name"],
        ["mutagen", "Mutagen"],
        ["cultivar", "Cultivar"],
        ["generation", "Generation"],
      ],
    };
    const kind = pathname.split("/").pop();
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        kind,
        species: "Glycine max",
        site_variant: "external",
        release_id: null,
        template_id: null,
        template_name: "builtin-default",
        is_builtin_default: true,
        columns: (builtin[kind] ?? builtin.variants).map(([key, label_en]) => ({
          key,
          label_zh: label_en,
          label_en,
          visible: true,
        })),
        // genome_preview is opt-in per kind (mutation sites enable it by
        // default; a gene result row already links to the gene detail).
        actions:
          kind === "mutation_sites"
            ? { jbrowse: true, genome_preview: true }
            : { jbrowse: true, genome_preview: false },
      }),
    );
    return;
  }

  // Mock featured news with the documented envelope: the homepage renders its
  // empty state from a valid empty response. A malformed envelope is rejected
  // by the client as an error (never silently empty, never a render crash).
  if (req.method === "GET" && pathname === `${PREFIX}/api/v1/news/featured`) {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ featured: [], carousel: [] }));
    return;
  }

  // Mock news: an empty list is the honest offline answer (no fake headlines).
  if (req.method === "GET" && pathname.startsWith(`${PREFIX}/api/v1/news`)) {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ items: [], total: 0 }));
    return;
  }

  // A valid empty unpublished source response is different from a failed API.
  // E2E fixture only: it never publishes test data.
  if (req.method === "GET" && pathname === `${PREFIX}/api/v1/preview/test-data/mutation-sites/by-gene`) {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify([]));
    return;
  }

  // Mock gene search: by default return an empty result envelope so the result
  // table renders its column headers without inventing rows. With
  // GENES_JBROWSE_FIXTURE=1 (and only for the fixture query) it returns one
  // deterministic row so the JBrowse deep-link assertion can run offline.
  // A gene DETAIL path (`/genes/<gene_id>`) is a different contract from the
  // search list. This server only has an optional one-row SEARCH fixture, so
  // answering a detail request with the list envelope would hand the page a
  // malformed record (the list envelope has no `start_pos`/`end_pos`, and a
  // detail consumer that trusts its types then crashes). Answer honestly with
  // 404 so the page renders its empty state; the focused gene tests install
  // their own mocks.
  if (
    req.method === "GET" &&
    pathname.startsWith(`${PREFIX}/api/v1/genes/`) &&
    !pathname.startsWith(`${PREFIX}/api/v1/genes/assemblies`)
  ) {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({ error: { code: "NOT_FOUND", message: "gene detail is not mocked offline" } }),
    );
    return;
  }

  if (
    req.method === "GET" &&
    pathname.startsWith(`${PREFIX}/api/v1/genes`) &&
    !pathname.startsWith(`${PREFIX}/api/v1/genes/assemblies`)
  ) {
    const search = url.searchParams.get("search") ?? "";
    const items =
      process.env.GENES_JBROWSE_FIXTURE === "1" && search === GENE_JBROWSE_FIXTURE_QUERY
        ? [GENE_JBROWSE_FIXTURE_ROW]
        : [];
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        items,
        next_cursor: null,
        has_more: false,
        page: 1,
        page_size: 20,
        total: items.length,
        total_pages: items.length ? 1 : 0,
      }),
    );
    return;
  }

  // Mock region variant search: empty list (no fake rows).
  if (
    req.method === "GET" &&
    pathname.startsWith(`${PREFIX}/api/v1/variants/region`)
  ) {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify([]));
    return;
  }

  if (pathname === `${PREFIX}/` || pathname === PREFIX) {
    sendFile(req, res, join(ROOT, "index.html"));
    return;
  }

  // A Vite artifact may be built for a sub-path (e.g. /soymutdb-next/) while
  // this local server is mounted at / for visual QA. Accept both the mount
  // prefix and the artifact's baked deployment prefix for static assets.
  if (PREFIX === "" && pathname.startsWith("/soymutdb-next/")) {
    pathname = pathname.slice("/soymutdb-next".length);
  } else if (PREFIX !== "" && pathname.startsWith(`${PREFIX}/`)) {
    pathname = pathname.slice(PREFIX.length);
  } else if (PREFIX !== "") {
    // A root-based artifact mounted under a sub-path: the emitted HTML/JS
    // reference root-absolute assets (`/assets/...`, `/fonts/...`), while only
    // documents are meant to live under the mount prefix. Serve a real file at
    // ROOT instead of 404ing the SPA's own assets; unknown routes still 404.
    const rootBaked = join(ROOT, normalize(pathname).replace(/^\/+/, ""));
    if (!existsSync(rootBaked) || statSync(rootBaked).isDirectory()) {
      res.writeHead(404, { "Content-Type": "text/plain" });
      res.end("not found");
      return;
    }
  }

  if (pathname === "/") {
    sendFile(req, res, join(ROOT, "index.html"));
    return;
  }

  if (!extname(pathname)) {
    const withHtml = join(ROOT, normalize(pathname).replace(/^\/+/, "") + ".html");
    if (existsSync(withHtml)) pathname += ".html";
  }

  // A prerendered route is a *directory* document: GitHub Pages, Cloudflare
  // Pages and nginx all answer `/path` with `/path/index.html`. GitHub Pages and
  // nginx do this by asking the filesystem, not by inspecting the extension —
  // which matters here, because a gene accession such as
  // `/genes/Glyma.01G000100` looks like it has the extension `.01G000100`.
  // Probing the directory after the direct file keeps real assets winning.
  let file = join(ROOT, normalize(pathname).replace(/^\/+/, ""));
  if (!existsSync(file) || statSync(file).isDirectory()) {
    const directoryIndex = join(file, "index.html");
    if (existsSync(directoryIndex)) {
      sendFile(req, res, directoryIndex);
      return;
    }
    // SPA fallback: index.html for unknown extensionless routes; real 404 for
    // assets and API paths (mirrors GitHub Pages behaviour).
    //
    // Only `/api/*` counts as an API path here: the artifact's API base is the
    // `/api/v1` sub-path, so a bare detail route such as `/genes/<accession>`
    // or `/mutants/<public_id>` must fall back to the SPA document instead of
    // being mistaken for a missing API endpoint.
    if (pathname.startsWith("/assets/") || pathname.startsWith("/api/")) {
      res.writeHead(404, { "Content-Type": "text/plain" });
      res.end("not found");
      return;
    }
    file = join(ROOT, "index.html");
  }

  sendFile(req, res, file);
});

server.listen(PORT, () => {
  console.log(`[static-server] ${ROOT} → http://localhost:${PORT}${PREFIX || ""}/`);
});
