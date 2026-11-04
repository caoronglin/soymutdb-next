//! 0-based half-open interval overlap, backed by rust-lapper.
//!
//! The index is scoped to one (assembly, release, ref_name, dataset checksum).
//! Nothing here queries PostgreSQL or decides visibility; the Python layer
//! must resolve an authorized, published dataset first.

use crate::errors::BioCoreError;
use rust_lapper::{Interval, Lapper};
use serde::Serialize;

pub const MAX_REGIONS: usize = 1000;
pub const MAX_HITS: usize = 1000;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct IntervalRecord {
    pub start0: u64,
    pub end0: u64,
    /// Index into the caller's published record list, never a private DB id.
    pub record_index: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct IntervalHit {
    pub start0: u64,
    pub end0: u64,
    pub overlap_bp: u64,
    pub record_index: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct OverlapQuery {
    pub overlap_count: usize,
    pub covered_bp: u64,
    pub hits: Vec<IntervalHit>,
    pub limited: bool,
}

/// Build an index from validated intervals.  Empty, reversed and zero-length
/// intervals are rejected, never silently corrected.
pub fn build_index(intervals: &[IntervalRecord]) -> Result<Lapper<u64, u64>, BioCoreError> {
    if intervals.is_empty() {
        return Err(BioCoreError::InvalidInterval);
    }
    let mut entries = Vec::with_capacity(intervals.len());
    for r in intervals {
        if r.end0 <= r.start0 {
            return Err(BioCoreError::InvalidInterval);
        }
        entries.push(Interval {
            start: r.start0,
            stop: r.end0,
            val: r.record_index,
        });
    }
    Ok(Lapper::new(entries))
}

/// Query overlap for one half-open region.  `overlap_count` counts overlapping
/// *records* (duplicates count separately); `covered_bp` is the union length of
/// the overlapping parts, so duplicates never inflate coverage.
pub fn find_overlaps(
    index: &Lapper<u64, u64>,
    start0: u64,
    end0: u64,
    limit: usize,
) -> Result<OverlapQuery, BioCoreError> {
    if end0 <= start0 {
        return Err(BioCoreError::InvalidInterval);
    }
    let cap = limit.min(MAX_HITS);
    let mut hits = Vec::new();
    let mut count = 0usize;
    let mut covered_intervals: Vec<(u64, u64)> = Vec::new();
    for iv in index.find(start0, end0) {
        count += 1;
        let ov_start = start0.max(iv.start);
        let ov_end = end0.min(iv.stop);
        let ov_bp = ov_end.saturating_sub(ov_start);
        if ov_bp == 0 {
            continue; // `find` may include a touching interval; require +length.
        }
        covered_intervals.push((ov_start, ov_end));
        if hits.len() < cap {
            hits.push(IntervalHit {
                start0: iv.start,
                end0: iv.stop,
                overlap_bp: ov_bp,
                record_index: iv.val,
            });
        }
    }
    Ok(OverlapQuery {
        overlap_count: count,
        covered_bp: union_len(&covered_intervals),
        hits,
        limited: count > cap,
    })
}

fn union_len(intervals: &[(u64, u64)]) -> u64 {
    if intervals.is_empty() {
        return 0;
    }
    let mut v = intervals.to_vec();
    v.sort_by_key(|x| x.0);
    let mut total = 0u64;
    let (mut cs, mut ce) = v[0];
    for &(s, e) in v.iter().skip(1) {
        if s <= ce {
            ce = ce.max(e);
        } else {
            total += ce - cs;
            cs = s;
            ce = e;
        }
    }
    total + (ce - cs)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn idx() -> Lapper<u64, u64> {
        build_index(&[
            IntervalRecord {
                start0: 10,
                end0: 20,
                record_index: 0,
            },
            IntervalRecord {
                start0: 10,
                end0: 20,
                record_index: 1,
            }, // duplicate
            IntervalRecord {
                start0: 19,
                end0: 30,
                record_index: 2,
            },
            IntervalRecord {
                start0: 100,
                end0: 110,
                record_index: 3,
            },
        ])
        .unwrap()
    }

    #[test]
    fn adjacent_does_not_overlap() {
        let i = build_index(&[IntervalRecord {
            start0: 10,
            end0: 20,
            record_index: 0,
        }])
        .unwrap();
        assert_eq!(find_overlaps(&i, 20, 30, 100).unwrap().overlap_count, 0);
    }

    #[test]
    fn one_base_overlap() {
        let i = build_index(&[IntervalRecord {
            start0: 10,
            end0: 20,
            record_index: 0,
        }])
        .unwrap();
        let r = find_overlaps(&i, 19, 30, 100).unwrap();
        assert_eq!(r.overlap_count, 1);
        assert_eq!(r.covered_bp, 1);
    }

    #[test]
    fn exact_overlap_length() {
        let i = build_index(&[IntervalRecord {
            start0: 10,
            end0: 20,
            record_index: 0,
        }])
        .unwrap();
        assert_eq!(find_overlaps(&i, 10, 20, 100).unwrap().covered_bp, 10);
    }

    #[test]
    fn count_is_records_coverage_is_union() {
        let r = find_overlaps(&idx(), 10, 30, 100).unwrap();
        // records 0,1,2 overlap -> count 3, union [10,30) = 20
        assert_eq!(r.overlap_count, 3);
        assert_eq!(r.covered_bp, 20);
    }

    #[test]
    fn invalid_intervals_rejected() {
        assert!(matches!(
            build_index(&[IntervalRecord {
                start0: 20,
                end0: 10,
                record_index: 0
            }]),
            Err(BioCoreError::InvalidInterval)
        ));
        assert!(matches!(
            build_index(&[IntervalRecord {
                start0: 10,
                end0: 10,
                record_index: 0
            }]),
            Err(BioCoreError::InvalidInterval)
        ));
        assert!(matches!(
            build_index(&[]),
            Err(BioCoreError::InvalidInterval)
        ));
        let i = idx();
        assert_eq!(
            find_overlaps(&i, 20, 10, 100),
            Err(BioCoreError::InvalidInterval)
        );
    }

    #[test]
    fn limit_is_bounded() {
        let r = find_overlaps(&idx(), 10, 30, 1).unwrap();
        assert_eq!(r.hits.len(), 1);
        assert!(r.limited);
    }
}
