# News recycle bin and administrator purge — design draft

## Decision scope
This slice adds an administrator-only recycle-bin list, recovery action, and immediate permanent purge for already soft-deleted NewsArticle rows. The human direction selected immediate administrator purge. Existing audit logs are retained as immutable operational records; only allow-listed lifecycle metadata is ever written.

## Product boundary
- Existing DELETE /api/v1/admin/news/{id} remains a content-editor soft delete returning 204.
- Administrators may list deleted rows, restore a row, or permanently purge a row.
- A purge is irreversible: the UI requires a second confirmation and exact slug entry; the API remains the authorization authority.
- Restore remains administrator-only. A content editor who moved an article to the trash cannot restore it unless separately granted administrator.

## API contract
### GET /api/v1/admin/news/deleted
- Administrator-only.
- page (>=1) and page_size (1..100); optional title search/category/status filters only if implemented consistently with the active list.
- Sort: deleted_at DESC, id DESC.
- Response: items, total, page, page_size with a new DeletedNewsSummary projection: id, title_en, title_zh, slug, category, status, published_at, created_at, updated_at, deleted_at.
- Never return rich HTML, public/preview URL, preview token, media URL, provenance platform/URL/hash/timestamps, or deleted_by identity.

### DELETE /api/v1/admin/news/{news_id}/purge
- Administrator-only, returns 204.
- Requires the target to already be soft-deleted; an active/missing row returns the existing not-found shape.
- Writes a news_purged AuditLog entry with article id and slug, then deletes the article in the same transaction, commits, then best-effort invalidates news/snapshot cache aliases.
- It does not delete MediaAsset objects because cover assets can be shared. It releases the slug and external source URL unique-index claim with the NewsArticle row.

## Service and persistence boundary
- Add a dedicated deleted-news list method; do not add an include_deleted switch to the normal admin list, which must retain its non-deleted invariant.
- Add a dedicated purge method that queries deleted rows explicitly. Audit metadata contains only lifecycle and slug; never persist title body, source hash, preview token, credentials, or request headers.
- No new persistence table or migration is needed: deleted_at/deleted_by and AuditLog already exist.
- No attempt is made to purge or rewrite old audit logs. Audit resource_id is a string rather than a NewsArticle foreign key and stays historically meaningful after purge.

## Admin UI
- Add static /news/trash before /news/$id.
- Page shows a metadata-only Ant Design table and pagination plus Back to news. There is no edit, preview, reorder, rich-content excerpt, or public link.
- Add a Trash entry point on the active news list. Client-side visibility may improve usability but cannot authorize; API 401/403 states stay explicit.
- Restore uses a confirmation modal. Purge is a destructive modal requiring the exact slug, states irreversibility, and offers no bulk action.
- Update current delete copy from cannot be undone to move to trash; explain recovery is administrator-only.

## Typed client and delivery
- Add typed wrappers for listDeletedAdminNews, restoreNews, and purgeNews; update the existing DELETE comment to soft delete.
- Synchronize OpenAPI/API-client artifacts only through the repository’s existing canonical generation workflow; do not hand-edit generated output.

## Compatibility and non-goals
- No change to default GET /admin/news, public/legacy news reads, preview-token behavior, external provenance, news status/window semantics, or soft-delete migration.
- No bulk purge, retention scheduler, audit erasure, asset garbage collection, versioning, scheduling, or React Query migration.
- Permanent purge is intentional live-state deletion; no production destructive command is executed as part of this implementation.

## Acceptance evidence
1. Content editors receive 403 for trash list, restore, and purge; administrator calls succeed only as appropriate.
2. Trash pagination contains only deleted rows and never serializes protected fields.
3. Restore removes the row from trash and emits lifecycle audit; purge removes it from all lists, preserves only news_purged audit metadata, and releases its slug/source URL row constraint.
4. Active soft-delete behavior remains 204 and public/legacy/snapshot reads remain unchanged.
5. UI cannot render body/preview data in trash, confirms restore/purge, requires exact slug for purge, and refreshes after action.
6. Focused API/client/admin tests plus typecheck/lint/build pass; live PostgreSQL remains a separate verification requirement.
