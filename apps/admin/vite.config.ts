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
 * Rewrite the CSP's `connect-src` with the configured API origin.
 *
 * The source `_headers` ships a conservative same-origin policy: a placeholder
 * origin must never be the default, and a published admin console whose CSP
 * blocks its own API is the failure this rewrite exists to prevent. The header
 * file is copied verbatim into `dist/`, so the rewrite happens after the copy.
 */
function injectApiOrigin(apiOrigin: string): Plugin {
  return {
    name: "admin-csp-api-origin",
    apply: "build",
    closeBundle() {
      const headers = join(import.meta.dirname, "dist", "_headers");
      const policy = readFileSync(headers, "utf8").replace(
        /connect-src[^;]*/,
        `connect-src 'self' ${new URL(apiOrigin).origin}`,
      );
      writeFileSync(headers, policy);
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, import.meta.dirname, "");
  const apiOrigin =
    env.VITE_API_BASE_URL?.trim() ||
    (mode === "development" ? "http://localhost:8000" : "");
  if (!apiOrigin) {
    // Fail closed: an admin bundle with no API origin would load and then fail
    // every request with an opaque network error.
    throw new Error(
      "VITE_API_BASE_URL is required for the admin build (the console has no default API origin)",
    );
  }
  return {
    base: normalizeBasePath(env.VITE_BASE_URL),
    plugins: [vue(), tailwindcss(), injectApiOrigin(apiOrigin)],
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
