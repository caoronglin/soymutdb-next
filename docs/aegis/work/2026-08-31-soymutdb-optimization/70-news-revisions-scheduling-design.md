# News revisions and durable scheduling design

## Approved decisions
- Implement immutable news revisions plus optimistic concurrency and durable scheduled publishing.
- Admin scheduling UI uses Asia/Shanghai (UTC+8). Persist the execution instant in UTC plus IANA zone and entered local wall time.
- A trigger missed while no eligible worker can execute it is not auto-published; it transitions to `missed` and requires manual publish or rescheduling.
- A stale write returns HTTP 409 and requires manual merge; last-write-wins and server auto-merge are forbidden.
- Revisions are retained indefinitely and administrator-only. Purge never deletes revisions. Any legal redaction/erasure path is a separately approved future design.

## Ownership and data model
`NewsArticle` remains the authoritative live projection and gains a monotonic `lock_version` and a schedule generation/fence. `NewsArticleRevision` is append-only, tenant-scoped where tenancy exists, and contains a sanitized publication snapshot plus revision number, actor, reason, timestamp, and lifecycle metadata. It never stores preview tokens, request headers, credentials, or unverified provenance.

`NewsPublicationSchedule` is a durable, tenant-scoped job owner with article ID, expected article lock version, schedule generation, UTC execution instant, IANA timezone, submitted local time, state, lease, attempts, terminal reason, and idempotency identity. States are pending, leased, published, canceled, superseded, missed, and failed. Validation failures (deleted, canceled, stale generation/version) terminate without retry. Transient database/worker failures use bounded lease-based retries with backoff and observability.

## Transaction and fencing contract
Every article mutation atomically appends a revision, updates the projection and lock version, writes allowlisted audit data, and writes required durable schedule/outbox intent in one transaction. Public cache invalidation remains post-commit.

Schedule execution publishes through a conditional transaction requiring matching article, tenant, lock version, schedule generation, pending/leased schedule state, and `deleted_at IS NULL`. Manual publish, cancel, reschedule, delete, restore, or another successful mutation advances the relevant fence and makes prior jobs terminal/superseded. A worker lease alone is never authority to publish.

## API and UI contract
Admin detail responses expose lock version and safe schedule/revision metadata. All news mutations send expected lock version; mismatches return a stable 409 payload with current version, current revision ID, and safe conflict metadata. Revision content/history is administrator-only and never public/trash-list data.

Schedule create/cancel/reschedule/manual-publish operations are idempotent. UI labels local time as Beijing time, shows lifecycle terminal states, explains missed triggers, and supplies safe reload/manual merge controls. The client never attempts automatic rich-text merge.

## Compatibility, migration, and security
Add schema first, backfill one initial revision per existing article, initialize lock versions and schedule fences, validate counts, then enforce expected versions. Existing queued work without a valid fence cannot publish. Existing public visibility, source-attestation, soft-delete, retained audit, preview denial, and metadata-only trash rules remain authoritative. Cache/search/CDN invalidation must cover publish, unpublish, delete, restore, and schedule terminal transitions.

## Acceptance evidence
Strict TDD covers stale update 409, revision append atomicity, scheduling fence races, missed/no-catch-up transition, retries/terminal states, timezone conversion, delete/restore/purge interactions, audit redaction boundary, and post-commit cache behavior. Live PostgreSQL migration validation covers upgrade/rerun/backfill/downgrade safety. UI tests cover conflict and schedule state flows.
