import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import tailwindcss from "@tailwindcss/vite";
import { defineConfig, loadEnv, type Plugin } from "vite";
import vue from "@vitejs/plugin-vue";

import { normalizeBasePath, resolveDevAllowedHosts } from "@soymutdb/shared/deployment";

// Admin console. Unlike the public portal this app is never anonymous: it talks
// to the same API with an administrator credential, so it has a single site
// variant and a single origin requirement.
/**
 * Write the real API origin into both CSP carriers.
 *
 * The console has two policies and the browser obeys the *intersection*: the
 * `<meta>` in the document and the `Content-Security-Policy` line in `_headers`.
 * Rewriting only the header left the document on the placeholder policy, and a
 * `default-src 'self'` document blocks the design system's runtime inline styles
 * — which is not a cosmetic failure: the console renders unstyled and reads as
 * broken. Both are rewritten here, from one computed policy.
 */
function adminCsp(apiOrigin: string, documentPath: string): Plugin {
  const origin = new URL(apiOrigin).origin;
  const csp = (policy: string) =>
    policy.replace(/connect-src[^;]*/, `connect-src 'self' ${origin}`);

  return {
    name: "admin-csp-api-origin",
    // Applies in dev too: `vite dev` serves the source index.html, whose
    // placeholder `connect-src 'self'` would block every cross-origin API call
    // and leave the console looking broken. The web portal's equivalent plugin
    // already runs in dev; this keeps the two consistent.
    transformIndexHtml(html) {
      return html.replace(
        /(<meta\s+http-equiv="Content-Security-Policy"\s+content=")([^"]*)(")/s,
        (_match, head: string, policy: string, tail: string) =>
          `${head}${csp(policy)}${tail}`,
      );
    },
    closeBundle() {
      // `_headers` is copied verbatim into `dist/`, so the rewrite happens after
      // the copy rather than on the source file.
      const headers = join(import.meta.dirname, "dist", "_headers");
      writeFileSync(headers, csp(readFileSync(headers, "utf8")));
      void documentPath;
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, import.meta.dirname, "");
  const apiOrigin =
    env.VITE_API_BASE_URL?.trim() ||
    (mode === "development" ? "http://localhost:8010" : "");
  if (!apiOrigin) {
    // Fail closed: an admin bundle with no API origin would load and then fail
    // every request with an opaque network error.
    throw new Error(
      "VITE_API_BASE_URL is required for the admin build (the console has no default API origin)",
    );
  }
  return {
    base: normalizeBasePath(env.VITE_BASE_URL),
    plugins: [vue(), tailwindcss(), adminCsp(apiOrigin, "dist/index.html")],
    server: {
      port: 5174,
      host: "0.0.0.0",
      // CNB preview proxies reach this server through generated `*.cnb.space`
      // hosts, which Vite 6 rejects unless allowlisted. Dev transport only.
      allowedHosts: resolveDevAllowedHosts(env.SOYMUTDB_DEV_ALLOWED_HOSTS),
      proxy: { "/api": { target: apiOrigin, changeOrigin: true } },
    },
    preview: {
      port: 4174,
      host: "0.0.0.0",
      allowedHosts: resolveDevAllowedHosts(env.SOYMUTDB_DEV_ALLOWED_HOSTS),
    },
    build: { target: "es2022", outDir: "dist", sourcemap: false },
  };
});
