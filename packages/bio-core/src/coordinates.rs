//! Coordinate boundary conversion.
//!
//! Internally every interval is 0-based half-open `[start0, end0)`.  Public
//! genome coordinates are 1-based inclusive `[start1, end1]`.  The only legal
//! conversions are the two functions below; no other module is allowed to
//! silently add or subtract one.

use crate::errors::BioCoreError;

/// Convert a public 1-based inclusive interval to 0-based half-open.
pub fn to_half_open(start1: u64, end1: u64) -> Result<(u64, u64), BioCoreError> {
    if start1 == 0 || end1 < start1 {
        return Err(BioCoreError::InvalidInterval);
    }
    Ok((start1 - 1, end1))
}

/// Convert a 0-based half-open interval back to public 1-based inclusive.
pub fn to_one_based(start0: u64, end0: u64) -> Result<(u64, u64), BioCoreError> {
    if end0 <= start0 {
        return Err(BioCoreError::InvalidInterval);
    }
    let start1 = start0
        .checked_add(1)
        .ok_or(BioCoreError::CoordinateOverflow)?;
    Ok((start1, end0))
}

/// Positive-length overlap of two half-open intervals.  Adjacent intervals
/// `[10,20)` and `[20,30)` yield 0, not 1.
pub fn overlap_bp(start_a: u64, end_a: u64, start_b: u64, end_b: u64) -> u64 {
    let start = start_a.max(start_b);
    let end = end_a.min(end_b);
    end.saturating_sub(start)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip() {
        for (s1, e1) in [(1, 1), (1000, 1200), (u64::MAX - 1, u64::MAX)] {
            let (s0, e0) = to_half_open(s1, e1).unwrap();
            assert_eq!(to_one_based(s0, e0).unwrap(), (s1, e1));
        }
    }

    #[test]
    fn rejects_zero_and_reversed() {
        assert_eq!(to_half_open(0, 5), Err(BioCoreError::InvalidInterval));
        assert_eq!(to_half_open(10, 9), Err(BioCoreError::InvalidInterval));
        assert_eq!(to_one_based(10, 10), Err(BioCoreError::InvalidInterval));
    }

    #[test]
    fn adjacent_intervals_do_not_overlap() {
        assert_eq!(overlap_bp(10, 20, 20, 30), 0);
        assert_eq!(overlap_bp(10, 20, 19, 30), 1);
        assert_eq!(overlap_bp(10, 20, 10, 20), 10);
    }
}
