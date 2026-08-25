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
 *     that yields valid primer pairs.
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
const PREFIX = process.argv[4] ?? "/soymutdb-next";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
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

const LOGIN_TEST_CREDENTIALS = Object.freeze({
  email: "researcher@example.org",
  password: "correct-horse-battery-staple",
});

const API_PATH_RE =
  /^\/(api|auth|stats|genes|variants|news|site|blast|tools|analyses|gwas|notifications|seed-requests|content|expression|homolog|releases|sra|downloads|mutants|health|admin|widget)\//;

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf-8");
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);
  let pathname = decodeURIComponent(url.pathname);

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

    const valid =
      body?.email === LOGIN_TEST_CREDENTIALS.email &&
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

  // Mock gene search: return an empty result envelope so the result table
  // renders its column headers (never fake rows).
  if (
    req.method === "GET" &&
    pathname.startsWith(`${PREFIX}/api/v1/genes`) &&
    !pathname.startsWith(`${PREFIX}/api/v1/genes/assemblies`)
  ) {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        items: [],
        next_cursor: null,
        has_more: false,
        page: 1,
        page_size: 20,
        total: 0,
        total_pages: 0,
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
    res.writeHead(200, { "Content-Type": MIME[".html"] });
    createReadStream(join(ROOT, "index.html")).pipe(res);
    return;
  }

  // A Vite artifact may be built for a sub-path (e.g. /soymutdb-next/) while
  // this local server is mounted at / for visual QA. Accept both the mount
  // prefix and the artifact's baked deployment prefix for static assets.
  if (PREFIX === "/" && pathname.startsWith("/soymutdb-next/")) {
    pathname = pathname.slice("/soymutdb-next".length);
  } else if (PREFIX !== "/" && pathname.startsWith(`${PREFIX}/`)) {
    pathname = pathname.slice(PREFIX.length);
  } else if (PREFIX !== "/") {
    res.writeHead(404, { "Content-Type": "text/plain" });
    res.end("not found");
    return;
  }

  if (pathname === "/") {
    res.writeHead(200, { "Content-Type": MIME[".html"] });
    createReadStream(join(ROOT, "index.html")).pipe(res);
    return;
  }

  if (!extname(pathname)) {
    const withHtml = join(ROOT, normalize(pathname).replace(/^\/+/, "") + ".html");
    if (existsSync(withHtml)) pathname += ".html";
  }

  let file = join(ROOT, normalize(pathname).replace(/^\/+/, ""));
  if (!existsSync(file) || statSync(file).isDirectory()) {
    // SPA fallback: index.html for unknown extensionless routes; real 404
    // for assets and API-shaped paths (mirrors GitHub Pages behaviour).
    if (pathname.startsWith("/assets/") || API_PATH_RE.test(pathname)) {
      res.writeHead(404, { "Content-Type": "text/plain" });
      res.end("not found");
      return;
    }
    file = join(ROOT, "index.html");
  }

  const mime = MIME[extname(file)] ?? "application/octet-stream";
  res.writeHead(200, { "Content-Type": mime });
  createReadStream(file).pipe(res);
});

server.listen(PORT, () => {
  console.log(`[static-server] ${ROOT} → http://localhost:${PORT}${PREFIX}/`);
});
