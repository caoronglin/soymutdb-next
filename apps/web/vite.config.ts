import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));

// Public portal — served on port 5173 in dev.
// Manual TanStack Router (no file-based plugin). Routes defined in src/routes/.
// Tailwind v4 is wired via postcss.config.mjs (not as a Vite plugin).
export default defineConfig({
    plugins: [react()],
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
});
