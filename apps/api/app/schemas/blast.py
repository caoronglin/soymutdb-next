"""Pydantic v2 schemas for BLAST job submission and results.

Validation notes:
- ``query_sequence`` is checked for FASTA shape and for alphabet membership
  (nucleotide vs. protein, chosen by ``program``). Protein structure — empty
  records, duplicate record ids, terminal stops — is decided by
  :mod:`soymutdb_jobs.protein_fasta`, the one owner shared with the worker,
  so a submission that is accepted here is searchable there.
- BLAST parameters are range/whitelist checked here; the service layer maps
  them to worker-safe CLI names (see ``BlastService._worker_parameters``).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from soymutdb_jobs.blast_catalog import public_source_url
from soymutdb_jobs.protein_fasta import PROTEIN_ALPHABET as PROTEIN_ALPHABET
from soymutdb_jobs.protein_fasta import (
    ProteinFastaError,
    parse_protein_fasta,
)

from ..core.compat import StrEnum

#: Allowed characters for a BLAST database *name* — matches the worker-side
#: whitelist (alphanumeric / ``-`` / ``_``) so identifiers can never carry
#: path separators or traversal sequences.
_DATABASE_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")


class BlastProgram(StrEnum):
    """Every program value that can appear in a *stored* job row.

    This is a storage/response vocabulary, not a submission contract. The
    search engine is DIAMOND ``blastp`` only; the other values remain here so
    that jobs persisted before the engine was reduced can still be read and
    rendered. :class:`BlastSubmitProgram` is what new requests must use.
    """

    BLASTN = "blastn"
    BLASTP = "blastp"
    BLASTX = "blastx"
    TBLASTN = "tblastn"
    TBLASTX = "tblastx"


class BlastSubmitProgram(StrEnum):
    """The only program this deployment can execute: DIAMOND ``blastp``."""

    BLASTP = "blastp"


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

#: IUPAC nucleotide codes (uppercase; ``-`` for gaps). Historic vocabulary:
#: only ``blastp`` is submittable, but stored job rows may still name the
#: nucleotide programs, so this alphabet stays readable.
NUCLEOTIDE_ALPHABET = frozenset("ACGTUNRYSWKMBDHVX-")
#: ``PROTEIN_ALPHABET`` is imported above from the shared contract, so the API
#: and the worker cannot drift apart on what counts as a protein residue.
#: Programs whose *query* is a protein sequence. The only executable program
#: is ``blastp``, so every submitted query is protein.
_PROTEIN_QUERY_PROGRAMS = frozenset({"blastp"})

#: BLAST matrix whitelist (case-insensitive on input).
ALLOWED_MATRICES = frozenset(
    {"BLOSUM62", "BLOSUM45", "BLOSUM80", "PAM30", "PAM70", "PAM250"}
)


def validate_sequence_charset(sequence: str, program: str) -> str:
    """Reject characters outside the alphabet for *program*.

    FASTA header lines (``>``) and whitespace are ignored; raises
    :class:`ValueError` listing the first offending characters.
    """
    if program in _PROTEIN_QUERY_PROGRAMS:
        parse_protein_fasta(sequence)
        return sequence
    body = "".join(
        part for part in sequence.splitlines() if not part.startswith(">")
    )
    alphabet = NUCLEOTIDE_ALPHABET
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
    max_target_seqs: int = Field(default=50, ge=1, le=500)
    gap_open: int | None = Field(default=None, ge=0)
    gap_extend: int | None = Field(default=None, ge=0)
    matrix: str | None = None
    #: Client-side filter only; not forwarded to the search binary.
    percent_identity: float | None = Field(default=None, ge=0.0, le=100.0)
    #: Retired NCBI-BLAST inputs. ``BlastParameters`` is a submission-only
    #: schema (stored job payloads are read as raw dicts), so these are
    #: rejected outright rather than silently ignored — DIAMOND has no
    #: equivalent and quietly ignoring them would misreport the search.
    word_size: int | None = Field(default=None, ge=4, le=64)
    dust: bool | None = None
    soft_masking: bool | None = None

    @field_validator("word_size", "dust", "soft_masking")
    @classmethod
    def _reject_retired_blast_params(cls, v, info):
        if v is None:
            return v
        raise ValueError(
            f"parameters.{info.field_name} is a retired NCBI BLAST option; "
            "this deployment searches with DIAMOND blastp, which has no equivalent"
        )

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
    #: Only DIAMOND ``blastp`` is executable; the wider :class:`BlastProgram`
    #: vocabulary exists solely to read historical rows.
    program: BlastSubmitProgram = BlastSubmitProgram.BLASTP
    #: Numeric id of an active database from ``GET /blast/databases``.
    database_id: int | None = Field(default=None, gt=0)
    #: Database *name* alias (e.g. ``"williams82_cds"``); must match an active
    #: entry in the database whitelist (``blast_databases`` table).  ``database``
    #: and ``database_id`` are interchangeable — when both are given they must
    #: resolve to the same row (the service enforces that).  When neither is
    #: given, the configured default database is used.
    database: str | None = Field(default=None, max_length=256)
    query_sequence: str = Field(..., min_length=10, max_length=100_000)
    parameters: BlastParameters = Field(default_factory=BlastParameters)

    @field_validator("database")
    @classmethod
    def _validate_database_name(cls, v: str | None) -> str | None:
        """Reject names that could carry path separators / traversal.

        Defense at the API boundary: the service re-checks existence against
        the database whitelist before the job is created.
        """
        if v is None:
            return None
        if not _DATABASE_NAME_RE.fullmatch(v):
            raise ValueError(
                "database must be a plain identifier (letters, digits, '-', '_')"
            )
        return v

    @field_validator("query_sequence", mode="before")
    @classmethod
    def _validate_fasta(cls, v: object) -> str:
        """Refuse a query the worker could not search.

        ``mode="before"`` so an empty or header-only submission reports the
        real reason instead of the length cap, which would otherwise fire first
        and tell the submitter their empty query "should have at least 10
        characters".

        The previous check only inspected the first header, so a later empty
        record was accepted here and then failed inside DIAMOND with an opaque
        ``Missing fields in input line``. Empty records and duplicate record
        ids are now rejected at submission time with a 422.
        """
        if not isinstance(v, str):
            return v  # type: ignore[return-value]
        if len(v) > 100_000:
            # Let the field's size constraint reject before allocating a parse.
            return v
        try:
            parse_protein_fasta(v)
        except ProteinFastaError as exc:
            raise ValueError(f"query_sequence: {exc}") from exc
        return v.strip(" \t\r\n")


class BlastJobResponse(BaseModel):
    job_id: str
    status: BlastJobStatus
    program: BlastProgram
    database_id: int
    database: str | None = None
    query_sequence: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    hit_count: int = 0
    submitted_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    result_url: str | None = None
    #: Release/assembly provenance of the searched database, resolved through
    #: the job's database row. A stored result must state which release and
    #: assembly it was computed against, otherwise it is indistinguishable from
    #: one produced by a different coordinate namespace.
    release_id: int | None = None
    assembly_name: str | None = None

    model_config = {"from_attributes": True}


class PublicBlastSubmission(BaseModel):
    """The capability is returned once; send it only in X-Blast-Token."""

    job: BlastJobResponse
    access_token: str
    expires_at: datetime


class BlastJobListResponse(BaseModel):
    items: list[BlastJobResponse] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


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
    #: Human-readable assembly identifier resolved from ``assemblies`` —
    #: lets clients group/search databases per genome assembly.
    assembly_name: str | None = None
    assembly_version: str | None = None
    assembly_is_default: bool | None = None
    #: Published release the database's assembly belongs to. Surfaced so a
    #: client can prove the list is release-scoped.
    release_id: int | None = None

    model_config = {"from_attributes": True}

    engine: Literal["diamond", "ncbi_blast"] = "diamond"
    sequence_type: Literal[
        "genome", "cds", "transcript", "protein", "repeat_masked",
        "pan_genome", "family_consensus", "custom",
    ] | None = None
    annotation_version: str | None = None
    source_url: str | None = None
    sequence_count: int | None = Field(default=None, ge=0)
    total_length: int | None = Field(default=None, ge=0)
    fasta_sha256: str | None = None
    index_version: str | None = None
    build_status: Literal["pending", "ready", "building", "failed"] = "pending"
    is_default: bool = False
    license: str | None = None

    @field_validator("source_url", mode="before")
    @classmethod
    def public_source_url(cls, value: object) -> str | None:
        """Stored provenance is untrusted; omit paths and private URL authorities."""
        return public_source_url(value)
