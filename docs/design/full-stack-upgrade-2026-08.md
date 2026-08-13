# SoyMutDB Next Full-Stack Upgrade Design

Status: approved execution baseline, 2026-08-12

This document is the authoritative architecture decision for the 2026 full-stack
upgrade. `upgrade-plan.md` and `upgrade-2026-08.md` remain historical inputs where
they conflict with this document.

## Goals

- Make scientific data correct, traceable, reproducible, and exportable.
- Close authorization, task-delivery, API-contract, and release-governance gaps.
- Standardize Web, Admin, and JBrowse on stable Ant Design 6 without Umi or Pro
  Components.
- Make every production artifact reproducible, observable, testable, and
  independently reversible.

## Non-goals

- No microservice decomposition without measured need.
- No Umi/Max migration, React SSR migration, or runtime dual UI stack.
- No new generic UI compatibility package.
- No SQLAlchemy repository layer solely for architectural symmetry.
- No production use of `apps/core-rs` without benchmarks and a unique role.

## Target Architecture

The runtime remains a modular FastAPI application with independently scalable
workers. PostgreSQL is the authoritative store. Redis, ClickHouse, and MinIO are
derived or reconstructable stores. Business jobs are committed through a
transactional outbox and executed at least once by idempotent Celery workers.
OpenAPI is the single REST contract source. MCP is an authenticated, rate-limited,
audited adapter over the API rather than a second domain layer.

Web, Admin, and JBrowse retain React 19, Vite 6, TanStack Router/Query, Tailwind 4,
and the existing deployment modes. All three applications resolve one Ant Design
6 runtime. Admin uses Ant Design Table/Form/Layout directly. Shared design tokens
may live in a CSS-only package that exports no React components.

## Storage Boundaries

- PostgreSQL: users, permissions, releases, provenance, audits, jobs, outbox,
  publication state, and other authoritative business state.
- ClickHouse: versioned, rebuildable scientific fact and analytics tables.
- Redis cache: disposable cache, rate limits, and short-lived coordination.
- Redis Celery: broker and result transport, isolated from cache eviction.
- MinIO: source files, generated exports, and analysis artifacts referenced by
  authoritative PostgreSQL records.

`variant_facts` has one versioned schema. ClickHouse DDL, worker writes, API reads,
materialized views, and tests must derive from that contract.

## Contract Boundaries

- `/api/v1` remains backward compatible. Removal, renaming, or semantic changes
  require `/api/v2`.
- Public high-volume lists use cursor pagination. Admin management lists may use
  offset pagination when explicitly documented.
- Error responses preserve `error`, `request_id`, and `status_code` semantics.
- Generated OpenAPI types are the only response-model source in
  `@soymutdb/api-client`.
- Export and long-running job state is persisted in PostgreSQL, not only in the
  Celery result backend.

## Task Semantics

- Transaction commit and task publication are coupled through the outbox.
- `event_id` remains the Celery task ID and idempotency identity.
- Transient failures retry with bounded exponential backoff.
- Deterministic failures do not requeue indefinitely.
- Exhausted events enter a visible dead-letter terminal state.
- Cancellation is cooperative: API writes `CANCEL_REQUESTED`, workers check at
  safe boundaries, clean partial artifacts, then write `CANCELLED`.
- Progress, failure details, and result references are persisted and queryable.

## Security Boundaries

- BLAST and analysis jobs enforce owner or privileged-service access for status,
  result, and download operations.
- MCP has server-validated identity, shared Redis rate limits, Nginx protection,
  and structured audit records.
- Only the public ingress is host-exposed in production. Database, Redis,
  ClickHouse, MinIO, metrics, and application ports remain private.
- Production startup fails on placeholder origins, default credentials, missing
  secrets, or unsigned/unresolvable artifacts.

## Scientific Product Requirements

Every applicable query, chart, table, and export exposes species, genome build,
release, source, method, units, sample count, and update time. Filters and sort
state are reproducible through URLs. Exports include a manifest containing the
query, selected fields, release/build, sources, generation time, record count,
checksum, and citation information.

Release activation, rollback, archiving, role changes, destructive imports, and
other high-risk actions require explicit state transitions and audit records.

## Delivery Phases

1. Stabilize security, ClickHouse correctness, dependency locking, deployment
   configuration, MCP protection, and contract visibility.
2. Make OpenAPI authoritative and implement reliable outbox, job, export,
   progress, cancellation, and dead-letter lifecycles.
3. Complete release/provenance/Admin capabilities and migrate all three frontend
   applications to stable Ant Design 6.
4. Enforce CI gates, artifact signing, observability, SLOs, backup scheduling,
   recovery drills, performance budgets, and final release evidence.

Each phase has an Oracle review gate. A phase cannot advance while material
findings remain unresolved.

## Release and Rollback

Database changes use expand/contract migrations. Old columns/tables remain until
new readers and writers pass consistency checks. ClickHouse schema migration uses
shadow or versioned tables where destructive in-place rollback would be unsafe.
Application rollback uses immutable image digests. Pages retains the previous
static artifact, and Admin retains the previous signed desktop package. Runtime
feature flags do not keep old and new UI systems loaded together.

## Final Definition of Done

- No known critical authorization defect.
- One versioned ClickHouse fact schema with write/read/DDL consistency tests.
- OpenAPI and all consumers reconcile with no undeclared endpoint or response.
- All business jobs are durable, idempotent, observable, cancellable where
  applicable, and dead-lettered after bounded retries.
- Release, provenance, export manifest, Admin governance, and audit journeys work
  end to end.
- Web, Admin, and JBrowse use Ant Design 6 only; Pro Components and
  `@soymutdb/ui` are absent.
- Frozen installs, lint, typecheck, tests, contracts, builds, scans, browser
  checks, Tauri checks, MCP checks, and recovery drills are blocking gates.
- `apps/core-rs` is either benchmark-gated and deployed with a unique role or
  removed with its stale documentation.
