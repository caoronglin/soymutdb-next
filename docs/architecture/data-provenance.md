# Data provenance and assembly safety

Every imported record and generated artifact carries source, DOI/accession, species, assembly, annotation release, source version, import time, license, checksum and transformation history. Evidence is classified as experimentally validated, manually curated, computationally predicted, transferred by orthology or externally imported.

Release context is resolved before reads and writes. A database, gene, variant, expression value or coordinate from another release is not substituted as a fallback. Coordinate conversion is an explicit, separately versioned operation. Missing values remain missing; they are never rendered as zero.

BLAST results retain the searched database, release and assembly. A job from release A remains release A after release B becomes active. Browser navigation resolves subject IDs through the corresponding assembly and only then emits a genomic locus.

Administrators publish only validated immutable snapshots. Rollback changes the active release pointer; it does not mutate old artifacts. Downloads and MCP responses expose source and release metadata so downstream analyses can cite the exact data used.
