# ADR-0004: `module_data_rows` role — staging with promotion to canonical tables

Status: Accepted

Date: 2026-09-20

Supersedes: none. Decision source: Gate A (`docs/ops/gate-a-decision-brief-2026-09-20.md`).

## Context

`module_data_rows` (migration `0015`) is written by the `module_tsv` import in
`apps/worker` (`tables.py`) but has **no reader in the portal read path
(`apps/api`)**. The portal `/genes` reads the `genes` table, so imported module
data never reaches the public read path. The table has a unique constraint
`uq_module_data_rows_module_release_row` and indexes on `module_key`/`release_id`,
which is the shape of a landing/staging table, not a canonical domain table.
Evidence: `docs/ops/phase-0-fact-baseline-2026-09-20.md` §MODULE-ROWS (E1).

## Decision

`module_data_rows` is a **staging/landing table with an explicit promotion step
into canonical read tables** (`genes`, etc.). It is not itself a canonical read
source and must not remain write-only.

Required once promotion is implemented:

- retention policy (how long staged rows live);
- promotion state and the consumer that copies staged rows into canonical tables;
- cleanup after successful promotion;
- retry semantics on partial promotion;
- schema-evolution ownership (who owns the staged schema version).

Until promotion exists, the table stays staging-only and its writer is the sole
owner; the gap between "import writes staging" and "portal reads canonical" must
be closed in Phase 2, not left implicit.

## Consequences

- Phase 2 import work must define the promotion path, not just the writer.
- Rejected: treating it as plugin/extension storage (no such contract exists yet)
  and deleting it (the import pipeline still needs a landing surface).
- If a future need makes it canonical, that is a new ADR, not a silent switch.

---

## Amendment (review 2026-09-20, F3)

"Promotion into canonical read tables" is **per `module_key`**, not a single
hard-coded target. `module_data_rows` is keyed generically by `module_key`
(+ `release_id`, row identity); each `module_key` maps to its own canonical
destination (e.g. a genes-shaped module promotes into `genes`; other modules to
their respective canonical tables). Phase 2 must define the `module_key →
canonical table` mapping explicitly rather than assuming everything lands in
`genes`.
