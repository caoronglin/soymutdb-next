# SoyMutDB Next Full-Stack Upgrade Execution Plan

> **已归档（2026-10-01）**：2026-08 设计波次与旧基线快照。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md；门户布局以 `docs/superpowers/specs/2026-08-14-public-web-layout-alignment-design.md` 为准。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

This plan implements `docs/design/full-stack-upgrade-2026-08.md`. Work may run in
parallel only inside the ownership lanes below. Database schema and public API
changes require integration review before dependent lanes proceed.

## Phase 1: Stabilize Trust Boundaries

### Security lane

- Add owner-aware BLAST status/result authorization in
  `apps/api/app/api/v1/blast.py` and `apps/api/app/services/blast_service.py`.
- Add owner-aware analysis status/download authorization in
  `apps/api/app/api/v1/analyses.py` and
  `apps/api/app/services/analyses_service.py`.
- Add regression tests for anonymous, cross-user, owner, and administrator paths.

### ClickHouse lifecycle lane

- Replace cached coroutine behavior in `apps/api/app/core/database.py` with a
  reusable client lifecycle managed by FastAPI lifespan.
- Verify repeated readiness, analytics inserts, and variant queries.

### ClickHouse schema lane

- Reconcile `infra/clickhouse/init.sql`, worker ingest columns, and API query
  columns.
- Add a versioned, idempotent upgrade path and a schema-consistency test.
- Preserve existing production data through additive/shadow migration semantics.

### Supply-chain and ingress lane

- Generate and use real Python lock files; remove empty-lock CI workarounds.
- Fail builds containing placeholder CSP origins.
- Restrict production host ports and reject default production credentials.
- Add immutable image publication prerequisites without changing application
  behavior.

### MCP lane

- Configure shared authenticated Redis rate limiting and health checks.
- Add ingress authentication/rate limiting and structured tool-call audit data.
- Preserve streamable HTTP behavior and add an end-to-end smoke test.

### Contract visibility lane

- Extend contract checks to detect frontend/client endpoint and response drift.
- Make newly introduced drift fail without attempting the full API redesign yet.

### Frontend deployment baseline lane

- Establish one base/API/JBrowse-origin contract for Vite, SSG, CSP, service
  worker, and Turbo hashing.
- Fix root-path redirects and nested SSG asset resolution.
- Do not begin the Ant Design migration in this phase.

### Phase 1 gate

- Focused API security tests pass.
- Repeated ClickHouse client operations pass.
- ClickHouse DDL/write/read schemas reconcile.
- Frozen dependency builds work without generated placeholders.
- Production CSP and ingress checks pass.
- MCP auth/rate-limit smoke passes.
- Oracle review has no unresolved material finding.

## Phase 2: Contracts and Reliable Jobs

- Normalize v1 pagination/filter/sort behavior and derive client types from
  generated OpenAPI types.
- Document all common error responses and preserve request IDs through MCP.
- Move export/import/static task dispatch into the transactional outbox.
- Add retry scheduling, dead-letter state, metrics, and administrative replay.
- Add persistent export/job progress and result records.
- Add analyses workers and queue metrics.
- Implement cooperative cancellation and cleanup.
- Add contract, retry, idempotency, cancellation, and export lifecycle tests.

## Phase 3: Scientific Capabilities and Ant Design 6

- Implement release current/provenance/stats and audited state transitions.
- Implement the Admin routes actually consumed by release, user, track, assembly,
  variant, BLAST, and seed-management pages.
- Implement export manifests and complete GWAS/public scientific journeys.
- Migrate Web, Admin, and JBrowse atomically to stable Ant Design 6.
- Replace ProTable/ProForm with Ant Design Table/Form and TanStack Query.
- Move shared values to CSS-only design tokens and non-UI helpers to shared or
  application-local modules.
- Remove Pro Components, `@soymutdb/ui`, Radix/CVA/tailwind-merge direct
  dependencies, aliases, imports, and exemptions.

## Phase 4: Production Evidence

- Make lint, typecheck, tests, contracts, builds, image scans, and bundle budgets
  blocking for all affected applications.
- Publish signed images with SBOMs and deploy by digest.
- Add Alertmanager, backup-success metrics, centralized logs, and OpenTelemetry.
- Define and dashboard availability, latency, queue, task, and recovery SLOs.
- Schedule backups and monthly isolated restore drills.
- Validate Pages subpaths, Admin browser and Tauri artifacts, JBrowse standalone
  and iframe modes, MCP through Nginx, accessibility, keyboard paths, and visual
  baselines.

## Parallel Ownership Rules

- Security and ClickHouse lifecycle may run in parallel because they own separate
  API files.
- ClickHouse schema work exclusively owns `infra/clickhouse/init.sql` and worker
  ingest schema changes during Phase 1.
- Supply-chain work owns Docker/workflow/deployment files; MCP work may edit only
  its compose environment block in coordination with that lane.
- Contract visibility does not change endpoint behavior in Phase 1.
- Frontend deployment work does not modify UI components or package versions in
  Phase 1.
- Cross-lane conflicts are resolved by the orchestrator after specialists finish;
  agents must not revert concurrent changes.
