import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
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

// Admin console — served on port 5174 in dev, bound to 127.0.0.1 only.
// Manual TanStack Router (no file-based plugin).
// Tailwind v4 is wired via postcss.config.mjs (not as a Vite plugin).
export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, __dirname, "");
    const base = normalizeBasePath(env.VITE_BASE_URL?.trim() || "/");

    return {
        base,
        plugins: [react()],
        resolve: {
            alias: {
                "@": resolve(__dirname, "src"),
            },
        },
        server: {
            port: 5174,
            host: "127.0.0.1",
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
                        if (id.includes("node_modules/react") || id.includes("node_modules/react-dom")) return "react";
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
