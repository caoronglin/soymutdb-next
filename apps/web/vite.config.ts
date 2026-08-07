import { defineConfig, type PluginOption } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/postcss";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));

// Public portal — served on port 5173 in dev.
// Manual TanStack Router (no file-based plugin). Routes defined in src/routes/.
export default defineConfig({
    plugins: [
        react(),
        tailwindcss() as unknown as PluginOption,
    ],
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
                manualChunks(id: string) {
                    if (id.includes("node_modules")) {
                        if (id.includes("echarts")) return "echarts";
                        if (id.includes("gsap") || id.includes("lenis")) return "motion-vendor";
                        if (id.includes("react") || id.includes("scheduler")) return "react";
                        if (id.includes("@tanstack")) return "router";
                    }
                },
            },
        },
    },
});
