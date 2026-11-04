//! PyO3 binding layer.  Python receives only plain values (str / int / bool /
//! list of dict), never Rust handles.  Every failure becomes a stable
//! `BioCoreException` carrying a machine-readable `code`; no Rust panic is
//! allowed to cross the FFI boundary.

use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::errors::BioCoreError;
use crate::sequence::{self, AlignmentMode, Alphabet};

create_exception!(
    soymutdb_bio_core,
    BioCoreException,
    PyException,
    "Structured error from the SoyMutDB bio core"
);

fn raise<T>(err: BioCoreError) -> PyResult<T> {
    Err(BioCoreException::new_err((
        err.code().to_string(),
        err.to_string(),
    )))
}

fn alphabet_of(name: &str) -> PyResult<Alphabet> {
    match name {
        "dna" => Ok(Alphabet::Dna),
        "rna" => Ok(Alphabet::Rna),
        "protein" => Ok(Alphabet::Protein),
        _ => raise(BioCoreError::UnsupportedAlphabet),
    }
}

fn alignment_mode_of(name: &str) -> PyResult<AlignmentMode> {
    match name {
        "local" => Ok(AlignmentMode::Local),
        "global" => Ok(AlignmentMode::Global),
        "semiglobal" => Ok(AlignmentMode::SemiGlobal),
        _ => raise(BioCoreError::UnsupportedParameter),
    }
}

fn hit_dict<'py>(py: Python<'py>, h: &sequence::MatchHit) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("start0", h.start0)?;
    d.set_item("end0", h.end0)?;
    // Public coordinates are 1-based inclusive.
    d.set_item("start", h.start0 + 1)?;
    d.set_item("end", h.end0)?;
    d.set_item(
        "strand",
        match h.strand {
            sequence::Strand::Forward => "+",
            sequence::Strand::Reverse => "-",
        },
    )?;
    d.set_item("edit_distance", h.edits)?;
    Ok(d)
}

#[pyfunction]
#[pyo3(signature = (sequence, alphabet="dna", preserve_case=false))]
fn reverse_complement(
    py: Python<'_>,
    sequence: &str,
    alphabet: &str,
    preserve_case: bool,
) -> PyResult<String> {
    let a = alphabet_of(alphabet)?;
    // Releases the GIL for the pure-CPU part; no Python objects are touched.
    let out = py.detach(|| sequence::reverse_complement(sequence.as_bytes(), a, preserve_case));
    let bytes = out.or_else(raise)?;
    String::from_utf8(bytes)
        .map_err(|_| BioCoreException::new_err(("INVALID_CHARACTER", "invalid utf-8")))
}

#[pyfunction]
#[allow(
    clippy::too_many_arguments,
    reason = "flat PyO3 signature is the Python API contract"
)]
#[pyo3(signature = (target, pattern, alphabet="dna", mode="exact", both_strands=true, max_edits=0, max_hits=100))]
fn find_matches(
    py: Python<'_>,
    target: &str,
    pattern: &str,
    alphabet: &str,
    mode: &str,
    both_strands: bool,
    max_edits: u8,
    max_hits: usize,
) -> PyResult<Vec<Py<PyDict>>> {
    let a = alphabet_of(alphabet)?;
    let hits = py
        .detach(|| -> Result<Vec<sequence::MatchHit>, BioCoreError> {
            match mode {
                "exact" => sequence::match_exact(
                    target.as_bytes(),
                    pattern.as_bytes(),
                    a,
                    both_strands,
                    max_hits,
                ),
                "approximate" => sequence::match_approximate(
                    target.as_bytes(),
                    pattern.as_bytes(),
                    max_edits,
                    max_hits,
                ),
                _ => Err(BioCoreError::UnsupportedParameter),
            }
        })
        .or_else(raise)?;
    hits.iter().map(|h| Ok(hit_dict(py, h)?.unbind())).collect()
}

#[pyfunction]
#[allow(
    clippy::too_many_arguments,
    reason = "flat PyO3 signature is the Python API contract"
)]
#[pyo3(signature = (query, target, alphabet="dna", mode="local", match_score=2, mismatch_score=-3, gap_open=-5, gap_extend=-1))]
fn align_pairwise(
    py: Python<'_>,
    query: &str,
    target: &str,
    alphabet: &str,
    mode: &str,
    match_score: i32,
    mismatch_score: i32,
    gap_open: i32,
    gap_extend: i32,
) -> PyResult<Py<PyDict>> {
    let a = alphabet_of(alphabet)?;
    let m = alignment_mode_of(mode)?;
    let r = py
        .detach(|| {
            sequence::align_pairwise(
                query.as_bytes(),
                target.as_bytes(),
                a,
                m,
                match_score,
                mismatch_score,
                gap_open,
                gap_extend,
            )
        })
        .or_else(raise)?;
    let d = PyDict::new(py);
    d.set_item("score", r.score)?;
    d.set_item("query_start0", r.query_start0)?;
    d.set_item("query_end0", r.query_end0)?;
    d.set_item("target_start0", r.target_start0)?;
    d.set_item("target_end0", r.target_end0)?;
    d.set_item("query_range", (r.query_start0 + 1, r.query_end0))?;
    d.set_item("target_range", (r.target_start0 + 1, r.target_end0))?;
    d.set_item("cigar", r.cigar)?;
    d.set_item("identity", r.identity)?;
    Ok(d.unbind())
}

#[pyfunction]
#[pyo3(signature = (sequence, alphabet="dna", exclude_ambiguous=true))]
fn sequence_statistics(
    py: Python<'_>,
    sequence: &str,
    alphabet: &str,
    exclude_ambiguous: bool,
) -> PyResult<Py<PyDict>> {
    let a = alphabet_of(alphabet)?;
    let r = py
        .detach(|| sequence::sequence_statistics(sequence.as_bytes(), a, exclude_ambiguous))
        .or_else(raise)?;
    let d = PyDict::new(py);
    d.set_item("length", r.length)?;
    d.set_item("gc_count", r.gc_count)?;
    d.set_item("at_count", r.at_count)?;
    d.set_item("ambiguous_count", r.ambiguous_count)?;
    d.set_item("a", r.a)?;
    d.set_item("c", r.c)?;
    d.set_item("g", r.g)?;
    d.set_item("t", r.t)?;
    d.set_item("denominator", r.denominator)?;
    d.set_item("gc_fraction", r.gc_fraction)?;
    Ok(d.unbind())
}

#[pyfunction]
#[pyo3(signature = (sequence, min_len=90, limit=1000))]
fn find_orfs(
    py: Python<'_>,
    sequence: &str,
    min_len: usize,
    limit: usize,
) -> PyResult<Vec<Py<PyDict>>> {
    let r = py
        .detach(|| sequence::find_orfs(sequence.as_bytes(), min_len, limit))
        .or_else(raise)?;
    r.iter()
        .map(|o| {
            let d = PyDict::new(py);
            d.set_item("start0", o.start0)?;
            d.set_item("end0", o.end0)?;
            d.set_item("start", o.start0 + 1)?;
            d.set_item("end", o.end0)?;
            d.set_item(
                "strand",
                match o.strand {
                    sequence::Strand::Forward => "+",
                    sequence::Strand::Reverse => "-",
                },
            )?;
            d.set_item("frame", o.frame)?;
            Ok(d.unbind())
        })
        .collect()
}

#[pyfunction]
#[pyo3(signature = (sequence, genetic_code_id=1, frame=0))]
fn translate_sequence(
    py: Python<'_>,
    sequence: &str,
    genetic_code_id: u32,
    frame: u8,
) -> PyResult<Py<PyDict>> {
    let r = py
        .detach(|| {
            crate::translation::translate_sequence(sequence.as_bytes(), genetic_code_id, frame)
        })
        .or_else(raise)?;
    let d = PyDict::new(py);
    d.set_item("protein", r.protein)?;
    d.set_item("genetic_code_id", r.genetic_code_id)?;
    d.set_item("frame", r.frame)?;
    d.set_item("warnings", r.warnings)?;
    d.set_item("codons", r.codons)?;
    d.set_item("trailing_bases", r.trailing_bases)?;
    Ok(d.unbind())
}

#[pyfunction]
#[pyo3(signature = (sequence, k, canonical=true, ambiguity_policy="skip", max_items=1000))]
fn kmer_counts(
    py: Python<'_>,
    sequence: &str,
    k: usize,
    canonical: bool,
    ambiguity_policy: &str,
    max_items: usize,
) -> PyResult<Py<PyDict>> {
    let r = py
        .detach(|| {
            crate::sequence::kmer_counts(
                sequence.as_bytes(),
                k,
                canonical,
                ambiguity_policy,
                max_items,
            )
        })
        .or_else(raise)?;
    let d = PyDict::new(py);
    d.set_item("k", r.k)?;
    d.set_item("canonical", r.canonical)?;
    d.set_item("total_windows", r.total_windows)?;
    d.set_item("valid_windows", r.valid_windows)?;
    d.set_item("skipped_windows", r.skipped_windows)?;
    d.set_item("distinct_kmers", r.distinct_kmers)?;
    d.set_item("limited", r.limited)?;
    d.set_item(
        "items",
        r.items
            .iter()
            .map(|i| (i.kmer.clone(), i.count))
            .collect::<Vec<_>>(),
    )?;
    Ok(d.unbind())
}

#[pyfunction]
#[pyo3(signature = (intervals, regions, max_hits=1000))]
fn overlap_intervals(
    py: Python<'_>,
    intervals: Vec<(u64, u64, u64)>,
    regions: Vec<(u64, u64)>,
    max_hits: usize,
) -> PyResult<Vec<Py<PyDict>>> {
    if regions.len() > crate::intervals::MAX_REGIONS {
        return raise(BioCoreError::BudgetExceeded);
    }
    let recs: Vec<crate::intervals::IntervalRecord> = intervals
        .into_iter()
        .map(|(s, e, v)| crate::intervals::IntervalRecord {
            start0: s,
            end0: e,
            record_index: v,
        })
        .collect();
    let idx = crate::intervals::build_index(&recs).or_else(raise)?;
    let mut out = Vec::new();
    for (s, e) in regions {
        let q = py
            .detach(|| crate::intervals::find_overlaps(&idx, s, e, max_hits))
            .or_else(raise)?;
        let d = PyDict::new(py);
        d.set_item("overlap_count", q.overlap_count)?;
        d.set_item("covered_bp", q.covered_bp)?;
        d.set_item("limited", q.limited)?;
        d.set_item(
            "hits",
            q.hits
                .iter()
                .map(|h| (h.start0, h.end0, h.overlap_bp, h.record_index))
                .collect::<Vec<_>>(),
        )?;
        out.push(d.unbind());
    }
    Ok(out)
}

#[pyfunction]
fn validate_fasta(py: Python<'_>, data: &[u8]) -> PyResult<Py<PyDict>> {
    let r = py
        .detach(|| crate::formats::inspect_fasta(data))
        .or_else(raise)?;
    let d = PyDict::new(py);
    d.set_item("total_records", r.total_records)?;
    d.set_item("truncated", r.truncated)?;
    d.set_item(
        "records",
        r.records
            .iter()
            .map(|x| (x.name.clone(), x.length))
            .collect::<Vec<_>>(),
    )?;
    Ok(d.unbind())
}

#[pyfunction]
fn validate_fastq(py: Python<'_>, data: &[u8]) -> PyResult<Py<PyDict>> {
    let r = py
        .detach(|| crate::formats::inspect_fastq(data))
        .or_else(raise)?;
    let d = PyDict::new(py);
    d.set_item("total_records", r.total_records)?;
    d.set_item("truncated", r.truncated)?;
    d.set_item(
        "records",
        r.records
            .iter()
            .map(|x| (x.name.clone(), x.length))
            .collect::<Vec<_>>(),
    )?;
    Ok(d.unbind())
}

#[pyfunction]
fn validate_bed(py: Python<'_>, data: &[u8]) -> PyResult<usize> {
    py.detach(|| crate::formats::inspect_bed(data))
        .or_else(raise)
}

#[pyfunction]
fn capabilities(py: Python<'_>) -> PyResult<Py<PyDict>> {
    let d = PyDict::new(py);
    d.set_item("engine", crate::ENGINE)?;
    d.set_item("engine_version", crate::ENGINE_VERSION)?;
    d.set_item("max_inline_sequence", crate::sequence::MAX_INLINE_SEQUENCE)?;
    d.set_item("max_pattern", crate::sequence::MAX_PATTERN)?;
    d.set_item("max_alignment_cells", crate::sequence::MAX_ALIGNMENT_CELLS)?;
    d.set_item("max_regions", crate::intervals::MAX_REGIONS)?;
    d.set_item("max_hits", crate::intervals::MAX_HITS)?;
    d.set_item("k_range", (1, 32))?;
    d.set_item(
        "genetic_codes",
        crate::translation::implemented_genetic_codes(),
    )?;
    d.set_item("coordinate_system_internal", "0-based-half-open")?;
    d.set_item("coordinate_system_public", "1-based-inclusive")?;
    Ok(d.unbind())
}

#[pymodule]
fn soymutdb_bio_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("BioCoreException", m.py().get_type::<BioCoreException>())?;
    m.add_function(wrap_pyfunction!(reverse_complement, m)?)?;
    m.add_function(wrap_pyfunction!(find_matches, m)?)?;
    m.add_function(wrap_pyfunction!(align_pairwise, m)?)?;
    m.add_function(wrap_pyfunction!(sequence_statistics, m)?)?;
    m.add_function(wrap_pyfunction!(find_orfs, m)?)?;
    m.add_function(wrap_pyfunction!(translate_sequence, m)?)?;
    m.add_function(wrap_pyfunction!(kmer_counts, m)?)?;
    m.add_function(wrap_pyfunction!(overlap_intervals, m)?)?;
    m.add_function(wrap_pyfunction!(validate_fasta, m)?)?;
    m.add_function(wrap_pyfunction!(validate_fastq, m)?)?;
    m.add_function(wrap_pyfunction!(validate_bed, m)?)?;
    m.add_function(wrap_pyfunction!(capabilities, m)?)?;
    Ok(())
}
