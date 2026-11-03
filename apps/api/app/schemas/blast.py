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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from soymutdb_jobs.blast_catalog import public_source_url
from soymutdb_jobs.blast_search import (
    normalize_query,
    validate_search_parameters,
)
from soymutdb_jobs.protein_fasta import PROTEIN_ALPHABET as PROTEIN_ALPHABET

from ..core.compat import StrEnum

#: Allowed characters for a BLAST database *name* — matches the worker-side
#: whitelist (alphanumeric / ``-`` / ``_``) so identifiers can never carry
#: path separators or traversal sequences.
_DATABASE_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")


class BlastProgram(StrEnum):
    """Program vocabulary shared by stored jobs and current responses."""

    BLASTN = "blastn"
    BLASTP = "blastp"
    BLASTX = "blastx"
    TBLASTN = "tblastn"
    TBLASTX = "tblastx"


class BlastSubmitProgram(StrEnum):
    """Programs supported by the explicit NCBI BLAST+ engine."""

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


def validate_sequence_charset(sequence: str, program: str) -> str:
    """Use the same query owner as the executing worker."""
    normalize_query(sequence, program)
    return sequence


class BlastParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    evalue: float = Field(default=1e-5, gt=0, le=1000)
    max_target_seqs: int = Field(default=50, ge=1, le=500)
    gap_open: int | None = Field(default=None, ge=0, le=100)
    gap_extend: int | None = Field(default=None, ge=0, le=100)
    matrix: str | None = None
    word_size: int | None = Field(default=None, ge=2, le=64)
    dust: bool | None = None
    soft_masking: bool | None = None
    percent_identity: float | None = Field(default=None, ge=0, le=100)

    @field_validator("matrix")
    @classmethod
    def _validate_matrix(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    def canonical_parameters(self, program: str, engine: str) -> dict:
        params = self.model_dump(exclude_none=True)
        if "percent_identity" in params:
            if engine != "ncbi_blast" or program != "blastn":
                raise ValueError("percent_identity is supported only by NCBI blastn")
            params["perc_identity"] = params.pop("percent_identity")
        for old, new in (("gap_open", "gapopen"), ("gap_extend", "gapextend")):
            if old in params:
                params[new] = params.pop(old)
        return validate_search_parameters(program, engine, params)


class BlastSubmitRequest(BaseModel):
    #: New submissions choose NCBI BLAST+ unless DIAMOND is explicit.
    engine: Literal["ncbi_blast", "diamond"] = "ncbi_blast"
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
    def _validate_query_shape(cls, value, info):
        if isinstance(value, str) and len(value) <= 100000:
            normalize_query(value, info.data.get("program", BlastSubmitProgram.BLASTP).value)
        return value

    @model_validator(mode="after")
    def _validate_search(self) -> BlastSubmitRequest:
        self.parameters.canonical_parameters(self.program.value, self.engine)
        normalize_query(self.query_sequence, self.program.value)
        self.query_sequence = self.query_sequence.strip(" \t\r\n")
        return self


class BlastJobResponse(BaseModel):
    engine: Literal["ncbi_blast", "diamond"] = "diamond"
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
    query_id: str | None = None
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
