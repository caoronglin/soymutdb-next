# ruff: noqa: E501
"""Seed the *NCBI Database Retrieval Operation Guide* static page.

Inserts (or updates) a :class:`StaticPage` row with ``slug="ncbi-database-guide"``
and a comprehensive bilingual (English / Chinese) Markdown body covering NCBI
core databases, the Entrez search system, BLAST sequence search, the JBrowse
genome browser, the NCBI E-utilities API, search best practices and result
interpretation.

Run it from the repository root (``soymutdb/``)::

    python -m apps.api.app.scripts.seed_ncbi_guide

The script is idempotent: if a page with the same slug already exists it is
updated in place, otherwise a new row is created.

Schema note
-----------
The current ``StaticPage`` ORM model only maps ``slug``, ``title_en``,
``title_zh``, ``content_en`` and ``content_zh`` (plus timestamps). The
additional metadata requested for this guide — ``summary_en``, ``summary_zh``,
``status``, ``category`` and ``sort_order`` — is therefore applied through a
safe setter that persists a value only when the column exists on the model, so
the script remains runnable today and automatically picks up those fields if
they are added to the model later. The summary text is additionally embedded as
the opening block of each content body so the information is never lost.

A ``ContentVersion`` record (``version=1``) is created when a
``ContentVersion`` model is available; if the model is not present in the
current schema the step is skipped with a notice rather than raising.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select

from ..core.database import close_db, get_session_factory
from ..models.content import StaticPage

# ContentVersion is optional — it is not part of the current schema. Import it
# defensively so the script keeps working whether or not the model exists.
try:  # pragma: no cover - depends on optional model presence
    from ..models.content import ContentVersion  # type: ignore[attr-defined]

    _HAS_CONTENT_VERSION: bool = True
except ImportError:  # pragma: no cover
    ContentVersion = None  # type: ignore[assignment, misc]
    _HAS_CONTENT_VERSION = False

logger = logging.getLogger("seed_ncbi_guide")

SLUG = "ncbi-database-guide"

TITLE_EN = "NCBI Database Retrieval Operation Guide"
TITLE_ZH = "NCBI数据库检索操作指南"

SUMMARY_EN = (
    "Comprehensive guide for NCBI database retrieval including BLAST, Entrez, "
    "JBrowse, and E-utilities"
)
SUMMARY_ZH = (
    "NCBI数据库检索综合操作指南，涵盖BLAST、Entrez、JBrowse和E-utilities工具"
)

STATUS = "published"
CATEGORY = "guide"
SORT_ORDER = 1


# ---------------------------------------------------------------------------
# English content
# ---------------------------------------------------------------------------

CONTENT_EN = """\
> **Summary:** Comprehensive guide for NCBI database retrieval including BLAST, Entrez, JBrowse, and E-utilities

# NCBI Database Retrieval Operation Guide

## 1. Introduction

The National Center for Biotechnology Information (NCBI), part of the U.S.
National Library of Medicine (NLM), hosts dozens of interconnected public
databases that together form the largest genomic and bibliographic resource in
the world. SoyMutDB integrates with several of these resources — BLAST for
sequence similarity search, the Entrez search system for cross-database
queries, JBrowse for genome visualization, and the E-utilities API for
programmatic access — to help soybean researchers move from a mutation of
interest to published knowledge, functional annotation, and raw sequencing
evidence.

This guide explains, step by step, how to retrieve information from NCBI
effectively. It is written for wet-lab biologists, bioinformaticians, and
curators who use SoyMutDB and need to validate variants, annotate genes, or
trace a phenotype back to its primary literature. Each section combines a
conceptual overview with concrete parameters, tables, and worked examples so
that you can use it both as a tutorial and as a day-to-day reference.

After reading this guide you will be able to: (1) choose the right NCBI
database for a given question; (2) construct precise Entrez queries using
field qualifiers and Boolean operators; (3) run and tune BLAST searches,
including selecting the correct program, task mode, and parameters; (4) browse
soybean genomes in JBrowse 2 and overlay SoyMutDB tracks; (5) call the
E-utilities API from Python scripts; and (6) interpret alignment scores,
E-values, gene records, and publication records critically.

## 2. NCBI Core Databases

NCBI organizes data into domain-specific databases that are linked through the
Entrez retrieval system. Understanding what each database contains is the first
step to formulating an efficient query.

### Gene
The **Gene** database is a curated record of genes from many organisms. Each
record consolidates nomenclature, genomic location, RefSeq transcripts and
proteins, known aliases, phenotypes, pathways (via BioSystems), Gene Ontology
(GO) annotations, expression data, and links to PubMed. For soybean, Gene
records are keyed by NCBI Gene IDs (e.g., `100798926`) and cross-reference the
Wm82 reference assembly. Use Gene when you need an authoritative summary of a
locus.

### Nucleotide
The **Nucleotide** database (formerly `nuccore`) is a comprehensive collection
of nucleotide sequences from GenBank, RefSeq, PDB, and the Third Party
Annotation (TPA) database. It includes mRNA, genomic contigs, BAC clones, and
whole chromosomes. Records are identified by accession.version strings (e.g.,
`NM_001252639.2`). Use Nucleotide to fetch the raw sequence of a transcript or
genomic region.

### Protein
The **Protein** database aggregates amino-acid sequences from GenBank,
RefSeq, PDB, Swiss-Prot, PIR, and PRF. It is the primary source for sequence
retrieval before running `blastp` or building multiple alignments. RefSeq
proteins (accessions prefixed `NP_`, `XP_`, `YP_`) are non-redundant and
preferred for annotation work.

### PubMed
**PubMed** comprises more than 36 million citations for biomedical
literature, including abstracts, MeSH terms, author affiliations, and links to
full text via PubMed Central (PMC). It is the entry point for finding primary
publications associated with a gene, variant, or method.

### SRA (Sequence Read Archive)
The **Sequence Read Archive** stores raw next-generation sequencing reads
(Illumina, PacBio, Oxford Nanopore, etc.) along with metadata describing the
experiment, library strategy (WGS, RNA-seq, ChIP-seq), and instrument. SRA
Experiment and Run accessions (e.g., `SRX...`, `SRR...`) let you reanalyze the
underlying reads of a published study.

### dbSNP
The **Single Nucleotide Polymorphism Database (dbSNP)** catalogs small-scale
genetic variations — single nucleotide polymorphisms (SNPs), small insertions
and deletions (indels), and microsatellites — across hundreds of organisms.
Each variant is assigned a unique `rs` (RefSNP) identifier (e.g.,
`rs123456789`). For soybean, dbSNP stores SNP calls discovered in
resequencing projects, cultivar panels, and mutagenized populations. Records
include allele frequency, flanking sequence, validation status, and links back
to BioProject and SRA. Use dbSNP to survey known variants in a gene before
designing marker assays or validating EMS mutations.

### GEO (Gene Expression Omnibus)
**GEO** is a public repository of high-throughput functional genomics data —
microarray and RNA-seq expression, methylation, and ChIP. Records are
organized as Series (`GSE...`), Samples (`GSM...`), and Platforms (`GPL...`).
Use GEO to compare the expression profile of a soybean gene across tissues or
stress conditions.

### OMIM
**Online Mendelian Inheritance in Man (OMIM)** is a curated catalog of human
genes and genetic phenotypes. While soybean is not a human system, OMIM is
useful for transferring functional insight from well-characterized human
orthologs to soybean genes identified by reciprocal BLAST.

### Genome
The **Genome** database lists assembled and annotated genomes for organisms
across the tree of life. Each record links to the assembly, annotation
release, chromosomes, and the BioProject/BioSample hierarchy. The soybean
*Glycine max* Wm82 reference genome is found here.

### Structure
The **Structure** database (Molecular Modeling Database, MMDB) contains
experimentally determined 3D structures from PDB, computationally derived
models from AlphaFold, and Conserved Domain (CDD) architectures. Use it to
predict the structural impact of a nonsynonymous mutation on a protein.

## 3. Entrez Search System

Entrez is NCBI's integrated search and retrieval system. A single query bar
(https://www.ncbi.nlm.nih.gov/search/) can target any database, and results
from one database link to related records in others.

### Basic search
A basic query is one or more terms optionally qualified by a field tag in
square brackets. For example, to find gene records mentioning p53 in the
context of cancer:

```
p53[gene] AND cancer[mesh]
```

Unqualified terms are matched against the default search fields of the target
database (often All Fields), which is convenient but can return noisy results.
Adding field qualifiers narrows the search to a specific index.

### Boolean operators
Entrez supports three Boolean operators, which **must be capitalized**:

- `AND` — both terms must be present (intersection).
- `OR` — either term may be present (union); useful for synonyms.
- `NOT` — exclude records containing the term (use sparingly; it can drop
  relevant hits).

Parentheses group sub-expressions. For example:

```
(glycine max[organism] OR soybean[title]) AND drought[title/abstract]
```

### Advanced search builder
The *Advanced* link under the search bar opens a builder that lists every
available field for the selected database, lets you type a value, and inserts
the qualified term into the query box with the correct syntax. This is the
recommended way to discover field tags and to construct complex queries without
memorizing them.

### Field qualifiers table
The table below lists the most commonly used field qualifiers across Entrez
databases.

| Qualifier | Field | Example |
|-----------|-------|---------|
| `[gene]` | Gene name | `wrky[gene]` |
| `[mesh]` | MeSH term | `drought stress[mesh]` |
| `[organism]` | Organism | `glycine max[organism]` |
| `[author]` | Author | `smith j[author]` |
| `[title]` | Article title | `mutagenesis[title]` |
| `[title/abstract]` | Title or abstract | `ems[title/abstract]` |
| `[journal]` | Journal name | `plant cell[journal]` |
| `[dp]` | Date of publication (YYYY/MM/DD) | `2020/01/01[dp]` |
| `[pdat]` | Publication date range | `2018:2024[pdat]` |
| `[uid]` | Record UID | `100798926[uid]` |
| `[accn]` | Accession | `nm_001252639[accn]` |
| `[seqid]` | Sequence ID | `gi|12345[seqid]` |
| `[keyword]` | Author keyword | `salt tolerance[keyword]` |
| `[property]` | Record property | `review[property]` |

## 4. BLAST Sequence Search

The Basic Local Alignment Search Tool (BLAST) finds regions of local
similarity between a query sequence and database sequences. The comparison
yields statistical matches that can infer homology and shared function.

### BLAST program types
Choose the program based on the type of your query and the type of the
database.

| Program | Query | Database | Typical use case |
|---------|-------|----------|------------------|
| `blastn` | Nucleotide | Nucleotide | General nucleotide similarity |
| `blastp` | Protein | Protein | Identify protein homologs |
| `blastx` | Translated nucleotide | Protein | Annotate a new transcript |
| `tblastn` | Protein | Translated nucleotide | Find a protein in a genome |
| `tblastx` | Translated nucleotide | Translated nucleotide | Find distant gene homologs |

### Step-by-step operation
1. **Enter the query.** Paste a FASTA sequence or an accession into the
   "Enter Query Sequence" box. You may also upload a file or enter a BLAST
   name.
2. **Select the database.** Choose a pre-built database (e.g., `nr`,
   `core_nt`) or a custom database. For SoyMutDB, use the built-in soybean
   CDS or genome databases.
3. **Choose the program.** The web interface auto-suggests a program based on
   the query type; confirm it matches your intent.
4. **Set parameters.** Expand "Algorithm parameters" to adjust word size,
   expect threshold, scoring, filters, and task mode (see below).
5. **Submit and review.** Click BLAST and wait for the results page, which
   shows a graphical overview, a hit table, and pairwise alignments.

### Parameter optimization
The table below summarizes the parameters that most strongly affect BLAST
results for nucleotide searches.

| Parameter | Megablast | blastn | blastn-short | Notes |
|-----------|-----------|--------|--------------|-------|
| `word_size` | 28 | 11 | 7 | Larger word = faster, less sensitive |
| `expect` (E-value) | 10 | 10 | 1000 | Lower = more stringent; use 0.001 for confident hits |
| `reward` | 1 | 2 | 1 | Match score |
| `penalty` | -2 | -3 | -3 | Mismatch penalty |
| `gapopen` | 0 | 5 | 5 | Cost to open a gap |
| `gapextend` | 0 | 2 | 2 | Cost to extend a gap |
| `dust` | yes | yes | yes | Masks low-complexity nucleotide regions |
| `soft_masking` | true | true | false | Apply masking only for finding seeds |
| `perc_identity` | optional | optional | optional | Minimum percent identity (0–100) |

For protein searches, replace DUST with SEG and use substitution matrices
(BLOSUM62 by default; BLOSUM45 for distant, BLOSUM80 for close homologs).

### Four task modes
Nucleotide-nucleotide BLAST offers four task modes that pre-configure the
parameters above for different biological scenarios:

- **megablast** — for highly similar sequences (e.g., the same gene in a
  close cultivar). Uses a large word size (28) for speed.
- **discontiguous megablast (dc-megablast)** — for interspecies comparisons.
  Uses discontiguous words to balance speed and sensitivity.
- **blastn** — for somewhat similar sequences. Smaller word size (11),
  higher sensitivity, slower.
- **blastn-short** — optimized for queries shorter than 30 nt. Uses a tiny
  word size (7) and a high E-value threshold to avoid missing short matches.

### Database selection guide
| Database | Content | When to use |
|----------|---------|-------------|
| `nr` | Non-redundant protein | Broad protein homology search |
| `core_nt` | Core nucleotide (GenBank + RefSeq) | Default nucleotide search |
| `refseq_rna` | RefSeq mRNA/ncRNA | Annotate transcripts against curated set |
| `refseq_protein` | RefSeq proteins | Annotate against curated proteins |
| `est` | Expressed Sequence Tags | Find expression evidence in related species |
| `wgs` | Whole Genome Shotgun | Search unassembled/contig data |
| `gss` | Genome Survey Sequences | Search single-pass genomic reads |
| `chromosome` | Complete chromosomes | Search finished reference chromosomes |
| `genome` | Genome assemblies | Search across whole assemblies |
| `pat` | Patented sequences | Check prior-art sequences |

### Result interpretation
The BLAST report contains several sections:

- **Score** — alignment bit-score; higher is better. Bit-scores are normalized
  across matrices so they are comparable between runs.
- **E-value** — expected number of chance hits with this score or better. An
  E-value of `1e-50` is highly significant; `10` is borderline. E-values
  depend on database size, so always interpret them relative to the database
  searched.
- **Identity%** — percent of identical residues in the alignment.
- **Coverage** (query coverage) — fraction of the query length that aligns.
  High identity with low coverage may indicate a domain match rather than a
  full-length homolog.
- **Taxonomy report** — the organisms producing hits; useful to detect
  contamination or horizontal transfer.

### Soybean-specific BLAST recommendations
When searching against the soybean genome or transcriptome, use the
following parameter guidelines:

- **Validating EMS mutations** — run megablast with `word_size=28`,
  `expect=1e-10`, and `perc_identity=99` to accept only near-perfect matches
  against the reference CDS or genome.
- **Gene family discovery** — start with blastn (`word_size=11`,
  `expect=1e-5`); if no hits are found, switch to dc-megablast for more
  distant homologs.
- **Short mutagenized reads (< 50 bp)** — use blastn-short with
  `expect=1000` to maximise sensitivity; manually inspect hits with
  bit-score < 50.
- **Cross-checking SoyMutDB variants** — BLAST the flanking sequence of a
  variant (100 bp upstream + 100 bp downstream) against the soybean RefSeq
  genome to confirm the genomic context.

## 5. JBrowse Genome Browser

JBrowse 2 is a next-generation genome browser with a fast, modular
architecture. SoyMutDB embeds JBrowse 2 to let users visualize variants,
genes, and user-uploaded tracks on the soybean reference genome.

### Overview
JBrowse 2 supports four view types:

- **Linear genome view** — the classic 1D track display along a chromosome.
- **Circular view** — synteny and rearrangement visualization on a circle.
- **Dotplot view** — pairwise comparison of two assemblies as a scatter plot.
- **Synteny view** — side-by-side linear views with connecting ribbons for
  homologous regions.

### Supported data formats
| Format | Use |
|--------|-----|
| FASTA | Reference sequence |
| GFF3 / GTF | Gene and feature annotation |
| BED | Generic intervals |
| BigBed | Indexed, scalable BED |
| BAM / CRAM | Read alignments |
| VCF (tabix-indexed) | Variants |
| BigWig | Quantitative signal (coverage, expression) |
| BEDPE | Structural variants / paired features |

### Key features
- **Structural variant visualization** — breakends, inversions, and
  translocations render directly from VCF.
- **Protein 3D structure** — view AlphaFold/PDB structures alongside the
  coding sequence.
- **Plugin ecosystem** — extensions for read vs. reference, multiple
  sequence alignment, and more.
- **Shared sessions** — share a precise view state via a URL.

### Navigation
- **Pan** — click and drag the track area, or use the arrow keys.
- **Zoom** — scroll wheel, the +/- buttons, or select a region with the mouse.
- **Locus search** — type a chromosome:position (e.g., `Gm01:5,000,000-6,000,000`)
  or a gene name into the location box and press Enter.

### Track types
| Track type | Displays |
|------------|----------|
| `ReferenceSequenceTrack` | Reference nucleotides / translations |
| `FeatureTrack` | Genes, exons, variants as boxes |
| `VariantTrack` | VCF variants with genotypes |
| `QuantitativeTrack` | BigWig signal as a histogram/line |
| `AlignmentsTrack` | BAM/CRAM pileup with mismatches |
| `PileupTrack` | Summarized alignment coverage |

### How to use JBrowse in SoyMutDB
1. On the SoyMutDB **Genome Browser** page, select the reference assembly
   (e.g., Wm82.a2.v1).
2. Toggle the tracks you want from the track selector — gene models, SoyMutDB
   variants, and any user-uploaded BigWig/BAM.
3. Search for a locus by gene name or chromosome coordinate.
4. Click a feature to open a details panel with annotation, variant impact,
   and links back to NCBI Gene and BLAST.

## 6. NCBI E-utilities API

The Entrez Programming Utilities (E-utilities) provide a stable HTTP API to
query and fetch NCBI records programmatically.

### Core tools
| Tool | Purpose |
|------|---------|
| `EInfo` | List databases and their indexed fields |
| `ESearch` | Search a database; returns a list of UIDs |
| `EFetch` | Download full records in a chosen format |
| `ESummary` | Fetch document summaries (metadata) |
| `ELink` | Find related records across databases |
| `EPost` | Upload UIDs to a server-side history |
| `EGQuery` | Global query counts across all databases |

### Rate limits
- **Without an API key:** at most **3 requests per second**.
- **With an API key:** up to **10 requests per second**.

Obtain a key from your NCBI account settings and pass it as the `api_key`
parameter on every request. Exceeding the limit returns HTTP 429 errors.

### Example workflow: search → fetch → parse
The following Python snippet uses `httpx` to find soybean gene UIDs for "WRKY"
and fetch their summaries.

```python
import time
import httpx

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
API_KEY = "YOUR_NCBI_API_KEY"  # optional but recommended

# 1. ESearch — find gene UIDs
params = {
    "db": "gene",
    "term": "WRKY[gene] AND glycine max[organism]",
    "retmax": 20,
    "retmode": "json",
}
if API_KEY:
    params["api_key"] = API_KEY
r = httpx.get(BASE + "/esearch.fcgi", params=params, timeout=30)
r.raise_for_status()
uids = r.json()["esearchresult"]["idlist"]

# 2. ESummary — fetch metadata for each UID
time.sleep(0.35)  # respect the 3 req/s limit without a key
summ = httpx.get(
    BASE + "/esummary.fcgi",
    params={"db": "gene", "id": ",".join(uids), "retmode": "json"},
    timeout=30,
)
summ.raise_for_status()
for uid, doc in summ.json()["result"].items():
    if uid == "uids":
        continue
    print(uid, doc.get("name"), doc.get("title"))
```

For large result sets, use `EPost` to upload UIDs to the history server and
then page through `EFetch` with `WebEnv` and `query_key`.

## 7. Best Practices

- **Always specify the organism.** Add `glycine max[organism]` (or the
  relevant species) to avoid being flooded with hits from model organisms.
- **Use field qualifiers for precision.** Prefer `drought[title/abstract]`
  over a bare `drought` term to target the right index.
- **Start with megablast, then relax.** Run megablast first for speed; if it
  returns nothing informative, switch to dc-megablast or blastn for distant
  homology.
- **Adjust E-value to your goal.** Use `1e-5` or stricter for confident
  orthology; relax to `1e-2` when exploring novel gene families.
- **Use batch processing for multiple queries.** Submit many sequences in one
  BLAST request (one FASTA file) or use E-utilities with the history server
  to avoid rate-limit errors.
- **Cache results.** E-utilities responses change rarely; cache them locally
  to reduce load and speed up repeated analyses.
- **Validate cross-database links.** When following an ELink from Gene to
  PubMed, check the publication date and journal to ensure relevance.
- **Log your queries.** Record the database, term, parameters, and date so
  your analysis is reproducible.

## 8. Result Interpretation Guide

### BLAST results
- **Alignment score (bits):** compare across hits within the same run; a
  bit-score of 80+ usually indicates clear homology.
- **E-value significance:** treat E ≤ 1e-5 as significant for nucleotide
  searches and E ≤ 1e-3 for protein searches, but always consider query
  length and database size.
- **Identity matrix:** inspect identity, similarity, and gaps together. A
  95% identity over 20% of the query is a domain hit, not a full ortholog.
- **Coverage:** require ≥ 70% query coverage for functional transfer unless
  you are deliberately searching for domains.

### Gene records
- **RefSeq transcripts:** the `XM_`/`NM_` accessions give the canonical
  transcript model; check the `XM_` vs `NM_` prefix — `NM_` records are
  experimentally validated, `XM_` are model-predicted.
- **GO annotations:** review the evidence codes (IDA, IMP, IEA, etc.); IEA
  (electronic) is the weakest.
- **Pathway info:** follow links to BioSystems and KEGG to place the gene in
  a biological context.

### Publication records
- **DOI:** use the DOI for permanent linking and citation; resolve it via
  `https://doi.org/<DOI>`.
- **PMID:** the PubMed ID is the stable handle for a citation within NCBI.
- **Abstract analysis:** read the abstract for the experimental system
  (organism, tissue, method) before transferring conclusions to soybean;
  confirm orthology before extrapolating function.

### Common pitfalls
- **Over-interpreting a single BLAST hit:** always cross-check the top hit
  against a reciprocal BLAST (query the hit sequence back against the
  original database) before claiming orthology.
- **Ignoring the database size effect on E-values:** the same alignment
  scores yield smaller E-values in larger databases; compare E-values only
  within the same database.
- **Confusing RefSeq and GenBank accessions:** GenBank accessions can be
  submitted by anyone and may lack curation; prefer RefSeq (`NM_`, `NP_`,
  `XM_`, `XP_`) records for annotation work.
- **Forgetting to filter low-complexity regions:** unfiltered searches can
  return hits driven by repetitive or coiled-coil regions rather than by
  true homology.
- **Trusting IEA annotations as experimental evidence:** Inferred from
  Electronic Annotation (IEA) is automated; seek records with IDA, IMP, or
  IPI evidence codes when biological confidence matters.

## 9. Soybean Mutation Research Strategies

This section provides specific search strategies for soybean mutation
research, complementing SoyMutDB with external NCBI resources.

### Finding EMS-induced mutations in NCBI
Ethyl methanesulfonate (EMS) mutagenesis creates predominantly G/C-to-A/T
transitions. To find EMS-induced mutations documented in NCBI:

1. **Search dbSNP** for soybean accessions with a "validated" filter,
   then restrict by variant class (`snv`) and functional impact
   (`missense`, `nonsense`).

2. **Query SRA** for raw sequencing data from EMS-treated populations
   using terms like:
   ```
   ("glycine max"[organism] OR soybean) AND (EMS OR "ethyl methanesulfonate")
   AND ("whole genome sequencing"[strategy] OR WGS)
   ```

3. **Cross-reference with PubMed** to find publications that describe
   specific soybean mutant lines, then extract the variant coordinates
   reported in supplementary tables.

### Using NCBI to validate SoyMutDB variants
SoyMutDB aggregates variants from multiple sources. When you encounter a
variant of interest:

1. **Check dbSNP for prior reports** — query the flanking sequence or
   genomic coordinate to see if the variant has been submitted by other
   projects. The presence of a RefSNP (`rs`) record adds confidence.

2. **Retrieve the reference sequence** from Nucleotide or RefSeq for the
   affected gene, then run BLAST to confirm that the variant coordinate
   maps to the expected locus.

3. **Search PubMed** for the gene name and "mutation" or "variant" to
   find functional studies that may have characterised the same allele.

4. **Examine SRA accessions** linked from a Gene record to check whether
   RNA-seq data exists for the relevant tissue or treatment, which can
   support expression-level interpretation of the variant.

### Database cross-linking workflow
| Step | Database | Action | Purpose |
|------|----------|--------|---------|
| 1 | SoyMutDB | Identify variant (gene, position, allele) | Start from mutation |
| 2 | NCBI Gene | Retrieve gene summary, RefSeq ID, GO terms | Annotate the locus |
| 3 | dbSNP | Search rs ID or coordinate for prior evidence | Validate novelty |
| 4 | PubMed | Search gene + variant keywords for literature | Find functional studies |
| 5 | SRA / GEO | Check expression data availability | Contextualise impact |
| 6 | BLAST | Confirm sequence specificity | Avoid mapping errors |

### Example queries for soybean researchers

**Find all soybean nucleotide sequences submitted in 2023–2024:**
```
glycine max[organism] AND 2023/01/01:2024/12/31[dp]
```

**Locate articles about soybean drought tolerance with functional data:**
```
(glycine max[organism] OR soybean[title]) AND drought[title/abstract]
AND (expression[title/abstract] OR transcriptome[title/abstract])
```

**Retrieve RefSeq protein records for soybean WRKY transcription factors:**
```
WRKY[gene] AND glycine max[organism] AND refseq[filter]
```

---

*This guide is maintained as part of SoyMutDB. For the latest NCBI
documentation, consult the official NCBI Handbook and the JBrowse 2
documentation.*
"""


# ---------------------------------------------------------------------------
# Chinese content
# ---------------------------------------------------------------------------

CONTENT_ZH = """\
> **摘要：** NCBI数据库检索综合操作指南，涵盖BLAST、Entrez、JBrowse和E-utilities工具

# NCBI数据库检索操作指南

## 1. 引言

美国国家生物技术信息中心（NCBI）隶属于美国国家医学图书馆（NLM），托管数十个相互关联的公共数据库，共同构成了全球规模最大的基因组与文献资源。SoyMutDB 与其中多项资源集成——使用 BLAST 进行序列相似性检索，使用 Entrez 检索系统进行跨库查询，使用 JBrowse 进行基因组可视化，并通过 E-utilities API 实现程序化访问——帮助大豆研究人员从感兴趣的突变出发，追溯到已发表的知识、功能注释和原始测序证据。

本指南逐步讲解如何高效地从 NCBI 检索信息，面向使用 SoyMutDB 的湿实验生物学家、生物信息学分析人员和数据策展人，适用于需要验证变异、注释基因或将表型追溯到原始文献的场景。每一节都结合概念性概述与具体参数、表格和实例，既可作为教程，也可作为日常参考。

阅读本指南后，您将能够：（1）针对不同问题选择合适的 NCBI 数据库；（2）使用字段限定符和布尔运算符构建精确的 Entrez 查询；（3）运行并调优 BLAST 检索，包括选择正确的程序、任务模式和参数；（4）在 JBrowse 2 中浏览大豆基因组并叠加 SoyMutDB 轨道；（5）从 Python 脚本调用 E-utilities API；（6）批判性地解读比对得分、E 值、基因记录和文献记录。

## 2. NCBI 核心数据库

NCBI 将数据按领域组织为不同的数据库，并通过 Entrez 检索系统相互链接。了解每个数据库收录的内容是构建高效查询的第一步。

### Gene（基因）
**Gene** 数据库是经过人工审核的多物种基因记录库。每条记录整合了基因命名、基因组位置、RefSeq 转录本与蛋白、已知别名、表型、通路（通过 BioSystems）、Gene Ontology（GO）注释、表达数据以及 PubMed 链接。对于大豆，Gene 记录以 NCBI Gene ID（如 `100798926`）为键，并与 Wm82 参考组装交叉引用。当需要某一基因位点的权威摘要时，请使用 Gene 数据库。

### Nucleotide（核苷酸）
**Nucleotide** 数据库（原 `nuccore`）汇集了来自 GenBank、RefSeq、PDB 和第三方注释（TPA）数据库的核苷酸序列，包括 mRNA、基因组 contig、BAC 克隆和整条染色体。记录以 accession.version 字符串标识（如 `NM_001252639.2`）。需要获取转录本或基因组区域的原始序列时，请使用 Nucleotide。

### Protein（蛋白）
**Protein** 数据库汇集了来自 GenBank、RefSeq、PDB、Swiss-Prot、PIR 和 PRF 的氨基酸序列，是运行 `blastp` 或构建多序列比对前获取序列的主要来源。RefSeq 蛋白（前缀为 `NP_`、`XP_`、`YP_`）去冗余且经过审核，注释工作应优先使用。

### PubMed
**PubMed** 收录超过 3600 万条生物医学文献引文，包括摘要、MeSH 主题词、作者单位以及通过 PubMed Central（PMC）链接的全文。它是查找与基因、变异或方法相关原始文献的入口。

### SRA（Sequence Read Archive，序列读取档案）
**SRA** 存储原始的二代测序 reads（Illumina、PacBio、Oxford Nanopore 等）以及描述实验、文库策略（WGS、RNA-seq、ChIP-seq）和仪器的元数据。SRA 的 Experiment 和 Run accession（如 `SRX...`、`SRR...`）可用于重新分析已发表研究的原始 reads。

### dbSNP（单核苷酸多态性数据库）
**dbSNP** 收录跨数百个物种的小规模遗传变异——单核苷酸多态性（SNP）、小的插入缺失（indel）和微卫星标记。每个变异被分配一个唯一的 `rs`（RefSNP）标识符（如 `rs123456789`）。对于大豆，dbSNP 存储了在重测序项目、品种群体和诱变群体中发现的 SNP 调用信息。记录包括等位基因频率、侧翼序列、验证状态以及回链到 BioProject 和 SRA 的链接。在设计标记检测或验证 EMS 突变之前，使用 dbSNP 调查基因中的已知变异。

### GEO（Gene Expression Omnibus）
**GEO** 是高通量功能基因组学数据的公共仓库——包括芯片和 RNA-seq 表达、甲基化和 ChIP 数据。记录按 Series（`GSE...`）、Sample（`GSM...`）和 Platform（`GPL...`）组织。可使用 GEO 比较大豆基因在不同组织或胁迫条件下的表达谱。

### OMIM
**OMIM（在线人类孟德尔遗传）** 是经过审核的人类基因和遗传表型目录。虽然大豆不是人类系统，但 OMIM 可用于将研究充分的人类同源基因的功能洞见，通过双向 BLAST 转移到大豆基因上。

### Genome（基因组）
**Genome** 数据库列出各物种已组装并注释的基因组。每条记录链接到组装、注释版本、染色体以及 BioProject/BioSample 层级结构。大豆 *Glycine max* Wm82 参考基因组即在此处。

### Structure（结构）
**Structure** 数据库（分子建模数据库 MMDB）包含来自 PDB 的实验测定三维结构、来自 AlphaFold 的计算模型以及保守结构域（CDD）架构。可用于预测错义突变对蛋白结构的影响。

## 3. Entrez 检索系统

Entrez 是 NCBI 的集成检索与获取系统。一个查询框（https://www.ncbi.nlm.nih.gov/search/）即可定位任意数据库，且一个数据库的结果可链接到其他数据库的相关记录。

### 基本检索
基本查询由若干检索词组成，每个词可用方括号中的字段标签限定。例如，查找在癌症背景下提及 p53 的基因记录：

```
p53[gene] AND cancer[mesh]
```

未限定的词会与目标数据库的默认检索字段（通常为 All Fields）匹配，使用方便但结果可能嘈杂。添加字段限定符可将检索范围收窄到特定索引。

### 布尔运算符
Entrez 支持三个布尔运算符，**必须大写**：

- `AND` — 两个词必须同时出现（交集）。
- `OR` — 任一词出现即可（并集），常用于同义词。
- `NOT` — 排除包含该词的记录（慎用，可能误删相关结果）。

括号用于分组子表达式。例如：

```
(glycine max[organism] OR soybean[title]) AND drought[title/abstract]
```

### 高级检索构建器
检索框下方的 *Advanced* 链接打开构建器，列出所选数据库的全部可用字段，输入值后会将带限定符的检索词以正确语法插入查询框。这是发现字段标签、构建复杂查询的推荐方式，无需记忆标签。

### 字段限定符表
下表列出 Entrez 各数据库中最常用的字段限定符。

| 限定符 | 字段 | 示例 |
|--------|------|------|
| `[gene]` | 基因名称 | `wrky[gene]` |
| `[mesh]` | MeSH 主题词 | `drought stress[mesh]` |
| `[organism]` | 物种 | `glycine max[organism]` |
| `[author]` | 作者 | `smith j[author]` |
| `[title]` | 文章标题 | `mutagenesis[title]` |
| `[title/abstract]` | 标题或摘要 | `ems[title/abstract]` |
| `[journal]` | 期刊 | `plant cell[journal]` |
| `[dp]` | 出版日期（YYYY/MM/DD） | `2020/01/01[dp]` |
| `[pdat]` | 出版日期范围 | `2018:2024[pdat]` |
| `[uid]` | 记录 UID | `100798926[uid]` |
| `[accn]` | 登录号 | `nm_001252639[accn]` |
| `[seqid]` | 序列 ID | `gi|12345[seqid]` |
| `[keyword]` | 作者关键词 | `salt tolerance[keyword]` |
| `[property]` | 记录属性 | `review[property]` |

## 4. BLAST 序列检索

基本局部比对搜索工具（BLAST）用于查找查询序列与数据库序列之间的局部相似区域，并通过统计评估推断同源性和共有功能。

### BLAST 程序类型
根据查询序列和数据库的类型选择程序。

| 程序 | 查询 | 数据库 | 典型用途 |
|------|------|--------|----------|
| `blastn` | 核苷酸 | 核苷酸 | 通用核苷酸相似性检索 |
| `blastp` | 蛋白 | 蛋白 | 鉴定蛋白同源 |
| `blastx` | 翻译的核苷酸 | 蛋白 | 注释新转录本 |
| `tblastn` | 蛋白 | 翻译的核苷酸 | 在基因组中查找蛋白 |
| `tblastx` | 翻译的核苷酸 | 翻译的核苷酸 | 查找远缘基因同源 |

### 操作步骤
1. **输入查询序列。** 将 FASTA 序列或登录号粘贴到“Enter Query Sequence”框中，也可上传文件或输入 BLAST 名称。
2. **选择数据库。** 选择预构建数据库（如 `nr`、`core_nt`）或自定义数据库。SoyMutDB 中请使用内置的大豆 CDS 或基因组数据库。
3. **选择程序。** 网页界面会根据查询类型自动建议程序，请确认其符合您的意图。
4. **设置参数。** 展开“Algorithm parameters”调整 word size、期望阈值、打分、过滤器和任务模式（见下）。
5. **提交并查看。** 点击 BLAST，等待结果页，其中包含图形化概览、命中表和两两比对。

### 参数优化
下表汇总了对核苷酸检索结果影响最大的参数。

| 参数 | Megablast | blastn | blastn-short | 说明 |
|------|-----------|--------|--------------|------|
| `word_size` | 28 | 11 | 7 | 字越大越快但灵敏度越低 |
| `expect`（E 值） | 10 | 10 | 1000 | 越低越严格；可信命中用 0.001 |
| `reward` | 1 | 2 | 1 | 匹配得分 |
| `penalty` | -2 | -3 | -3 | 错配罚分 |
| `gapopen` | 0 | 5 | 5 | 打开空位代价 |
| `gapextend` | 0 | 2 | 2 | 延伸空位代价 |
| `dust` | yes | yes | yes | 屏蔽低复杂度核苷酸区域 |
| `soft_masking` | true | true | false | 仅在寻找种子时屏蔽 |
| `perc_identity` | 可选 | 可选 | 可选 | 最小一致性百分比（0–100） |

蛋白检索时，用 SEG 替代 DUST，并使用替换矩阵（默认 BLOSUM62；远缘用 BLOSUM45，近缘用 BLOSUM80）。

### 四种任务模式
核苷酸-核苷酸 BLAST 提供四种任务模式，针对不同生物学场景预配置上述参数：

- **megablast** — 用于高度相似的序列（如近缘品种中的同一基因）。使用大字长（28）以提速。
- **discontiguous megablast（dc-megablast）** — 用于种间比较。使用非连续字，兼顾速度与灵敏度。
- **blastn** — 用于有一定相似性的序列。字长较小（11），灵敏度更高，速度较慢。
- **blastn-short** — 针对短于 30 nt 的查询优化。使用极小字长（7）和高 E 值阈值，避免遗漏短匹配。

### 数据库选择指南
| 数据库 | 内容 | 使用场景 |
|--------|------|----------|
| `nr` | 非冗余蛋白 | 广泛的蛋白同源检索 |
| `core_nt` | 核心核苷酸（GenBank + RefSeq） | 默认核苷酸检索 |
| `refseq_rna` | RefSeq mRNA/ncRNA | 用审核集注释转录本 |
| `refseq_protein` | RefSeq 蛋白 | 用审核蛋白注释 |
| `est` | 表达序列标签 | 在近缘物种中查找表达证据 |
| `wgs` | 全基因组鸟枪法 | 检索未组装/contig 数据 |
| `gss` | 基因组调查序列 | 检索单遍基因组 reads |
| `chromosome` | 完整染色体 | 检索完成的参考染色体 |
| `genome` | 基因组组装 | 跨组装检索 |
| `pat` | 专利序列 | 检索在先专利序列 |

### 结果解读
BLAST 报告包含若干部分：

- **Score（得分）** — 比对的 bit-score，越高越好。bit-score 跨矩阵归一化，可在不同运行间比较。
- **E-value（E 值）** — 期望出现该得分或更好的随机命中数。`1e-50` 极显著；`10` 处于边缘。E 值依赖数据库大小，解读时务必相对于所检索数据库。
- **Identity%（一致性）** — 比对中相同残基的百分比。
- **Coverage（查询覆盖度）** — 与查询序列比对上的长度比例。高一致性但低覆盖可能仅是结构域匹配，而非全长同源。
- **Taxonomy report（分类报告）** — 产生命中的物种列表，可用于检测污染或水平转移。

### 大豆特异性 BLAST 推荐
针对大豆基因组或转录组进行检索时，请参考以下参数指南：

- **验证 EMS 突变** — 使用 megablast，设置 `word_size=28`、`expect=1e-10`、`perc_identity=99`，以仅接受与参考 CDS 或基因组的近乎完美匹配。
- **基因家族发现** — 从 blastn（`word_size=11`、`expect=1e-5`）开始；若无命中，切换至 dc-megablast 查找更远缘的同源。
- **短诱变 reads（< 50 bp）** — 使用 blastn-short 和 `expect=1000` 以最大化灵敏度；手动检查 bit-score < 50 的命中。
- **交叉验证 SoyMutDB 变异** — 将变异侧翼序列（上游 100 bp + 下游 100 bp）与大豆 RefSeq 基因组进行 BLAST，以确认基因组上下文。

## 5. JBrowse 基因组浏览器

JBrowse 2 是新一代基因组浏览器，具有快速、模块化的架构。SoyMutDB 嵌入 JBrowse 2，让用户在大豆参考基因组上可视化变异、基因和用户上传的轨道。

### 概述
JBrowse 2 支持四种视图类型：

- **线性基因组视图** — 经典的沿染色体 1D 轨道展示。
- **环状视图** — 在圆环上展示共线性与重排。
- **点阵视图** — 两个组装的两两比较散点图。
- **共线性视图** — 并排线性视图，用连接带表示同源区域。

### 支持的数据格式
| 格式 | 用途 |
|------|------|
| FASTA | 参考序列 |
| GFF3 / GTF | 基因与特征注释 |
| BED | 通用区间 |
| BigBed | 索引化、可扩展的 BED |
| BAM / CRAM | reads 比对 |
| VCF（tabix 索引） | 变异 |
| BigWig | 定量信号（覆盖度、表达） |
| BEDPE | 结构变异/成对特征 |

### 关键特性
- **结构变异可视化** — 断点、倒位和易位可直接从 VCF 渲染。
- **蛋白三维结构** — 在编码序列旁查看 AlphaFold/PDB 结构。
- **插件生态** — 提供 reads 对参考、多序列比对等扩展。
- **共享会话** — 通过 URL 共享精确的视图状态。

### 导航
- **平移** — 点击并拖动轨道区域，或使用方向键。
- **缩放** — 滚轮、+/- 按钮，或用鼠标框选区域。
- **位点搜索** — 在位置框中输入 染色体:位置（如 `Gm01:5,000,000-6,000,000`）或基因名，回车跳转。

### 轨道类型
| 轨道类型 | 展示内容 |
|----------|----------|
| `ReferenceSequenceTrack` | 参考核苷酸/翻译 |
| `FeatureTrack` | 基因、外显子、变异（方框） |
| `VariantTrack` | 带基因型的 VCF 变异 |
| `QuantitativeTrack` | BigWig 信号（直方图/折线） |
| `AlignmentsTrack` | BAM/CRAM pileup 及错配 |
| `PileupTrack` | 汇总的比对覆盖度 |

### 在 SoyMutDB 中使用 JBrowse
1. 在 SoyMutDB **基因组浏览器**页面，选择参考组装（如 Wm82.a2.v1）。
2. 从轨道选择器中勾选所需轨道——基因模型、SoyMutDB 变异以及任何用户上传的 BigWig/BAM。
3. 按基因名或染色体坐标搜索位点。
4. 点击特征打开详情面板，包含注释、变异影响以及回链到 NCBI Gene 和 BLAST 的链接。

## 6. NCBI E-utilities API

Entrez 编程工具（E-utilities）提供稳定的 HTTP API，用于以程序化方式查询和获取 NCBI 记录。

### 核心工具
| 工具 | 用途 |
|------|------|
| `EInfo` | 列出数据库及其索引字段 |
| `ESearch` | 检索数据库，返回 UID 列表 |
| `EFetch` | 以指定格式下载完整记录 |
| `ESummary` | 获取文档摘要（元数据） |
| `ELink` | 跨库查找相关记录 |
| `EPost` | 将 UID 上传到服务器端历史 |
| `EGQuery` | 跨所有数据库的全局查询计数 |

### 速率限制
- **无 API key：** 每秒最多 **3 个请求**。
- **有 API key：** 每秒最多 **10 个请求**。

在 NCBI 账户设置中获取 key，并在每次请求时通过 `api_key` 参数传入。超限会返回 HTTP 429 错误。

### 示例工作流：检索 → 获取 → 解析
以下 Python 片段使用 `httpx` 查找“WRKY”相关的大豆基因 UID 并获取其摘要。

```python
import time
import httpx

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
API_KEY = "YOUR_NCBI_API_KEY"  # 可选但推荐

# 1. ESearch — 查找基因 UID
params = {
    "db": "gene",
    "term": "WRKY[gene] AND glycine max[organism]",
    "retmax": 20,
    "retmode": "json",
}
if API_KEY:
    params["api_key"] = API_KEY
r = httpx.get(BASE + "/esearch.fcgi", params=params, timeout=30)
r.raise_for_status()
uids = r.json()["esearchresult"]["idlist"]

# 2. ESummary — 获取每个 UID 的元数据
time.sleep(0.35)  # 无 key 时遵守 3 请求/秒限制
summ = httpx.get(
    BASE + "/esummary.fcgi",
    params={"db": "gene", "id": ",".join(uids), "retmode": "json"},
    timeout=30,
)
summ.raise_for_status()
for uid, doc in summ.json()["result"].items():
    if uid == "uids":
        continue
    print(uid, doc.get("name"), doc.get("title"))
```

对于大规模结果集，可使用 `EPost` 将 UID 上传到历史服务器，再用 `WebEnv` 和 `query_key` 分页获取 `EFetch`。

## 7. 最佳实践

- **始终指定物种。** 添加 `glycine max[organism]`（或相关物种），避免被模式生物的命中淹没。
- **使用字段限定符提高精度。** 优先使用 `drought[title/abstract]` 而非裸词 `drought`，以定位正确索引。
- **先用 megablast，再放宽。** 先跑 megablast 提速；若无信息量结果，再切换到 dc-megablast 或 blastn 检索远缘同源。
- **按目标调整 E 值。** 置信直系同源用 `1e-5` 或更严；探索新基因家族时可放宽到 `1e-2`。
- **多查询使用批处理。** 在一次 BLAST 请求中提交多条序列（一个 FASTA 文件），或使用 E-utilities 的历史服务器，避免触发速率限制。
- **缓存结果。** E-utilities 响应变化较少，本地缓存可减轻负载并加速重复分析。
- **验证跨库链接。** 从 Gene 经 ELink 跳转到 PubMed 时，核对出版日期和期刊以确保相关性。
- **记录查询。** 记下数据库、检索词、参数和日期，保证分析可复现。

## 8. 结果解读指南

### BLAST 结果
- **比对得分（bits）：** 在同一运行内跨命中比较；bit-score 80+ 通常表明明确同源。
- **E 值显著性：** 核苷酸检索 E ≤ 1e-5、蛋白检索 E ≤ 1e-3 视为显著，但务必结合查询长度和数据库大小。
- **一致性矩阵：** 同时查看一致性、相似度和空位。95% 一致性但仅覆盖查询的 20% 是结构域命中，而非全长直系同源。
- **覆盖度：** 除非刻意检索结构域，否则功能转移时要求查询覆盖度 ≥ 70%。

### 基因记录
- **RefSeq 转录本：** `XM_`/`NM_` 登录号给出规范转录本模型；注意前缀——`NM_` 经实验验证，`XM_` 为模型预测。
- **GO 注释：** 审查证据代码（IDA、IMP、IEA 等）；IEA（电子注释）最弱。
- **通路信息：** 跟随 BioSystems 和 KEGG 链接，将基因置于生物学背景中。

### 文献记录
- **DOI：** 使用 DOI 进行永久链接和引用，通过 `https://doi.org/<DOI>` 解析。
- **PMID：** PubMed ID 是 NCBI 内引用的稳定句柄。
- **摘要分析：** 将结论外推到大豆前，先阅读摘要中的实验体系（物种、组织、方法）；外推功能前确认同源性。

### 常见陷阱
- **过度解读单条 BLAST 命中：** 在断言直系同源前，务必用反向 BLAST（将命中序列回检到原数据库）交叉验证最佳命中。
- **忽视数据库大小对 E 值的影响：** 相同比对得分在更大的数据库中会得到更小的 E 值；只能在同一数据库内比较 E 值。
- **混淆 RefSeq 与 GenBank 登录号：** GenBank 登录号任何人都可以提交，可能缺乏审核；注释工作应优先使用 RefSeq（`NM_`、`NP_`、`XM_`、`XP_`）记录。
- **忘记屏蔽低复杂度区域：** 未屏蔽的检索可能返回由重复序列或卷曲螺旋区域驱动的命中，而非真实同源。
- **将 IEA 注释当作实验证据：** IEA（电子注释）为自动推断；当生物学可信度重要时，应寻找带 IDA、IMP 或 IPI 证据代码的记录。

## 9. 大豆突变研究策略

本节提供针对大豆突变研究的具体检索策略，将 SoyMutDB 与外部 NCBI 资源相结合。

### 在 NCBI 中查找 EMS 诱导突变
甲磺酸乙酯（EMS）诱变主要产生 G/C-to-A/T 转换。要在 NCBI 中查找已记录的 EMS 诱导突变：

1. **搜索 dbSNP**，使用"validated"过滤器筛选大豆 accession，然后按变异类别（`snv`）和功能影响（`missense`、`nonsense`）进一步限制。

2. **查询 SRA** 以获取 EMS 处理群体的原始测序数据，使用如下检索词：
   ```
   ("glycine max"[organism] OR soybean) AND (EMS OR "ethyl methanesulfonate")
   AND ("whole genome sequencing"[strategy] OR WGS)
   ```

3. **交叉参考 PubMed** 查找描述特定大豆突变体系的文献，然后从补充表格中提取报告的变异坐标。

### 使用 NCBI 验证 SoyMutDB 变异
SoyMutDB 汇集了来自多个来源的变异。当您遇到感兴趣的变异时：

1. **在 dbSNP 中检查既往报告** — 查询侧翼序列或基因组坐标，查看该变异是否已被其他项目提交。存在 RefSNP（`rs`）记录可增加可信度。

2. **从 Nucleotide 或 RefSeq 检索受影响基因的参考序列**，然后运行 BLAST 确认变异坐标映射到预期的基因座。

3. **在 PubMed 中搜索基因名称加"mutation"或"variant"**，查找可能已描述同一等位基因的功能研究。

4. **检查 Gene 记录链接的 SRA accession**，查看相关组织或处理是否存在 RNA-seq 数据，这有助于从表达水平解读变异的影响。

### 数据库交叉链接工作流程
| 步骤 | 数据库 | 操作 | 目的 |
|------|--------|------|------|
| 1 | SoyMutDB | 识别变异（基因、位置、等位基因） | 从突变出发 |
| 2 | NCBI Gene | 获取基因摘要、RefSeq ID、GO 术语 | 注释基因座 |
| 3 | dbSNP | 搜索 rs ID 或坐标获取既往证据 | 验证新颖性 |
| 4 | PubMed | 搜索基因 + 变异关键词获取文献 | 查找功能研究 |
| 5 | SRA / GEO | 检查表达数据可用性 | 评估影响背景 |
| 6 | BLAST | 确认序列特异性 | 避免映射错误 |

### 大豆研究人员示例查询

**查找 2023–2024 年提交的所有大豆核苷酸序列：**
```
glycine max[organism] AND 2023/01/01:2024/12/31[dp]
```

**查找关于大豆耐旱性且包含功能数据的文章：**
```
(glycine max[organism] OR soybean[title]) AND drought[title/abstract]
AND (expression[title/abstract] OR transcriptome[title/abstract])
```

**检索大豆 WRKY 转录因子的 RefSeq 蛋白记录：**
```
WRKY[gene] AND glycine max[organism] AND refseq[filter]
```

---

*本指南由 SoyMutDB 维护。如需最新 NCBI 文档，请查阅官方 NCBI Handbook 和 JBrowse 2 文档。*
"""


# ---------------------------------------------------------------------------
# Seed logic
# ---------------------------------------------------------------------------

# Metadata fields requested by the task. Only those actually mapped as columns
# on the StaticPage model are persisted; the rest are skipped so the script
# stays runnable against the current schema.
_METADATA_FIELDS: dict[str, Any] = {
    "slug": SLUG,
    "title_en": TITLE_EN,
    "title_zh": TITLE_ZH,
    "summary": SUMMARY_EN,
    "status": STATUS,
    "category": CATEGORY,
    "sort_order": SORT_ORDER,
}


def _apply_metadata(page: StaticPage) -> list[str]:
    """Apply metadata to *page*, persisting only mapped columns.

    Returns the list of field names that were skipped because they are not
    present on the current ``StaticPage`` model.
    """
    mapped_columns = set(StaticPage.__table__.columns.keys())
    skipped: list[str] = []
    for field, value in _METADATA_FIELDS.items():
        if field in mapped_columns:
            setattr(page, field, value)
        else:
            skipped.append(field)
    # content is always mapped, set explicitly for clarity.
    page.content_en = CONTENT_EN
    page.content_zh = CONTENT_ZH
    return skipped


# A tiny holder so _upsert_content_version can hand the object back to the
# session scope without changing its signature.
_PENDING_CONTENT_VERSION: list[Any] = [None]


async def _upsert_content_version(page_id: int) -> None:
    """Create a ContentVersion (version=1) row if the model exists."""
    if not _HAS_CONTENT_VERSION or ContentVersion is None:
        logger.warning(
            "ContentVersion model is not present in the current schema; "
            "skipping version record creation."
        )
        return

    # Best-effort: the ContentVersion schema is not fixed in the current
    # codebase, so we only set commonly-expected fields when they exist.
    cv = ContentVersion()  # type: ignore[abstract]
    column_names = set(ContentVersion.__table__.columns.keys())  # type: ignore[union-attr]
    candidate_fields = {
        "page_id": page_id,
        "version": 1,
        "content_en": CONTENT_EN,
        "content_zh": CONTENT_ZH,
        "title_en": TITLE_EN,
        "title_zh": TITLE_ZH,
        "summary": SUMMARY_EN,
    }
    for field, value in candidate_fields.items():
        if field in column_names:
            setattr(cv, field, value)
    _PENDING_CONTENT_VERSION[0] = cv


async def seed_ncbi_guide() -> None:
    """Insert or update the NCBI database retrieval guide static page."""
    factory = get_session_factory()
    async with factory() as session:
        existing = await session.scalar(
            select(StaticPage).where(StaticPage.slug == SLUG)
        )

        if existing is None:
            page = StaticPage()
            session.add(page)
            action = "created"
        else:
            page = existing
            action = "updated"

        skipped = _apply_metadata(page)
        await session.flush()

        # ContentVersion (optional, only if the model exists).
        _PENDING_CONTENT_VERSION[0] = None
        await _upsert_content_version(page.id)  # type: ignore[arg-type]
        cv = _PENDING_CONTENT_VERSION[0]
        if cv is not None:
            session.add(cv)

        await session.commit()

        print(
            f"[seed_ncbi_guide] {action} StaticPage slug={page.slug!r} "
            f"id={page.id}"
        )
        if skipped:
            print(
                "[seed_ncbi_guide] note: the following requested fields are "
                "not mapped on the current StaticPage model and were not "
                "persisted: " + ", ".join(skipped)
            )
        if not _HAS_CONTENT_VERSION:
            print(
                "[seed_ncbi_guide] note: ContentVersion model not found; "
                "no version record was created."
            )
        else:
            print(
                "[seed_ncbi_guide] ContentVersion record (version=1) "
                "created."
            )


async def _main() -> None:
    await seed_ncbi_guide()
    await close_db()


def main() -> None:
    """Console-script entry point."""
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(_main())


if __name__ == "__main__":
    main()
