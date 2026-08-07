"""Pydantic v2 schemas for BLAST job submission and results.

Validation notes:
- ``query_sequence`` is checked for FASTA shape and for alphabet membership
  (nucleotide vs. protein, chosen by ``program``).
- BLAST parameters are range/whitelist checked here; the service layer maps
  them to worker-safe CLI names (see ``BlastService._worker_parameters``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from ..core.compat import StrEnum


class BlastProgram(StrEnum):
    BLASTN = "blastn"
    BLASTP = "blastp"
    BLASTX = "blastx"
    TBLASTN = "tblastn"
    TBLASTX = "tblastx"


class BlastJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# Sequence alphabet validation
# ---------------------------------------------------------------------------

#: IUPAC nucleotide codes (uppercase; ``-`` for gaps).
NUCLEOTIDE_ALPHABET = frozenset("ACGTUNRYSWKMBDHVX-")
#: Standard amino-acid codes plus ambiguity letters and ``*`` (stop/gap).
PROTEIN_ALPHABET = frozenset("ACDEFGHIKLMNPQRSTVWYBZX*-")
#: Programs whose *query* is a protein sequence.
_PROTEIN_QUERY_PROGRAMS = frozenset({"blastp", "tblastn"})

#: BLAST matrix whitelist (case-insensitive on input).
ALLOWED_MATRICES = frozenset(
    {"BLOSUM62", "BLOSUM45", "BLOSUM80", "PAM30", "PAM70", "PAM250"}
)


def validate_sequence_charset(sequence: str, program: str) -> str:
    """Reject characters outside the alphabet for *program*.

    FASTA header lines (``>``) and whitespace are ignored; raises
    :class:`ValueError` listing the first offending characters.
    """
    body = "".join(
        part for part in sequence.splitlines() if not part.startswith(">")
    )
    alphabet = (
        PROTEIN_ALPHABET if program in _PROTEIN_QUERY_PROGRAMS else NUCLEOTIDE_ALPHABET
    )
    invalid = sorted(
        {ch.upper() for ch in body.replace(" ", "") if ch.upper() not in alphabet}
    )
    if invalid:
        raise ValueError(
            f"Invalid characters in query sequence: {invalid[:10]}"
            f"{'…' if len(invalid) > 10 else ''}"
        )
    return sequence


class BlastParameters(BaseModel):
    evalue: float = Field(default=1e-5, gt=0)
    word_size: int | None = Field(default=None, ge=4, le=64)
    max_target_seqs: int = Field(default=50, ge=1, le=500)
    gap_open: int | None = Field(default=None, ge=0)
    gap_extend: int | None = Field(default=None, ge=0)
    matrix: str | None = None
    dust: bool = True
    soft_masking: bool = True
    #: Client-side filter only; not forwarded to the BLAST binary.
    percent_identity: float | None = Field(default=None, ge=0.0, le=100.0)

    @field_validator("matrix")
    @classmethod
    def _validate_matrix(cls, v: str | None) -> str | None:
        if v is None:
            return None
        normalized = v.upper()
        if normalized not in ALLOWED_MATRICES:
            raise ValueError(
                f"Unsupported substitution matrix {v!r}; "
                f"allowed: {sorted(ALLOWED_MATRICES)}"
            )
        return normalized


class BlastSubmitRequest(BaseModel):
    program: BlastProgram
    database_id: int
    query_sequence: str = Field(..., min_length=10, max_length=100_000)
    parameters: BlastParameters = Field(default_factory=BlastParameters)

    @field_validator("query_sequence")
    @classmethod
    def _validate_fasta(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("query_sequence must not be empty")
        if stripped.startswith(">"):
            lines = stripped.split("\n", 1)
            if len(lines) < 2 or not lines[1].strip():
                raise ValueError(
                    "FASTA input must contain a header line and a sequence"
                )
        return stripped

    @model_validator(mode="after")
    def _validate_sequence_alphabet(self) -> BlastSubmitRequest:
        validate_sequence_charset(self.query_sequence, self.program.value)
        return self


class BlastJobResponse(BaseModel):
    job_id: str
    status: BlastJobStatus
    program: BlastProgram
    database_id: int
    submitted_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    result_url: str | None = None

    model_config = {"from_attributes": True}


#: Flat, per-HSP hit row persisted to ``blast_hits`` and returned to clients.
class BlastHit(BaseModel):
    hsp_num: int = Field(..., ge=1)
    subject_id: str
    subject_title: str = ""
    percent_identity: float = Field(..., ge=0.0, le=100.0)
    alignment_length: int = Field(..., ge=1)
    mismatches: int = Field(..., ge=0)
    gap_opens: int = Field(..., ge=0)
    query_start: int = Field(..., ge=1)
    query_end: int = Field(..., ge=1)
    subject_start: int = Field(..., ge=1)
    subject_end: int = Field(..., ge=1)
    evalue: float = Field(..., ge=0)
    bit_score: float
    query_strand: str = "plus"
    subject_strand: str = "plus"


class BlastHsp(BaseModel):
    """Legacy nested HSP shape, kept for API compatibility."""

    hsp_num: int = Field(..., ge=1)
    bit_score: float
    evalue: float
    identity: int = Field(..., ge=0)
    gaps: int = Field(default=0, ge=0)
    align_len: int = Field(..., ge=1)
    query_from: int = Field(..., ge=1)
    query_to: int = Field(..., ge=1)
    hit_from: int = Field(..., ge=1)
    hit_to: int = Field(..., ge=1)
    percent_identity: float = Field(..., ge=0.0, le=100.0)


class BlastResultResponse(BaseModel):
    """Status-aware result envelope.

    ``status`` disambiguates states: for pending/running/failed/cancelled jobs
    ``hits`` is ``None`` (never a placeholder); for completed jobs it holds
    the real hit list (possibly empty when BLAST genuinely found no hits).
    """

    job_id: str
    status: BlastJobStatus
    program: BlastProgram
    database_id: int
    query_id: str | None = None
    query_len: int | None = None
    hits: list[BlastHit] | None = None
    total_hits: int | None = None
    search_stats: dict[str, Any] | None = None
    error_message: str | None = None
    completed_at: datetime | None = None
    download_url: str | None = None

    model_config = {"from_attributes": True}


class BlastDatabaseResponse(BaseModel):
    id: int
    name: str
    db_type: str
    assembly_id: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
