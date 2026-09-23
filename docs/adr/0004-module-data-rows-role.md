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

---

## Amendment (implementation, 2026-09-23)

Promotion is implemented for the first canonical module (``genes``) in
``apps/worker/src/soymutdb_worker/tasks/module_promotion.py``. It runs inside
the ``module_tsv`` import transaction, after staging is written and validated
and before the data set is marked ready. This answers the five open items:

- **Promotion state**: the transaction is the state machine. "Staged but not
  promoted" cannot be committed; a failed promotion rolls staging back and the
  data set never reaches ``ready``. ``data_sets.validation_evidence`` and
  ``data_sets.manifest`` carry the promotion counters for audit.
- **Consumer**: the worker import adapter is the only promoter; the API keeps
  reading canonical tables only.
- **Retention / cleanup**: staged rows are retained with the release
  (``module_data_rows.release_id`` cascades on release delete) as an audit and
  replay source; a successful promotion does not delete them.
- **Retry semantics**: the importer clears staging before rewriting, and every
  promotion write is an idempotent upsert keyed by stable identity
  (``(assembly_id, accession)`` for genes, ``(assembly_id, name)`` for
  chromosomes), so a retry after partial progress converges.
- **Schema evolution**: ``packages/jobs-py``'s ``MODULE_SCHEMAS`` owns the
  staged row shape; ``PROMOTION_TARGETS`` owns the destination mapping. Adding
  a module means adding both, and an unmapped key fails closed.

### Mapping and visibility rules

- ``module_key -> target``: ``genes -> genes``; any other key is an error.
- Assembly resolution: the ``releases.assembly_id`` pin, else exactly one
  ``assemblies.release_id`` row. Zero or several fails closed rather than
  guessing.
- Chromosomes referenced by staged genes are created when absent with a
  provisional length = the longest observed gene end; an existing length is
  only extended, never shortened.
- Genes are upserted by ``(assembly_id, accession)``. ``strand`` defaults to
  ``+`` (the genes module schema has no strand column) and
  ``mutation_feature`` is preserved under ``genes.attributes``.
- Visibility follows the existing release rule: the portal resolves only
  PUBLISHED releases through ``assemblies.release_id``, so draft promotion is
  not publicly readable (regression-tested in the PostgreSQL suite).
