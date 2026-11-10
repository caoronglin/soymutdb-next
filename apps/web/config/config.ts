import tailwindcss from "@tailwindcss/postcss";
import { resolve } from "node:path";
import { defineConfig } from "@umijs/max";
import {
  buildCsp,
  isMinimalDeploymentMode,
  normalizeBasePath,
  requireDeploymentOrigin,
  resolveAnalyticsProvider,
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
// Remote file preview is opt-in per variant. `build-sites.ts` maps only the
// building variant's non-VITE input into this pair, so neither artifact can
// carry the other variant's viewer. A viewer without an allowlisted artifact
// origin stays disabled at runtime (preview-policy.ts fails closed).
const fileViewerUrl = env.VITE_FILE_VIEWER_URL?.trim() || undefined;
const fileViewerFrameOrigins = fileViewerUrl
  ? [
      requireDeploymentOrigin(fileViewerUrl, "File viewer", {
        allowInsecureHttp: allowInsecureDevOrigins,
      }),
    ]
  : [];
const fileViewerArtifactOrigins = (env.VITE_FILE_VIEWER_ARTIFACT_ORIGINS ?? "")
  .split(",")
  .map((origin) => origin.trim())
  .filter((origin) => origin.length > 0)
  .map((origin) =>
    requireDeploymentOrigin(origin, "File viewer artifact", {
      allowInsecureHttp: allowInsecureDevOrigins,
    }),
  );
// The VITE_* spelling is a legacy alias from the pre-Umi build; keep reading it
// so existing Cloudflare Pages projects do not silently lose analytics.
const analyticsToken = (
  env.SOYMUTDB_CLOUDFLARE_ANALYTICS_TOKEN ?? env.VITE_CLOUDFLARE_ANALYTICS_TOKEN
)?.trim();
// The platform's own `/track.gif` collector is the default; the Cloudflare
// beacon is opt-in. Resolved through the shared helper so this config and the
// CSP finalizer cannot disagree about which provider a build selected.
const analytics = resolveAnalyticsProvider(env.SOYMUTDB_ANALYTICS_PROVIDER, analyticsToken);
if (analytics.reason.startsWith("legacy:")) {
  // Build-time notice only: the reason describes how this artifact was
  // configured, so it must never reach the emitted page bytes.
  process.stderr.write(`[analytics] ${analytics.reason}\n`);
}
const configuredDevHosts = resolveDevAllowedHosts(env.SOYMUTDB_DEV_ALLOWED_HOSTS);
const csp = buildCsp(
  { apiOrigin, jbrowseOrigin, frameOrigins: fileViewerFrameOrigins },
  analytics.cloudflare,
);
const headScripts = analytics.cloudflare
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
  VITE_FILE_VIEWER_ARTIFACT_ORIGINS: fileViewerArtifactOrigins.join(","),
  VITE_FILE_VIEWER_URL: fileViewerUrl || "",
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
