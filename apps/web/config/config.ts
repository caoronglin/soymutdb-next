import tailwindcss from "@tailwindcss/postcss";
import { resolve } from "node:path";
import { defineConfig } from "@umijs/max";
import {
  buildCsp,
  isMinimalDeploymentMode,
  normalizeBasePath,
  requireDeploymentOrigin,
  resolveDevAllowedHosts,
} from "@soymutdb/shared/deployment";
import { resolveSiteVariant } from "../src/lib/site-variant";
import { chartSupportCacheGroups } from "../../../scripts/webpack/chart-split-groups";

type WebpackChain = Parameters<NonNullable<Parameters<typeof defineConfig>[0]["chainWebpack"]>>[0];

const env = process.env;
const development = env.NODE_ENV === "development";
const deploymentMode = env.VITE_DEPLOYMENT_MODE?.trim() || (development ? "development" : "standard");
const siteVariant = resolveSiteVariant(env.VITE_SITE_VARIANT);
const base = normalizeBasePath(env.VITE_BASE_URL);
const allowInsecureDevOrigins = development || env.SOYMUTDB_LOCAL_TEST_PREVIEW_ENABLED === "true" || env.SOYMUTDB_LOCAL_TEST_PREVIEW_ENABLED === "1";
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
  // The public portal deliberately renders with the system CJK stack for first
  // paint (see the font note in src/index.css): its CSS declares no HarmonyOS
  // @font-face, so a font preload here would download a file nothing uses. The
  // self-hosted HarmonyOS subsets are admin-only.
  links: [],
  routes: [
        { path: "/", component: "@/umi-entry" },
        { path: "/*", component: "@/umi-entry" },
      ],
  metas: [
    { "http-equiv": "Content-Security-Policy", content: csp },
    ...(siteVariant === "internal" ? [{ name: "robots", content: "noindex,nofollow" }] : []),
  ],
  headScripts,
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
        // Keep the facade out of the application route chunk. The chart gate
        // charges whole downloaded chunks, including any unrelated modules.
        // These engine dependencies also appear in general vendor chunks.
        // Separate their initial and async consumers so extracting them does
        // not make async-only chart helpers part of the initial download.
        ...chartSupportCacheGroups(),
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
        // Chart engine budget. AntV G2 is the only production engine; the ECharts
        // terms are retired because no portal module imports them any more.
        // Priority is above `ui` (20) on purpose — the `ui` test also matches the
        // `@ant-design` scope, so a lower priority would hand `@ant-design/plots`
        // to the antd group and under-report the engine.
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
    // pdf.js has a Node-only branch (`process.getBuiltinModule("module")
    // .createRequire(import.meta.url)`). Webpack inlines that `import.meta.url`
    // as a file:// build-machine path in the browser bundle. The branch never
    // runs in a browser; blank the identifier so no local path is emitted.
    "import.meta.url": JSON.stringify(""),
    __SITE_VARIANT__: JSON.stringify(siteVariant),
    __SOYMUTDB_INTERNAL_SITE__: JSON.stringify(siteVariant === "internal"),
    "process.env.SITE_VARIANT": JSON.stringify(siteVariant),
    "process.env.VITE_SITE_VARIANT": JSON.stringify(siteVariant),
  },
});
