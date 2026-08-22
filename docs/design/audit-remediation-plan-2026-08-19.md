# Multi-Agent Audit Remediation Plan (2026-08-19)

Status: execution delta for `full-stack-upgrade-2026-08.md`; it does not replace that approved architecture baseline.

## Decisions

- Keep PostgreSQL as the authoritative production control-plane database. The API and workers depend on PostgreSQL row locks, `FOR UPDATE SKIP LOCKED`, advisory locks, native types, Alembic migrations, and a multi-writer topology.
- If a zero-administration demo is required, evaluate SQLite only as a separate single-process, feature-limited profile. It must not silently claim support for outbox dispatch, concurrent refresh, release/publication transitions, imports, or Celery writers.
- Keep the modular FastAPI/Celery architecture. The audit found correctness and delivery gaps, not evidence that a framework or microservice rewrite would improve outcomes.

For lower database operations overhead, prefer managed PostgreSQL. MySQL/MariaDB would still require lock, type, migration, SQL, deployment, and recovery rewrites; DuckDB and ClickHouse are analytical stores, not replacements for this transactional control plane.

## Verified Baseline

The current working tree has focused fixes for migration enum creation, upload contract synchronization, controlled Admin upload state, safe S3 `HEAD` error mapping, and backup/restore writer quiescence. The quiescence contract now derives the API/worker/beat writer set from Compose and includes `worker-analyses` in backup, restore, and operator instructions.

Local evidence collected during this audit:

- Frontend lint and typecheck passed; 227 Vitest tests passed.
- Demo Web production/SSG build passed.
- API modified suites passed except 23 Testcontainers cases that require Docker.
- Worker, MCP, migration/outbox, deployment, and backup contract suites passed in their available local environments.
- Backup/restore contracts: 27 passed; ShellCheck, Bash syntax, and whitespace checks passed.

These results are not substitutes for the environment-dependent gates listed below.

## Wave 1 — Input and Storage Integrity (P0)

### Public upload publication boundary

Upload first to a private quarantine prefix. Persist owner, purpose, declared size/checksum, state, and expiry. A finalize endpoint must read the stored object, verify real size/checksum, fully decode with pixel limits, re-encode supported images, and only then copy to the public bucket. Add per-owner byte/object quotas, rate limits, audit events, and cleanup for abandoned uploads.

Acceptance: renamed HTML/SVG, truncated images, polyglots, checksum changes, cross-owner finalize, quota exhaustion, and expired uploads are rejected against the deployed MinIO version; valid images are published only after re-encoding.

### Analysis input integrity

After every S3 download, verify actual byte count and SHA-256 before invoking fastp/scanpy. Map missing inputs to deterministic user-safe failures and redact storage endpoint, credential, and SDK details from task errors.

Acceptance: valid input succeeds; size mismatch, digest mismatch, missing object, access denial, and connectivity failure have regression coverage; no internal sentinel reaches persisted/public errors.

## Wave 2 — Release-Correct Reads and Builds (P0)

Make assemblies, chromosomes, dashboard statistics, and all scientific reads use one release context. Include release identity in cache keys and reject draft/unpublished releases on public routes. Redesign versioned facts so repeated stable scientific IDs can coexist across immutable releases, using release-scoped keys or version tables.

Replace the SSG layout type assertion with an explicit API DTO, runtime validation, and mapping from `page_name`/`display_name`/`widgets`. Exercise the live-data build with the real OpenAPI response shape and hostile text fixtures.

Acceptance: two releases may contain the same assembly/gene IDs; activation and rollback return only the selected snapshot; cache switching is correct; a production release-data SSG build completes without `undefined` fields or executable-content injection.

## Wave 3 — Recovery and Artifact Identity (P0)

Before any destructive restore, verify target-environment UUID markers stored independently in PostgreSQL, ClickHouse, and MinIO. A different Compose filename or an asserted environment variable is not proof of isolation. Refuse source/production identity before `dropdb`, ClickHouse replacement, or S3 mirroring.

Change GitHub Pages so the bytes that pass manifest/digest verification are the exact bytes deployed. Do not verify one artifact and rebuild another. CI dependency installation must use the same frozen `uv`/pnpm lock graph and Python versions as production images.

Acceptance: an alternate Compose file pointing at a production-equivalent endpoint fails before mutation; a long-running `worker-analyses` task prevents backup/restore; deployed Pages files reproduce the verified manifest; `uv lock --check`, frozen sync, image build, and runtime smoke use one dependency graph.

## Wave 4 — Durable Notifications and Operations (P1)

Add recipient-level delivery idempotency (`event + recipient + channel` or provider idempotency key), `next_attempt_at`, bounded exponential backoff with jitter, event-specific attempt limits, a dead-letter state, metrics, and audited replay. Keep broker delivery at-least-once while making the external side effect effectively once per recipient.

Acceptance: inject a crash after provider acceptance but before `mark_sent`; each recipient receives one message. Temporary outages back off, terminal failures dead-letter, and authorized replay is observable.

## Parallel Ownership

- Storage lane owns upload quarantine/finalize and analysis object verification.
- Release lane owns schemas, release context, scientific queries, cache keys, and SSG DTO mapping.
- Delivery lane owns restore identity, Pages artifacts, and frozen CI/install behavior.
- Reliability lane owns outbox/email retries, receipts, dead-letter, and replay.

Lanes may run concurrently only with disjoint files. Schema or public API changes require integration review before downstream client or deployment work proceeds. Every task must return changed files, focused test output, remaining unknowns, and a rollback path.

## Required Environment Evidence

The following remain explicitly unverified until run in an isolated, non-production stack:

- the 23 Docker/Testcontainers PostgreSQL cases;
- a real PostgreSQL/ClickHouse/MinIO/Celery backup, restore, and rollback drill;
- the production release-data Web build;
- browser-to-MinIO multipart upload and checksum compatibility;
- restore target identity markers before destructive commands;
- historical MinIO versions and deletion-marker recovery;
- multi-dispatcher outbox crash/lease competition.

Release readiness requires all applicable evidence above, not only local unit tests.
