import tailwindcss from "@tailwindcss/postcss";
import { defineConfig } from "@umijs/max";
import {
  buildCsp,
  isMinimalDeploymentMode,
  normalizeBasePath,
  requireDeploymentOrigin,
  resolveDevAllowedHosts,
} from "@soymutdb/shared/deployment";
import { resolveSiteVariant } from "../src/lib/site-variant";

type WebpackChain = Parameters<NonNullable<Parameters<typeof defineConfig>[0]["chainWebpack"]>>[0];

const env = process.env;
const development = env.NODE_ENV === "development";
const deploymentMode = env.VITE_DEPLOYMENT_MODE?.trim() || (development ? "development" : "standard");
const siteVariant = resolveSiteVariant(env.VITE_SITE_VARIANT);
const base = normalizeBasePath(env.VITE_BASE_URL);
const allowInsecureDevOrigins = development;
const apiBaseUrl =
  env.VITE_API_BASE_URL?.trim() || (development ? "http://localhost:8010" : undefined);
const apiOrigin = requireDeploymentOrigin(apiBaseUrl, "API", {
  allowInsecureHttp: allowInsecureDevOrigins,
});
const minimalDeployment = isMinimalDeploymentMode(deploymentMode);
const jbrowseBaseUrl = minimalDeployment
  ? undefined
  : env.VITE_JBROWSE_BASE_URL?.trim() ||
    env.VITE_JBROWSE_URL?.trim() ||
    (development ? "http://localhost:5175" : undefined);
const jbrowseOrigin = jbrowseBaseUrl
  ? requireDeploymentOrigin(jbrowseBaseUrl, "JBrowse", {
      allowInsecureHttp: allowInsecureDevOrigins,
    })
  : undefined;
const analyticsToken = env.VITE_CLOUDFLARE_ANALYTICS_TOKEN?.trim();
const configuredDevHosts = resolveDevAllowedHosts(env.SOYMUTDB_DEV_ALLOWED_HOSTS);
const csp = buildCsp({ apiOrigin, jbrowseOrigin }, Boolean(analyticsToken));
const headScripts = analyticsToken
  ? [
      `<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon='${JSON.stringify({ token: analyticsToken })}'></script>`,
    ]
  : [];

const viteEnv = {
  BASE_URL: base,
  DEV: development,
  MODE: env.NODE_ENV || "production",
  PROD: !development,
  VITE_API_BASE_URL: apiBaseUrl || "",
  VITE_BASE_URL: base,
  VITE_DEMO_MODE: String(deploymentMode === "demo"),
  VITE_DEPLOYMENT_MODE: deploymentMode,
  VITE_JBROWSE_BASE_URL: jbrowseBaseUrl || "",
  VITE_JBROWSE_ENABLED: String(!minimalDeployment),
  VITE_JBROWSE_URL: jbrowseBaseUrl || "",
  VITE_SITE_VARIANT: siteVariant,
  VITE_SOYMUTDB_RELEASE_ID: env.VITE_SOYMUTDB_RELEASE_ID || env.SOYMUTDB_RELEASE_ID || "",
  VITE_SW_ENABLED: env.VITE_SW_ENABLED || "true",
};

export default defineConfig({
  base,
  publicPath: base,
  outputPath: env.SOYMUTDB_DIST_DIR?.trim() || "dist",
  hash: true,
  title: siteVariant === "internal" ? "SoyMutDB Internal Portal" : "SoyMutDB",
  favicons: [`${base}favicon.svg`],
  routes: [
    { path: "/", component: "@/umi-entry" },
    { path: "/*", component: "@/umi-entry" },
  ],
  metas: [
    { "http-equiv": "Content-Security-Policy", content: csp },
    ...(siteVariant === "internal" ? [{ name: "robots", content: "noindex,nofollow" }] : []),
  ],
  headScripts,
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
        // React core only. Routing libraries used to share this group, which
        // made the "react" budget measure React + react-router +
        // @tanstack/react-router together (105KB gzip) — too coarse to tell a
        // React regression from a routing one, and impossible to keep under a
        // React-sized budget.
        react: {
          test: /[\\/]node_modules[\\/](?:react|react-dom|scheduler)[\\/]/,
          name: "react",
          priority: 40,
          enforce: true,
        },
        // Router/runtime routing stack, budgeted separately.
        router: {
          test: /[\\/]node_modules[\\/](?:react-router|react-router-dom|@tanstack[\\/](?:react-router|router-core|history))[\\/]/,
          name: "router",
          priority: 38,
          enforce: true,
        },
        query: {
          test: /[\\/]node_modules[\\/]@tanstack[\\/](?:react-query|query-core)[\\/]/,
          name: "query",
          priority: 35,
          enforce: true,
        },
        pro: {
          test: /[\\/]node_modules[\\/]@ant-design[\\/]pro-[^\\/]+[\\/]/,
          name: "pro",
          priority: 30,
          enforce: true,
        },
        ui: {
          test: /[\\/]node_modules[\\/](?:antd|@ant-design|rc-[^\\/]+)[\\/]/,
          name: "ui",
          priority: 20,
          enforce: true,
        },
        charts: {
          test: /[\\/]node_modules[\\/](?:echarts|zrender)[\\/]/,
          name: "charts",
          priority: 15,
          enforce: true,
        },
      },
    });
  },
  define: {
    "import.meta.env": JSON.stringify(viteEnv),
    __SITE_VARIANT__: JSON.stringify(siteVariant),
    __SOYMUTDB_INTERNAL_SITE__: JSON.stringify(siteVariant === "internal"),
    "process.env.SITE_VARIANT": JSON.stringify(siteVariant),
    "process.env.VITE_SITE_VARIANT": JSON.stringify(siteVariant),
  },
});
