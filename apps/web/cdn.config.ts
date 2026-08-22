/**
 * CDN configuration — optional external loading for ECharts.
 *
 * When VITE_CDN_ENABLED=true, these libraries are loaded from CDN script
 * tags instead of bundled. Falls back to bundled when disabled or when
 * CDN URLs are not provided. This supports restricted-network deployments
 * (e.g. air-gapped research clusters) where CDN may be unreachable.
 *
 * Env vars (read from .env files via Vite's loadEnv):
 *   VITE_CDN_ENABLED=true|false  (default: false — bundled)
 *   VITE_ECHARTS_CDN=<url>       (e.g. https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js)
 */

export interface CdnConfig {
    enabled: boolean;
    /** Packages to mark as external in rollupOptions. */
    external: string[];
    /** Global variable names for external packages. */
    globals: Record<string, string>;
    /** CDN script tags to inject into index.html. */
    scripts: Array<{ url: string; global: string }>;
}

/**
 * Resolve CDN config from Vite env vars (obtained via loadEnv).
 * Pass the env object returned by `loadEnv(mode, envDir, 'VITE_')`.
 */
export function resolveCdnConfig(env: Record<string, string> = {}): CdnConfig {
    const enabled = env.VITE_CDN_ENABLED === "true" || env.VITE_CDN_ENABLED === "1";

    if (!enabled) {
        return { enabled: false, external: [], globals: {}, scripts: [] };
    }

    const external: string[] = [];
    const globals: Record<string, string> = {};
    const scripts: Array<{ url: string; global: string }> = [];

    const echartsCdn = env.VITE_ECHARTS_CDN;
    if (echartsCdn) {
        external.push("echarts");
        globals["echarts"] = "echarts";
        scripts.push({ url: echartsCdn, global: "echarts" });
    }

    return { enabled: true, external, globals, scripts };
}

/**
 * Vite plugin that injects CDN script tags into index.html when CDN is enabled.
 * Must be used with the CdnConfig from resolveCdnConfig().
 */
export function cdnScriptInjector(cdn: CdnConfig) {
    return {
        name: "cdn-script-injector",
        transformIndexHtml(html: string): string {
            if (!cdn.enabled || cdn.scripts.length === 0) return html;
            const tags = cdn.scripts
                .map((s) => `    <script src="${s.url}"></script>`)
                .join("\n");
            return html.replace("</head>", `${tags}\n  </head>`);
        },
    };
}
