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
);
