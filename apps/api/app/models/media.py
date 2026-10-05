"""Durable media assets used by the CMS and public content."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class MediaAssetStatus(StrEnum):
    """Lifecycle state for an uploaded object."""

    PENDING = "pending"
    READY = "ready"
    ARCHIVED = "archived"


class MediaAsset(Base, TimestampMixin):
    """A verified object in the public media bucket.

    The object store is deliberately not the CMS source of truth. This row
    records the immutable upload facts and editable accessibility metadata so
    editors can reuse an image without copying a URL into every content item.
    status is soft-delete friendly: an archived asset is hidden from normal
    pickers but remains auditable and can be garbage-collected asynchronously.
    """

    __tablename__ = "media_assets"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    object_key: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    public_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    credit: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_decorative: Mapped[bool] = mapped_column(
        default=False, server_default="false", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), default=MediaAssetStatus.READY.value, server_default="ready", nullable=False
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_media_assets_status_purpose", "status", "purpose"),
        Index("ix_media_assets_checksum", "checksum_sha256"),
    )

    def __repr__(self) -> str:
        return (
            f"<MediaAsset id={self.id} filename={self.original_filename!r} "
            f"status={self.status!r}>"
        )


__all__ = ["MediaAsset", "MediaAssetStatus"]
