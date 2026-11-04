//! Golden scientific cases derived from the 2026-11-05 specification.
use soymutdb_bio_core::intervals::{self, IntervalRecord};
use soymutdb_bio_core::sequence::{self, AlignmentMode, Alphabet};
use soymutdb_bio_core::translation;

#[test]
fn spec_reverse_complement_iupac() {
    assert_eq!(
        sequence::reverse_complement(b"ATGCRY", Alphabet::Dna, false).unwrap(),
        b"RYGCAT"
    );
}

#[test]
fn spec_kmer_golden() {
    let r = sequence::kmer_counts(b"ACGTACGTNACG", 4, true, "skip", 1000).unwrap();
    assert_eq!(
        (
            r.total_windows,
            r.valid_windows,
            r.skipped_windows,
            r.distinct_kmers
        ),
        (9, 5, 4, 3)
    );
    assert_eq!(r.items.iter().map(|i| i.count).sum::<usize>(), 5);
}

#[test]
fn spec_interval_golden() {
    let idx = intervals::build_index(&[
        IntervalRecord {
            start0: 10,
            end0: 20,
            record_index: 0,
        },
        IntervalRecord {
            start0: 19,
            end0: 30,
            record_index: 1,
        },
    ])
    .unwrap();
    let r = intervals::find_overlaps(&idx, 10, 20, 100).unwrap();
    assert_eq!(r.overlap_count, 2);
    assert_eq!(r.covered_bp, 10);
}

#[test]
fn spec_alignment_golden() {
    let r = sequence::align_pairwise(
        b"ACGT",
        b"ACGT",
        Alphabet::Dna,
        AlignmentMode::Local,
        2,
        -3,
        -5,
        -1,
    )
    .unwrap();
    assert_eq!(r.score, 8);
    assert_eq!(r.cigar, "4M");
    assert!((r.identity - 1.0).abs() < 1e-12);
}

#[test]
fn spec_translation_64_codons() {
    let bases = b"ACGT";
    let mut seq = Vec::new();
    for &a in bases {
        for &b in bases {
            for &c in bases {
                seq.extend_from_slice(&[a, b, c]);
            }
        }
    }
    let r = translation::translate_sequence(&seq, 1, 0).unwrap();
    assert_eq!(r.codons, 64);
    assert_eq!(r.protein.matches('*').count(), 3);
    assert_eq!(r.protein.matches('M').count(), 1);
}

#[test]
fn spec_coordinate_contract() {
    use soymutdb_bio_core::coordinates;
    let (s0, e0) = coordinates::to_half_open(1000, 1200).unwrap();
    assert_eq!((s0, e0), (999, 1200));
    assert_eq!(coordinates::to_one_based(s0, e0).unwrap(), (1000, 1200));
    assert_eq!(coordinates::overlap_bp(10, 20, 20, 30), 0);
}
