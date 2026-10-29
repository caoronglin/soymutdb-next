import tailwindcss from "@tailwindcss/postcss";
import { resolve } from "node:path";
import { defineConfig } from "@umijs/max";
import { chartSupportCacheGroups } from "../../../scripts/webpack/chart-split-groups";
import { normalizeBasePath, requireDeploymentOrigin, resolveDevAllowedHosts } from "@soymutdb/shared/deployment";

type WebpackChain = Parameters<NonNullable<Parameters<typeof defineConfig>[0]["chainWebpack"]>>[0];

const env = process.env;
const development = env.NODE_ENV === "development";
const base = normalizeBasePath(env.VITE_BASE_URL);
// Two different jobs, deliberately fed from two different variables.
//
// `apiBaseUrl` is baked into `import.meta.env` and therefore read *by the
// browser*, so it must stay unset for any deployment that serves the console
// and the API from the same origin — setting it pins the artifact to one host
// and breaks the console for every other hostname (e.g. a LAN address). The
// client already falls back to the same-origin `/api/v1`.
//
// `apiOrigin` only feeds the CSP `connect-src` allowlist and the artifact
// identity checks, so it still needs an absolute URL at build time. It accepts
// the non-`VITE_`-prefixed spelling, which Vite does not auto-inject.
const apiBaseUrl = env.VITE_API_BASE_URL?.trim() || undefined;
const apiOriginValue =
  apiBaseUrl ||
  env.SOYMUTDB_ADMIN_API_URL?.trim() ||
  (development ? "http://localhost:8010" : undefined);
const apiOrigin = requireDeploymentOrigin(apiOriginValue, "Admin API", {
  allowInsecureHttp: development || env.SOYMUTDB_LOCAL_TEST_PREVIEW_ENABLED === "true" || env.SOYMUTDB_LOCAL_TEST_PREVIEW_ENABLED === "1",
});
const configuredDevHosts = resolveDevAllowedHosts(env.SOYMUTDB_DEV_ALLOWED_HOSTS);
const csp = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: https:",
  "font-src 'self' data:",
  `connect-src 'self' ${apiOrigin}`,
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
].join("; ");
const viteEnv = {
  BASE_URL: base,
  DEV: development,
  MODE: env.NODE_ENV || "production",
  PROD: !development,
  VITE_API_BASE_URL: apiBaseUrl || "",
  VITE_BASE_URL: base,
  VITE_PUBLIC_URL: env.VITE_PUBLIC_URL?.trim() || "",
  VITE_REMOTE_INSTANCES_ENABLED: env.VITE_REMOTE_INSTANCES_ENABLED || "false",
  VITE_SOYMUTDB_RELEASE_ID: env.VITE_SOYMUTDB_RELEASE_ID || env.SOYMUTDB_RELEASE_ID || "",
};

export default defineConfig({
  base,
  publicPath: base,
  outputPath: env.SOYMUTDB_DIST_DIR?.trim() || "dist",
  hash: true,
  title: "SoyMutDB Admin",
  favicons: [`${base}favicon.svg`],
  // Start the Regular subset before CSS is parsed. `crossorigin` is required for
  // a font preload to match the CORS fetch the browser makes for @font-face;
  // without it the preload is discarded and the font is downloaded twice.
  links: [
    {
      rel: "preload",
      href: `${base}fonts/harmonyos/HarmonyOS-Sans-SC-Regular-latin.woff2`,
      as: "font",
      type: "font/woff2",
      crossorigin: "anonymous",
    },
  ],
  routes: [
    { path: "/", component: "@/umi-entry" },
    { path: "/*", component: "@/umi-entry" },
  ],
  metas: [{ "http-equiv": "Content-Security-Policy", content: csp }],
  // esbuild hoists each chunk's shared helpers to the TOP LEVEL of the
  // emitted async chunk, so two chunks can both declare `var n = <spread>`
  // in the global scope. The last chunk loaded then wins for BOTH, and
  // antd's `{ ...optional }` called the unguarded helper ->
  // "getOwnPropertyDescriptors(undefined)" -> blank page. Terser keeps
  // helpers inside the module/chunk scope, so the collision cannot form.
  jsMinifier: "terser",
  plugins: [
    resolve(__dirname, "plugins/defer-html-scripts.cjs"),
    // Chart dependency closure instrumentation. Registration only: it writes
    // .build/chart-closure/<app>-<variant>.json at the end of the compilation
    // and never changes the module graph or the emitted bytes.
    resolve(__dirname, "../../../scripts/webpack/chart-closure-plugin.cjs"),
  ],
  extraPostCSSPlugins: [tailwindcss()],
  mfsu: false,
  layout: false,
  access: false,
  model: false,
  initialState: false,
  request: false,
  proxy: {
    "/api": { target: apiOrigin, changeOrigin: true },
  },
  chainWebpack(memo: WebpackChain) {
    if (configuredDevHosts === true) {
      memo.devServer.set("allowedHosts", "all");
    } else {
      memo.devServer.allowedHosts.merge(configuredDevHosts);
    }
    memo.output
      .filename("assets/[name].[contenthash:8].js")
      .chunkFilename("assets/[name].[contenthash:8].async.js")
      .set("assetModuleFilename", "assets/[name].[contenthash:8][ext][query]");
    memo.optimization.splitChunks({
      chunks: "all",
      cacheGroups: {
        ...chartSupportCacheGroups(),
        charts: {
          test: /[\\/]node_modules[\\/](?:@antv[\\/]|@ant-design[\\/]plots[\\/])/,
          name: "charts",
          priority: 22,
          enforce: true,
        },
      },
    });
  },
  define: {
    "import.meta.env": JSON.stringify(viteEnv),
  },
});
