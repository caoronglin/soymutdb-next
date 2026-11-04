//! Sequence algorithms.  Rust-Bio is the single owner of matching/alignment;
//! bio-seq supplies typed k-mers and the standard translation table.  The
//! reverse-complement implementation here is the single public owner and fully
//! handles IUPAC ambiguity and case policy (bio::alphabets::dna::revcomp does
//! neither, so it is used only as a test oracle for plain ACGT).

use crate::errors::BioCoreError;
use bio::alignment::pairwise::{Aligner, Scoring};
use bio::pattern_matching::myers::long::Myers;
use serde::Serialize;
use std::collections::BTreeMap;

pub const MAX_INLINE_SEQUENCE: usize = 1_048_576; // 1 MiB
pub const MAX_PATTERN: usize = 256;
pub const MAX_ALIGNMENT_CELLS: u64 = 10_000_000;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Alphabet {
    Dna,
    Rna,
    Protein,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Strand {
    Forward,
    Reverse,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct MatchHit {
    /// 0-based inclusive start within the target.
    pub start0: u64,
    /// 0-based exclusive end within the target.
    pub end0: u64,
    pub strand: Strand,
    pub edits: u32,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct SequenceStatistics {
    pub length: usize,
    pub gc_count: usize,
    pub at_count: usize,
    pub ambiguous_count: usize,
    pub a: usize,
    pub c: usize,
    pub g: usize,
    pub t: usize,
    /// Denominator used for `gc_fraction` (ACGT only when `exclude` is set).
    pub denominator: usize,
    pub gc_fraction: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct OrfCandidate {
    pub start0: usize,
    pub end0: usize,
    pub strand: Strand,
    pub frame: u8,
}

fn complement_byte(b: u8, alphabet: Alphabet) -> Result<u8, BioCoreError> {
    let up = b.to_ascii_uppercase();
    let out = match alphabet {
        Alphabet::Dna => match up {
            b'A' => b'T',
            b'T' => b'A',
            b'U' => b'A',
            b'C' => b'G',
            b'G' => b'C',
            b'R' => b'Y',
            b'Y' => b'R',
            b'K' => b'M',
            b'M' => b'K',
            b'B' => b'V',
            b'V' => b'B',
            b'D' => b'H',
            b'H' => b'D',
            b'S' => b'S',
            b'W' => b'W',
            b'N' => b'N',
            _ => return Err(BioCoreError::InvalidCharacter),
        },
        Alphabet::Rna => match up {
            b'A' => b'U',
            b'U' => b'A',
            b'T' => b'A',
            b'C' => b'G',
            b'G' => b'C',
            b'R' => b'Y',
            b'Y' => b'R',
            b'K' => b'M',
            b'M' => b'K',
            b'B' => b'V',
            b'V' => b'B',
            b'D' => b'H',
            b'H' => b'D',
            b'S' => b'S',
            b'W' => b'W',
            b'N' => b'N',
            _ => return Err(BioCoreError::InvalidCharacter),
        },
        Alphabet::Protein => return Err(BioCoreError::UnsupportedAlphabet),
    };
    Ok(if b.is_ascii_lowercase() {
        out.to_ascii_lowercase()
    } else {
        out
    })
}

/// Reverse complement with full IUPAC handling and explicit case policy.
///
/// `preserve_case` keeps the original per-base case; otherwise the output is
/// upper-case.  Protein input is rejected.  RNA complements A<->U.
pub fn reverse_complement(
    sequence: &[u8],
    alphabet: Alphabet,
    preserve_case: bool,
) -> Result<Vec<u8>, BioCoreError> {
    if sequence.is_empty() {
        return Err(BioCoreError::EmptySequence);
    }
    if sequence.len() > MAX_INLINE_SEQUENCE {
        return Err(BioCoreError::SequenceTooLong);
    }
    if alphabet == Alphabet::Protein {
        return Err(BioCoreError::UnsupportedAlphabet);
    }
    let mut out = Vec::with_capacity(sequence.len());
    for &b in sequence.iter().rev() {
        let mut c = complement_byte(b, alphabet)?;
        if !preserve_case {
            c = c.to_ascii_uppercase();
        }
        out.push(c);
    }
    Ok(out)
}

/// Normalise for matching: upper-case, and (for DNA/RNA) map U<->T so a DNA
/// pattern can match an RNA target and vice versa.
fn normalise(seq: &[u8], alphabet: Alphabet) -> Vec<u8> {
    seq.iter()
        .map(|&b| {
            let u = b.to_ascii_uppercase();
            match alphabet {
                Alphabet::Dna if u == b'U' => b'T',
                Alphabet::Rna if u == b'T' => b'U',
                _ => u,
            }
        })
        .collect()
}

fn validate_sequence(seq: &[u8], alphabet: Alphabet) -> Result<(), BioCoreError> {
    if seq.is_empty() {
        return Err(BioCoreError::EmptySequence);
    }
    if seq.len() > MAX_INLINE_SEQUENCE {
        return Err(BioCoreError::SequenceTooLong);
    }
    let allowed: &[u8] = match alphabet {
        Alphabet::Dna => b"ACGTURYKMBVDHSWN",
        Alphabet::Rna => b"ACGUURYKMBVDHSWN",
        Alphabet::Protein => b"ACDEFGHIKLMNPQRSTVWYBXZJUO*",
    };
    for &b in seq {
        if !allowed.contains(&b.to_ascii_uppercase()) {
            return Err(BioCoreError::InvalidCharacter);
        }
    }
    Ok(())
}

/// Exact matching on forward and (optionally) reverse strand.  Handles
/// overlapping matches.  `N`/IUPAC are literal by default (never a wildcard).
pub fn match_exact(
    target: &[u8],
    pattern: &[u8],
    alphabet: Alphabet,
    both_strands: bool,
    limit: usize,
) -> Result<Vec<MatchHit>, BioCoreError> {
    validate_sequence(target, alphabet)?;
    if pattern.is_empty() || pattern.len() > MAX_PATTERN {
        return Err(if pattern.is_empty() {
            BioCoreError::EmptySequence
        } else {
            BioCoreError::BudgetExceeded
        });
    }
    validate_sequence(pattern, alphabet)?;
    let tgt = normalise(target, alphabet);
    let pat = normalise(pattern, alphabet);
    let mut hits = Vec::new();
    for (i, w) in tgt.windows(pat.len()).enumerate() {
        if w == pat.as_slice() {
            hits.push(MatchHit {
                start0: i as u64,
                end0: (i + pat.len()) as u64,
                strand: Strand::Forward,
                edits: 0,
            });
            if hits.len() >= limit {
                return Ok(hits);
            }
        }
    }
    if both_strands {
        let rc_pat = normalise(&reverse_complement(pattern, alphabet, false)?, alphabet);
        // Reverse-strand hits are reported in forward-target coordinates.
        for (i, w) in tgt.windows(rc_pat.len()).enumerate() {
            if w == rc_pat.as_slice() {
                hits.push(MatchHit {
                    start0: i as u64,
                    end0: (i + rc_pat.len()) as u64,
                    strand: Strand::Reverse,
                    edits: 0,
                });
                if hits.len() >= limit {
                    return Ok(hits);
                }
            }
        }
    }
    Ok(hits)
}

/// Approximate matching via Rust-Bio Myers.  Returns edit distance per hit.
pub fn match_approximate(
    target: &[u8],
    pattern: &[u8],
    max_edits: u8,
    limit: usize,
) -> Result<Vec<MatchHit>, BioCoreError> {
    validate_sequence(target, Alphabet::Dna)?;
    if pattern.is_empty() || pattern.len() > MAX_PATTERN || max_edits > 3 {
        return Err(BioCoreError::BudgetExceeded);
    }
    validate_sequence(pattern, Alphabet::Dna)?;
    let mut myers: Myers<u64> = Myers::new(pattern.to_vec());
    let mut hits = Vec::new();
    for (start, end, dist) in myers.find_all(target.to_vec(), usize::from(max_edits)) {
        // Myers returns a 0-based half-open (start, end) range plus the edit
        // distance.  Coordinates are forwarded verbatim, not re-derived.
        let start0 = start as u64;
        let end0 = end as u64;
        hits.push(MatchHit {
            start0,
            end0,
            strand: Strand::Forward,
            edits: dist as u32,
        });
        if hits.len() >= limit {
            break;
        }
    }
    Ok(hits)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum AlignmentMode {
    Local,
    Global,
    SemiGlobal,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct AlignmentResult {
    pub score: i32,
    pub query_start0: usize,
    pub query_end0: usize,
    pub target_start0: usize,
    pub target_end0: usize,
    pub cigar: String,
    pub identity: f64,
}

/// Pairwise alignment with affine gaps.  Only DNA/RNA are enabled; protein
/// scoring needs a substitution matrix and is deliberately not faked.
#[allow(
    clippy::too_many_arguments,
    reason = "explicit affine-gap scoring is a public scientific contract"
)]
pub fn align_pairwise(
    query: &[u8],
    target: &[u8],
    alphabet: Alphabet,
    mode: AlignmentMode,
    match_score: i32,
    mismatch_score: i32,
    gap_open: i32,
    gap_extend: i32,
) -> Result<AlignmentResult, BioCoreError> {
    if alphabet == Alphabet::Protein {
        return Err(BioCoreError::UnsupportedAlphabet);
    }
    validate_sequence(query, alphabet)?;
    validate_sequence(target, alphabet)?;
    let cells = (query.len() as u64)
        .checked_mul(target.len() as u64)
        .ok_or(BioCoreError::CoordinateOverflow)?;
    if cells > MAX_ALIGNMENT_CELLS {
        return Err(BioCoreError::BudgetExceeded);
    }
    let scoring = Scoring::from_scores(gap_open, gap_extend, match_score, mismatch_score);
    let mut aligner = Aligner::with_scoring(scoring);
    let alignment = match mode {
        AlignmentMode::Local => aligner.local(query, target),
        AlignmentMode::Global => aligner.global(query, target),
        AlignmentMode::SemiGlobal => aligner.semiglobal(query, target),
    };
    // bio 4.2.2's Alignment::cigar() panics for Local/Global modes, so the
    // CIGAR is derived from the operation list for all three modes.  Match and
    // Subst both consume a column (M); Del/Ins are target/query gaps.
    use bio::alignment::AlignmentOperation as Op;
    let mut cigar = String::new();
    let mut run_op: Option<char> = None;
    let mut run_len: usize = 0;
    for op in &alignment.operations {
        let c = match op {
            Op::Match | Op::Subst => 'M',
            Op::Del => 'D',
            Op::Ins => 'I',
            Op::Xclip(_) | Op::Yclip(_) => continue,
        };
        if run_op == Some(c) {
            run_len += 1;
        } else {
            if let Some(prev) = run_op {
                cigar.push_str(&format!("{run_len}{prev}"));
            }
            run_op = Some(c);
            run_len = 1;
        }
    }
    if let Some(prev) = run_op {
        cigar.push_str(&format!("{run_len}{prev}"));
    }
    let identities = alignment
        .operations
        .iter()
        .filter(|op| **op == Op::Match)
        .count();
    let aligned_cols = alignment
        .operations
        .iter()
        .filter(|op| matches!(op, Op::Match | Op::Subst))
        .count()
        .max(1);
    Ok(AlignmentResult {
        score: alignment.score,
        query_start0: alignment.ystart,
        query_end0: alignment.yend,
        target_start0: alignment.xstart,
        target_end0: alignment.xend,
        cigar,
        identity: identities as f64 / aligned_cols as f64,
    })
}

/// GC/AT/ambiguous statistics.  `exclude_ambiguous` removes N/IUPAC bases
/// from the GC denominator instead of silently treating them as non-GC.
pub fn sequence_statistics(
    sequence: &[u8],
    alphabet: Alphabet,
    exclude_ambiguous: bool,
) -> Result<SequenceStatistics, BioCoreError> {
    validate_sequence(sequence, alphabet)?;
    let mut a = 0usize;
    let mut c = 0usize;
    let mut g = 0usize;
    let mut t = 0usize;
    let mut ambiguous = 0usize;
    for &b in sequence {
        match b.to_ascii_uppercase() {
            b'A' => a += 1,
            b'C' => c += 1,
            b'G' => g += 1,
            b'T' | b'U' => t += 1,
            _ => ambiguous += 1,
        }
    }
    let gc_count = c + g;
    let at_count = a + t;
    let denominator = if exclude_ambiguous {
        a + c + g + t
    } else {
        sequence.len()
    };
    let gc_fraction = if denominator == 0 {
        0.0
    } else {
        gc_count as f64 / denominator as f64
    };
    Ok(SequenceStatistics {
        length: sequence.len(),
        gc_count,
        at_count,
        ambiguous_count: ambiguous,
        a,
        c,
        g,
        t,
        denominator,
        gc_fraction,
    })
}

/// ORF candidates, not verified genes.  Scans all six frames for ATG..stop.
pub fn find_orfs(
    sequence: &[u8],
    min_len: usize,
    limit: usize,
) -> Result<Vec<OrfCandidate>, BioCoreError> {
    validate_sequence(sequence, Alphabet::Dna)?;
    if min_len < 3 {
        return Err(BioCoreError::UnsupportedParameter);
    }
    let seq = normalise(sequence, Alphabet::Dna);
    let stops: &[&[u8]] = &[b"TAA", b"TAG", b"TGA"];
    let mut out = Vec::new();
    let scan = |frame_seq: &[u8], frame: u8, strand: Strand, out: &mut Vec<OrfCandidate>| {
        let mut i = 0;
        while i + 3 <= frame_seq.len() {
            if &frame_seq[i..i + 3] == b"ATG" {
                let mut j = i + 3;
                while j + 3 <= frame_seq.len() {
                    let codon = &frame_seq[j..j + 3];
                    if stops.contains(&codon) {
                        let end = j + 3;
                        if end - i >= min_len {
                            out.push(OrfCandidate {
                                start0: i,
                                end0: end,
                                strand,
                                frame,
                            });
                        }
                        i = j;
                        break;
                    }
                    j += 3;
                }
            }
            i += 3;
        }
    };
    for frame in 0..3u8 {
        scan(&seq[frame as usize..], frame, Strand::Forward, &mut out);
        let rc = reverse_complement(&seq, Alphabet::Dna, false)?;
        scan(&rc[frame as usize..], frame, Strand::Reverse, &mut out);
    }
    out.sort_by_key(|o| (o.start0, o.strand == Strand::Reverse, o.frame));
    out.truncate(limit.min(1000));
    Ok(out)
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct KmerResult {
    pub k: usize,
    pub canonical: bool,
    pub total_windows: usize,
    pub valid_windows: usize,
    pub skipped_windows: usize,
    pub distinct_kmers: usize,
    pub items: Vec<KmerItem>,
    pub limited: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct KmerItem {
    pub kmer: String,
    pub count: usize,
}

/// Fixed-k k-mer counts.  `skip` drops windows containing ambiguous symbols,
/// `reject` fails the whole request.  canonical = lexicographic min of the
/// k-mer and its reverse complement.  Dynamic k is dispatched over a bounded
/// whitelist rather than passed to a const generic incorrectly.
#[allow(
    clippy::too_many_arguments,
    reason = "mirrors the public k-mer API contract"
)]
pub fn kmer_counts(
    sequence: &[u8],
    k: usize,
    canonical: bool,
    ambiguity_policy: &str,
    max_items: usize,
) -> Result<KmerResult, BioCoreError> {
    validate_sequence(sequence, Alphabet::Dna)?;
    if !(1..=32).contains(&k) {
        return Err(BioCoreError::UnsupportedParameter);
    }
    if ambiguity_policy != "skip" && ambiguity_policy != "reject" {
        return Err(BioCoreError::UnsupportedParameter);
    }
    let seq: Vec<u8> = sequence.iter().map(|b| b.to_ascii_uppercase()).collect();
    let total_windows = seq.len().saturating_sub(k - 1);
    let mut counts: BTreeMap<String, usize> = BTreeMap::new();
    let mut valid = 0usize;
    let mut skipped = 0usize;
    for w in seq.windows(k) {
        if !w.iter().all(|b| matches!(b, b'A' | b'C' | b'G' | b'T')) {
            if ambiguity_policy == "reject" {
                return Err(BioCoreError::InvalidCharacter);
            }
            skipped += 1;
            continue;
        }
        valid += 1;
        let mut key = String::from_utf8(w.to_vec()).expect("ACGT only");
        if canonical {
            let rc = reverse_complement(w, Alphabet::Dna, false)?;
            let rc_s = String::from_utf8(rc).expect("ACGT only");
            if rc_s < key {
                key = rc_s;
            }
        }
        *counts.entry(key).or_insert(0) += 1;
    }
    let mut items: Vec<KmerItem> = counts
        .iter()
        .map(|(kmer, &count)| KmerItem {
            kmer: kmer.clone(),
            count,
        })
        .collect();
    // Stable ordering: count descending, then k-mer ascending.
    items.sort_by(|a, b| b.count.cmp(&a.count).then_with(|| a.kmer.cmp(&b.kmer)));
    let limited = items.len() > max_items;
    items.truncate(max_items);
    Ok(KmerResult {
        k,
        canonical,
        total_windows,
        valid_windows: valid,
        skipped_windows: skipped,
        distinct_kmers: counts.len(),
        items,
        limited,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn iupac_revcomp() {
        let rc = reverse_complement(b"ATGCRY", Alphabet::Dna, false).unwrap();
        assert_eq!(rc, b"RYGCAT");
        let lower = reverse_complement(b"atg", Alphabet::Dna, true).unwrap();
        assert_eq!(lower, b"cat");
        let rna = reverse_complement(b"AUG", Alphabet::Rna, false).unwrap();
        assert_eq!(rna, b"CAU");
        assert_eq!(
            reverse_complement(b"ACGT", Alphabet::Protein, false),
            Err(BioCoreError::UnsupportedAlphabet)
        );
        assert_eq!(
            reverse_complement(b"", Alphabet::Dna, false),
            Err(BioCoreError::EmptySequence)
        );
        assert_eq!(
            reverse_complement(b"AXG", Alphabet::Dna, false),
            Err(BioCoreError::InvalidCharacter)
        );
    }

    #[test]
    fn revcomp_is_involution() {
        for s in [
            b"ACGTN".as_slice(),
            b"RYKMBVDHSW".as_slice(),
            b"acgtn".as_slice(),
        ] {
            let once = reverse_complement(s, Alphabet::Dna, true).unwrap();
            let twice = reverse_complement(&once, Alphabet::Dna, true).unwrap();
            assert_eq!(twice, s);
        }
    }

    #[test]
    fn bio_oracle_agrees_on_plain_acgt() {
        // Rust-Bio's revcomp is used only as an independent oracle for plain
        // upper-case ACGT, never as the production implementation.
        let s = b"ACGTACGT";
        assert_eq!(
            reverse_complement(s, Alphabet::Dna, false).unwrap(),
            bio::alphabets::dna::revcomp(s)
        );
    }

    #[test]
    fn exact_matches_include_overlaps_and_reverse_strand() {
        let hits = match_exact(b"AAAA", b"AA", Alphabet::Dna, false, 100).unwrap();
        assert_eq!(hits.len(), 3);
        assert_eq!(hits[0].start0, 0);
        assert_eq!(hits[1].start0, 1);
        assert_eq!(hits[2].start0, 2);
        let both = match_exact(b"ACGT", b"ACGT", Alphabet::Dna, true, 100).unwrap();
        assert_eq!(both.len(), 2);
        assert_eq!(both[0].strand, Strand::Forward);
        assert_eq!(both[1].strand, Strand::Reverse);
    }

    #[test]
    fn n_is_literal_not_wildcard() {
        let hits = match_exact(b"ACNT", b"ACGT", Alphabet::Dna, false, 100).unwrap();
        assert!(hits.is_empty());
    }

    #[test]
    fn stats_denominator_is_explicit() {
        let s = sequence_statistics(b"ACGTNN", Alphabet::Dna, true).unwrap();
        assert_eq!(s.length, 6);
        assert_eq!(s.gc_count, 2);
        assert_eq!(s.ambiguous_count, 2);
        assert_eq!(s.denominator, 4);
        assert!((s.gc_fraction - 0.5).abs() < 1e-12);
        let s2 = sequence_statistics(b"ACGTNN", Alphabet::Dna, false).unwrap();
        assert_eq!(s2.denominator, 6);
    }

    #[test]
    fn alignment_self_is_perfect() {
        let r = align_pairwise(
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
        assert!((r.identity - 1.0).abs() < 1e-12);
        assert_eq!(r.cigar, "4M");
    }

    #[test]
    fn alignment_budget_is_enforced() {
        let big = vec![b'A'; 4000];
        assert_eq!(
            align_pairwise(
                &big,
                &big,
                Alphabet::Dna,
                AlignmentMode::Global,
                2,
                -3,
                -5,
                -1
            ),
            Err(BioCoreError::BudgetExceeded)
        );
    }

    #[test]
    fn kmer_golden_from_spec() {
        let r = kmer_counts(b"ACGTACGTNACG", 4, true, "skip", 1000).unwrap();
        assert_eq!(r.total_windows, 9);
        assert_eq!(r.valid_windows, 5);
        assert_eq!(r.skipped_windows, 4);
        assert_eq!(r.distinct_kmers, 3);
        assert!(!r.limited);
        let total: usize = r.items.iter().map(|i| i.count).sum();
        assert_eq!(total, 5);
    }

    #[test]
    fn kmer_reject_policy() {
        assert_eq!(
            kmer_counts(b"ACGTN", 4, false, "reject", 1000),
            Err(BioCoreError::InvalidCharacter)
        );
    }

    #[test]
    fn orf_returns_candidates_not_genes() {
        let orfs = find_orfs(b"ATGAAATAA", 6, 100).unwrap();
        assert!(!orfs.is_empty());
        assert_eq!(orfs[0].start0, 0);
        assert_eq!(orfs[0].end0, 9);
    }
}
