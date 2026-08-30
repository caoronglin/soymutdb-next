"""API contracts for the verified CMS media library."""

from __future__ import annotations

import os
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from ..core.compat import StrEnum
from ..services.presign import sanitize_filename, validate_uploads_key
from .uploads import (
    ALLOWED_UPLOAD_EXTENSIONS,
    ALLOWED_UPLOAD_MIME_TYPES,
    ALLOWED_UPLOAD_PURPOSES,
    MAX_UPLOAD_SIZE_BYTES,
)


class MediaAssetStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    ARCHIVED = "archived"


def _trim_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class MediaAssetCompleteRequest(BaseModel):
    """Complete a presigned upload after the object reached S3/MinIO."""

    object_key: str = Field(..., min_length=1, max_length=1024)
    filename: str = Field(..., min_length=1, max_length=512)
    purpose: str = Field(..., min_length=1, max_length=32)
    size: int = Field(..., ge=1, le=MAX_UPLOAD_SIZE_BYTES)
    content_type: str = Field(..., min_length=1, max_length=128)
    checksum_sha256: str = Field(..., pattern=r"^[0-9a-fA-F]{64}$")

    @field_validator("object_key")
    @classmethod
    def _key_is_in_upload_namespace(cls, value: str) -> str:
        return validate_uploads_key(value)

    @field_validator("purpose")
    @classmethod
    def _purpose_is_allowed(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in ALLOWED_UPLOAD_PURPOSES:
            raise ValueError(
                "purpose must be one of: " + ", ".join(sorted(ALLOWED_UPLOAD_PURPOSES))
            )
        return value

    @field_validator("content_type")
    @classmethod
    def _mime_is_allowed(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in ALLOWED_UPLOAD_MIME_TYPES:
            raise ValueError(
                "content_type must be one of: " + ", ".join(sorted(ALLOWED_UPLOAD_MIME_TYPES))
            )
        return value

    @field_validator("checksum_sha256")
    @classmethod
    def _checksum_is_normalized(cls, value: str) -> str:
        return value.lower()

    @field_validator("filename")
    @classmethod
    def _filename_is_allowed(cls, value: str) -> str:
        value = sanitize_filename(value)
        extension = os.path.splitext(value)[1].lower()
        if extension not in ALLOWED_UPLOAD_EXTENSIONS:
            raise ValueError(
                "file extension must be one of: " + ", ".join(sorted(ALLOWED_UPLOAD_EXTENSIONS))
            )
        return value

    @model_validator(mode="after")
    def _key_matches_purpose(self):
        if not self.object_key.startswith(f"uploads/{self.purpose}/"):
            raise ValueError("object_key does not belong to the requested media purpose")
        return self


class MediaAssetUpdateRequest(BaseModel):
    """Editable accessibility metadata; object identity is immutable."""

    alt_text: str | None = Field(default=None, max_length=2000)
    caption: str | None = Field(default=None, max_length=2000)
    credit: str | None = Field(default=None, max_length=512)
    is_decorative: bool | None = None

    @field_validator("alt_text", "caption", "credit")
    @classmethod
    def _trim_text(cls, value: str | None) -> str | None:
        return _trim_optional(value)


class MediaAssetResponse(BaseModel):
    id: UUID
    object_key: str
    public_url: str
    original_filename: str
    purpose: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    width: int | None = None
    height: int | None = None
    alt_text: str | None = None
    caption: str | None = None
    credit: str | None = None
    is_decorative: bool = False
    status: MediaAssetStatus
    uploaded_by: UUID
    verified_at: datetime | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    usage_count: int = 0

    model_config = {"from_attributes": True}


class MediaAssetListResponse(BaseModel):
    items: list[MediaAssetResponse]
    total: int
    page: int
    page_size: int


__all__ = [
    "MediaAssetCompleteRequest",
    "MediaAssetListResponse",
    "MediaAssetResponse",
    "MediaAssetStatus",
    "MediaAssetUpdateRequest",
]
