import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));

// Admin console — served on port 5174 in dev, bound to 127.0.0.1 only.
// Manual TanStack Router (no file-based plugin).
// Tailwind v4 is wired via postcss.config.mjs (not as a Vite plugin).
export default defineConfig({
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
                    // AntD Pro split (G2 budget: antd ≤ 280KB / pro ≤ 180KB gzip).
                    // pro-components depends on @ant-design/pro-* — check it
                    // first so those land in the "pro" chunk, not "antd".
                    if (
                        id.includes("node_modules/@ant-design/pro-components") ||
                        id.includes("node_modules/@ant-design/pro-")
                    ) {
                        return "pro";
                    }
                    // rc-* 基础组件（rc-table / rc-select / rc-pagination / rc-tree /
                    // rc-picker / rc-virtual-list 等）拆到独立 rc chunk。
                    // antd 与 pro-components 都依赖它们，合入 antd chunk 曾使
                    // antd chunk 达 ~397KB gzip（G2 预算 280KB）；拆出后 antd
                    // chunk 只含 antd 本体 + @ant-design/icons + cssinjs + dayjs。
                    if (id.includes("node_modules/rc-")) {
                        return "rc";
                    }
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
});
