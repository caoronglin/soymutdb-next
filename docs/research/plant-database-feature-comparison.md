# Plant comparative genomics feature comparison

Research date: 2026-11-03. Updated with a second, first-party fetch pass on
2026-11-03 (this PR). Capability cells sourced from the project brief remain
**research candidates** unless a row in the verification ledger records a
successful first-party fetch. A failed, blocked or empty first-party fetch is
recorded as such; it is never promoted to a claim of availability, API access,
download format, provenance or license.

## Capability matrix (candidate scope)

| Database | Scientific domain | Main functions | Data types | Search / visualization | API / downloads | Provenance / license | SoyMutDB equivalent | Priority |
|---|---|---|---|---|---|---|---|---|
| Phytozome / PhytoMine | Plant comparative genomics | Multi-species genomes, gene families, orthology, functional annotation | Assemblies, genes, proteins, families, annotations | BLAST, JBrowse, InterMine queries | BioMart/InterMine and bulk downloads | JGI species and release metadata; verify each dataset license | Species/assembly center, gene families, read-only mining | P1 |
| Ensembl Plants Compara | Comparative genomics | Orthologs/paralogs, protein trees, whole-genome alignments, synteny | Genes, proteins, trees, alignments | GeneTree, synteny and alignment views | REST, BioMart, FTP and converters | Ensembl release and stable-ID history | Homology API with method/evidence and release context | P1 |
| PLAZA | Plant gene-family evolution | Families/subfamilies, alignments, phylogenies, WGD and enrichment | Gene models, families, trees, GO | Family browser, trees and workbench | Instance-specific downloads and query tools | Versioned PLAZA instances; instance terms apply | Family workbench and phylogeny imports | P1 |
| SoyBase | Soybean crop genomics | BLAST, maps, expression, GWAS/QTL, germplasm, GlycineMine | Genome, markers, QTL, expression, stocks | Genome Context Viewer, maps, expression and GWAS views | GlycineMine, DataStore and bulk files | SoyBase source/version metadata; verify license per file | Soybean-specific tools over shared release model | P1 |
| MaizeGDB | Maize genetics | Gene center, pan-gene, domains, expression, variants, phenotypes, QTL | Genes, transcripts, proteins, stocks, maps, markers | Genome browser and dataset views | JSON/JSON-LD API and dataset downloads | Dataset-level provenance and terms | Gene/phenotype/variation center and adapters | P1 |
| Gramene | Crop comparative genomics | BLAST, VEP, converters, Plant Reactome, pan-genomes, expression | Genomes, variants, pathways, expression | Genome browser and pathway views | REST/tools, Gramene Mart and downloads | Release 69 and source-specific terms | Release-aware comparative and pathway adapters | P1 |
| Sol Genomics Network | Solanaceae genomics | Genes, families, phenotypes, QTL, markers, maps, expression | Genes, markers, maps, traits, images | Genome and comparative maps | BLAST and downloadable records | SGN accession and dataset provenance | Crop adapter pattern and marker/QTL search | P2 |
| TAIR | Arabidopsis functional genomics | BLAST, JBrowse2, synteny, PhyloGenes, GO, AraCyc, motifs | Genes, annotations, pathways, motifs | JBrowse2, synteny and enrichment | Bulk retrieval and tool endpoints | TAIR release and attribution terms | Functional annotation and browser links | P1 |
| PlantTFDB | Regulatory genomics | TF families, domains, motifs and regulatory links | TF genes, domains, motifs, targets | Family and motif views | Downloadable motif/classification data | Versioned database and source literature | TF annotation import with evidence labels | P2 |
| PlantCARE | Cis-regulatory annotation | Cis-elements, promoter motifs, positions and strand | Promoters, motif matrices, evidence | Motif and promoter views | Web query and reports | Experimental vs predicted evidence must remain distinct | Promoter/motif report, only when licensed | P2 |
| PlantCyc / PMN | Plant metabolism | Pathways, enzymes, compounds, reactions, metabolic overview | Pathways, reactions, compounds, enzymes | Query pages and metabolic/omics viewers | Pathway Tools/JavaCyc and license-controlled bundles | SRI/PMN terms; bundle may require license form | Pathway adapter and evidence-aware links | P2 |
| GBIF | Taxonomy and biodiversity | Taxonomy, occurrences, specimens, images and maps | Names, occurrences, media, datasets | Maps and occurrence views | Stable REST JSON API and asynchronous downloads | Dataset attribution and download citation required | Optional biodiversity integration, never genomic source of truth | P2 |

## Verification ledger (first-party fetches)

"Verified" means the fetched first-party content itself contained the named
capability. It does not mean SoyMutDB implements it, holds a license to the
data, or has ingested a single record.

| Resource | First-party result (this PR) | Verified from fetched content | Still unverified / complexity |
|---|---|---|---|
| Ensembl Plants Compara | `200`, 22.6 KB HTML from `/info/genome/compara/index.html` | Navigation documents whole-genome alignments, synteny, gene families, GeneTree/stable IDs, homology types, orthology/paralogy QC, protein trees, BioMart and REST | Exact REST/converter response shapes, FTP formats and license terms need separate verification. High complexity. |
| SoyBase tools | `200`, 36.2 KB HTML from `/tools/` | Tool list names SequenceServer BLAST, Genome Browsers, CMap-js genetic map viewer, Genome Context Viewer, Expression Explorer, GCViT SNP comparison, ZZBrowse GWAS/QTL, GlycineMine (InterMine), Germplasm GIS, QTL and DataStore | Per-file download formats, release IDs and license terms not verified. High complexity. |
| GBIF API docs | `200`, 23.5 KB HTML from `techdocs.gbif.org/en/openapi/` | Docs expose species, occurrence, image, map, registry APIs and `/occurrence/download/request` asynchronous downloads | Per-dataset license/citation and exact export format must be checked per download. Medium complexity. |
| GBIF live species API | `200`, JSON from `api.gbif.org/v1/species/match?name=Glycine%20max` | Real accepted-name response: `Glycine max`, usageKey 5359660, rank SPECIES, kingdom Plantae, family Fabaceae, matchType EXACT | Confirms name resolution only, not occurrence/media licensing. Optional external adapter. |
| PlantCARE paper | `200`, 20.5 KB HTML from `pmc.ncbi.nlm.nih.gov/articles/PMC99092/` | Article is reachable and discusses cis-element positions | The paper is a 2002 methods article; it does not prove a current database, live API, download format or license. Predicted vs experimental evidence still needs a source dataset. |
| Gramene | `200`, 4.0 KB HTML from `gramene.org/` | Client bundle declares `defaultServer=https://data.gramene.org/v58/swagger` (release 58) | Homepage is a JS shell; individual tools, Mart, formats and terms not verified. High complexity. |
| Phytozome | `200` from `/` and `/blast-search/`, 1.6 KB HTML | Only the application title; pages are JS shells | PhytoMine URL returned `410`. Multi-species collections, families, orthology, JBrowse, BioMart, downloads and license remain candidates. |
| PLAZA | `403` from homepage; documented tutorial URL `404` | None | Instance capabilities, alignments, trees, WGD, API and terms remain candidates. High complexity. |
| MaizeGDB | `403` from homepage, genome browser and `/api` | None | Gene center, pan-gene, JSON/JSON-LD API and dataset downloads remain candidates. High complexity. |
| PlantCyc / PMN | `403` from tools page and homepage | None in this pass. Earlier pass recorded pathway/reaction/enzyme/compound queries, Pathway Tools and JavaCyc with a license form; treat that as prior-observation, not this-pass verification | Bundle terms, species-specific Omics Viewer and exact export formats unverified. High complexity. |
| PlantTFDB | `503` from homepage | None | TF families, motifs, binding-site prediction and downloadable datasets remain candidates. |
| Sol Genomics Network | No successful fetch (connection failed) | None | Gene/family/phenotype/QTL/marker/map capabilities remain candidates. |
| TAIR | `200`, 2.4 KB HTML from `/tools/` | Only analytics/bootstrap markup | BLAST, JBrowse2, synteny, PhyloGenes, GO enrichment, AraCyc, motif analysis and bulk retrieval remain candidates. |
| PhytoMine | `410` from `/phytomine/html/start.html` | None | InterMine query and bulk download capabilities remain candidates. |

No dataset license grants are inferred from website accessibility. Exact
downloadable formats and data provenance require release-specific verification
before ingestion. This report satisfies the *audit* acceptance criterion but
explicitly does **not** claim completion of external data ingestion or licensing.

## Status of SoyMutDB behavior

Four states are kept distinct; none implies the next.

- **Currently available in this repository (verified by tests in this PR):**
  release-scoped BLAST database discovery; authenticated researcher BLAST job
  submission and anonymous capability-authorized submission; NCBI BLAST+ for
  all five standard programs (`blastn`, `blastp`, `blastx`, `tblastn`,
  `tblastx`) with real 2.17.0+ binary searches; DIAMOND `blastp` retained as an
  explicitly selected backend; immutable `makeblastdb`/`blastdbcmd` index
  catalog; transactional outbox, idempotent worker writes, job ownership and
  quota; release-aware gene, homolog, variant, expression, GWAS, phenotype,
  JBrowse and MCP read contracts.
- **Legacy / compatibility behavior:** `/search/blast` remains a compatibility
  route; stored BLAST rows retain the five program names; old DIAMOND-only
  payloads are still accepted with `engine` defaulting to `diamond`. These are
  not new capabilities.
- **External functionality:** only the verification-ledger rows above. None of
  these observations imply SoyMutDB has imported their data or accepted their
  licenses.
- **Proposed functionality:** gene/family/orthology workbench, synteny views,
  expression/phenotype composition, licensed TF/motif/pathway/GBIF adapters,
  no-SQL bulk query builder. These are roadmap items, not shipped features.

See `docs/architecture/blast-plus-architecture.md` and
`docs/implementation/blast-verification-pr.md` for the executable evidence.

## Sources

- https://phytozome-next.jgi.doe.gov/
- https://phytozome-next.jgi.doe.gov/blast-search/
- https://phytozome-next.jgi.doe.gov/phytomine/html/start.html
- https://plants.ensembl.org/info/genome/compara/index.html
- https://rest.ensembl.org/info/compara_methods
- https://bioinformatics.psb.ugent.be/plaza/
- https://bioinformatics.psb.ugent.be/plaza_development/documentation/tutorial
- https://www.soybase.org/tools/
- https://www.maizegdb.org/
- https://alpha.maizegdb.org/api
- https://gramene.org/
- https://data.gramene.org/v58/swagger
- https://solgenomics.net/
- https://www.arabidopsis.org/tools/
- https://planttfdb.gao-lab.org/
- https://pmc.ncbi.nlm.nih.gov/articles/PMC99092/
- https://plantcyc.org/pmn-tools-overview/
- https://techdocs.gbif.org/en/openapi/
- https://api.gbif.org/v1/species/match?name=Glycine%20max
