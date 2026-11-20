//! Bounded format inspection via noodles.  Only validation/preview; these
//! functions never persist, publish, or read from the network.  The Python
//! layer passes already-authorized bytes.

use crate::errors::BioCoreError;
use noodles::fasta;
use noodles::fastq;
use serde::Serialize;
use std::io::Cursor;

pub const MAX_RECORDS: usize = 100_000;
pub const MAX_RECORD_BYTES: usize = 1_048_576;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct FastxRecord {
    pub name: String,
    pub length: usize,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct FastxInspection {
    pub records: Vec<FastxRecord>,
    pub total_records: usize,
    pub truncated: bool,
}

fn check_bounds(records: &[FastxRecord], truncated: &mut bool) -> Result<(), BioCoreError> {
    if records.len() >= MAX_RECORDS {
        *truncated = true;
    }
    Ok(())
}

/// Validate FASTA bytes and return a bounded record listing.  Duplicate IDs
/// are reported by the caller (they are legal FASTA but worth flagging).
pub fn inspect_fasta(data: &[u8]) -> Result<FastxInspection, BioCoreError> {
    if data.is_empty() {
        return Err(BioCoreError::InvalidRecord);
    }
    let mut reader = fasta::io::Reader::new(Cursor::new(data));
    let mut records = Vec::new();
    let mut truncated = false;
    for result in reader.records() {
        let record = result.map_err(|_| BioCoreError::InvalidRecord)?;
        if record.sequence().len() > MAX_RECORD_BYTES {
            return Err(BioCoreError::BudgetExceeded);
        }
        if record.sequence().is_empty() {
            return Err(BioCoreError::InvalidRecord);
        }
        let name = String::from_utf8_lossy(record.name()).to_string();
        records.push(FastxRecord {
            name,
            length: record.sequence().len(),
        });
        check_bounds(&records, &mut truncated)?;
        if truncated {
            break;
        }
    }
    if records.is_empty() {
        return Err(BioCoreError::InvalidRecord);
    }
    Ok(FastxInspection {
        total_records: records.len(),
        records,
        truncated,
    })
}

/// Validate FASTQ bytes.  Sequence and quality lengths must match exactly.
pub fn inspect_fastq(data: &[u8]) -> Result<FastxInspection, BioCoreError> {
    if data.is_empty() {
        return Err(BioCoreError::InvalidRecord);
    }
    let mut reader = fastq::io::Reader::new(Cursor::new(data));
    let mut records = Vec::new();
    let mut truncated = false;
    for result in reader.records() {
        let record = result.map_err(|_| BioCoreError::InvalidRecord)?;
        if record.sequence().len() != record.quality_scores().len() {
            return Err(BioCoreError::InvalidRecord);
        }
        let name = record.name().to_string();
        records.push(FastxRecord {
            name,
            length: record.sequence().len(),
        });
        check_bounds(&records, &mut truncated)?;
        if truncated {
            break;
        }
    }
    if records.is_empty() {
        return Err(BioCoreError::InvalidRecord);
    }
    Ok(FastxInspection {
        total_records: records.len(),
        records,
        truncated,
    })
}

/// Legal GFF3/GTF/BED records are line-oriented with tab-separated columns;
/// this bounded validator checks column counts and BED half-open coordinates.
/// Full parent/phase assembly stays in the Python import service (P3).
pub fn inspect_bed(data: &[u8]) -> Result<usize, BioCoreError> {
    if data.is_empty() {
        return Err(BioCoreError::InvalidRecord);
    }
    let text = std::str::from_utf8(data).map_err(|_| BioCoreError::InvalidRecord)?;
    let mut count = 0usize;
    for line in text.lines() {
        if line.is_empty()
            || line.starts_with('#')
            || line.starts_with("track ")
            || line.starts_with("browser ")
        {
            continue;
        }
        let cols: Vec<&str> = line.split('\t').collect();
        if cols.len() < 3 {
            return Err(BioCoreError::InvalidRecord);
        }
        let start: u64 = cols[1].parse().map_err(|_| BioCoreError::InvalidInterval)?;
        let end: u64 = cols[2].parse().map_err(|_| BioCoreError::InvalidInterval)?;
        if end <= start {
            return Err(BioCoreError::InvalidInterval);
        }
        count += 1;
        if count >= MAX_RECORDS {
            break;
        }
    }
    Ok(count)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn multiline_fasta() {
        let data = b">gene1 desc\nACGT\nACGT\n>gene2\nAAAA\n";
        let r = inspect_fasta(data).unwrap();
        assert_eq!(r.total_records, 2);
        assert_eq!(r.records[0].name, "gene1");
        assert_eq!(r.records[0].length, 8);
        assert_eq!(r.records[1].name, "gene2");
    }

    #[test]
    fn empty_fasta_rejected() {
        assert_eq!(inspect_fasta(b""), Err(BioCoreError::InvalidRecord));
        assert_eq!(
            inspect_fasta(b">only_header\n"),
            Err(BioCoreError::InvalidRecord)
        );
    }

    #[test]
    fn fastq_length_mismatch_rejected() {
        let bad = b"@r1\nACGT\n+\n!!!\n"; // 4 bases, 3 quality chars
        assert_eq!(inspect_fastq(bad), Err(BioCoreError::InvalidRecord));
        let good = b"@r1\nACGT\n+\n!!!!\n";
        assert_eq!(inspect_fastq(good).unwrap().total_records, 1);
    }

    #[test]
    fn bed_half_open_validation() {
        assert_eq!(inspect_bed(b"chr1\t10\t20\n"), Ok(1));
        assert_eq!(
            inspect_bed(b"chr1\t20\t10\n"),
            Err(BioCoreError::InvalidInterval)
        );
        assert_eq!(
            inspect_bed(b"chr1\t10\t10\n"),
            Err(BioCoreError::InvalidInterval)
        );
        assert_eq!(inspect_bed(b"chr1\t10\n"), Err(BioCoreError::InvalidRecord));
    }
}
