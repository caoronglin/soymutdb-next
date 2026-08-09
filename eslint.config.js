// SoyMutDB Next — shared ESLint flat config (ESLint 10).
// Single root config: every workspace package resolves this file via
// ESLint's upward eslint.config.js lookup, so apps/* and packages/*
// share one ruleset.
import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";

export default tseslint.config(
    {
        ignores: [
            "**/node_modules/**",
            "**/dist/**",
            "**/.turbo/**",
            "**/coverage/**",
            "**/public/**",
            "**/*.gen.ts",
            "**/src-tauri/**",
            "apps/api/**",
            "apps/worker/**",
            "apps/core-rs/**",
            "deploy/**",
            "infra/**",
            "artifacts/**",
            "reports/**",
            "tools/**",
        ],
    },
    js.configs.recommended,
    ...tseslint.configs.recommended,
    {
        files: ["**/*.{ts,tsx,mts,cts}"],
        languageOptions: {
            globals: {
                ...globals.browser,
                ...globals.node,
            },
        },
        plugins: {
            "react-hooks": reactHooks,
        },
        rules: {
            ...reactHooks.configs.recommended.rules,
            // react-hooks v7 compiler-era rules: great signal for new code,
            // too strict as errors for this existing codebase (would force
            // large refactors). Kept as warnings so they stay visible.
            "react-hooks/set-state-in-effect": "warn",
            "react-hooks/refs": "warn",
            "@typescript-eslint/no-unused-vars": [
                "error",
                {
                    argsIgnorePattern: "^_",
                    varsIgnorePattern: "^_",
                    caughtErrorsIgnorePattern: "^_",
                },
            ],
            // API-layer code legitimately uses `any` at trust boundaries.
            "@typescript-eslint/no-explicit-any": "warn",
            "no-empty": ["error", { allowEmptyCatch: true }],
        },
    },
    {
        // Paths owned by parallel workstreams (api client internals, motion
        // package, web src/lib): their lint debt is reported but not fixed
        // here, so demote to warnings instead of blocking the pipeline.
        files: ["apps/web/src/lib/**", "packages/motion/**"],
        rules: {
            "@typescript-eslint/no-unused-vars": "warn",
        },
    },
    {
        // ------------------------------------------------------------------
        // B2 — packages/ui 退役令（2026-08-09，见 docs/design/upgrade-plan.md §二）：
        // apps/web/src 下「新文件」禁止 import @soymutdb/ui（packages/ui 原地
        // 冻结，不删源码，逐路由迁移到 AntD 后删除引用）。
        // 现有文件通过下方 files 清单豁免（冻结时点已存在的引用）。
        // 迁移完成一个文件后，从下方清单删除对应条目，让门禁继续收口。
        // ------------------------------------------------------------------
        files: ["apps/web/src/**/*.{ts,tsx}"],
        rules: {
            "no-restricted-imports": [
                "error",
                {
                    paths: [
                        {
                            name: "@soymutdb/ui",
                            message:
                                "packages/ui 已冻结退役（upgrade-plan.md §二）。新代码请改用 AntD 5；迁移后从 eslint.config.js 豁免清单移除该文件。",
                        },
                    ],
                },
            ],
        },
    },
    {
        // packages/ui 退役豁免清单（2026-08-09 冻结时点已存在、仍引用
        // @soymutdb/ui 的 apps/web 文件）。逐路由迁移后删除条目。
        files: [
            "apps/web/src/main.tsx",
            "apps/web/src/lib/format.ts",
            "apps/web/src/lib/analyses-upload.ts",
            "apps/web/src/components/site-header.tsx",
            "apps/web/src/components/error-boundary.tsx",
            "apps/web/src/components/chromosome-hero.tsx",
            "apps/web/src/components/stat-card.tsx",
            "apps/web/src/components/genome-browser-widget.tsx",
            "apps/web/src/components/track-viewer.tsx",
            "apps/web/src/components/animation-control.tsx",
            "apps/web/src/components/data-table.tsx",
            "apps/web/src/components/command-palette.tsx",
            "apps/web/src/components/analyses/upload-dropzone.tsx",
            "apps/web/src/components/analyses/researcher-gate.tsx",
            "apps/web/src/components/charts/expression-heatmap.tsx",
            "apps/web/src/components/charts/variant-type-chart.tsx",
            "apps/web/src/components/charts/expression-bar-chart.tsx",
            "apps/web/src/components/charts/impact-distribution.tsx",
            "apps/web/src/components/charts/chromosome-density-chart.tsx",
            "apps/web/src/components/charts/release-trend.tsx",
            "apps/web/src/routes/index.tsx",
            "apps/web/src/routes/analytics.tsx",
            "apps/web/src/routes/browser.tsx",
            "apps/web/src/routes/compare.tsx",
            "apps/web/src/routes/downloads.tsx",
            "apps/web/src/routes/guide.tsx",
            "apps/web/src/routes/help.tsx",
            "apps/web/src/routes/login.tsx",
            "apps/web/src/routes/publications.tsx",
            "apps/web/src/routes/search.tsx",
            "apps/web/src/routes/sra.tsx",
            "apps/web/src/routes/tools/index.tsx",
            "apps/web/src/routes/tools/seqfetch.tsx",
            "apps/web/src/routes/tools/enrichment.tsx",
            "apps/web/src/routes/tools/exppattern.tsx",
            "apps/web/src/routes/analyses/index.tsx",
            "apps/web/src/routes/analyses/fastp.tsx",
            "apps/web/src/routes/analyses/scanpy.tsx",
            "apps/web/src/routes/analyses/$jobId.tsx",
        ],
        rules: {
            "no-restricted-imports": "off",
        },
    },
);
