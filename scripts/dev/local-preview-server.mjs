/**
 * Local preview server: one frontend app and the API behind one origin.
 *
 * The portal and the console are separate deployments with separate origins —
 * separate artifacts, separate caches, separate CSP. Serving them from one
 * origin (`/` and `/admin/`) would quietly undo that boundary in the only place
 * a developer actually looks at it, so each app gets its own process and port
 * here, and each one proxies `/api/*` to the API on its own origin (which is why
 * neither needs a CORS allowlist for its own API calls).
 *
 * Usage
 *   node scripts/dev/local-preview-server.mjs --app portal --port 8090
 *   node scripts/dev/local-preview-server.mjs --app admin  --port 8091
 *   node scripts/dev/local-preview-server.mjs --app portal --dist apps/web/dist/internal --port 8094
 *
 * Env
 *   SOYMUTDB_PREVIEW_API_HOST  default 127.0.0.1
 *   SOYMUTDB_PREVIEW_API_PORT  default 8010
 */
import { createServer, request as httpRequest } from "node:http";
import { createReadStream, existsSync, statSync } from "node:fs";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const APPS = {
  portal: resolve(REPO_ROOT, "apps", "web", "dist", "external"),
  admin: resolve(REPO_ROOT, "apps", "admin", "dist"),
  jbrowse: resolve(REPO_ROOT, "apps", "jbrowse", "dist"),
};

const args = process.argv.slice(2);
function argValue(flag, fallback) {
  const index = args.indexOf(flag);
  return index >= 0 && args[index + 1] ? args[index + 1] : fallback;
}

const appName = argValue("--app", "portal");
const APP_ROOT = argValue("--dist", APPS[appName]);
if (!APP_ROOT) {
  console.error(`unknown --app ${appName}; expected one of ${Object.keys(APPS).join(", ")}`);
  process.exit(2);
}

// JBrowse is served under the portal/console origin at /jbrowse/, matching the
// deployment shape where the browser frame is same-origin with its shell. The
// built /jbrowse asset URLs are relative, so stripping the prefix is enough.
const JBROWSE_ROOT = APPS.jbrowse;
const JBROWSE_PREFIX = "/jbrowse";

const API_HOST = process.env.SOYMUTDB_PREVIEW_API_HOST ?? "127.0.0.1";
const API_PORT = Number(process.env.SOYMUTDB_PREVIEW_API_PORT ?? 8010);
const PORT = Number(argValue("--port", process.env.SOYMUTDB_PREVIEW_PORT ?? 8090));

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
  ".xml": "application/xml",
  ".gz": "application/gzip",
  ".ico": "image/x-icon",
};

function proxy(req, res, url) {
  const upstream = httpRequest(
    {
      host: API_HOST,
      port: API_PORT,
      path: url.pathname + url.search,
      method: req.method,
      headers: { ...req.headers, host: `${API_HOST}:${API_PORT}` },
    },
    (upstreamRes) => {
      res.writeHead(upstreamRes.statusCode ?? 502, upstreamRes.headers);
      upstreamRes.pipe(res);
    },
  );
  upstream.on("error", () => {
    res.writeHead(502, { "content-type": "application/json" });
    res.end(
      JSON.stringify({
        detail: `the API is not reachable on ${API_HOST}:${API_PORT}`,
      }),
    );
  });
  req.pipe(upstream);
}

function serveStatic(res, pathname, root = APP_ROOT) {
  let filePath = join(root, normalize(pathname));
  if (!filePath.startsWith(root)) {
    res.writeHead(403).end();
    return;
  }
  if (!existsSync(filePath) || statSync(filePath).isDirectory()) {
    const indexCandidate = join(filePath, "index.html");
    filePath = existsSync(indexCandidate) ? indexCandidate : join(root, "index.html");
  }
  if (!existsSync(filePath)) {
    res.writeHead(404, { "content-type": "text/plain" });
    res.end("not found");
    return;
  }
  res.writeHead(200, { "content-type": MIME[extname(filePath)] ?? "application/octet-stream" });
  createReadStream(filePath).pipe(res);
}

createServer((req, res) => {
  const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);
  if (
    url.pathname.startsWith("/api/") ||
    url.pathname === "/health" ||
    url.pathname.startsWith("/docs") ||
    url.pathname.startsWith("/openapi")
  ) {
    proxy(req, res, url);
    return;
  }
  // `_headers` is a host feature (Cloudflare Pages), not something this server
  // implements. The document's own `<meta>` policy is what a browser here
  // obeys, which is why the admin build rewrites it too rather than relying on
  // the header alone.
  if (url.pathname === JBROWSE_PREFIX || url.pathname.startsWith(`${JBROWSE_PREFIX}/`)) {
    const stripped = url.pathname.slice(JBROWSE_PREFIX.length) || "/";
    serveStatic(res, stripped, JBROWSE_ROOT);
    return;
  }
  serveStatic(res, url.pathname);
}).listen(PORT, "0.0.0.0", () => {
  console.log(`[${appName}] http://localhost:${PORT}  (app + /api/v1 proxy)`);
});
