"""Pydantic schemas for admin uploads (D4).

Contract:
- ``POST /api/v1/admin/uploads/presign``  UploadPresignRequest -> UploadPresignResponse

The flow is stateless (mirrors ``apps/api/app/schemas/analyses.py`` upload
schemas): the client receives a pre-signed PUT URL plus the object key and
persists ``public_url`` itself (e.g. as ``news_articles.cover_url``).
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from ..services.presign import sanitize_filename

#: Max length for the purpose segment (a single safe word, e.g. "news").
_MAX_PURPOSE_LENGTH = 32


class UploadPresignRequest(BaseModel):
    """Request a pre-signed upload URL for a public resource."""

    filename: str = Field(..., min_length=1, max_length=512)
    purpose: str = Field(default="news", min_length=1, max_length=512)

    @field_validator("filename", "purpose")
    @classmethod
    def _sanitize(cls, value: str) -> str:
        """Reject traversal / empty names early (mirrors presign checks)."""
        try:
            sanitize_filename(value)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return value

    @field_validator("purpose")
    @classmethod
    def _purpose_is_safe_word(cls, value: str) -> str:
        value = sanitize_filename(value).lower()
        if len(value) > _MAX_PURPOSE_LENGTH:
            raise ValueError(
                f"purpose must be at most {_MAX_PURPOSE_LENGTH} characters"
            )
        return value


class UploadPresignResponse(BaseModel):
    """Pre-signed PUT URL + object key + public URL (nothing persisted)."""

    upload_url: str
    object_key: str
    public_url: str
    expires_in: int
