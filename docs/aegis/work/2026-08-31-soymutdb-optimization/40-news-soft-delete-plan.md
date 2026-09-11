# News soft deletion and audit implementation plan

## Problem and baseline
NewsArticle is hard deleted by NewsService.delete_article. Public visibility is centralized in public_news_visibility_conditions, but admin read/reorder paths and content snapshot aggregation access NewsArticle directly. AuditLog already has actor/action/resource/old_value/new_value fields. Existing DELETE response is 204; news status/is_published double-write and signed external provenance must remain unchanged.

## Compatibility boundary
- DELETE /api/v1/admin/news/{id} remains 204 for content_editor.
- Deleted slug remains reserved under the existing unique slug constraint.
- Restore is a new administrator-only endpoint; no existing payload changes.
- No raw rich HTML, HMAC token, source hash, or request header enters AuditLog JSON.
- Public, legacy, featured, snapshot, ordinary admin list/detail, and reorder all exclude deleted rows.

## TDD Route
- Mode: off
- Decision: skipped
- Strict authority: not applicable; the user did not request strict TDD.
- Test posture: focused post-change API/service/migration regressions.
- Verification: existing test suites plus added delete/restore, read filtering, audit, and migration contracts.

## Execution route
- Decision: inline sequential implementation.
- Evidence: model/migration/service/query changes share NewsArticle ownership and must be integrated in dependency order.
- Fallback: stop before worker/scheduling/versioning expansion; those are a separate design.
- User confirmation required: no; approved design keeps the existing delete contract and adds only restore.

## Task 1 — model and migration
Files:
- apps/api/app/models/content.py
- apps/api/migrations/versions/0030_news_soft_delete_audit.py
- apps/api/tests/test_news_soft_delete_migration.py (new)

Implement:
1. Add nullable deleted_at (timezone aware) and deleted_by (users.id, SET NULL) to NewsArticle, plus an index that supports deleted-at filtering.
2. Create monotonic migration 0030 from 0029. Add columns with rerun-safe guards and the index without weakening current slug/source uniqueness.
3. Downgrade drops only the new index/columns/foreign key.
4. Add static migration contract tests for revision chain, additive columns, FK action, index, and rerun guards.

Verify:
- focused migration contract test and offline Alembic SQL inspection where available.

## Task 2 — safe lifecycle service boundary
Files:
- apps/api/app/services/news_service.py
- apps/api/app/models/auth.py (import only if needed)
- apps/api/tests/test_news_api.py
- apps/api/tests/test_news_cache_invalidation.py

Implement:
1. Add a shared non-deleted predicate owned by NewsService and compose it into public_news_visibility_conditions.
2. Make _get_by_id exclude deleted rows by default; add a private include_deleted path used only by restore.
3. Replace db.delete with a soft-delete transition: set deleted_at/deleted_by, write an AuditLog action news_deleted with allow-listed state metadata, commit, then invalidate caches.
4. Add restore_article: require an explicitly deleted row, clear deletion fields, write news_restored audit metadata, commit, then invalidate caches.
5. Keep normal update/reorder/list calls unable to operate on deleted rows. Preserve external provenance and status behavior.

Verify:
- service fake-session tests cover 204-compatible deletion semantics, repeat delete 404, audit row shape without body/token/hash, and only post-commit invalidation.

## Task 3 — admin restore and authorization
Files:
- apps/api/app/api/v1/admin_news.py
- apps/api/tests/test_news_api.py
- packages/api-client/src/admin-news.ts (only if a typed client route helper exists)

Implement:
1. Add POST /api/v1/admin/news/{news_id}/restore returning NewsDetailResponse.
2. Keep DELETE content_editor-capable; gate restore with administrator role using existing role hierarchy helpers.
3. Do not expose deleted source content through ordinary list/detail endpoints.

Verify:
- unauthenticated 401, content-editor restore 403, administrator restore success, and normal deleted detail/list 404 or omitted result as defined by existing endpoint conventions.

## Task 4 — every read path and snapshot
Files:
- apps/api/app/api/v1/news.py
- apps/api/app/api/v1/content.py
- apps/api/app/services/content_snapshot_service.py
- apps/api/app/services/news_service.py
- apps/api/tests/test_legacy_content_news_visibility.py
- apps/api/tests/test_content_snapshot.py
- apps/api/tests/test_news_api.py

Implement:
1. Compose NewsService non-deleted condition into public list/detail/featured and retained legacy content routes.
2. Compose it into snapshot list/detail aggregation so deleted articles cannot leave SSG payloads.
3. Ensure ordinary admin list/detail and reorder exclude deleted rows, while restore alone requests the deleted row explicitly.
4. Do not alter visibility-window semantics; a restored article is public only if published/is_published/window conditions already permit it.

Verify:
- SQL/query contract tests assert deleted filter on public and legacy paths; snapshot test confirms deleted row exclusion; feature/list/detail regressions stay green.

## Task 5 — integrated verification and records
Files:
- docs/aegis/work/2026-08-31-soymutdb-optimization/20-checkpoint.md
- docs/aegis/work/2026-08-31-soymutdb-optimization/90-evidence.md

Run:
- PYTHONPATH=packages/jobs-py/src:apps/api:apps/api/.venv/lib/python3.14/site-packages python3 -m pytest -q targeted news, snapshot, migration, cache, and legacy suites.
- ruff check affected API/model/migration/test files.
- git diff --check scoped files.

## Stop conditions and deferred work
Stop after NewsArticle soft delete/audit/restore is verified. Do not add immutable NewsArticleVersion, expected_version, scheduling tables, beat polling, typed worker tasks, StaticPage changes, or Page Builder convergence in this plan. Those require their own approval because they add contracts, schema, and worker ownership.
