import tailwindcss from "@tailwindcss/postcss";
import { resolve } from "node:path";
import { defineConfig } from "@umijs/max";
import { normalizeBasePath, requireDeploymentOrigin, resolveDevAllowedHosts } from "@soymutdb/shared/deployment";

type WebpackChain = Parameters<NonNullable<Parameters<typeof defineConfig>[0]["chainWebpack"]>>[0];

const env = process.env;
const development = env.NODE_ENV === "development";
const base = normalizeBasePath(env.VITE_BASE_URL);
const apiBaseUrl =
  env.VITE_API_BASE_URL?.trim() || (development ? "http://localhost:8010" : undefined);
const apiOrigin = requireDeploymentOrigin(apiBaseUrl, "Admin API", {
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
  VITE_PUBLIC_URL: env.VITE_PUBLIC_URL || base,
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
  plugins: [resolve(__dirname, "plugins/defer-html-scripts.cjs")],
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
  },
  define: {
    "import.meta.env": JSON.stringify(viteEnv),
  },
});
