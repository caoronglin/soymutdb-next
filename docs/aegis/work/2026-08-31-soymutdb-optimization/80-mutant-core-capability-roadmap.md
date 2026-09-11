# SoyMutDB mutant-database core capability roadmap

## Product priority
SoyMutDB is a soybean mutant research database. CMS and generic control-plane work are supporting capabilities, not the primary product. The scientific user question is: which line has which phenotype, in which background and environment, what genomic evidence supports it, where is the stock, and how can the result be reproduced?

## Current verified foundation
- Assembly/gene/transcript/alias, release context, ClickHouse variant filters, JBrowse/tracks, BLAST, expression, GWAS, seed-request workflow, dataset manifests, provenance, and asynchronous exports exist.
- Mutant lines and basic phenotypes exist but were thin. Public visibility filtering and aggregate PostgreSQL VariantSummary counts have now been repaired.
- Public client contract now uses canonical /mutants APIs; the previous fictional /mutant-lines surface was retired.
- Specialized biological importers remain fail-closed; admin submission now exposes only the durable module TSV path.

## Delivery order
### P0 — trust and coherent discovery
1. Dedicated public mutant browse/detail/phenotype pages using the canonical API.
2. Release-scoped visibility, stable material IDs, aliases, and correct counts.
3. Truthful static comparison labeling until a release-pinned evidence comparison API exists.
4. Public/API/client tests for visibility, counts, zero-result semantics, and contract fidelity.

### P1 — biological evidence model
1. Soybean-first germplasm/accession identity, aliases, population/background, mutagenesis event and lineage/cross graph.
2. Ontology- and environment-qualified phenotype observations: term/version, study, protocol, stage, treatment, numeric value/unit, replicate/statistics, evidence source and release.
3. Callset/sample/genotype evidence tied to assembly, pipeline, quality, release and a stable normalized variant identity.
4. Explicit variant–gene–phenotype assertions with confidence tiers: validated, strong candidate, candidate, linked marker, background, prediction-only.

### P1 — operational science
1. Public seed catalog with availability/lot/viability and policy-aware request-to-reservation traceability.
2. Typed staging writers for VCF, seed, phenotype, expression and homolog data; no count-only success state.
3. Release/dataset catalog exposing manifests, assembly, record counts, licenses, citations, checksums, source versions and changelog.

### P2 — FAIR and interoperability
1. Release-pinned CSV/TSV/JSON packages with machine-readable manifest and citation metadata.
2. RO-Crate/PROV-compatible source mappings and Bioschemas Dataset/DataCatalog markup.
3. BrAPI germplasm/phenotyping after the internal evidence model stabilizes; GA4GH read-only adapters only after release/fencing proof.

## Borrowed patterns
- SoyBase: soybean-specific cross-links across genes, traits, germplasm, alleles, QTL/GWAS and genomic tools.
- TAIR: curated, evidence-traceable phenotype assertions rather than unqualified labels.
- Ensembl Plants/Gramene: assembly-aware genomic context, deep links, releases and bulk/programmatic distribution.
- USDA GRIN: germplasm-centric stable identity, accession and inventory/evaluation information.

## Deliberate boundaries
- Default implementation is soybean-first; no multi-species germplasm promise until explicitly approved.
- No automatic publication or non-durable biological import.
- No external federation mixed into canonical internal scientific search results.
- No mutation evidence claim without source/release/provenance and confidence classification.
