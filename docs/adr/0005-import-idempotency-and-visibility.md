# ADR-0005: Import idempotency and publish-visibility protocol

Status: Accepted

Date: 2026-09-20

Decision source: Gate A (`docs/ops/gate-a-decision-brief-2026-09-20.md`).

## Context

Seven classic scientific import types are fail-closed by design
(`features.py` defaults False; `ingest.py`/`data_adapters.py` raise
`UnsupportedImportError`). Per the contract this fail-closed state is a
**legitimate protection**, not a defect: the missing piece is a writer plus an
idempotency/visibility protocol. ClickHouse `MergeTree` does not provide
PostgreSQL-style unique constraints or cross-step ACID, and its insert-dedup
token has a finite window, so it cannot be the sole exactly-once guarantee.
Evidence: `docs/ops/phase-0-fact-baseline-2026-09-20.md` D5/§CH (engine still
RUNTIME_ONLY until a ClickHouse instance is available).

## Decision

Adopt an **application-level manifest as the control plane**, with database
dedup used only as an auxiliary guard:

- **import_fingerprint** = `source_sha256 + release_id + assembly_id +
  importer_version + schema_version + normalization_version + semantic config
  hash`. Any input that can change output facts must enter the fingerprint;
  filename/upload-time do not.
- **PostgreSQL manifest** records `import_id, fingerprint, status, expected_rows,
  written_rows, started_at, completed_at, failure_code`, with state machine
  `CREATED → PARSING → WRITING → VERIFYING → PUBLISHED ↘ FAILED`, and an explicit
  rule for which states are visible to the portal.
- **Publish visibility rule**: the portal sees only `PUBLISHED` imports; partial
  writes are never visible.
- **Final verification**: row-count and checksum match before publish.
- ClickHouse insert-dedup token and/or `ReplacingMergeTree` may assist, but are
  **not** the correctness guarantee.

## Consequences

- Phase 2 implements staging/finalize per this contract and must pass the
  crash/retry/ambiguous-ACK fixtures (same-file/same-release idempotent;
  different release/assembly isolated; crash mid-write invisible; checksum
  mismatch not published).
- Rejected: relying solely on ClickHouse dedup token; ReplacingMergeTree+FINAL as
  the primary guarantee (eventual, perf cost).
- Re-enabling the 7 import feature flags is gated on this protocol being in place.
