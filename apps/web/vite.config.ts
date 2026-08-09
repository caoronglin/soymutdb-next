import { defineConfig, loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

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
                    "script-src 'self' 'unsafe-inline'",
                    "script-src 'self' 'unsafe-inline' https://static.cloudflareinsights.com",
                )
                .replace(
                    "connect-src 'self' https://api.example.com",
                    "connect-src 'self' https://api.example.com https://cloudflareinsights.com",
                );
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

    // Deployment base path (oracle review R1, fixed 2026-08-09):
    // gh-pages hosts the site under /soymutdb-next/ — without a base the
    // built index.html references /assets/... which resolves to the
    // github.io ROOT (404, app JS crashes).  Override per deployment via
    // VITE_BASE_URL (e.g. "/" for a Cloudflare root domain).
    const deployBase =
        env.VITE_BASE_URL?.trim() || (mode === "production" ? "/soymutdb-next/" : "/");

    return {
        base: deployBase,
        plugins: [react(), cloudflareWebAnalytics(cfAnalyticsToken)],
        resolve: {
            alias: {
                "@": resolve(__dirname, "src"),
            },
        },
        server: {
            port: 5173,
            host: "0.0.0.0",
            proxy: {
                "/api": {
                    target: "http://localhost:8000",
                    changeOrigin: true,
                },
            },
        },
        build: {
            target: "es2022",
            outDir: "dist",
            sourcemap: false,
            chunkSizeWarningLimit: 2048,
            rollupOptions: {
                output: {
                    // G2 体积分块预算（docs/design/upgrade-plan.md §七）：
                    //   antd ≤280KB / pro-components ≤180KB / 主入口 ≤200KB (gzip)
                    // 阈值由 scripts/check-bundle-size.sh 硬门禁执行（CI + 本地）。
                    // 注：@ant-design/vite-plugin 在 npm registry 上不存在（404，
                    // 方案中列出的包名有误），antd v5 走 ESM + cssinjs 运行时按需，
                    // 不需要构建期按需插件；如需 dayjs 优化可用 antd-dayjs-vite-plugin。
                    manualChunks(id: string) {
                        if (id.includes("node_modules")) {
                            // pro-components 及其 @ant-design/pro-* 依赖 → 独立 chunk
                            if (id.includes("@ant-design/pro")) return "pro-components";
                            // rc-*（rc-table/rc-select/rc-pagination 等 antd 运行时
                            // 依赖）→ 独立 chunk（G2 预算：拆出后 antd 本体 ≤280KB）
                            if (id.includes("/rc-")) return "rc";
                            // antd + @ant-design/* → 独立 chunk
                            if (id.includes("/antd/") || id.includes("@ant-design")) {
                                return "antd";
                            }
                            if (id.includes("echarts")) return "echarts";
                            if (id.includes("gsap") || id.includes("lenis")) return "motion-vendor";
                            if (id.includes("react") || id.includes("scheduler")) return "react";
                            if (id.includes("@tanstack")) return "router";
                        }
                    },
                },
            },
        },
    };
});
