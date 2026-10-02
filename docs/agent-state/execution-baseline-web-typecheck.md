# Web Typecheck Baseline & Resolution (Phase 4 + t6 follow-up)

> **已归档（2026-10-01）**：智能体执行日志与提示词草稿（治理要求工作区不存放日志）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §7 变更记录；执行结论见 docs/dev/project-status.md。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

Recorded by ui-frontend (tasks t2, t6).

Command: `apps/web/node_modules/.bin/tsc -p apps/web/tsconfig.json --noEmit`

## t2 (Phase 4) result: 13 pre-existing errors

Handwritten api-client ↔ web-UI mismatches (not contract-generated):
- blast.tsx (2): `getBlastJobs`/`getBlastHits` wrong params.
- genes/index.tsx (2): `GeneSearchParams`/`GeneSearchResponse` lacked page contract.
- login.tsx (1): `RouterState` cast.
- search.tsx (5): `FederatedSearchResponse` not exported from api-client.
- search/genes.tsx (1): `.total` missing.
- variants/index.tsx (2): page/total vs cursor contract.

## t6 (follow-up) result: 0 errors ✅

Fix strategy — align the handwritten `packages/api-client` types to the real
backend contract (the generated `openapi.d.ts` / FastAPI response models), then
reconcile web callers:

1. **`search.ts`**: exported `FederatedSearchResponse` + `FederatedSource` +
   `FederatedHit` (matches backend `_external_json_payload`); `globalSearch`
   now returns `SearchResponse | FederatedSearchResponse`.
2. **`genes.ts`**: `GeneSearchResponse` now `{ items, next_cursor, has_more,
   page, page_size, total, total_pages }`; `GeneSearchParams` gained
   `page`/`page_size` (backend `GeneListResponse`/`GeneListParams` are
   page-capable). No web change needed — `genes/index.tsx` and
   `search/genes.tsx` already used the page contract.
3. **`blast.ts`**: `getBlastJobs({ page, page_size, status })` →
   `{ items, total, page, page_size }`; `getBlastHits({ limit, offset })` →
   `{ items, total }`. Updated `blast.tsx` (`page_size:100`→`limit:100`/`offset:0`)
   and `blast.test.ts` to the implemented contract.
4. **`variants/index.tsx`**: converted to cursor pagination (`cursor`/`limit`,
   `next_cursor`/`has_more`, `total_count`) since the backend
   `VariantListResponse` is cursor-only (no page/total). Replaced the antd
   page-number pagination with Prev/Next cursor buttons + optional total count.
5. **`login.tsx`**: cast through `unknown` (`as unknown as { redirect?: unknown }`).
6. i18n: added `variants.totalCount` (en/zh).

## Verification
- apps/web `tsc --noEmit`: exit 0 (13 → 0 errors).
- apps/web vitest: 46/46 pass.
- packages/api-client vitest: 76/76 pass.
- packages/api-client tsc: no new errors in modified files (pre-existing
  test-file `vi`/`describe` global + `client.ts` import.meta.env + expression
  enum debts remain, unrelated to this work).
- apps/web `vite build`: succeeds.
- No backend files changed. Behavior preserved (page UI for genes/jobs; cursor
  for variants which the backend requires).
