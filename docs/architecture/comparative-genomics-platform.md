# Comparative genomics platform architecture

SoyMutDB remains a release-aware FastAPI, PostgreSQL, Redis/Celery and object-storage system. Existing gene, homolog, expression, variant, GWAS, phenotype, JBrowse, download and MCP services remain owners of their contracts. New comparative features compose those services rather than creating parallel stores.

## Boundaries

- A species and assembly registry owns scientific names, assemblies, annotation versions, chromosome lengths, checksums and release publication state.
- Gene and protein records retain assembly and release foreign keys. A coordinate is never rendered without both contexts.
- Homology imports store method, source release, relationship type (one-to-one, one-to-many, many-to-many), confidence and evidence. A BLAST hit is a candidate similarity result, not an orthology assertion.
- Families store immutable membership snapshots, subfamilies, alignment/tree artifacts and source provenance. Trees and alignments are asynchronous artifacts.
- Synteny consumes existing JBrowse tracks and curated alignment/block data. JBrowse remains the genomic visualization owner.
- Downloads use the existing asynchronous job and object-storage path, with release, checksum, generation time and license in the manifest.

## Access modes

`/blast` remains the authenticated researcher workflow for owned jobs and history. Public form/database discovery remain readable without a session. `/search/blast` provides anonymous execution through separate capability-authorized HTTP endpoints over the same job/outbox/worker pipeline. A signed, purpose-specific credential is bound to one explicitly anonymous job and expires within 24 hours. Private account ownership and researcher submission authorization remain unchanged. See [public BLAST operations](../ops/public-blast.md).

## Delivery order

1. BLAST+ database catalog and worker execution contract.
2. Gene detail composition and family/homology evidence.
3. Synteny and tree artifacts.
4. Expression and phenotype links.
5. Licensed functional and biodiversity adapters.

Every import is staged, validated, checksummed and published through the existing release workflow. Draft data is invisible to public queries.
