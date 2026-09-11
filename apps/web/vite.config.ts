import { defineConfig, loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
    buildCsp,
    isMinimalDeploymentMode,
    normalizeBasePath,
    requireDeploymentOrigin,
    resolveDevAllowedHosts,
} from "./src/lib/deployment";

const __dirname = fileURLToPath(new URL(".", import.meta.url));

/**
 * Cloudflare Web Analytics beacon injection (C3).
 *
 * The portal is deployed as a static site on Cloudflare Pages, so analytics
 * is a plain JS beacon embedded into index.html at BUILD time — no Workers,
 * no server-side components. When `VITE_CLOUDFLARE_ANALYTICS_TOKEN` is set:
 *   - the `%CLOUDFLARE_ANALYTICS_TOKEN%` placeholder in index.html is replaced
 *     with the full beacon <script> tag;
 *   - the <meta> CSP is widened to allow the beacon origins
 *     (`script-src https://static.cloudflareinsights.com` and
 *     `connect-src https://cloudflareinsights.com`).
 * Without the token the placeholder is removed and the CSP is left untouched,
 * so a no-token build behaves exactly as before.
 *
 * NOTE: the meta CSP and apps/web/public/_headers carry the same CSP text
 * (browsers intersect both) — the _headers CSP is widened statically for the
 * beacon origins; keep the two in sync (see deploy/cloudflare.md §Web
 * Analytics).
 */
function cloudflareWebAnalytics(token: string | undefined): Plugin {
    return {
        name: "cloudflare-web-analytics",
        transformIndexHtml(html: string) {
            const placeholder = "<!-- %CLOUDFLARE_ANALYTICS_TOKEN% -->";
            if (!token) {
                // No token configured: drop the placeholder, keep CSP untouched.
                return html.replace(placeholder, "");
            }
            const beacon = `<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon='${JSON.stringify({ token })}'></script>`;
            return html
                .replace(placeholder, beacon)
                // Widen the <meta> CSP for the beacon (must stay in sync with
                // apps/web/public/_headers, whose CSP is widened statically).
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

function deploymentCsp(csp: string): Plugin {
    return {
        name: "deployment-csp",
        transformIndexHtml(html) {
            return html.replace(/(<meta\s+http-equiv="Content-Security-Policy"\s+content=")[^"]*("\s*\/>)/, `$1${csp}$2`);
        },
    };
}

// Public portal — served on port 5173 in dev.
// Manual TanStack Router (no file-based plugin). Routes defined in src/routes/.
// Tailwind v4 is wired via postcss.config.mjs (not as a Vite plugin).
export default defineConfig(({ mode }) => {
    // Load env WITHOUT the VITE_ prefix filter so the token is visible here.
    const env = loadEnv(mode, __dirname, "");
    const cfAnalyticsToken = env.VITE_CLOUDFLARE_ANALYTICS_TOKEN?.trim() || undefined;
    const siteVariant = (env.VITE_SITE_VARIANT?.trim().toLowerCase() || "external");
    if (siteVariant !== "external" && siteVariant !== "internal") {
        throw new Error(`VITE_SITE_VARIANT must be external or internal, got "${siteVariant}"`);
    }

    // Deployment base path (oracle review R1, fixed 2026-08-09):
    // gh-pages hosts the site under /soymutdb-next/ — without a base the
    // built index.html references /assets/... which resolves to the
    // github.io ROOT (404, app JS crashes).  Override per deployment via
    // VITE_BASE_URL (e.g. "/" for a Cloudflare root domain).
    const deployBase = normalizeBasePath(env.VITE_BASE_URL?.trim() || "/");
    const minimalDeployment = isMinimalDeploymentMode(env.VITE_DEPLOYMENT_MODE);
    // The portal still pins an explicit API origin in every production mode so
    // its CSP stays narrow and API-unavailable states remain deterministic.
    const allowInsecureDevOrigins = mode === "development";
    const apiOrigin = requireDeploymentOrigin(
        env.VITE_API_BASE_URL || (mode === "development" ? "http://localhost:8000" : undefined),
        "API",
        { allowInsecureHttp: allowInsecureDevOrigins },
    );
    const apiProxyTarget = apiOrigin;
    // Minimal Pages releases intentionally contain no JBrowse bundle. Do not
    // manufacture a localhost/placeholder frame origin: omit frame access
    // altogether and let the public UI use its linear/unavailable fallbacks.
    const jbrowseOrigin = minimalDeployment
        ? undefined
        : requireDeploymentOrigin(
            env.VITE_JBROWSE_BASE_URL || env.VITE_JBROWSE_URL || (mode === "development" ? "http://localhost:5175" : undefined),
            "JBrowse",
            { allowInsecureHttp: allowInsecureDevOrigins },
        );

    return {
        define: {
            __SOYMUTDB_INTERNAL_SITE__: siteVariant === "internal",
        },
        base: deployBase,
        plugins: [react(), deploymentCsp(buildCsp({ apiOrigin, jbrowseOrigin }, Boolean(cfAnalyticsToken))), cloudflareWebAnalytics(cfAnalyticsToken)],
        resolve: {
            alias: {
                "@": resolve(__dirname, "src"),
            },
        },
        server: {
            port: 5173,
            host: "0.0.0.0",
            // The CNB preview proxy reaches this server through a generated
            // `*.cnb.space` host, and Vite 6 rejects any Host it does not know
            // ("Blocked request. This host ... is not allowed"). The platform
            // hostnames are matched by pattern rather than by value because a
            // new hostname is minted for every cloud development environment.
            // Dev transport only: `server`/`preview` never affect a build.
            allowedHosts: resolveDevAllowedHosts(env.SOYMUTDB_DEV_ALLOWED_HOSTS),
            proxy: {
                "/api": {
                    target: apiProxyTarget,
                    changeOrigin: true,
                },
            },
        },
        preview: {
            port: 4173,
            host: "0.0.0.0",
            allowedHosts: resolveDevAllowedHosts(env.SOYMUTDB_DEV_ALLOWED_HOSTS),
        },
        build: {
            target: "es2022",
            outDir: env.SOYMUTDB_DIST_DIR?.trim() || "dist",
            sourcemap: false,
            chunkSizeWarningLimit: 2048,
            rollupOptions: {
                output: {
                    // AntD and every rc-* runtime module stay together. Splitting
                    // table internals created an antd -> table -> antd cycle and a
                    // production blank-screen risk.
                    manualChunks(id: string) {
                        if (id.includes("node_modules")) {
                            // icons-svg has no dependency back into antd. Splitting it
                            // keeps the core chunk inside the gzip budget while leaving
                            // the @ant-design/icons runtime co-located with antd.
                            if (id.includes("@ant-design/icons-svg")) return "antd-icons";
                            // rc-* 与 antd 存在相互运行时依赖。拆成独立 chunk 会
                            // 形成 ES module 初始化循环；同置优先保证生产制品可执行。
                            if (id.includes("/rc-")) return "antd";
                            // antd + @ant-design/* → 独立 chunk
                            if (id.includes("/antd/") || id.includes("@ant-design")) {
                                return "antd";
                            }
                            if (id.includes("echarts")) return "echarts";
                            // @tanstack 必须先于 react 分支：@tanstack/react-* 的
                            // 路径含 "react"，若被 react 分支截胡会与 router chunk
                            // （@tanstack 主体依赖 react）形成循环依赖。
                            if (id.includes("@tanstack")) return "router";
                            // react 分支必须精确匹配核心包路径 —— 宽泛的
                            // id.includes("react") 会把 @ant-design/react-slick、
                            // react-day-picker 等依赖 rc-* 的包也打入 react chunk，
                            // 形成 react→rc→antd→react 循环（线上表现为 antd chunk
                            // createContext undefined，2026-08-09 修复）。
                            if (
                                /node_modules\/(react|react-dom|react-is|scheduler|use-sync-external-store)(\/|@)/.test(
                                    id,
                                )
                            ) {
                                return "react";
                            }
                        }
                    },
                },
            },
        },
    };
});
