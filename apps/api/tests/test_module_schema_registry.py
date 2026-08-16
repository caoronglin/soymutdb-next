"""Unit tests for the strict module TSV schema registry."""

from __future__ import annotations

from app.services.module_schema_registry import validate_tsv


def test_gene_module_rejects_wrong_headers() -> None:
    result = validate_tsv("genes", b"gene\tchromosome\nG1\tChr01\n")
    assert result.ok is False
    assert result.errors[0].code == "header_mismatch"


def test_gene_module_reports_duplicate_key() -> None:
    data = b"gene_id\tchromosome\tstart\tend\nG1\tChr01\t1\t9\nG1\tChr01\t10\t20\n"
    result = validate_tsv("genes", data)
    assert result.errors[0].row == 3
    assert result.errors[0].code == "duplicate_key"


def test_gene_module_accepts_valid_rows_and_converts_integers() -> None:
    data = b"gene_id\tchromosome\tstart\tend\tmutation_feature\nG1\tChr01\t1\t9\tSNP\n"
    result = validate_tsv("genes", data)
    assert result.ok is True
    assert result.rows == [
        {
            "gene_id": "G1",
            "chromosome": "Chr01",
            "start": 1,
            "end": 9,
            "mutation_feature": "SNP",
        }
    ]


def test_gene_module_rejects_end_before_start() -> None:
    data = b"gene_id\tchromosome\tstart\tend\nG1\tChr01\t10\t9\n"
    result = validate_tsv("genes", data)
    assert result.ok is False
    assert result.errors[0].code == "end_before_start"


def test_gene_module_rejects_nul_bytes_and_invalid_utf8() -> None:
    assert validate_tsv("genes", b"\x00gene").errors[0].code == "nul_byte"
    assert validate_tsv("genes", b"\xff\xfe").errors[0].code == "invalid_utf8"


def test_unknown_schema_is_rejected() -> None:
    result = validate_tsv("not_a_module", b"a\nb\n")
    assert result.ok is False
    assert result.errors[0].code == "unknown_schema"
