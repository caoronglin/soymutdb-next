# Enrichment annotation snapshots

GO and KEGG enrichment data is release data. `gene_annotation_sets` stores one
immutable source identity for each release / assembly / ontology tuple, and
`gene_annotations` stores the gene-to-term evidence rows. Composite foreign
keys keep each row tied to the matching assembly, release, and assembly-scoped
gene accession. The API returns the annotation source name, version, public
URL, checksum, and import timestamp beside the assembly and release context.

## Normalized TSV format

The importer accepts UTF-8 TSV with a header. `gene_id`, `term_id`, and
`term_name` are required. `ontology`, `evidence_code`, `reference`, and
`qualifier` are optional. Ontology is selected once for the file with the CLI;
if an `ontology` column is present, each row must match it.

| gene_id | term_id | term_name | evidence_code | reference |
| --- | --- | --- | --- | --- |
| Glyma.01G000100 | GO:0008150 | biological process | IEA | PMID:123456 |

Exact duplicate evidence rows are collapsed. Multiple evidence records for the
same gene and term are retained. Unknown gene accessions, conflicting names
for one term, unsupported columns, and malformed rows reject the entire
transaction.

## Import a source snapshot

Run from `apps/api` with the API environment configured:

```bash
python scripts/import_gene_annotations.py /path/to/annotations.tsv \
  --release-id 12 \
  --assembly-id 3 \
  --ontology go \
  --source-name SoyBase-GO \
  --source-version 2026-08 \
  --source-url https://source.example/annotations/2026-08
```

Replace the example source name, version, and URL with the exact licensed
upstream snapshot being imported.

The importer computes and persists SHA-256; `--sha256` optionally checks a
separately recorded expected digest. Imports are accepted only for a draft
release whose assembly matches the selected release. The first import for an
ontology is immutable within that release. Repeating the same source and
checksum is idempotent; changed source data requires a new release.

No annotation dataset is bundled with the repository. Until an operator loads
a properly licensed, assembly-matched source, enrichment returns the existing
explicit empty-result message and reports that no annotation source is loaded.
