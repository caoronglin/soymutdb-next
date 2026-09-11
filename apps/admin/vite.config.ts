import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Plugin } from "vite";
import { fileURLToPath } from "node:url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));

// Normalise a deployment base path (e.g. "/admin/", "/soymutdb/admin/") to a
// single trailing-slash form; "/" stays "/". Keeps dynamic-import chunk paths
// and the injected `base` aligned when the console is served at a subpath
// (admin.soymutdb.org or a protected custom origin) rather than the domain root.
function normalizeBasePath(value: string): string {
    const trimmed = value.trim();
    if (!trimmed || trimmed === "/") return "/";
    return `/${trimmed.replace(/^\/+|\/+$/g, "")}/`;
}

/**
 * Duplicated from `apps/web/src/lib/deployment.ts` on purpose: the apps do not
 * import each other's source (only `packages/*` are shared), and the rule is
 * small enough to read in place. Keep the two in sync —
 * `scripts/test_ci_job_contracts.py` asserts that each config calls this helper
 * and that the web copy is executed against the generated CNB hostname.
 */
const CNB_DEV_HOST_SUFFIXES = [".cnb.space", ".cnb.run"];
const CNB_DEV_HOSTS = ["cnb.space", "cnb.run", "localhost", "127.0.0.1", "[::1]"];

function normalizeDevHost(entry: string): string {
    const value = entry.trim().replace(/^https?:\/\//i, "");
    if (!value) return "";
    return value.replace(/[/?#].*$/, "").replace(/:\d+$/, "").toLowerCase();
}

/**
 * Hosts the dev server accepts. CNB proxies preview ports through a generated
 * `*.cnb.space` host, which Vite 6 blocks by default:
 *
 *   Blocked request. This host ("cnb-38o-1k28dm5ta-001.cnb.space") is not allowed.
 *
 * The hostname is minted per environment, so the platform domains are matched by
 * pattern; anything else is opted in through `SOYMUTDB_DEV_ALLOWED_HOSTS`. This
 * is a `server`/`preview` transport rule only and never affects a build.
 */
function resolveDevAllowedHosts(value: string | undefined): true | string[] {
    const raw = value?.trim();
    if (raw === "true" || raw === "*") return true;
    const hosts = new Set<string>([...CNB_DEV_HOSTS, ...CNB_DEV_HOST_SUFFIXES]);
    for (const entry of (raw ?? "").split(/[\s,]+/)) {
        const host = normalizeDevHost(entry);
        if (host) hosts.add(host);
    }
    return [...hosts];
}

function resolveApiOrigin(value: string | undefined, deploymentMode: string): string | null {
    const candidate = value?.trim();
    if (!candidate) {
        if (deploymentMode === "production") {
            throw new Error("Admin production build requires VITE_API_BASE_URL");
        }
        return null;
    }
    let url: URL;
    try {
        url = new URL(candidate);
    } catch {
        throw new Error(
            `Admin API origin must be an absolute URL: ${candidate}`,
        );
    }
    if (url.hostname === "example.com" || url.hostname.endsWith(".example.com")) {
        throw new Error(
            `Admin API origin uses a placeholder domain: ${candidate}`,
        );
    }
    if (deploymentMode === "production" && url.protocol !== "https:") {
        throw new Error("Admin production API origin must use https:");
    }
    return url.origin;
}

function adminDeploymentHeaders(apiOrigin: string | null): Plugin {
    return {
        name: "soymutdb-admin-deployment-headers",
        apply: "build",
        closeBundle() {
            const headersPath = resolve(__dirname, "dist/_headers");
            if (!existsSync(headersPath)) {
                throw new Error(`Admin headers artifact missing: ${headersPath}`);
            }
            const headers = readFileSync(headersPath, "utf8");
            const connectSrc = `connect-src 'self'${apiOrigin ? ` ${apiOrigin}` : ""}`;
            if (headers.includes(connectSrc)) return;
            const policy = headers.replace(
                /connect-src 'self'(?: https?:\/\/[^;\s]+)?/,
                connectSrc,
            );
            if (policy === headers) {
                throw new Error("Admin headers artifact has no replaceable connect-src policy");
            }
            writeFileSync(headersPath, policy, "utf8");
        },
    };
}

// Admin console — served on port 5174 in dev, bound to all interfaces.
// Manual TanStack Router (no file-based plugin).
// Tailwind v4 is wired via postcss.config.mjs (not as a Vite plugin).
export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, __dirname, "");
    const base = normalizeBasePath(env.VITE_BASE_URL?.trim() || "/");
    const deploymentMode = env.VITE_DEPLOYMENT_MODE?.trim().toLowerCase() || "standard";
    const apiOrigin = resolveApiOrigin(env.VITE_API_BASE_URL, deploymentMode);
    const apiProxyTarget = apiOrigin || "http://localhost:8000";

    return {
        base,
        plugins: [react(), adminDeploymentHeaders(apiOrigin)],
        resolve: {
            alias: {
                "@": resolve(__dirname, "src"),
            },
        },
        server: {
            port: 5174,
            host: "0.0.0.0",
            // See resolveDevAllowedHosts: the CNB preview proxy uses a
            // generated `*.cnb.space` host that Vite 6 blocks by default.
            allowedHosts: resolveDevAllowedHosts(env.SOYMUTDB_DEV_ALLOWED_HOSTS),
            proxy: {
                "/api": {
                    target: apiProxyTarget,
                    changeOrigin: true,
                },
            },
        },
        preview: {
            port: 5174,
            host: "0.0.0.0",
            allowedHosts: resolveDevAllowedHosts(env.SOYMUTDB_DEV_ALLOWED_HOSTS),
        },
        build: {
            target: "es2022",
            outDir: "dist",
            sourcemap: false,
            rollupOptions: {
                output: {
                    manualChunks(id: string) {
                        if (id.includes("node_modules/echarts")) return "echarts";
                        // TipTap editor (E1) — tiptap + prosemirror + marked@17
                        // + mammoth land in their own chunk (lazy-loaded via
                        // RichEditor). Keep them out of the entry bundle.
                        if (
                            id.includes("node_modules/@tiptap") ||
                            id.includes("node_modules/prosemirror") ||
                            id.includes("node_modules/marked") ||
                            id.includes("node_modules/mammoth")
                        ) {
                            return "tiptap";
                        }
                        // react 分支必须精确匹配核心包路径 —— 宽泛的
                        // id.includes("react") 会把 @ant-design/react-slick、
                        // react-day-picker 等依赖 rc-* 的包也打入 react chunk，
                        // 形成 react→rc→antd→react 循环（生产白屏风险）。
                        if (
                            /node_modules\/(react|react-dom|react-is|scheduler|use-sync-external-store)(\/|@)/.test(
                                id,
                            )
                        ) {
                            return "react";
                        }
                        if (id.includes("node_modules/@tanstack")) return "router";
                        // rc-* 基础组件和 antd 存在相互依赖；拆成独立 chunk 会导致
                        // ES module 初始化循环，并让生产登录页在加载时白屏。保持它们
                        // 在同一个 antd chunk，优先保证 production artifact 可执行。
                        if (id.includes("node_modules/rc-")) return "antd";
                        if (
                            id.includes("node_modules/antd") ||
                            id.includes("node_modules/@ant-design") ||
                            id.includes("node_modules/dayjs")
                        ) {
                            return "antd";
                        }
                    },
                },
            },
        },
    };
});
