"""Pydantic schemas for admin uploads (D4 + E2-1 server-side validation).

Contract:
- ``POST /api/v1/admin/uploads/presign``  UploadPresignRequest -> UploadPresignResponse

The flow is stateless (mirrors ``apps/api/app/schemas/analyses.py`` upload
schemas): the client receives a pre-signed PUT URL plus the object key and
persists ``public_url`` itself (e.g. as ``news_articles.cover_url``).

E2-1 server-side validation (oracle 🔴):
- ``purpose`` must be in the allowlist (news/editor/about) — it becomes an
  object-key path segment.
- ``filename`` extension must be jpg/jpeg/png/webp — SVG is explicitly banned
  (XSS vector).
- ``size`` is required and capped at 10 MB (the presign flow has no bytes to
  sniff, so the client declares the size up front).
- ``content_type`` (optional, declared MIME) must be in the image allowlist.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field, field_validator

from ..services.presign import sanitize_filename

#: Max length for the purpose segment (a single safe word, e.g. "news").
_MAX_PURPOSE_LENGTH = 32

#: Allowed upload purposes (content-editor surfaces).  Anything else is
#: rejected — the purpose becomes an object-key path segment.
ALLOWED_UPLOAD_PURPOSES = frozenset({"news", "editor", "about"})

#: Allowed image extensions (SVG is explicitly banned — XSS vector).
ALLOWED_UPLOAD_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})

#: Allowed MIME types (declared by the client; content sniffing is out of
#: scope for the stateless presign flow).
ALLOWED_UPLOAD_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})

#: Hard ceiling for a single admin upload (bytes).
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024


class UploadPresignRequest(BaseModel):
    """Request a pre-signed upload URL for a public resource."""

    filename: str = Field(..., min_length=1, max_length=512)
    purpose: str = Field(default="news", min_length=1, max_length=512)
    size: int = Field(..., ge=1, le=MAX_UPLOAD_SIZE_BYTES)
    content_type: str | None = Field(default=None, max_length=128)

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
        if value not in ALLOWED_UPLOAD_PURPOSES:
            raise ValueError(
                "purpose must be one of: "
                + ", ".join(sorted(ALLOWED_UPLOAD_PURPOSES))
            )
        return value

    @field_validator("filename")
    @classmethod
    def _extension_allowed(cls, value: str) -> str:
        ext = os.path.splitext(value)[1].lower()
        if ext not in ALLOWED_UPLOAD_EXTENSIONS:
            raise ValueError(
                "file extension must be one of: "
                + ", ".join(sorted(ALLOWED_UPLOAD_EXTENSIONS))
            )
        return value

    @field_validator("content_type")
    @classmethod
    def _mime_allowed(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.lower() not in ALLOWED_UPLOAD_MIME_TYPES:
            raise ValueError(
                "content_type must be one of: "
                + ", ".join(sorted(ALLOWED_UPLOAD_MIME_TYPES))
            )
        return value.lower()


class UploadPresignResponse(BaseModel):
    """Pre-signed PUT URL + object key + public URL (nothing persisted)."""

    upload_url: str
    object_key: str
    public_url: str
    expires_in: int
