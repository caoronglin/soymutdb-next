# Administrator news recycle bin and permanent purge

## Goal
Implement the approved administrator recycle bin for soft-deleted news and immediate permanent purge while preserving a bounded immutable audit record. The existing news DELETE operation remains a content-editor soft delete and response-compatible 204.

## Architecture
The canonical authority remains NewsService plus PostgreSQL. A dedicated deleted-list service method and metadata-only schema prevent an ordinary admin list or detail/preview path from exposing deleted article bodies or provenance. The admin API is the authorization authority; the UI only improves discoverability and confirmation. A purge writes the immutable lifecycle audit record and deletes the NewsArticle in the same transaction, then invalidates caches after commit.

## Tech stack
FastAPI + SQLAlchemy async + Pydantic v2; PostgreSQL in production; React 19 + Ant Design v6 + TanStack Router; typed workspace API client; i18next locale JSON.

## Baseline / authority references
- Approved product design: docs/aegis/work/2026-08-31-soymutdb-optimization/50-news-recycle-bin-and-purge-design.md.
- Existing soft-delete/audit design: docs/aegis/work/2026-08-31-soymutdb-optimization/30-news-lifecycle-soft-delete-design.md.
- Existing lifecycle execution record: docs/aegis/work/2026-08-31-soymutdb-optimization/40-news-soft-delete-plan.md.
- Current owners: apps/api/app/services/news_service.py, apps/api/app/api/v1/admin_news.py, apps/api/app/schemas/news.py, packages/api-client/src/admin-news.ts, apps/admin/src/routes/news/index.tsx, apps/admin/src/App.tsx.

BaselineUsageDraft:
- Required baseline refs: approved recycle-bin design and current soft-delete service/API/schema owners.
- Cited in plan refs: all listed above.
- Missing refs: live PostgreSQL remains unavailable; use focused fake-session and offline contracts now, retain live validation as follow-up.
- Decision: continue.

## Compatibility boundary
- GET /api/v1/admin/news continues to exclude deleted rows and its client response remains unchanged.
- DELETE /api/v1/admin/news/{id} remains soft delete for content editors and returns 204.
- Restore and the new deleted-list/purge operations are administrator-only.
- Deleted-list responses must never serialize HTML, preview token/URL, cover/media URL, source platform/URL/hash/timestamps, or deleted_by identity.
- Public, legacy, snapshot, featured, reorder, and preview-token exclusions remain unchanged.
- No migration, retention scheduler, bulk purge, media garbage collection, audit erasure, external-source change, or automatic publication belongs to this slice.

## TDD Route
- Mode: auto.
- Decision: strict.
- Strict authority: recorded auto decision.
- Strict signals: permission boundary, destructive live-state API, transactional audit, service/API/client contract, and meaningful regression risk.
- Light eligibility: not eligible.
- Test posture: strict RED test for each backend/UI behavior before its production implementation; the existing test harness may use focused fakes where live PostgreSQL is unavailable.
- Verification: focused API/service tests, client/admin type checks or tests when package dependencies are available, locale key parity, scoped Ruff, diff check, and manual/live PostgreSQL evidence deferred until an environment is supplied.

## Requirement Ready Check
- Requirement source refs: direct approval “批准回收站设计，保留审计记录” and approved design document.
- Goals and scope refs: this plan’s goal/boundary and the soft-delete design.
- User/scenario refs: administrator lists trash, restores an item, or permanently purges an already-deleted item after exact-slug confirmation.
- Acceptance refs: design document acceptance evidence items 1–6.
- Open blocker questions: none for implementation; live PostgreSQL validation remains an infrastructure follow-up.
- Decision: ready.

## Change Necessity
- User-visible need: administrators need safe recovery and explicit irreversible removal of deleted news.
- No-change option: existing restore exists but no deleted-row discovery UI/API and no administrator purge.
- Why code change is necessary: hidden soft-deleted rows cannot be enumerated/recovered operationally, and safe purge needs a server-authorized transactional owner.
- Minimum boundary: news schemas/service/admin router, typed client, static admin route, localized UI copy and focused tests.
- Decision: code-change.

## Existence and architecture checks
Existence Check:
- Proposed new surfaces: DeletedNewsSummary schema, dedicated service list method, static trash route.
- Existing reuse candidates: NewsSummaryResponse, list_articles_admin, /news/$id detail route.
- Why insufficient: the normal summary exposes a cover URL and the normal list is explicitly non-deleted; detail route performs preview-token/public-detail behavior prohibited for trash.
- Creation proof: metadata-only response and static route enforce the approved no-body/no-preview boundary.
- Entropy impact: no duplicate active-list owner; deleted listing is separate by authority and projection.
- Decision: add-with-proof.

Architecture Integrity Lens:
- Invariant: normal reads never gain deleted content; purge can only delete a previously soft-deleted row and preserves audit history.
- Canonical owner: NewsService owns persistence/transaction/cache ordering; admin router owns RBAC and HTTP status; typed client owns browser transport.
- Responsibility overlap: do not place purge logic in UI or let normal list receive include_deleted.
- Higher-level simplification: reuse existing log_action and cache invalidator rather than new audit/cache owners.
- Verdict: proceed with dedicated service projection and static route.

Complexity Budget:
- Target owners: NewsService, news schemas, admin news router, API client, one new admin route.
- Current pressure: NewsService is broad but already owns deletion/restore; adding purge adjacent to those lifecycle methods is lower entropy than a second lifecycle service.
- Projected pressure: within-budget when list/purge methods stay small and metadata projection lives in schema.
- Planned governance: do not add an include_deleted flag to the normal admin list; no generated OpenAPI edits by hand.

## Execution Readiness View
- Intent Lock: deliver only administrator trash list, restore, individual immediate purge, retained bounded audit, and exact-slug UI confirmation.
- Scope Fence: no bulk action, schedule, versions, asset cleanup, audit erasure, desktop runtime, or normal-list behavior change.
- Baseline Lock: existing soft delete/restore/cache/RBAC boundaries remain authoritative.
- Compatibility Boundary: ordinary list and public paths stay non-deleted; DELETE remains 204 soft delete.
- Retirement Boundary: no active production owner is removed; the stale UI wording is already corrected.
- Test Obligations: negative RBAC/projection/purge-active tests, transaction/audit/cache tests, route ordering, restore/purge UI flows, client contract, translations.
- Review Gates: independent review after backend contract then after UI/client integration.
- Drift / Rewind Rules: stop if a change needs body/provenance in trash, reuses /news/$id, requires a migration, deletes MediaAsset/AuditLog, or broadens editor permissions.
- Evidence Required: focused test output, type/lint output where dependencies permit, and explicit live-PostgreSQL limitation.

## Task 1 — Add backend metadata-only deleted-list contract
Files:
- Modify apps/api/app/schemas/news.py.
- Modify apps/api/app/services/news_service.py.
- Modify apps/api/app/api/v1/admin_news.py.
- Modify apps/api/tests/test_news_api.py.

Why: administrators need a paginated recycle bin without exposing deleted-body or provenance data.

Impact / compatibility: leave NewsListResponse and list_articles_admin unchanged. Add DeletedNewsSummaryResponse with exactly id, title_en, title_zh, slug, category, status, published_at, created_at, updated_at, deleted_at. It must not inherit NewsSummaryResponse because that would expose cover fields and would invite later projection drift.

Steps:
1. In test_news_api.py, add administrator success, content-editor 403, and metadata allowlist assertions for GET /admin/news/deleted. Assert deleted rows are ordered deleted_at DESC then id DESC, pagination is bounded at 1..100, and no body, cover, source, preview, or deleted_by key appears.
2. Verify RED with the focused GET deleted-list tests.
3. Add DeletedNewsSummaryResponse and DeletedNewsListResponse in schemas/news.py; use from_attributes and id coercion like the active summary, but declare only the approved metadata fields.
4. Add NewsService.list_deleted_articles_admin(db, page, page_size). It selects only deleted_at IS NOT NULL, counts from that same predicate, orders deleted_at.desc(), id.desc(), and creates the dedicated schema projection.
5. Add GET /deleted before every dynamic /{news_id} route in admin_news.py. Call _require_administrator, pass bounded pagination values, and return DeletedNewsListResponse.
6. Verify GREEN with focused API tests plus existing normal-list deletion-filter regressions.

## Task 2 — Add administrator-only transactional purge
Files:
- Modify apps/api/app/services/news_service.py.
- Modify apps/api/app/api/v1/admin_news.py.
- Modify apps/api/tests/test_news_api.py.
- Modify apps/api/tests/test_news_cache_invalidation.py if existing cache fake needs explicit purge coverage.

Why: approved operators need immediate irreversible removal without losing the lifecycle audit record.

Impact / compatibility: only a soft-deleted NewsArticle can be purged; missing and active rows use the existing not-found shape. MediaAsset rows, AuditLog rows, and unrelated external data are never deleted. Slug and source URL become available only because the NewsArticle row itself is deleted.

Steps:
1. In test_news_api.py, write failing cases for content-editor 403, administrator active/missing 404, administrator deleted success 204, retained news_purged audit metadata, and no body/source/hash in audit metadata.
2. Add a service purge_article(db, news_id, actor_id) adjacent to restore_article. Select a deleted row explicitly, preferably with row locking; reject an active/missing row with NotFoundError. Capture id and slug before deletion.
3. Call log_action with action news_purged, resource_type news_article, resource_id string id, and only lifecycle + slug old/new values. Delete only the NewsArticle object, commit once, then call _invalidate_public_news_caches after the successful commit.
4. Add DELETE /{news_id}/purge in admin_news.py after restore. Require _require_administrator and return 204.
5. Verify GREEN against focused API/cache tests. Assert a subsequent deleted list no longer contains the row and ordinary list/public behavior remains non-deleted.

## Task 3 — Add typed client contracts
Files:
- Modify packages/api-client/src/admin-news.ts.
- Modify or create focused API-client tests only if the package already has the appropriate test pattern.

Why: the browser must call the new server contracts through the standard authenticated http owner.

Impact / compatibility: retain listAdminNews and deleteNews semantics. Define DeletedAdminNewsItem/DeletedAdminNewsListResponse only with metadata fields. Add listDeletedAdminNews(params), restoreNews(id), purgeNews(id); preserve no body/provenance types in the deleted type.

Steps:
1. Add type-level/client test or compile assertion that deleted-list output excludes disallowed fields and endpoints/methods are exact.
2. Implement wrappers using http.get, http.post, and http.delete. Restore returns AdminNewsDetail; purge resolves void.
3. Update top-of-file API contract comments to document deleted list, restore, and purge accurately.
4. Run package typecheck when pnpm is operational; otherwise record the known pnpm store limitation and use static/source checks only.

## Task 4 — Build static administrator recycle-bin UI
Files:
- Create apps/admin/src/routes/news/trash.tsx.
- Modify apps/admin/src/App.tsx.
- Modify apps/admin/src/routes/news/index.tsx.
- Optionally modify apps/admin/src/components/admin-sidebar.tsx only if a persistent navigation entry is added.
- Modify both packages/i18n/src/locales/*/common.json.
- Add or modify apps/admin/src/routes/news/*.test.tsx following existing news-list patterns.

Why: administrators need discoverable restore and irreversible purge flows without accidentally rendering deleted content.

Impact / compatibility: /news/trash must be a static route registered before /news/$id. Never navigate trash rows to /news/$id. The normal news list gets a Trash entry point but retains its active behavior.

Steps:
1. Write failing UI tests for loading metadata-only rows, restore confirmation/request/refresh, and purge modal rejection until the exact slug is typed; assert no preview or edit action exists.
2. Implement TrashPage with an Ant Design metadata table, pagination, loading/error/empty states, Back to News control, and an explicit normal-list Trash entry point.
3. Restore uses a confirmation modal, invokes restoreNews, then reloads.
4. Purge uses a danger modal with exact-slug input. Disable confirmation until the input equals the row slug, invoke purgeNews only then, reload on success, and display explicit error messages.
5. Add static lazy route in App.tsx before newsEditRoute. Do not reuse getAdminNewsDetail or preview token logic.
6. Add matching English/Chinese keys for trash labels, deleted timestamp, restore states, purge explanation, exact-slug validation, and success/failure messages. Update existing delete success wording to say moved to trash if still stale.
7. Verify focused UI tests/typecheck if dependencies are restored, locale key parity, and route source/order assertions.

## Task 5 — Review and release evidence
Files:
- Modify docs/aegis/work/2026-08-31-soymutdb-optimization/20-checkpoint.md.
- Modify docs/aegis/work/2026-08-31-soymutdb-optimization/90-evidence.md.

Why: preserve approval, boundary, tests, residual environment limitation, and no-live-state execution evidence for the next operator.

Steps:
1. Run focused API lifecycle/cache/deleted-list/purge suite and scoped Ruff/diff checks.
2. Run client/admin checks available in the environment. If pnpm still cannot open its store database, record the command and failure without claiming a frontend test pass.
3. Request independent code review specifically for RBAC, metadata projection, transactional audit/delete ordering, cache invalidation, route ordering, exact-slug confirmation, and accidental preview/body exposure.
4. Record the exact outputs and unresolved live PostgreSQL requirements. Do not create a task commit because the user did not request a commit and the worktree contains unrelated dirty changes.

## Risks and rollback
- Purge is irreversible only for the NewsArticle row. The retained AuditLog is the rollback/audit boundary; no audit erasure is authorized.
- A failed transaction must not leave a news_purged audit event without the article deletion; use one session transaction and commit once.
- Cache invalidation remains best effort and post-commit only.
- Restore can encounter a uniqueness conflict only if another article claims its reserved identifiers; current soft-delete behavior keeps rows in place, so normal restore remains safe. If a future purge releases identifiers, restoring that purged record is intentionally impossible because it no longer exists.
- Live PostgreSQL still must verify 0030 and this purge behavior before production rollout. The current host has no docker or psql.

## Retirement
- Old path: ordinary list include_deleted parameter or deleted detail/preview reuse.
- Decision: do not add either path.
- Preserved capability: normal list and active edit/preview behavior.
- Retired behavior: none at runtime; only stale delete wording has already been corrected.

## Execution route
- Decision: subagent-driven.
- Evidence: backend contract/purge and frontend/client UI have independent bounded ownership after Task 1’s schema contract, and review value is high.
- Fallback: inline implementation if the dirty worktree creates an overlap or a subagent cannot be isolated.
- User confirmation required: no; user explicitly approved retained-audit purge.
