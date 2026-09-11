# News soft deletion and audit — design draft

## Decision scope
First lifecycle slice covers NewsArticle only. It provides reversible deletion and a transactional audit record. Immutable revisions, optimistic concurrency, scheduling, StaticPage convergence, and Page Builder changes are intentionally excluded.

## Compatibility contract
- Keep DELETE /admin/news/{id} response as 204.
- Keep existing slug ownership after deletion; a deleted slug is not reusable.
- Add an administrator-only restore endpoint rather than widening ordinary editor actions by default.
- Do not change existing NewsCreate/NewsUpdate payload contracts in this slice.

## Data model and migration
- Add nullable deleted_at and deleted_by to news_articles.
- Add an index suitable for deleted-at filtering; deleted rows remain under the existing slug uniqueness rule.
- Add a foreign key for deleted_by only if it matches the repository’s established user-ID deletion patterns and migration conventions.
- Do not add a version table or audit schema: use the existing AuditLog model with allow-listed metadata.

## Service behavior
- NewsService.delete_article obtains the existing article, rejects repeated delete as not found, sets deleted_at/deleted_by, writes a NewsArticle audit event, commits atomically, then invalidates public news/snapshot caches.
- NewsService.restore_article is administrator-authorized at the route boundary, clears deletion fields, writes a restoration audit event, commits atomically, and invalidates the same cache aliases.
- Audit metadata records article id, slug, lifecycle transition, actor id, and timestamps. It never records rich HTML, preview tokens, source hashes, credentials, or raw request data.

## Read behavior
Deleted articles must be excluded from all ordinary paths:
- modern public news list/detail/featured;
- retained legacy content news routes;
- content snapshot aggregation;
- normal admin list/detail/reorder paths.
A dedicated administrator restore route may address a deleted article directly. A later trash-list UX is additive and out of scope.

## Authorization
- content_editor keeps current create/update/delete capability for compatibility;
- administrator is required for restore;
- audit visibility remains controlled by existing administrator audit routes.

## Acceptance evidence
1. Delete preserves row/history and returns 204.
2. Deleted article is absent from every public, legacy, featured, snapshot, and ordinary-admin query.
3. Restore requires administrator, restores visibility according to ordinary status/window rules, and emits a second audit event.
4. Both state changes persist audit rows and invalidate caches only after commit.
5. Existing visibility/status and external-provenance tests remain green.

## Deferred risks
No schedule/worker is introduced. Publication at a time must later use a durable schedule row, frozen target version, locking, typed outbox task, and idempotent worker transition; it must not use a browser timer or direct Celery ETA.
