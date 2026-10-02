# Ant Design 6 final smoke record

> **已归档（2026-10-01）**：一次性的基础模式验收战役记录（操作手册仍在 ops/）。继任：`docs/ops/README.md` 及其下的现行运维手册；部署事实见 `docs/dev/project-status.md`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

Date: 2026-08-25

## Runtime/library audit

- `apps/admin/src/lib/admin-ui.tsx`: deleted.
- `packages/ui`: deleted; no app imports `@soymutdb/ui`.
- `apps/admin/src` and `apps/web/src`: no `lucide-react`, `admin-ui`, Radix, Headless UI, Mantine, Chakra, or `@soymutdb/ui` references.
- Ant Design workspace catalog: `6.6.1`.
- Web/Admin use explicit `@/lib/antd` facades; native semantic table elements remain only where they are the correct semantic primitive.

## Smoke commands/results

- Web TypeScript: `./node_modules/.bin/tsc --noEmit -p apps/web/tsconfig.json` — **PASS**.
- Home PageDefinition binding: `apps/web/src/routes/__tests__/home-page-definition-binding.test.tsx`, 2 tests — **PASS**.
- Admin TypeScript: `./node_modules/.bin/tsc --noEmit -p apps/admin/tsconfig.json` — **PASS**.
- Admin Vitest: 20 files / 56 tests — **PASS**.
- Admin ESLint: 0 errors, 18 existing warnings — **PASS**.
- Demo UI build with explicit API/JBrowse test origins — **PASS** (Vite build 16.80s).
- `git diff --check` — **PASS**.

## Website visual verification

- Command: `cd e2e && npm run test:visual`.
- Evidence: `e2e/visual-artifacts/20260825T011833Z/report.json` and 15 PNG screenshots.
- Routes: `/`, `/search/genes`, `/search/location`, `/search/gbrowse`, `/blast`.
- Viewports: 1440x900, 1024x768, 390x844.
- Result: **15/15 passed**, no page-level horizontal overflow, main content/headings visible, body non-empty, `undersized=0` for every metric.
- Layout order verified: independent Hero/search block → latest news + carousel → search tools/resource guide.

This record proves frontend smoke/layout quality only. It does not turn the Demo build into production, and does not prove real Wm82 data, external JBrowse availability, write authorization, or production DNS/staging evidence.
