"""Pydantic v2 schemas for the GWAS feature (EMMAX / GEMMA association runs).

Validation notes:
- ``method`` is a whitelisted enum (``emmax`` / ``gemma``).
- Object keys are validated at the service layer (``gwas/`` namespace +
  ``/input/`` segment); the schema keeps format checks for filename
  extensions and the file-size ceiling constant is reused from ``presign``.
- ``params`` is a whitelist-checked JSON object (see
  ``app.services.gwas_service._PARAM_SPECS``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from ..core.compat import StrEnum

#: Max upload size shared with the analyses upload flow (500 MB).
from ..services.presign import MAX_UPLOAD_SIZE

#: Allowed filename extensions per input-file role (defense in depth; the
#: worker re-validates the file contents when the job runs).
_PHENOTYPE_EXTENSIONS = frozenset({".pheno", ".trait", ".txt", ".tsv", ".csv"})
_GENOTYPE_EXTENSIONS = frozenset({".tped", ".bed", ".bimbam", ".geno", ".txt", ".tsv"})
_KINSHIP_EXTENSIONS = frozenset({".kin", ".cXX.txt", ".rel", ".matrix", ".txt"})
_COVARIATE_EXTENSIONS = frozenset({".cov", ".txt", ".tsv", ".csv"})


class GwasMethod(StrEnum):
    """Supported association-testing engines."""

    EMMAX = "emmax"
    GEMMA = "gemma"


class GwasFileType(StrEnum):
    """Input file family (``snp`` = EMMAX-style per-SNP phenotype format)."""

    SNP = "snp"
    OTHER = "other"


class GwasJobStatus(StrEnum):
    """Job status values – BLAST-style spelling aligned with the shared state
    machine."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _lower_extension(filename: str) -> str:
    """Return the lowercase suffix of *filename* (after the last dot)."""
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    return base.lower()


class GwasSubmitRequest(BaseModel):
    method: GwasMethod
    object_type: GwasFileType = GwasFileType.SNP
    #: Object key returned by ``POST /api/v1/gwas/uploads`` for the phenotype
    #: file (required).  Genotype / kinship / covariate files are optional and
    #: depend on the engine and the analysis design.
    phenotype_object_key: str = Field(..., min_length=1, max_length=2048)
    genotype_object_key: str | None = Field(default=None, max_length=2048)
    kinship_object_key: str | None = Field(default=None, max_length=2048)
    covariate_object_key: str | None = Field(default=None, max_length=2048)
    #: Whitelisted engine parameters (see service ``_PARAM_SPECS``).
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "phenotype_object_key",
        "genotype_object_key",
        "kinship_object_key",
        "covariate_object_key",
    )
    @classmethod
    def _validate_key_shape(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not v or v.startswith("/") or "//" in v or ".." in v.split("/"):
            raise ValueError("object key must be a plain S3 key (no traversal)")
        return v

    @field_validator("phenotype_object_key")
    @classmethod
    def _validate_phenotype_extension(cls, v: str) -> str:
        ext = _lower_extension(v)
        if not any(ext.endswith(e) for e in _PHENOTYPE_EXTENSIONS):
            raise ValueError(
                "phenotype file must use one of the extensions "
                f"{sorted(_PHENOTYPE_EXTENSIONS)}"
            )
        return v

    @field_validator("genotype_object_key")
    @classmethod
    def _validate_genotype_extension(cls, v: str | None) -> str | None:
        if v is None:
            return None
        ext = _lower_extension(v)
        if not any(ext.endswith(e) for e in _GENOTYPE_EXTENSIONS):
            raise ValueError(
                "genotype file must use one of the extensions "
                f"{sorted(_GENOTYPE_EXTENSIONS)}"
            )
        return v

    @field_validator("kinship_object_key")
    @classmethod
    def _validate_kinship_extension(cls, v: str | None) -> str | None:
        if v is None:
            return None
        ext = _lower_extension(v)
        if not any(ext.endswith(e) for e in _KINSHIP_EXTENSIONS):
            raise ValueError(
                "kinship file must use one of the extensions "
                f"{sorted(_KINSHIP_EXTENSIONS)}"
            )
        return v

    @field_validator("covariate_object_key")
    @classmethod
    def _validate_covariate_extension(cls, v: str | None) -> str | None:
        if v is None:
            return None
        ext = _lower_extension(v)
        if not any(ext.endswith(e) for e in _COVARIATE_EXTENSIONS):
            raise ValueError(
                "covariate file must use one of the extensions "
                f"{sorted(_COVARIATE_EXTENSIONS)}"
            )
        return v


class GwasUploadRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=256)


class GwasUploadResponse(BaseModel):
    upload_url: str
    object_key: str
    expires_in: int
    max_upload_size: int = MAX_UPLOAD_SIZE


class GwasJobResponse(BaseModel):
    """Job status envelope; ``result`` is the worker-written summary once the
    job completes (MinIO object keys + association statistics), ``None``
    otherwise."""

    job_id: str
    method: GwasMethod
    status: GwasJobStatus
    object_type: GwasFileType = GwasFileType.SNP
    submitted_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    result: dict[str, Any] | None = None


class GwasResultResponse(BaseModel):
    """Status-aware result envelope for a GWAS job.

    Completed jobs carry pre-signed download URLs for the Manhattan data
    JSON, the QQ data JSON and the self-contained ``Manhattan_QQ.html``
    report (all stored under ``gwas/{job_id}/output/`` in MinIO).
    """

    job_id: str
    method: GwasMethod
    status: GwasJobStatus
    manhattan_url: str | None = None
    qq_url: str | None = None
    report_url: str | None = None
    assoc_url: str | None = None
    n_variants: int | None = None
    error_message: str | None = None
    completed_at: datetime | None = None
