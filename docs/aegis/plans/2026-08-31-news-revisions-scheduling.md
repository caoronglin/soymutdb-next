# News revisions and Beijing-time scheduling implementation plan

## Basis and readiness
- Approved design: `docs/aegis/work/2026-08-31-soymutdb-optimization/70-news-revisions-scheduling-design.md`.
- Baseline owners: `apps/api/app/models/content.py`, `services/news_service.py`, `api/v1/admin_news.py`, `schemas/news.py`, `models/outbox.py`, `services/outbox_service.py`, and `packages/api-client/src/admin-news.ts`.
- Compatibility: preserve public reads, source-preview attestation, soft delete, retained audits, and post-commit cache invalidation. Existing writes remain compatible only through an explicit transition policy; never silently last-write-wins.
- Change necessity: persistence, API contract, worker fencing, and UI state are required to prevent edit loss and make scheduled publication durable. Decision: code-change.
- Existence: reuse the established content model, NewsService, AuditLog, snapshot cache and outbox lease patterns; add revision/schedule models because none is an existing canonical owner. Decision: add-with-proof.

## TDD Route
- Mode: auto
- Decision: strict
- Strict authority: recorded auto decision
- Strict signals: shared service, persistence, migration, public admin contract, permission, worker producer/consumer and meaningful regressions.
- Test posture: strict RED test, GREEN implementation, focused regression.

## Task 1 — Model and migration foundation
Files: `apps/api/app/models/content.py`, `apps/api/app/models/__init__.py`, `apps/api/migrations/versions/0031_news_revisions_scheduling.py`, migration tests.
1. RED: test migration order/rerun and model constraints.
2. Add article lock version and schedule-generation fence; add append-only revision and schedule tables/state enum, indexes, FK/unique/check constraints.
3. Backfill one initial sanitized revision per existing article; initialize lock version/fence; reject unsafe downgrade when revisions/schedules exist.
4. GREEN: run focused migration/model tests, Ruff and diff check.

## Task 2 — Transactional revision and optimistic concurrency owner
Files: `services/news_service.py`, `schemas/news.py`, `api/v1/admin_news.py`, `tests/test_news_api.py`, new revision tests.
1. RED: stale update/delete/restore/reorder tests return stable 409; create/update/lifecycle mutations append exactly one revision atomically.
2. Implement expected-lock-version schema/header contract, safe conflict response metadata, and canonical helper that appends sanitized revision plus increments lock version in the same transaction as projection/audit mutation.
3. Require all mutation paths to use the helper; preserve source-preview rules and post-commit invalidation.
4. GREEN: focused API/revision/cache suite and scoped static checks.

## Task 3 — Durable schedule state machine and lease worker
Files: new `services/news_schedule_service.py`, `models/content.py`, `services/outbox_service.py` only if dispatch reuse is needed, worker/task owner discovered from existing jobs, new schedule tests.
1. RED: schedule creation, conditional claim, generation fencing, cancel/reschedule/manual-publish supersession, missed/no-catch-up, deleted/stale terminalization, bounded transient retry.
2. Implement UTC/IANA/local-time validation, idempotent schedule command owner, lease claim/finalize logic, retry classification, metrics and audit metadata.
3. Publish only through conditional projection update requiring matching lock version/generation/state/not-deleted; append revision/audit transactionally, invalidate cache post-commit.
4. GREEN: focused worker/state-machine tests; PostgreSQL integration where environment permits.

## Task 4 — Admin API and typed client
Files: `api/v1/admin_news.py`, `schemas/news.py`, `packages/api-client/src/admin-news.ts`, client/API tests.
1. RED: schedule create/cancel/reschedule/list, revision history, 409 payload, role restrictions, idempotency behavior.
2. Add admin-only revision history and schedule endpoints before dynamic routes; metadata-only schedule list and revision authorization.
3. Add typed client wrappers and conflict/schedule types; do not expose revision bodies in trash/public endpoints.
4. GREEN: API/client test and type-check evidence.

## Task 5 — Admin UX and locale
Files: news edit route/components, new revision/schedule components only if existing route is unsuitable, `App.tsx` route wiring if needed, locales and UI tests.
1. RED: 409 reload/manual-merge prompt, Beijing-time labeling, missed/canceled/superseded states, schedule invalidation on manual publish, revision access absence for non-admin UI.
2. Implement schedule controls and revision history with exact state explanation. No automatic rich-text merge or browser timer.
3. GREEN: focused Vitest, locale parity and scoped diff checks.

## Task 6 — Migration/runtime/review evidence
1. Run focused API, migration, cache, worker, client and UI suites.
2. Use disposable PostgreSQL under /tmp to verify upgrade/rerun/backfill/downgrade fences; do not touch project/production data.
3. Independent spec and quality review; update checkpoint/evidence with any CI-only frontend limitation.

## Risks and retirement
- No legacy writes may bypass lock version after the explicit compatibility window; remove transitional path once client rollout evidence exists.
- No in-memory timers, direct Celery ETA, browser scheduler, or stale worker may publish content.
- A legal redaction path, tenancy expansion, DST zone preferences, and external schedule distribution are intentionally deferred.
