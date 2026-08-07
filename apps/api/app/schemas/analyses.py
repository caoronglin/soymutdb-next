"""Pydantic v2 schemas for the analyses feature (fastp / scanpy).

Validation notes:
- Upload requests enforce the 500 MB size ceiling and reject filenames that
  contain path separators or traversal segments (``..``).
- Submit requests carry the object keys returned by the upload endpoint;
  the service layer re-checks the ``analyses/`` prefix on every key.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ..core.compat import StrEnum
from ..services.presign import MAX_UPLOAD_SIZE


class AnalysisType(StrEnum):
    """Supported analysis pipelines (path parameter of the submit endpoint)."""

    FASTP = "fastp"
    SCANPY = "scanpy"


class AnalysisJobStatus(StrEnum):
    """Job status values – aligned with the shared Job state machine."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Upload presign
# ---------------------------------------------------------------------------


class AnalysesUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0, le=MAX_UPLOAD_SIZE)
    content_type: str | None = Field(default=None, max_length=128)

    @field_validator("filename")
    @classmethod
    def _reject_path_in_filename(cls, v: str) -> str:
        """Reject path separators and traversal segments in the client filename.

        The stored key is built from the sanitized basename only, so a
        malicious name can never escape the ``analyses/{job_id}/input/``
        prefix.
        """
        name = v.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if not name or name in {".", ".."}:
            raise ValueError("filename must not be empty or a path segment")
        if name != v:
            raise ValueError("filename must not contain path separators")
        return name


class AnalysesUploadResponse(BaseModel):
    upload_url: str
    object_key: str
    expires_in: int


# ---------------------------------------------------------------------------
# Job submission / status
# ---------------------------------------------------------------------------


class AnalysesSubmitRequest(BaseModel):
    input_objects: list[str] = Field(min_length=1, max_length=100)
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("input_objects")
    @classmethod
    def _no_empty_keys(cls, v: list[str]) -> list[str]:
        if any(not key.strip() for key in v):
            raise ValueError("input_objects must not contain empty keys")
        return v


class AnalysesSubmitResponse(BaseModel):
    job_id: str
    status: Literal["queued"]


class AnalysesJobResponse(BaseModel):
    job_id: str
    analysis_type: AnalysisType
    status: AnalysisJobStatus
    error_message: str | None = None
    #: Worker-written summary; ``None`` until the job completes.
    result: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class AnalysesDownloadResponse(BaseModel):
    download_url: str
    expires_in: int


__all__ = [
    "AnalysesDownloadResponse",
    "AnalysesJobResponse",
    "AnalysesSubmitRequest",
    "AnalysesSubmitResponse",
    "AnalysesUploadRequest",
    "AnalysesUploadResponse",
    "AnalysisJobStatus",
    "AnalysisType",
]
