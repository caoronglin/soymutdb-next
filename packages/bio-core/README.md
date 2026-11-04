# soymutdb-bio-core

SoyMutDB 0.1.2 biological computation core. A single Rust kernel exposed to
Python 3.15 through PyO3/maturin.

## Ownership (single owner per scientific action)

| Action | Owner |
| --- | --- |
| Exact / approximate matching, pairwise alignment, ORF, statistics | Rust-Bio (`bio 4.2.2`) |
| IUPAC/case-aware reverse complement | this crate (`sequence::reverse_complement`; Rust-Bio only a test oracle) |
| Fixed-k k-mers, standard genetic code translation | `bio-seq 0.15.2` |
| 0-based half-open interval overlap | `rust-lapper 1.3.0` |
| FASTA/FASTQ/BED bounded validation | `noodles 0.118.0` |
| Auth, release/assembly resolution, SQL, object storage, jobs | Python API / Celery worker (never this crate) |

## Coordinates

Internal intervals are 0-based half-open `[start0, end0)`; public genome
coordinates are 1-based inclusive. Conversion lives only in `coordinates.rs`.
Adjacent intervals do not overlap. Coverage is a union, not a record count.

## Genetic codes

Only NCBI translation table 1 (`STANDARD`) is implemented. Any other id is
rejected with `UNKNOWN_GENETIC_CODE`; there is no silent fallback.

## Build

```bash
cargo fmt --all -- --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all-targets
maturin build --release --interpreter python3.15 --out ../../artifacts/wheels
```

The wheel must be installed into the API/worker environments before their
tests run; no runtime Rust toolchain is needed in production images.

## Python surface

```python
from soymutdb_bio_core import (
    reverse_complement, find_matches, align_pairwise, sequence_statistics,
    find_orfs, translate_sequence, kmer_counts, overlap_intervals,
    validate_fasta, validate_fastq, validate_bed, capabilities,
    BioCoreException,
)
```

Every failure raises `BioCoreException((code, message))`. No panic crosses the
FFI boundary, and error messages never contain sequence content or paths.
