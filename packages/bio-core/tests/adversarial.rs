//! Adversarial inputs: nothing may panic, silently succeed, or leak content.
use soymutdb_bio_core::formats;
use soymutdb_bio_core::sequence::{self, Alphabet};

#[test]
fn empty_and_control_inputs_are_rejected() {
    assert!(sequence::reverse_complement(b"", Alphabet::Dna, false).is_err());
    assert!(sequence::reverse_complement(b"A\x00G", Alphabet::Dna, false).is_err());
    assert!(sequence::match_exact(b"ACGT", b"", Alphabet::Dna, false, 10).is_err());
    assert!(sequence::kmer_counts(b"", 4, true, "skip", 10).is_err());
}

#[test]
fn oversized_inputs_are_bounded() {
    let big = vec![b'A'; sequence::MAX_INLINE_SEQUENCE + 1];
    assert!(sequence::reverse_complement(&big, Alphabet::Dna, false).is_err());
    let cells = vec![b'A'; 4000];
    assert!(
        sequence::align_pairwise(
            &cells,
            &cells,
            Alphabet::Dna,
            sequence::AlignmentMode::Global,
            2,
            -3,
            -5,
            -1
        )
        .is_err()
    );
}

#[test]
fn malformed_fastx_never_panics() {
    assert!(formats::inspect_fasta(b"").is_err());
    assert!(formats::inspect_fasta(b">h\n").is_err());
    assert!(formats::inspect_fastq(b"@r\nACGT\n+\n!!\n").is_err());
    assert!(formats::inspect_bed(b"chr1\t20\t10\n").is_err());
    assert!(formats::inspect_bed(b"chr1\tnot-a-number\t10\n").is_err());
}

#[test]
fn protein_revcomp_is_refused_not_faked() {
    assert!(sequence::reverse_complement(b"MKWV", Alphabet::Protein, false).is_err());
    assert!(
        sequence::align_pairwise(
            b"MKWV",
            b"MKWV",
            Alphabet::Protein,
            sequence::AlignmentMode::Global,
            2,
            -3,
            -5,
            -1
        )
        .is_err()
    );
}

#[test]
fn unknown_genetic_code_never_falls_back() {
    assert!(soymutdb_bio_core::translation::translate_sequence(b"ATGAAA", 999, 0).is_err());
}
