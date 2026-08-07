import { defineConfig, type PluginOption } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/postcss";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));

// Admin console — served on port 5174 in dev, bound to 127.0.0.1 only.
// Manual TanStack Router (no file-based plugin).
export default defineConfig({
    plugins: [react(), tailwindcss() as unknown as PluginOption],
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
                },
            },
        },
    },
});
