# Local minimal search validation

> **已归档（2026-10-01）**：一次性任务笔记与旧状态视图（结论已进入现状视图与计划）。继任：docs/dev/project-status.md；任务级进度见 `docs/aegis/plans/`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

This is a small, no-Docker preview for the supplied local test files. It serves
only on `127.0.0.1`, reads the source files in place, keeps the parsed index in
memory, and writes no database or generated data. It does not change the normal
SoyMutDB public or internal site builds.

The dataset is **unpublished test data**. The TSV has test-site coordinates,
stock labels, confidence and gene annotations, but no REF/ALT alleles. A result
is therefore a **test site**, not a complete variant and not a released public
record. The service does not read the reference FASTA body or verify alleles.

## Source files and observed counts

| Role | File | Observed contents |
| --- | --- | ---: |
| Reference sequence lengths and offsets | `01_annot/Gmax_880_v6.0.fa.fai` | 20 sequences, Gm01–Gm20 |
| Gene annotation | `01_annot/Gmax_880_Wm82.a6.v1.gene.gff3` | 48,387 gene features; header declares v6.0 / Wm82.a6.v1 |
| Test-site rows | `02_mut-infor/mu-infor_Gmax_880_Wm82-test.txt` | 3,697 data rows and 11 columns |

All reported genomic coordinates use **1-based inclusive** positions. The TSV
gene IDs are matched exactly to GFF3 IDs. In the supplied data, all 3,697 IDs
exist in GFF3, all 3,697 chromosome labels agree with those genes, and all
positions are within the matching FAI sequence length. GFF3 sequence names are
also checked against the FAI. The source files are never edited.

The TSV has three older-assembly alias columns (`W82_V2`, `W82_V4`, and
`DN53_V1`). The local search intentionally does not load or search these
columns. Their values are not a cross-version mapping contract, and the service
does not infer v6-to-v4/v2 equivalence from names, coordinates, or aliases.
In the supplied file, 47 distinct alias values in each of those columns occur
against more than one v6 gene ID, so they cannot be treated as unique
cross-version keys.

## Coordinate and annotation policy

The TSV's `gene_id` and `feature` values are returned as supplied. The service
checks that a gene exists in this same GFF3 and is on the TSV chromosome; it
checks that the site coordinate is within that chromosome's reference bounds.
It does **not** require a site to fall inside the annotated gene interval.

In the supplied TSV, 3,202 of 3,697 sites fall inside the interval of their
annotated gene. The other 495 are outside that gene interval: 224 have a `us`
feature label, 189 have `ds`, and 82 have `gene`. Of these 495, 493 are outside
every GFF3 gene interval and two fall within another gene interval. The UI/API
reports `gene_span_relation` against the TSV's annotated gene and preserves the
original gene ID and feature. It does not call these rows invalid, claim the
annotated gene contains the site, or silently assign another gene.

Malformed or inconsistent input is a startup error; rows are never silently
dropped. The service rejects malformed FAI/GFF3/TSV rows, duplicate sequence or
gene IDs, duplicate test-site IDs, unknown chromosomes, out-of-range positions,
unknown TSV gene IDs, gene/chromosome mismatches, invalid confidence codes,
and invalid availability codes. TSV errors include the source row number. A
gene-span mismatch alone is not a rejection condition.

## Start and use

From the repository root, run:

```bash
python3 scripts/minimal_search.py --data-dir "/home/rlcao/下载/03_soymut" --port 8765
```

Open <http://127.0.0.1:8765/>. The page provides gene ID/name search, optional
gene-interval filters, and physical-position search over TSV test sites with
chromosome, range, gene ID, stock, confidence and availability filters. Both
result lists are paginated. Stop the service with Ctrl-C in its terminal.

The read-only JSON endpoints are:

| Endpoint | Purpose |
| --- | --- |
| `/api/meta` | Assembly, annotation, source filenames, chromosome lengths and record counts |
| `/api/genes` | Gene ID/name search with optional chromosome and inclusive interval overlap filters |
| `/api/test-sites` | Test-site position search with stock and source annotation filters |

All responses identify `Gmax_880_v6.0`, `Wm82.a6.v1`, the
`unpublished_test_data` status and the `1-based-inclusive` coordinate system.
The listener is hard-coded to IPv4 loopback; there is no host option or
cross-origin API allowlist.

## Local validation

The focused tests use temporary synthetic files for API validation, inclusive
coordinate filtering, pagination, security headers and malformed input
behavior. To also run the supplied-data integration audit:

```bash
SOYMUTDB_TEST_DATA_DIR="/home/rlcao/下载/03_soymut" \
  python3 -m unittest scripts.test_minimal_search -v
```

The real-file integration check expects 20 FAI sequences, 48,387 genes, 3,697
test sites and the exact example `Gm01:98256` →
`SOYTE1M-Gm01-98256` / `Glyma.01G000100.Wm82.a6.v1`. This is a local test
deployment only; it does not publish or promote any record.
