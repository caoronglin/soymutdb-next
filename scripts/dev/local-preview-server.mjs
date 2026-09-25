/**
 * Local preview server: one origin for the portal, the admin console and the API.
 *
 * One origin is not a convenience: the portal's CSP requires an absolute API
 * origin, and a browser opened from anywhere other than this host cannot reach
 * `127.0.0.1`. Serving all three behind one host keeps that origin reachable
 * (and makes a tunnel to this port a complete demo).
 *
 *   /            -> apps/web/dist   (SPA + prerendered documents)
 *   /admin/*     -> apps/admin/dist
 *   /api/*       -> the FastAPI app on 127.0.0.1:8000
 *   /docs,/openapi.json -> the API
 *
 * One origin matters for a demo: the portal's CSP requires an absolute API
 * origin, and serving both behind one host keeps that origin reachable from
 * wherever the page is opened.
 */
import { createServer, request as httpRequest } from "node:http";
import { createReadStream, existsSync, statSync } from "node:fs";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const WEB = resolve(REPO_ROOT, "apps", "web", "dist");
const ADMIN = resolve(REPO_ROOT, "apps", "admin", "dist");
const API_HOST = process.env.SOYMUTDB_PREVIEW_API_HOST ?? "127.0.0.1";
const API_PORT = Number(process.env.SOYMUTDB_PREVIEW_API_PORT ?? 8000);
const PORT = Number(process.argv[2] ?? process.env.SOYMUTDB_PREVIEW_PORT ?? 8090);

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
    { host: API_HOST, port: API_PORT, path: url.pathname + url.search, method: req.method, headers: { ...req.headers, host: `${API_HOST}:${API_PORT}` } },
    (upstreamRes) => {
      res.writeHead(upstreamRes.statusCode ?? 502, upstreamRes.headers);
      upstreamRes.pipe(res);
    },
  );
  upstream.on("error", () => {
    res.writeHead(502, { "content-type": "application/json" });
    res.end(JSON.stringify({ detail: "the API is not running on 127.0.0.1:8000" }));
  });
  req.pipe(upstream);
}

function serveStatic(res, root, pathname) {
  let filePath = join(root, normalize(pathname));
  if (!filePath.startsWith(root)) {
    res.writeHead(403).end();
    return;
  }
  if (!existsSync(filePath) || statSync(filePath).isDirectory()) {
    const indexCandidate = join(filePath, "index.html");
    if (existsSync(indexCandidate)) filePath = indexCandidate;
    else filePath = join(root, "index.html"); // SPA fallback
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
  if (url.pathname.startsWith("/api/") || url.pathname === "/health" || url.pathname.startsWith("/docs") || url.pathname.startsWith("/openapi")) {
    proxy(req, res, url);
    return;
  }
  if (url.pathname === "/admin" || url.pathname.startsWith("/admin/")) {
    const rest = url.pathname.replace(/^\/admin\/?/, "") || "";
    serveStatic(res, ADMIN, rest === "" ? "/index.html" : `/${rest}`);
    return;
  }
  serveStatic(res, WEB, url.pathname);
}).listen(PORT, "0.0.0.0", () => {
  console.log(`demo server: http://localhost:${PORT}  (portal / admin /admin/ / api /api/v1)`);
});
