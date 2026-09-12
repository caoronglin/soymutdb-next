import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));

/**
 * Duplicated from `apps/web/src/lib/deployment.ts` on purpose (see the admin
 * config): Vite 6 blocks a request whose Host is not allowlisted, and CNB serves
 * every preview port through a generated `*.cnb.space` host.
 */
const CNB_DEV_HOST_SUFFIXES = [".cnb.space", ".cnb.run"];
const CNB_DEV_HOSTS = ["cnb.space", "cnb.run", "localhost", "127.0.0.1", "[::1]"];

function normalizeDevHost(entry: string): string {
    const value = entry.trim().replace(/^https?:\/\//i, "");
    if (!value) return "";
    return value.replace(/[/?#].*$/, "").replace(/:\d+$/, "").toLowerCase();
}

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

// JBrowse 2 standalone genome browser — port 5175.
// Tailwind v4 is wired via postcss.config.mjs (not as a Vite plugin).
export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, __dirname, "");
    const apiProxyTarget = env.VITE_API_BASE_URL?.trim() || "http://localhost:8000";

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
            allowedHosts: resolveDevAllowedHosts(env.SOYMUTDB_DEV_ALLOWED_HOSTS),
            proxy: {
                "/api": {
                    target: apiProxyTarget,
                    changeOrigin: true,
                },
                "/jbrowse-data": {
                    target: apiProxyTarget,
                    changeOrigin: true,
                },
            },
        },
        preview: {
            port: 5175,
            host: "0.0.0.0",
            allowedHosts: resolveDevAllowedHosts(env.SOYMUTDB_DEV_ALLOWED_HOSTS),
        },
        build: {
            target: "es2022",
            outDir: "dist",
            sourcemap: false,
        },
    };
});
