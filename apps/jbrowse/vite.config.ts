import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));

// JBrowse 2 standalone genome browser — port 5175.
// Tailwind v4 is wired via postcss.config.mjs (not as a Vite plugin).
export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, __dirname, "");

    return {
        base: env.VITE_BASE_URL?.trim() || "/",
        plugins: [react()],
        resolve: {
            alias: {
                "@": resolve(__dirname, "src"),
            },
        },
        server: {
            port: 5175,
            host: "0.0.0.0",
            proxy: {
                "/api": {
                    target: "http://localhost:8000",
                    changeOrigin: true,
                },
                "/jbrowse-data": {
                    target: "http://localhost:8000",
                    changeOrigin: true,
                },
            },
        },
        build: {
            target: "es2022",
            outDir: "dist",
            sourcemap: false,
        },
    };
});
