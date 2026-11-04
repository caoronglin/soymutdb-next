"""Minimal usage of the compiled wheel (requires CPython 3.15)."""
from soymutdb_bio_core import (
    capabilities,
    reverse_complement,
    kmer_counts,
    translate_sequence,
    overlap_intervals,
)

print(capabilities())
print(reverse_complement("ATGCRY"))                  # RYGCAT
print(kmer_counts("ACGTACGTNACG", 4))               # spec golden
print(translate_sequence("ATGAAATAA"))               # MK*
print(overlap_intervals([(10, 20, 0)], [(10, 20)]))
