# Plant comparative genomics feature comparison

Research date: 2026-11-03. This is a preliminary comparison. The capability matrix below includes research candidates supplied by the project brief; only the observations in the verification ledger have been confirmed from fetched first-party content. Unverified cells are not claims of current availability, API access, download formats, or licensing.

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

## Verification ledger

| Resource | Verified in this audit | Uncertainty / implementation complexity |
|---|---|---|
| Ensembl Plants | Compara documentation lists gene trees, orthology, families, whole-genome alignments and synteny | Redirected to June 2026 archive; live tools announce maintenance. REST, converters and license terms still need separate verification. High complexity. |
| PLAZA | Homepage lists latest 5.1 instances and archived versions | Individual family/analysis/API/download capabilities need instance documentation. High complexity. |
| Gramene | Homepage lists genome browser, Reactome, pan-genomes, BLAST, expression atlas, curated gene function and BioMart | Destination APIs, formats and license terms not verified. High complexity. |
| PlantCyc / PMN | Tools page documents enzyme BLAST, pathway/reaction/enzyme/compound queries, Pathway Tools and JavaCyc | Metabolic overview is species-specific and unavailable for multi-organism PlantCyc. Old Omics Viewer is legacy. Bundle uses a license form. High complexity. |
| GBIF | API reference documents species, occurrence, image and map APIs; REST JSON and async downloads | Dataset license/citation and exact export format must be checked per download. Optional external adapter; medium complexity. |
| Phytozome, SoyBase, MaizeGDB, SGN, TAIR, PlantTFDB, PlantCARE | No successful first-party feature-level fetch in this audit | Requests failed with upstream 403/502 or timeout. All capability cells for these resources remain candidates pending verification. License and API availability unknown. |

No dataset license grants are inferred from website accessibility. Exact downloadable formats and data provenance require release-specific verification before ingestion. This preliminary report does not satisfy the complete external-database research acceptance criterion yet.

## Current versus proposed SoyMutDB behavior

Currently available in this repository: release-scoped BLAST database discovery; authenticated researcher BLAST job submission; DIAMOND `blastp`; release-aware gene, homolog, variant, expression, GWAS, phenotype, JBrowse and MCP read contracts. The public `/blast` form and database list are available without login, but job submission is intentionally restricted to researcher-capable sessions.

Legacy or compatibility behavior: stored BLAST rows retain the five program names, while new submissions currently accept only `blastp`; `/search/blast` remains a compatibility route. These historical values must not be presented as executable capabilities.

External functionality: the verification ledger records observed features; other matrix entries remain research candidates. None of these observations imply that SoyMutDB has imported their data or accepted their licenses.

Proposed order: complete NCBI BLAST+ and immutable database catalog first; then gene/family and synteny contracts; then expression/phenotype integration; finally licensed TF, motif, pathway and GBIF adapters.

## Sources

- https://phytozome-next.jgi.doe.gov/
- https://plants.ensembl.org/info/genome/compara/index.html
- https://bioinformatics.psb.ugent.be/plaza/
- https://www.soybase.org/tools/
- https://www.maizegdb.org/
- https://gramene.org/
- https://solgenomics.net/
- https://www.arabidopsis.org/tools/
- https://planttfdb.gao-lab.org/
- https://pmc.ncbi.nlm.nih.gov/articles/PMC99092/
- https://plantcyc.org/pmn-tools-overview/
- https://techdocs.gbif.org/en/openapi/
