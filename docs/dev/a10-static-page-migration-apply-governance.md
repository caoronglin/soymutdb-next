# A-10 StaticPage Migration Apply Governance Design

> **已归档（2026-10-01）**：一次性任务笔记与旧状态视图（结论已进入现状视图与计划）。继任：docs/dev/project-status.md；任务级进度见 `docs/aegis/plans/`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

## Status and scope

**Status: design approved for governed apply only; no apply endpoint or UI is exposed.** This document defines the controls that must exist before a future mutation can be proposed. The currently exposed operation remains the administrator-gated, non-mutating dry run:

`POST /admin/content/pages/migrate-to-page-builder/dry-run`.

The implementation behind that preview is `apps/api/app/services/static_page_migration_service.py`. It validates each selected legacy `StaticPage`, reports the prospective `/pages/{slug}` target, does not add target rows or commit, and reports existing target routes as skipped. The service has an internal `dry_run=False` branch used by tests, but it is **not** an authorization boundary or a public contract. It must not be wired to a route, client, CLI, task, or UI until every gate in this document is met.

A migration creates a Page Builder draft; it does not publish content, archive or delete a source page, change source status, or change public routing. Publication remains a separate Page Builder approval/outbox flow.

## Evidence and current guarantees

The current tests establish these limited, important facts:

- dry run is administrator-gated and always invokes the migration service with `dry_run=True`;
- dry run is non-mutating, including no target creation, flush, or commit;
- a created target starts as `PageDefinitionStatus.DRAFT` with no publication timestamp;
- the bilingual bodies are represented as rich-text nodes and source content/status remain unchanged;
- an existing target route is skipped, making the present service retry-safe in the ordinary already-created case; and
- invalid pages receive a stable safe error code/message rather than internal validation detail.

These facts do **not** establish authority to apply, an approval trail, atomic batch behavior, source-version conflict protection, or rollback. Those are future acceptance requirements, not claims about the current implementation.

## Governance model

### Roles and separation of duties

Use existing authenticated RBAC as the base, but introduce explicit migration capabilities rather than treating the current administrator check as sufficient:

| Capability | Minimum authority | Constraints |
| --- | --- | --- |
| Run preview and read a migration record | Content Editor or Administrator | Preview remains non-mutating; Auditor has read-only access to records/evidence. |
| Create an apply request from a fresh preview | Content Editor or Administrator | Requestor supplies a bounded selection, reason, and preview digest. |
| Approve or reject an apply request | Administrator with migration-approver capability | Must not be the requestor for a high-risk or multi-page request. Approval records identity, role/capability snapshot, decision, reason, and expiry. |
| Execute an approved apply | Dedicated server-side execution identity or Administrator with executor capability | Execution must re-authorize and verify the approval; it may not trust a UI flag. |
| Roll back migrated targets | Administrator with rollback capability | Must be separately confirmed and audited; it never mutates legacy sources. |
| Inspect audit evidence | Auditor or Administrator | Read-only; audit access grants no mutation authority. |

Before endpoint exposure, the project must decide whether these capabilities are implemented as new roles or narrowly-scoped permissions. The decision must preserve the existing rule that Auditor is read-only and must enforce separation of duties server-side, not merely in the UI.

### Review and audit record

Persist an append-only migration request/run record linked to the source page IDs, target page/version IDs, preview digest, and actor IDs. Store immutable request-time evidence sufficient to reconstruct a decision:

- request ID, correlation/request ID, timestamp, initiator, capability/role snapshot, selected source IDs and slugs;
- canonical preview manifest and SHA-256 digest, including each source revision token, source content digest, intended route, converted-definition digest, and predicted outcome;
- human reason, risk classification, validation result, requested/approved/executed/failed/rolled-back state transitions;
- reviewer identity, decision, comment, decision time, expiry, and separation-of-duty check result;
- executor identity, idempotency key, database transaction outcome, per-item result, and conflict/error code; and
- rollback actor, reason, target versions removed or tombstoned, and verification result.

Write an `AuditLog` entry for every state transition in the same transaction as the governed record/state mutation. Audit events must reference the migration request/run ID and avoid storing raw rich-text bodies or secrets. Provide immutable audit retrieval with filters by request/run, source page, target route, actor, and time.

### Explicit confirmation

An apply must require a fresh, server-verifiable confirmation, not a checkbox alone:

1. The caller chooses exact source IDs/slugs from a completed preview and sends the preview manifest digest, request reason, and a unique idempotency key.
2. The server verifies the preview exists, belongs to the same tenant/context, is within a short expiry window, has no invalid items, and exactly covers the request selection.
3. The requester completes an explicit confirmation phrase containing the item count and preview digest suffix. The server records the confirmation time and binds it to the request.
4. An independent authorized reviewer approves the exact digest and selection. Any selection, digest, or source-token change invalidates approval and requires a new preview/request.
5. Immediately before execution, the service recomputes validation and source tokens inside its transaction. Any mismatch fails closed; it never silently applies a newer source state.

The eventual UI must show a diff/manifest, source and target routes, skipped/conflicted/invalid counts, draft-only consequence, source-preservation statement, reviewer decision, and expiry. It must make clear that confirmation does not publish the draft.

## Source and target invariants

A future apply implementation must enforce all of the following transactionally:

1. **Source preservation.** It never updates, deletes, archives, unpublishes, or changes the version/status/content of a `StaticPage`. It must assert source identity and revision/content digest against the approved preview before any target write.
2. **Target isolation.** It creates only a new `PageDefinition` and initial `PageDefinitionVersion` in `DRAFT`; no publication status, publication timestamp, public files, sitemap, outbox publication event, or redirect is created by migration apply.
3. **Deterministic conversion.** The target route is `/pages/{slug}`, and the canonical validated definition/digest must match the approved preview. Both language bodies remain represented; no silently discarded content is acceptable.
4. **Route ownership.** A pre-existing route is never overwritten, merged, or adopted. It is a conflict unless it is demonstrably the same completed migration recorded under the same idempotency key.
5. **No hidden broadening.** The selected source set is exact and bounded. Missing requested source rows, unexpected rows, invalid routes, or invalid converted definitions fail the request rather than being silently omitted.
6. **No implicit publication or archival.** Those decisions remain independently governed Page Builder or legacy-content operations.

## Conflict, retry, and transaction handling

The future command must use a client-supplied opaque idempotency key scoped to the authenticated actor and migration operation. Persist the normalized request digest and result. Reusing a key with identical input returns the existing terminal/in-progress result; reusing it with different input is rejected.

Execution must lock or compare version tokens for every selected `StaticPage` and target route. It should use a single database transaction for a bounded batch. If a database uniqueness race or optimistic conflict occurs, roll back the whole batch, mark the run conflicted with a safe per-item code, and require a new preview. Do not partially commit an unrecorded subset.

Transport failures are ambiguous. Clients must not automatically retry mutation requests; they query the request/run by idempotency key or request ID. The server may retry only clearly safe transient database work before a commit, never after an unknown commit result. A worker, if used, must have the same server-side idempotency and authorization checks; background execution does not relax governance.

Classify outcomes explicitly: `created`, `already_applied_same_request`, `conflict_source_changed`, `conflict_target_exists`, `invalid_source`, `authorization_denied`, `approval_expired`, `cancelled`, and `failed`. Do not expose internal exception text to the UI or audit export.

## Rollback and recovery

Because source rows are immutable under migration, rollback concerns targets only. A rollback command must be separate from apply, require rollback authority and explicit confirmation, and be limited to targets proven to have been created by the named migration run.

Rollback is allowed only while every target remains an unmodified, unpublished migration-created draft. It must verify target ID, route, initial-version digest, provenance marker, no later versions, and no publish/requested state. If any target has been edited, previewed into a durable version, requested, published, or otherwise changed, automatic deletion is prohibited; the run is marked `rollback_blocked` and a governed Page Builder recovery procedure is required.

For eligible targets, delete/tombstone only the created target and its migration-created draft in one transaction, retain the immutable migration/audit record, and verify afterward that the source is unchanged and the target route is absent. No rollback operation changes the original `StaticPage` or public publication state.

## Criteria before endpoint or UI exposure

Do not add a mutating endpoint, API-client method, button, CLI command, scheduled job, or feature flag that can invoke apply until all of the following are delivered and independently reviewed:

- [ ] Written capability/role decision, including approval/execution/rollback authority and server-enforced separation of duties.
- [ ] Persistent migration request/run, approval, manifest, and immutable audit schema with retention/access controls.
- [ ] Canonical preview manifest with source revision/content tokens and definition/route digests; preview expiry and invalidation logic.
- [ ] Server-side apply service that accepts only an approved request ID, confirmation proof, and idempotency key; no raw `dry_run=False` exposure.
- [ ] Transactional source assertions, target route uniqueness protection, deterministic conversion verification, bounded selection, and fail-closed conflict behavior.
- [ ] Idempotency/recovery read path for ambiguous client failures and a documented no-auto-retry client policy.
- [ ] Separate rollback service with provenance and eligibility checks, plus blocked-recovery documentation.
- [ ] Audit-log integration for request, confirmation, review, execution, conflict, failure, and rollback transitions.
- [ ] Focused unit, API, and PostgreSQL integration tests covering authorization, self-approval rejection, expired/stale preview, source change, target race, duplicate idempotency key, commit ambiguity lookup, source invariants, draft-only result, audit completeness, rollback eligibility, and rollback refusal after target changes.
- [ ] Security and product review of confirmation copy, audit access, retention, error disclosure, batch limit, and operational ownership; approval recorded in the governing task/decision log.
- [ ] API/OpenAPI contract and Admin UX reviewed only after all server-side gates pass. The UI must not be the authority for approval, confirmation, or conflict handling.

Until then, A-10 is accurately described as **in progress: dry-run/draft-only evidence exists; governed apply is design-approved but intentionally not exposed**.

## Validation for this design change

This document was derived from the current dry-run route, migration service, focused migration tests, Page Builder conflict/publication flow, RBAC role definitions, and AuditLog facilities. It introduces no executable code or apply surface.
