# P0 public mutant discovery plan

## Parent
- Roadmap: docs/aegis/work/2026-08-31-soymutdb-optimization/80-mutant-core-capability-roadmap.md.
- Scope is existing canonical public mutant data only; no new biological schema, no fake lineage/phenotype semantics, no CMS work.

## TDD route
- Mode: auto
- Decision: strict
- Strict signals: public scientific contract, visibility boundary, API/client/UI seam, meaningful regression risk.
- Test posture: RED API/client/UI regression, then GREEN implementation.

## Task 1 — complete public mutant API contract
Files: apps/api/app/api/v1/mutants.py, apps/api/app/schemas/variant.py, focused API tests.
1. RED tests for visibility, deterministic ordering, mutagen filter, aggregate VariantSummary counts, and limit bounds.
2. Preserve canonical GET /mutants, GET /mutants/{id}, GET /mutants/{id}/phenotypes. Add only safe, explicit pagination if necessary; never expose embargoed or deleted records.
3. GREEN focused pytest/Ruff/diff evidence.

## Task 2 — public mutant browse and detail routes
Files: apps/web/src/routes/mutants/index.tsx, apps/web/src/routes/mutants/$mutantId.tsx, navigation owner, public UI tests, generated route tree only through normal router generation.
1. RED tests for loading/error/empty states, mutagen filtering, links, metadata-only cards/table, hidden-record 404 behavior, and no unsupported seed/lineage/causal assertions.
2. Implement browse around real list fields: name, mutagen, cultivar, PostgreSQL VariantSummary count. Detail shows real species/generation/description/phenotype summary and phenotype observations, with variant discovery link constructed only from current supported variants filter.
3. Use the typed canonical client; do not use deprecated endpoints or static curated data as live facts.
4. GREEN direct Vitest or CI evidence, locale parity, type/diff checks.

## Task 3 — scientific provenance and discoverability
Files: public navigation, docs/user, API/client tests.
1. Add a concise disclosure that material visibility and associated data are release/publication controlled.
2. Link to existing variant browse/JBrowse only where a supported assembly/variant context exists; no fabricated genome claims.
3. Document current fields and their limits: phenotype is a legacy summary/observation field pending ontology/environment model; seed catalog and lineage are not yet represented.

## Acceptance
- A researcher can discover a public mutant line, inspect current supported metadata and phenotypes, and navigate to compatible variant discovery without encountering fictional APIs or data claims.
- Non-public/deleted material remains indistinguishable from absent material across list/detail/phenotype paths.
- UI/API/client evidence uses release-aware language and retains the future schema boundary.
