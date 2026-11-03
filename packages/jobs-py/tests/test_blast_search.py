from __future__ import annotations

import math

import pytest

from soymutdb_jobs.blast_search import (
    PROGRAM_DATABASE_TYPES,
    PROTEIN_QUERY_PROGRAMS,
    BlastSearchError,
    NormalizedQuery,
    normalize_query,
    validate_search_parameters,
)


@pytest.mark.parametrize(
    ("program", "db"),
    [
        ("blastn", "nucl"),
        ("blastp", "prot"),
        ("blastx", "prot"),
        ("tblastn", "nucl"),
        ("tblastx", "nucl"),
    ],
)
def test_program_database_contract(program, db):
    assert PROGRAM_DATABASE_TYPES[program] == db


def test_protein_query_programs_are_explicit():
    assert PROTEIN_QUERY_PROGRAMS == {"blastp", "tblastn"}


@pytest.mark.parametrize("program", ["blastn", "blastx", "tblastx"])
def test_nucleotide_plain_sequence_gets_stable_header_and_u_is_t(program):
    result = normalize_query("acgu nry\r\n", program)
    assert isinstance(result, NormalizedQuery)
    assert result.normalized_fasta == ">query-1\nACGTNRY\n"
    assert result.query_length == 7
    assert result.record_count == 1


def test_nucleotide_multifasta_wraps_and_normalizes_crlf():
    result = normalize_query(">a description\r\nACG U\r\n>b\nNNNN\n", "blastn")
    assert result.normalized_fasta == ">a\nACGT\n>b\nNNNN\n"
    assert result.query_length == 8
    assert result.record_count == 2


@pytest.mark.parametrize(
    "query",
    ["", ">q\n", ">q\nACG\n>q\nTTT", ">\nACG", "ACG\n>q\nTTT"],
)
def test_nucleotide_rejects_empty_duplicate_missing_id_and_mixed_shape(query):
    with pytest.raises(BlastSearchError):
        normalize_query(query, "blastn")


@pytest.mark.parametrize("symbol", ["X", "-", "*", "?", "1", "\x00", "\v"])
def test_nucleotide_rejects_non_iupac_and_controls(symbol):
    with pytest.raises(BlastSearchError):
        normalize_query(f">q\nACG{symbol}T", "blastn")


def test_protein_delegates_existing_parser_and_counts_records():
    result = normalize_query(">p\nmkta\n>q desc\nMKT", "blastp")
    assert result.normalized_fasta == ">p\nMKTA\n>q\nMKT\n"
    assert (result.query_length, result.record_count) == (7, 2)
    tblastn = normalize_query("MKTIIA", "tblastn")
    assert tblastn.normalized_fasta == ">query\nMKTIIA\n"


@pytest.mark.parametrize("program", ["blastn", "blastp", "blastx", "tblastn", "tblastx"])
def test_query_length_is_bounded(program):
    sequence = "ACGT" if program == "blastn" else "MKTW"
    with pytest.raises(BlastSearchError, match="max length"):
        normalize_query(sequence, program, max_length=3)


@pytest.mark.parametrize("program", ["blastn", "blastp", "blastx", "tblastn", "tblastx"])
def test_all_ncbi_programs_accept_common_safe_parameters(program):
    params = {"evalue": 1e-5, "max_target_seqs": 20, "num_threads": 2, "word_size": 4}
    if program != "blastn":
        params["matrix"] = "blosum62"
        if program != "tblastx":
            params["gapopen"] = 11
            params["gapextend"] = 1
    else:
        params["dust"] = True
    out = validate_search_parameters(program, "ncbi_blast", params)
    assert out["evalue"] == 1e-5
    assert out["num_threads"] == 2


def test_identity_filter_is_only_a_native_blastn_parameter():
    out = validate_search_parameters(
        "blastp",
        "diamond",
        {"evalue": 1e-5, "max_target_seqs": 10, "num_threads": 2, "matrix": "BLOSUM62"},
    )
    assert out["matrix"] == "BLOSUM62"
    with pytest.raises(BlastSearchError, match="not supported by DIAMOND"):
        validate_search_parameters("blastp", "diamond", {"perc_identity": 90})
    with pytest.raises(BlastSearchError, match="blastp only"):
        validate_search_parameters("blastn", "diamond", {})
    assert (
        validate_search_parameters("blastn", "ncbi_blast", {"perc_identity": 90})["perc_identity"]
        == 90.0
    )
    with pytest.raises(BlastSearchError, match="only for blastn"):
        validate_search_parameters("blastp", "ncbi_blast", {"perc_identity": 90})


@pytest.mark.parametrize(
    ("program", "params", "message"),
    [
        ("blastn", {"word_size": 3}, "blastn word_size"),
        ("blastp", {"dust": True}, "dust"),
        ("blastn", {"matrix": "BLOSUM62"}, "substitution matrices"),
        ("tblastx", {"gapopen": 1, "gapextend": 1}, "gap penalties"),
        ("blastp", {"gapopen": 1}, "together"),
        ("blastp", {"num_threads": 5}, "num_threads"),
        ("blastp", {"max_target_seqs": 0}, "max_target_seqs"),
        ("blastp", {"evalue": math.inf}, "evalue"),
        ("blastp", {"unknown": 1}, "unsupported"),
    ],
)
def test_program_specific_parameter_rejections(program, params, message):
    with pytest.raises(BlastSearchError, match=message):
        validate_search_parameters(program, "ncbi_blast", params)


def test_normalizes_parameter_keys_without_arbitrary_flags():
    assert validate_search_parameters("blastp", "ncbi_blast", {"matrix": "pam70"}) == {
        "matrix": "PAM70"
    }
    with pytest.raises(BlastSearchError):
        validate_search_parameters("blastp", "ncbi_blast", {"-outfmt": "6"})


@pytest.mark.parametrize("program", ["blastn", "blastp", "blastx", "tblastn", "tblastx"])
def test_query_metadata_and_unicode_are_not_unbounded_or_normalized_into_residues(program):
    for sequence in (">q\x00\nACGT", ">q\nACGſ", ">" + "x" * 5000 + "\nACGT"):
        with pytest.raises(BlastSearchError):
            normalize_query(sequence, program, max_length=10)


@pytest.mark.parametrize("program", ["blastp", "blastx", "tblastn", "tblastx"])
def test_identity_is_rejected_for_every_non_blastn_ncbi_program(program):
    with pytest.raises(BlastSearchError, match="only for blastn"):
        validate_search_parameters(program, "ncbi_blast", {"perc_identity": 90})


@pytest.mark.parametrize("program", ["blastp", "blastx", "tblastn"])
def test_ncbi_rejects_gap_pairs_outside_matrix_score_tables(program):
    with pytest.raises(BlastSearchError, match="combination"):
        validate_search_parameters(program, "ncbi_blast", {"gapopen": 999, "gapextend": 1})
    assert (
        validate_search_parameters(
            program,
            "ncbi_blast",
            {
                "gapopen": 14,
                "gapextend": 2,
                "matrix": "BLOSUM45",
            },
        )["gapopen"]
        == 14
    )


@pytest.mark.parametrize("program", ["blastn", "blastp", "blastx", "tblastn", "tblastx"])
def test_fasta_record_ids_are_bounded_in_utf8_bytes_without_truncation(program):
    sequence = (
        f">{'x' * 256}\nMKTIIA" if program in PROTEIN_QUERY_PROGRAMS else f">{'x' * 256}\nACGTN"
    )
    with pytest.raises(BlastSearchError, match="255 UTF-8 bytes"):
        normalize_query(sequence, program)


def test_multibyte_record_id_is_bounded_by_utf8_bytes():
    with pytest.raises(BlastSearchError, match="255 UTF-8 bytes"):
        normalize_query(">é" * 128 + "\nACGT", "blastn")
