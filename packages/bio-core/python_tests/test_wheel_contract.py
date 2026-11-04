"""Wheel contract tests: run against the INSTALLED compiled extension.

These are not Rust unit tests.  They assert the Python-visible surface of the
exact wheel the API/Worker images consume.  Run with CPython 3.15 after
installing artifacts/wheels/soymutdb_bio_core-*.whl.

    python -m pytest packages/bio-core/python_tests -q

The module is skipped (not passed) when the extension is unavailable, so a
missing wheel can never masquerade as a green gate.
"""

from __future__ import annotations

import importlib.util
import pytest

if importlib.util.find_spec("soymutdb_bio_core") is None:
    pytest.skip("compiled wheel not installed", allow_module_level=True)

import soymutdb_bio_core as core  # noqa: E402


def test_capabilities_are_explicit() -> None:
    cap = core.capabilities()
    assert cap["engine"] == "soymutdb-bio-core"
    assert cap["engine_version"]
    assert cap["genetic_codes"] == [1], "unimplemented tables must not be advertised"
    assert cap["coordinate_system_internal"] == "0-based-half-open"
    assert cap["coordinate_system_public"] == "1-based-inclusive"


def test_iupac_reverse_complement() -> None:
    assert core.reverse_complement("ATGCRY") == "RYGCAT"
    assert core.reverse_complement("AUG", alphabet="rna") == "CAU"
    assert core.reverse_complement("atg", preserve_case=True) == "cat"


def test_double_reverse_complement_is_identity() -> None:
    for seq in ("ACGTN", "RYKMBVDHSW", "acgtn"):
        assert core.reverse_complement(core.reverse_complement(seq, preserve_case=True), preserve_case=True) == seq


def test_errors_are_structured() -> None:
    with pytest.raises(core.BioCoreException) as exc:
        core.reverse_complement("AXG")
    assert exc.value.args[0] == "INVALID_CHARACTER"
    with pytest.raises(core.BioCoreException) as exc:
        core.translate_sequence("ATG", genetic_code_id=2)
    assert exc.value.args[0] == "UNKNOWN_GENETIC_CODE"


def test_spec_kmer_golden() -> None:
    r = core.kmer_counts("ACGTACGTNACG", 4)
    assert (r["total_windows"], r["valid_windows"], r["skipped_windows"], r["distinct_kmers"]) == (9, 5, 4, 3)
    assert sum(count for _, count in r["items"]) == 5


def test_coordinate_and_interval_contract() -> None:
    q = core.overlap_intervals([(10, 20, 0), (10, 20, 1), (19, 30, 2)], [(10, 30)])[0]
    assert q["overlap_count"] == 3, "duplicates count as separate records"
    assert q["covered_bp"] == 20, "coverage is a union, not a record count"
    assert core.overlap_intervals([(10, 20, 0)], [(20, 30)])[0]["overlap_count"] == 0


def test_translation_64_codons() -> None:
    bases = "ACGT"
    seq = "".join(a + b + c for a in bases for b in bases for c in bases)
    r = core.translate_sequence(seq)
    assert r["codons"] == 64
    assert r["protein"].count("*") == 3
    assert r["protein"].count("M") == 1


def test_alignment_is_not_blast() -> None:
    r = core.align_pairwise("ACGT", "ACGT")
    assert r["score"] == 8
    assert r["cigar"] == "4M"
    assert r["identity"] == 1.0


def test_formats_are_bounded() -> None:
    assert core.validate_fasta(b">g\nACGT\n")["total_records"] == 1
    assert core.validate_fastq(b"@r\nACGT\n+\n!!!!\n")["total_records"] == 1
    assert core.validate_bed(b"chr1\t10\t20\n") == 1
    with pytest.raises(core.BioCoreException):
        core.validate_fastq(b"@r\nACGT\n+\n!!!\n")
    with pytest.raises(core.BioCoreException):
        core.validate_bed(b"chr1\t20\t10\n")
