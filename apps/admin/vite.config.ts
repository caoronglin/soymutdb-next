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
                    if (
                        id.includes("node_modules/antd") ||
                        id.includes("node_modules/@ant-design") ||
                        id.includes("node_modules/rc-") ||
                        id.includes("node_modules/dayjs")
                    ) {
                        return "antd";
                    }
                },
            },
        },
    },
});
