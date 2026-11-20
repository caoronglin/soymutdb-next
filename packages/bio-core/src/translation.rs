//! Codon translation.  Only the NCBI standard genetic code (table 1) is
//! implemented, backed by bio-seq's `STANDARD` table.  Any other code id is
//! rejected explicitly rather than silently falling back to STANDARD.

use crate::errors::BioCoreError;
use bio_seq::prelude::*;
use bio_seq::translation::{PartialTranslationTable, STANDARD, TranslationTable};
use serde::Serialize;

pub const STANDARD_GENETIC_CODE: u32 = 1;

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct TranslationResult {
    pub protein: String,
    pub genetic_code_id: u32,
    pub frame: u8,
    pub warnings: Vec<String>,
    pub codons: usize,
    pub trailing_bases: usize,
}

/// Translate a DNA coding sequence.  `frame` is 0..2.  Ambiguous codons are
/// reported as `X` with a warning; partial trailing codons are dropped with a
/// warning rather than padded.  Internal stops are kept (`*`) and flagged.
pub fn translate_sequence(
    sequence: &[u8],
    genetic_code_id: u32,
    frame: u8,
) -> Result<TranslationResult, BioCoreError> {
    if genetic_code_id != STANDARD_GENETIC_CODE {
        return Err(BioCoreError::UnknownGeneticCode);
    }
    if frame > 2 {
        return Err(BioCoreError::UnsupportedParameter);
    }
    if sequence.is_empty() {
        return Err(BioCoreError::EmptySequence);
    }
    if sequence.len() > crate::sequence::MAX_INLINE_SEQUENCE {
        return Err(BioCoreError::SequenceTooLong);
    }
    let upper: Vec<u8> = sequence.iter().map(|b| b.to_ascii_uppercase()).collect();
    let frame_usize = usize::from(frame);
    if frame_usize >= upper.len() {
        return Err(BioCoreError::UnsupportedParameter);
    }
    let tail = &upper[frame_usize..];
    let trailing_bases = tail.len() % 3;
    let codons = tail.len() / 3;
    let mut warnings = Vec::new();
    if trailing_bases > 0 {
        warnings.push(format!(
            "{trailing_bases} trailing base(s) ignored (partial codon)"
        ));
    }
    let mut protein = String::with_capacity(codons);
    let mut internal_stops = 0usize;
    let mut ambiguous = 0usize;
    for chunk in tail.chunks(3).take(codons) {
        let codon = String::from_utf8_lossy(chunk).to_string();
        let seq: Seq<Iupac> = match codon.parse() {
            Ok(s) => s,
            Err(_) => return Err(BioCoreError::InvalidCharacter),
        };
        let aa = match STANDARD.try_to_amino(&seq) {
            Ok(a) => a,
            // Fall back to the complete table for unambiguous codons.
            Err(_) => {
                let dna: Seq<Dna> = match codon.parse() {
                    Ok(s) => s,
                    Err(_) => {
                        ambiguous += 1;
                        protein.push('X');
                        continue;
                    }
                };
                STANDARD.to_amino(&dna)
            }
        };
        let ch = aa.to_char();
        if ch == '*' && protein.len() + 1 < codons {
            internal_stops += 1;
        }
        protein.push(ch);
    }
    if internal_stops > 0 {
        warnings.push(format!("{internal_stops} internal stop codon(s)"));
    }
    if ambiguous > 0 {
        warnings.push(format!("{ambiguous} ambiguous codon(s) rendered as X"));
    }
    Ok(TranslationResult {
        protein,
        genetic_code_id,
        frame,
        warnings,
        codons,
        trailing_bases,
    })
}

/// List the genetic codes this kernel actually implements.  No claims about
/// unimplemented tables are made.
pub fn implemented_genetic_codes() -> Vec<u32> {
    vec![STANDARD_GENETIC_CODE]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn standard_code_golden() {
        // ATG AAA TAA CCC GGG TTT -> M K * P G F
        let r = translate_sequence(b"ATGAAATAACCCGGGTTT", 1, 0).unwrap();
        assert_eq!(r.protein, "MK*PGF");
        assert_eq!(r.codons, 6);
        assert_eq!(r.trailing_bases, 0);
    }

    #[test]
    fn all_64_codons_are_defined() {
        let bases = b"ACGT";
        let mut seq = Vec::new();
        for &a in bases {
            for &b in bases {
                for &c in bases {
                    seq.extend_from_slice(&[a, b, c]);
                }
            }
        }
        let r = translate_sequence(&seq, 1, 0).unwrap();
        assert_eq!(r.codons, 64);
        assert_eq!(r.protein.len(), 64);
        assert!(
            !r.protein.contains('X'),
            "unambiguous codons must all resolve"
        );
        // NCBI standard table: 3 stops.
        assert_eq!(r.protein.matches('*').count(), 3);
        assert_eq!(r.protein.matches('M').count(), 1);
    }

    #[test]
    fn unimplemented_code_is_rejected() {
        assert_eq!(
            translate_sequence(b"ATG", 11, 0),
            Err(BioCoreError::UnknownGeneticCode)
        );
    }

    #[test]
    fn frame_and_partial_codon() {
        let r = translate_sequence(b"AATGAAA", 1, 1).unwrap();
        assert_eq!(r.protein, "MK");
        assert_eq!(r.trailing_bases, 0);
        assert_eq!(r.codons, 2);
    }

    #[test]
    fn partial_codon_is_reported() {
        let r = translate_sequence(b"ATGAAAA", 1, 0).unwrap();
        assert_eq!(r.protein, "MK");
        assert_eq!(r.trailing_bases, 1);
        assert!(r.warnings.iter().any(|w| w.contains("partial codon")));
    }

    #[test]
    fn internal_stop_is_flagged() {
        let r = translate_sequence(b"ATGTAACCC", 1, 0).unwrap();
        assert_eq!(r.protein, "M*P");
        assert!(r.warnings.iter().any(|w| w.contains("internal stop")));
    }
}
