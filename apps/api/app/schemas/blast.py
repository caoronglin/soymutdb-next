"""Pydantic v2 schemas for BLAST job submission and results."""

from __future__ import annotations

from datetime import datetime
from ..core.compat import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


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
    EXPIRED = "expired"


class BlastParameters(BaseModel):
    evalue: float = Field(default=1e-5, gt=0)
    word_size: int | None = Field(default=None, ge=4, le=64)
    max_target_seqs: int = Field(default=50, ge=1, le=500)
    gap_open: int | None = None
    gap_extend: int | None = None
    matrix: str | None = None
    dust: bool = True
    soft_masking: bool = True
    percent_identity: float | None = Field(default=None, ge=0.0, le=100.0)


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


class BlastHsp(BaseModel):
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


class BlastHit(BaseModel):
    hit_num: int = Field(..., ge=1)
    hit_id: str
    hit_def: str = ""
    hit_accession: str
    hit_len: int = Field(..., ge=1)
    hsps: list[BlastHsp] = Field(default_factory=list)
    best_evalue: float | None = None
    best_bit_score: float | None = None
    gene_id: str | None = None
    chromosome: str | None = None


class BlastResultResponse(BaseModel):
    job_id: str
    program: BlastProgram
    database_id: int
    query_id: str
    query_len: int = Field(..., ge=1)
    hits: list[BlastHit] = Field(default_factory=list)
    total_hits: int = Field(default=0, ge=0)
    search_stats: dict[str, Any] = Field(default_factory=dict)
    completed_at: datetime

    model_config = {"from_attributes": True}


class BlastDatabaseResponse(BaseModel):
    id: int
    name: str
    db_type: str
    assembly_id: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
