import tailwindcss from "@tailwindcss/postcss";
import { defineConfig } from "@umijs/max";
import { normalizeBasePath, requireDeploymentOrigin, resolveDevAllowedHosts } from "@soymutdb/shared/deployment";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

type WebpackChain = Parameters<NonNullable<Parameters<typeof defineConfig>[0]["chainWebpack"]>>[0];

const env = process.env;
const development = env.NODE_ENV === "development";
const deploymentMode = env.VITE_DEPLOYMENT_MODE?.trim().toLowerCase() || "standard";
const base = normalizeBasePath(env.VITE_BASE_URL);
const apiBaseUrl = env.VITE_API_BASE_URL?.trim() || (development ? "http://localhost:8010" : undefined);
const apiOrigin = requireDeploymentOrigin(apiBaseUrl, "JBrowse API", {
  allowInsecureHttp: development || deploymentMode !== "production",
});
const dataUrl = env.VITE_JBROWSE_DATA_URL?.trim() || "/jbrowse-data";
const portalOrigin = env.SOYMUTDB_PORTAL_ORIGIN?.trim() || "";
const adminOrigin = env.SOYMUTDB_ADMIN_ORIGIN?.trim() || "";
const headersTemplate = readFileSync(resolve(process.cwd(), "public/_headers"), "utf8");
const cspMatch = headersTemplate.match(/^\s*Content-Security-Policy:\s*(.+)$/m);
if (!cspMatch) throw new Error("JBrowse public/_headers is missing its CSP template");
const requireFromConfig =
  typeof __filename === "string" ? createRequire(__filename) : createRequire(import.meta.url);
const browserBuffer = requireFromConfig.resolve("buffer/");
const configuredDevHosts = resolveDevAllowedHosts(env.SOYMUTDB_DEV_ALLOWED_HOSTS);

const viteEnv = {
  BASE_URL: base,
  DEV: development,
  MODE: env.NODE_ENV || "production",
  PROD: !development,
  VITE_API_BASE_URL: apiBaseUrl || "",
  VITE_BASE_URL: base,
  VITE_DEPLOYMENT_MODE: deploymentMode,
  VITE_JBROWSE_DATA_URL: dataUrl,
  SOYMUTDB_PORTAL_ORIGIN: portalOrigin,
  SOYMUTDB_ADMIN_ORIGIN: adminOrigin,
};

export default defineConfig({
  base,
  publicPath: base,
  outputPath: env.SOYMUTDB_DIST_DIR?.trim() || "dist",
  hash: true,
  title: "SoyMutDB Genome Browser",
  favicons: [`${base}favicon.svg`],
  routes: [
    { path: "/", component: "@/umi-entry" },
    { path: "/*", component: "@/umi-entry" },
  ],
  metas: [{ "http-equiv": "Content-Security-Policy", content: cspMatch[1].trim() }],
  extraPostCSSPlugins: [tailwindcss()],
  mfsu: false,
  layout: false,
  access: false,
  model: false,
  initialState: false,
  request: false,
  alias: {
    "@": resolve(process.cwd(), "src"),
    buffer: browserBuffer,
  },
  proxy: {
    "/api": { target: apiOrigin, changeOrigin: true },
    "/jbrowse-data": { target: apiOrigin, changeOrigin: true },
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
