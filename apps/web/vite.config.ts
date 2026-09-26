import tailwindcss from "@tailwindcss/vite";
import { defineConfig, loadEnv, type Plugin } from "vite";
import vue from "@vitejs/plugin-vue";

import {
  buildCsp,
  isMinimalDeploymentMode,
  normalizeBasePath,
  requireDeploymentOrigin,
  resolveDevAllowedHosts,
} from "@soymutdb/shared/deployment";
import { resolveSiteVariant } from "./src/lib/site-variant";

// Public portal — Vite 6 + Tailwind CSS 4 (@tailwindcss/vite) + the
// @soymutdb/ui-vue facade. The site variant is a build-time define (DB-CORE-5).
//
// `base` comes from the same VITE_BASE_URL the static artifact builder sets, so
// a subpath deployment (/soymutdb-next/) emits /soymutdb-next/assets/... asset
// URLs and import.meta.env.BASE_URL (which createWebHistory consumes) instead of
// rooting every URL at /.
//
// Deployment origins are required and validated here, at config time: a build
// with no API/JBrowse origin fails instead of shipping an artifact whose CSP
// blocks every cross-origin request (the failure mode that reads as "the API is
// down"). Development mode may use http loopback origins; every other mode may
// not.

/** Inject the CSP `<meta>` into the emitted documents. */
function deploymentCsp(csp: string): Plugin {
  return {
    name: "deployment-csp",
    transformIndexHtml(html) {
      return html.replace(
        /(<meta\s+http-equiv="Content-Security-Policy"\s+content=")[^"]*("\s*\/?>)/,
        `$1${csp}$2`,
      );
    },
  };
}

/** Cloudflare Web Analytics beacon, embedded at build time (no Workers). */
function cloudflareWebAnalytics(token: string | undefined): Plugin {
  return {
    name: "cloudflare-web-analytics",
    transformIndexHtml(html) {
      const placeholder = "<!-- %CLOUDFLARE_ANALYTICS_TOKEN% -->";
      if (!token) return html.replace(placeholder, "");
      const beacon = `<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon='${JSON.stringify({ token })}'></script>`;
      return html
        .replace(placeholder, beacon)
        .replace(
          /script-src 'self' 'unsafe-inline'([^;"]*)/,
          (_match, origins: string) =>
            origins.includes("https://static.cloudflareinsights.com")
              ? _match
              : `script-src 'self' 'unsafe-inline'${origins} https://static.cloudflareinsights.com`,
        )
        .replace(
          /connect-src 'self'([^;"]*)/,
          (_match, origins: string) =>
            origins.includes("https://cloudflareinsights.com")
              ? _match
              : `connect-src 'self'${origins} https://cloudflareinsights.com`,
        );
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, import.meta.dirname, "");
  const cfAnalyticsToken = env.VITE_CLOUDFLARE_ANALYTICS_TOKEN?.trim() || undefined;
  // Validate the site variant at config time: an illegal value must fail the
  // build, never become a third variant whose isInternal silently reads false
  // (DB-CORE-5). The runtime store repeats this check for non-Vite hosts.
  const siteVariant = resolveSiteVariant(env.VITE_SITE_VARIANT);
  const minimalDeployment = isMinimalDeploymentMode(env.VITE_DEPLOYMENT_MODE);
  // Development is the only mode allowed to bind a loopback origin.
  const allowInsecureDevOrigins = mode === "development";
  const apiOrigin = requireDeploymentOrigin(
    env.VITE_API_BASE_URL || (mode === "development" ? "http://localhost:8010" : undefined),
    "API",
    { allowInsecureHttp: allowInsecureDevOrigins },
  );
  // Minimal Pages releases ship no JBrowse bundle: no frame origin is
  // manufactured, the portal uses its unavailable fallback instead.
  const jbrowseOrigin = minimalDeployment
    ? undefined
    : requireDeploymentOrigin(
        env.VITE_JBROWSE_BASE_URL || env.VITE_JBROWSE_URL || (mode === "development" ? "http://localhost:5175" : undefined),
        "JBrowse",
        { allowInsecureHttp: allowInsecureDevOrigins },
      );

  return {
    base: normalizeBasePath(env.VITE_BASE_URL),
    plugins: [
      vue(),
      tailwindcss(),
      deploymentCsp(buildCsp({ apiOrigin, jbrowseOrigin }, Boolean(cfAnalyticsToken))),
      cloudflareWebAnalytics(cfAnalyticsToken),
    ],
    server: {
      port: 5173,
      host: "0.0.0.0",
      // CNB preview proxies reach this server through generated `*.cnb.space`
      // hosts, which Vite 6 rejects unless allowlisted. Dev transport only —
      // `server`/`preview` never affect a build.
      allowedHosts: resolveDevAllowedHosts(env.SOYMUTDB_DEV_ALLOWED_HOSTS),
      proxy: {
        "/api": { target: apiOrigin, changeOrigin: true },
      },
    },
    preview: {
      port: 4173,
      host: "0.0.0.0",
      allowedHosts: resolveDevAllowedHosts(env.SOYMUTDB_DEV_ALLOWED_HOSTS),
    },
    build: {
      target: "es2022",
      outDir:
        process.env.SOYMUTDB_VUE_DIST_DIR?.trim() ||
        env.SOYMUTDB_VUE_DIST_DIR?.trim() ||
        "dist",
      sourcemap: false,
      chunkSizeWarningLimit: 2048,
      rollupOptions: {
        output: {
          // Split the framework runtimes from the application code. Without
          // this the single entry chunk carries Vue + Router + Pinia +
          // Vue Query + every view, which makes the entry budget unenforceable
          // and forces a full re-download for any app-code change.
          manualChunks(id: string) {
            if (!id.includes("node_modules")) return undefined;
            if (id.includes("antdv-next") || id.includes("@ant-design")) return "ui";
            // `@tanstack/charts` is not vue-query: folding them together made
            // the query budget measure the chart runtime, which is a different
            // dependency with a different upgrade cadence.
            if (id.includes("@tanstack/charts")) return "charts";
            if (id.includes("@tanstack")) return "query";
            if (id.includes("/vue/") || id.includes("@vue/") || id.includes("/pinia/")) {
              return "vue";
            }
            return undefined;
          },
        },
      },
    },
    define: {
      __SITE_VARIANT__: JSON.stringify(siteVariant),
    },
  };
});
