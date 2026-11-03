"""Shared BLAST query and parameter validation for API and worker.

This module is the single validation owner for all five NCBI BLAST+ programs
and the explicitly narrower DIAMOND backend. It does not invoke a binary.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .protein_fasta import ProteinFastaError, parse_protein_fasta

PROGRAM_DATABASE_TYPES: dict[str, str] = {
    "blastn": "nucl",
    "blastp": "prot",
    "blastx": "prot",
    "tblastn": "nucl",
    "tblastx": "nucl",
}
PROTEIN_QUERY_PROGRAMS = frozenset({"blastp", "tblastn"})
NUCLEOTIDE_QUERY_PROGRAMS = frozenset(PROGRAM_DATABASE_TYPES) - PROTEIN_QUERY_PROGRAMS
SUPPORTED_ENGINES = frozenset({"ncbi_blast", "diamond"})
FASTA_ID_MAX_BYTES = 255
_NUCLEOTIDE_ALPHABET = frozenset("ACGTN RYSWKMBDHVU".replace(" ", ""))
_MATRICES = frozenset({"BLOSUM45", "BLOSUM62", "BLOSUM80", "PAM30", "PAM70", "PAM250"})
_PARAMETER_KEYS = frozenset(
    {
        "evalue",
        "max_target_seqs",
        "num_threads",
        "word_size",
        "dust",
        "soft_masking",
        "gapopen",
        "gapextend",
        "matrix",
        "perc_identity",
    }
)


# NCBI BLAST+ 2.17.0 reports these supported gapped protein score tables.
# Ungapped sentinel 32767/32767 is deliberately not a public gap setting.
_PROTEIN_GAP_PAIRS = {
    "BLOSUM45": {
        (13, 3),
        (12, 3),
        (11, 3),
        (10, 3),
        (16, 2),
        (15, 2),
        (14, 2),
        (13, 2),
        (12, 2),
        (19, 1),
        (18, 1),
        (17, 1),
        (16, 1),
    },
    "BLOSUM62": {
        (11, 2),
        (10, 2),
        (9, 2),
        (8, 2),
        (7, 2),
        (6, 2),
        (13, 1),
        (12, 1),
        (11, 1),
        (10, 1),
        (9, 1),
    },
    "BLOSUM80": {(25, 2), (13, 2), (9, 2), (8, 2), (7, 2), (6, 2), (11, 1), (10, 1), (9, 1)},
    "PAM30": {(7, 2), (6, 2), (5, 2), (10, 1), (9, 1), (8, 1), (15, 3), (14, 2), (14, 1), (13, 3)},
    "PAM70": {(8, 2), (7, 2), (6, 2), (11, 1), (10, 1), (9, 1), (11, 2), (12, 3)},
    "PAM250": {
        (15, 3),
        (14, 3),
        (13, 3),
        (12, 3),
        (11, 3),
        (17, 2),
        (16, 2),
        (15, 2),
        (14, 2),
        (13, 2),
        (21, 1),
        (20, 1),
        (19, 1),
        (18, 1),
        (17, 1),
    },
}


class BlastSearchError(ValueError):
    """A query or search option cannot be passed to a search binary."""


@dataclass(frozen=True, slots=True)
class NormalizedQuery:
    normalized_fasta: str
    query_length: int
    record_count: int


def _query_lines(sequence: str) -> list[str]:
    if not isinstance(sequence, str) or not sequence.strip():
        raise BlastSearchError("query is empty")
    if any(ord(char) < 32 and char not in "\r\n\t" for char in sequence):
        raise BlastSearchError("query contains control characters")
    return [
        line.strip(" \t") for line in sequence.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]


def _normalize_nucleotide(sequence: str, max_length: int) -> NormalizedQuery:
    lines = _query_lines(sequence)
    has_header = any(line.startswith(">") for line in lines)
    if not has_header:
        lines = [">query-1", *lines]
    records: list[tuple[str, str]] = []
    seen: set[str] = set()
    current_id: str | None = None
    chunks: list[str] = []
    total = 0

    def close() -> None:
        nonlocal total
        if current_id is None:
            return
        raw_body = "".join(chunks).replace(" ", "").replace("\t", "")
        if not raw_body:
            raise BlastSearchError(f"query record {current_id!r} is empty")
        if any(not char.isascii() for char in raw_body):
            raise BlastSearchError("nucleotide query contains non-ASCII symbols")
        body = raw_body.upper().replace("U", "T")
        invalid = sorted({char for char in body if char not in _NUCLEOTIDE_ALPHABET - {"U"}})
        if invalid:
            raise BlastSearchError(f"nucleotide query contains invalid symbols: {invalid[:10]}")
        if len(current_id.encode("utf-8")) > FASTA_ID_MAX_BYTES:
            raise BlastSearchError(f"query record id exceeds {FASTA_ID_MAX_BYTES} UTF-8 bytes")
        if current_id in seen:
            raise BlastSearchError(f"query record id {current_id!r} is duplicated")
        seen.add(current_id)
        records.append((current_id, body))
        total += len(body)
        if total > max_length:
            raise BlastSearchError(f"query exceeds max length {max_length} residues")

    for line_number, line in enumerate(lines, 1):
        if line.startswith(">"):
            close()
            header = line[1:].strip(" \t")
            current_id = header.split()[0] if header.split() else None
            if not current_id:
                raise BlastSearchError(f"query header on line {line_number} has no identifier")
            chunks = []
        elif current_id is None:
            if line:
                raise BlastSearchError(
                    f"query sequence precedes a FASTA header on line {line_number}"
                )
        else:
            chunks.append(line)
    close()
    if not records:
        raise BlastSearchError("query has no records")
    return NormalizedQuery(
        normalized_fasta="".join(f">{record_id}\n{body}\n" for record_id, body in records),
        query_length=total,
        record_count=len(records),
    )


def normalize_query(sequence: str, program: str, max_length: int = 100000) -> NormalizedQuery:
    """Normalize FASTA and validate query alphabet for *program*.

    ``U`` is canonicalized to ``T`` for NCBI's nucleotide programs. Protein
    validation delegates to the existing shared parser, including its exact
    duplicate-ID and residue semantics. Length is measured in residues/bases,
    while the serialized FASTA is bounded by that same biological count.
    """
    program = str(program).lower()
    if program not in PROGRAM_DATABASE_TYPES:
        raise BlastSearchError(f"unsupported BLAST program: {program!r}")
    if not isinstance(max_length, int) or isinstance(max_length, bool) or max_length < 1:
        raise BlastSearchError("max_length must be a positive integer")
    if not isinstance(sequence, str):
        raise BlastSearchError("query must be a string")
    # Bound headers/whitespace as well as residues before any parse/allocation.
    # Four bytes per allowed residue plus 4096 bytes of metadata is the budget.
    if len(sequence) > 4 * max_length + 4096:
        raise BlastSearchError("query exceeds serialized input byte limit")
    if program in PROTEIN_QUERY_PROGRAMS:
        try:
            parsed = parse_protein_fasta(sequence)
        except ProteinFastaError as exc:
            raise BlastSearchError(str(exc)) from exc
        if any(ord(char) < 32 and char not in "\r\n\t" for char in sequence):
            raise BlastSearchError("query contains control characters")
        for record in parsed.records:
            if len(record.record_id.encode("utf-8")) > FASTA_ID_MAX_BYTES:
                raise BlastSearchError(f"query record id exceeds {FASTA_ID_MAX_BYTES} UTF-8 bytes")
        # The legacy protein parser may fold Unicode lookalikes into residues;
        # reject those before the normalized output can reach a search engine.
        if not sequence.isascii():
            raise BlastSearchError("query must contain ASCII characters only")
        if parsed.query_length > max_length:
            raise BlastSearchError(f"query exceeds max length {max_length} residues")
        return NormalizedQuery(parsed.to_fasta, parsed.query_length, len(parsed.records))
    return _normalize_nucleotide(sequence, max_length)


def _boolean(value: Any, key: str) -> bool:
    if not isinstance(value, bool):
        raise BlastSearchError(f"{key} must be a boolean")
    return value


def validate_search_parameters(
    program: str, engine: str, params: dict[str, Any] | None
) -> dict[str, Any]:
    """Validate and normalize the bounded, canonical search parameter set."""
    program = str(program).lower()
    engine = str(engine).lower()
    if program not in PROGRAM_DATABASE_TYPES:
        raise BlastSearchError(f"unsupported BLAST program: {program!r}")
    if engine not in SUPPORTED_ENGINES:
        raise BlastSearchError(f"unsupported search engine: {engine!r}")
    source = dict(params or {})
    unknown = sorted(set(source) - _PARAMETER_KEYS)
    if unknown:
        raise BlastSearchError(f"unsupported search parameter(s): {unknown}")
    if engine == "diamond" and program != "blastp":
        raise BlastSearchError("DIAMOND supports blastp only")
    out: dict[str, Any] = {}
    if "evalue" in source:
        value = source["evalue"]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise BlastSearchError("evalue must be a finite positive number")
        out["evalue"] = float(value)
    for key in ("max_target_seqs", "num_threads", "word_size"):
        if key not in source:
            continue
        value = source[key]
        if isinstance(value, bool) or not isinstance(value, int):
            raise BlastSearchError(f"{key} must be an integer")
        maximum = 500 if key == "max_target_seqs" else 4 if key == "num_threads" else None
        minimum = 1 if key != "word_size" else 2
        if maximum is not None and not minimum <= value <= maximum:
            raise BlastSearchError(f"{key} must be between {minimum} and {maximum}")
        if maximum is None and value < minimum:
            raise BlastSearchError("word_size must be at least 2")
        if key == "word_size" and program == "blastn" and value < 4:
            raise BlastSearchError("blastn word_size must be at least 4")
        out[key] = value
    if "dust" in source:
        if program != "blastn":
            raise BlastSearchError("dust is supported only for blastn")
        out["dust"] = _boolean(source["dust"], "dust")
    if "soft_masking" in source:
        out["soft_masking"] = _boolean(source["soft_masking"], "soft_masking")
    for key in ("gapopen", "gapextend"):
        if key in source:
            value = source[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise BlastSearchError(f"{key} must be a non-negative integer")
            if program == "tblastx":
                raise BlastSearchError("tblastx does not support gap penalties")
            out[key] = value
    if "gapopen" in out and "gapextend" not in out or "gapextend" in out and "gapopen" not in out:
        raise BlastSearchError("gapopen and gapextend must be supplied together")
    if "matrix" in source:
        matrix = source["matrix"]
        if not isinstance(matrix, str) or matrix.upper() not in _MATRICES:
            raise BlastSearchError(f"matrix must be one of {sorted(_MATRICES)}")
        if program == "blastn":
            raise BlastSearchError("substitution matrices are not supported by blastn")
        out["matrix"] = matrix.upper()
    if engine == "ncbi_blast" and program not in {"blastn", "tblastx"} and "gapopen" in out:
        matrix = out.get("matrix", "BLOSUM62")
        if (out["gapopen"], out["gapextend"]) not in _PROTEIN_GAP_PAIRS[matrix]:
            raise BlastSearchError(f"unsupported gapopen/gapextend combination for {matrix}")
    if "perc_identity" in source:
        value = source["perc_identity"]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 100
        ):
            raise BlastSearchError("perc_identity must be between 0 and 100")
        if engine == "diamond":
            raise BlastSearchError("perc_identity is not supported by DIAMOND")
        if program != "blastn":
            raise BlastSearchError("perc_identity is supported only for blastn")
        out["perc_identity"] = float(value)
    if engine == "diamond":
        unsupported = set(out) - {
            "evalue",
            "max_target_seqs",
            "num_threads",
            "gapopen",
            "gapextend",
            "matrix",
        }
        if unsupported:
            raise BlastSearchError(f"DIAMOND does not support: {sorted(unsupported)}")
    return out


__all__ = [
    "BlastSearchError",
    "FASTA_ID_MAX_BYTES",
    "NormalizedQuery",
    "PROGRAM_DATABASE_TYPES",
    "PROTEIN_QUERY_PROGRAMS",
    "normalize_query",
    "validate_search_parameters",
]
