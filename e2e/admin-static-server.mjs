/**
 * Minimal static server for the Admin production-artifact Playwright gate.
 *
 * It serves the already-built `apps/admin/dist` directory at the origin root
 * and provides an SPA fallback for extensionless routes such as `/login`.
 * This deliberately does not start Vite or proxy an API: the smoke test must
 * exercise the emitted production files exactly as a static host would.
 *
 * Usage: node admin-static-server.mjs [root] [port]
 */

import { createServer } from "node:http";
import { createReadStream, existsSync, statSync } from "node:fs";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const defaultRoot = fileURLToPath(new URL("../apps/admin/dist/", import.meta.url));
const root = resolve(process.argv[2] ?? defaultRoot);
const port = Number(process.argv[3] ?? 4174);

if (!existsSync(root) || !statSync(root).isDirectory()) {
  throw new Error(`Admin production artifact not found: ${root}`);
}

const mimeTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json",
  ".map": "application/json",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".txt": "text/plain; charset=utf-8",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};

function resolveArtifactPath(pathname) {
  const candidate = resolve(root, `.${pathname}`);
  return candidate === root || candidate.startsWith(`${root}${sep}`) ? candidate : null;
}

const server = createServer((req, res) => {
  if (req.method !== "GET" && req.method !== "HEAD") {
    res.writeHead(405, { Allow: "GET, HEAD" });
    res.end();
    return;
  }

  let pathname;
  try {
    pathname = decodeURIComponent(new URL(req.url ?? "/", "http://localhost").pathname);
  } catch {
    res.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("Bad request");
    return;
  }

  let file = resolveArtifactPath(pathname);
  if (!file) {
    res.writeHead(403, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("Forbidden");
    return;
  }

  if (pathname === "/" || !extname(pathname)) {
    file = resolve(root, "index.html");
  }

  if (!existsSync(file) || statSync(file).isDirectory()) {
    res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("Not found");
    return;
  }

  res.writeHead(200, {
    "Cache-Control": "no-store",
    "Content-Type": mimeTypes[extname(file)] ?? "application/octet-stream",
  });
  if (req.method === "HEAD") {
    res.end();
    return;
  }
  createReadStream(file).pipe(res);
});

server.listen(port, "127.0.0.1", () => {
  console.log(`[admin-static-server] ${root} -> http://127.0.0.1:${port}`);
});
