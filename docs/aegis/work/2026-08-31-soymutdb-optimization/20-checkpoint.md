# Work checkpoint

## Todo checkpoint
- Completed: secure signed external-article preview provenance; legacy public-news visibility predicate; parser/token hardening; post-commit public-news cache invalidation.
- Completed: conservative compressed/unknown file dispatch; safe new-tab links for rendered documents; DOCX fetch cancellation; chart initialization/resize cleanup and linear expression lookup maps.
- Completed: browser analysis checksums now use 4 MiB sequential slices with an incremental SHA-256 implementation; global search and autocomplete escape SQL LIKE wildcards; Compose API liveness no longer assumes curl.
- Completed: endpoint-specific external-preview fixed-window limiter. It is scoped by editor + IP, configurable, production fail-closed on Redis failure, and applied before any outbound fetch.
- Completed: mutable content snapshots now emit revalidation-only Cache-Control with ETag on both 200 and 304; migration 0029 now has a stronger rerun contract test.
- Completed: NewsArticle reversible soft deletion with allow-listed transactional audit records, administrator-only restore, public/admin/legacy/snapshot/reorder exclusions, and preview-token denial. DELETE retains its 204 response contract; deleted slugs remain reserved.
- Completed: a reusable post-commit mutable snapshot-cache owner is now used by news, StaticPage, Publication, and about-settings mutations. Settings document reads skip omitted deployment-secret and stale unregistered rows.
- Active: administrator recycle-bin UI plus immediate permanent purge design. The user selected immediate administrator purge; the design retains immutable audit records, requires exact-slug confirmation in UI, and awaits design approval before code changes.
- Pending after recycle bin: immutable news revision/concurrency design, durable scheduled publishing, and live PostgreSQL migration execution.
- Completed planning: the isolated desktop-toolbox readiness audit confirms an external, network-disabled, unauthenticated Tauri/Rust spike only; implementation remains outside this monorepo and requires named ownership, platform, signing, retention, and algorithm choices.

## Resume state
Active objective: secure, operable SoyMutDB CMS with performance and reliability improvements. Do not add desktop runtime code to this web monorepo. Preserve the public provenance boundary: browser submits only a short-lived preview token; server derives source metadata. External previews are editor-only, reviewed, draft-only, HMAC-attested, and now rate limited before network access.

## Evidence
- API: 115 tests passed for config security, rate limiting, external preview, admin/public news API, content snapshot, and provenance migration contracts.
- Snapshot/migration follow-up: 7 tests passed for ETag/cache-control behavior and 0029 rerun contract assertions.
- Static analysis: scoped Ruff checks pass for rate-limit, config, admin news, content snapshot, and their tests.
- Earlier slices: focused CMS/search/outbox suite passed 128 tests; Compose contract passed 5 tests; admin/API-client/public-web TypeScript checks completed successfully.
- Lifecycle/cache slice: 114 focused API tests passed; scoped Ruff and scoped git diff --check passed. An advisory review found and the slice fixed guarded downgrade behavior (refuse to drop deletion fields while deleted rows exist) plus invalid-index detection on rerun.
- Outbox reliability follow-up: the older 0018 offline Alembic contract now self-contains the API virtualenv/PYTHONPATH setup used by newer migration contracts. A new unlabelled terminal-delivery exhaustion counter increments only after the actual exhausted-lease transition commits, and a critical immediate alert observes a 15-minute counter increase. The focused outbox/observability suite passes 54 tests, including a commit-failure guard that proves a rolled-back settlement does not increment the counter. An independent review found the narrow implementation correct, requested that guard, and noted only the known lack of live PostgreSQL evidence. A complete API collection found and the slice repaired three stale Docker-free test expectations (retired CDN route and newly mandatory production analytics salt); their focused suite now passes 16 tests.
- Live PostgreSQL migration validation now passed on a user-approved disposable local PostgreSQL 18 cluster provisioned through mamba: 0030 upgrade/rerun, lifecycle column/index presence, empty downgrade/re-upgrade, and soft-deleted-row downgrade guard. Docker Compose runtime checks remain unavailable because Docker itself is not installed.

## Drift check
Decision: continue. The third slice implemented the approved soft-delete/audit boundary without version-table or scheduling expansion. The migration now refuses a destructive downgrade when soft-deleted rows exist and refuses to silently accept an invalid index after a partial deployment. The fourth slice narrowed the next request to an administrator recycle bin with a deliberately separate deleted-list contract; immediate purge is live-state deletion and remains design-gated. Preserve audit history, never expose deleted rich content, and do not add browser timers, direct Celery ETA, or in-memory beat scheduling.
