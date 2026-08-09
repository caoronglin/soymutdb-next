"""Release, news, publication, page and download models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, enum_values

if TYPE_CHECKING:
    from .auth import User
    from .genomic import Assembly
    from .variant import MutantLine, VariantSummary


class ReleaseStatus(str, enum.Enum):
    DRAFT = "draft"
    STAGING = "staging"
    ACTIVE = "active"
    ARCHIVED = "archived"


class Release(Base, TimestampMixin):
    __tablename__ = "releases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    assembly_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    variant_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    gene_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mutant_line_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(ReleaseStatus, name="release_status_enum", create_constraint=True, values_callable=enum_values),
        default=ReleaseStatus.DRAFT,
        server_default="draft",
        nullable=False,
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    assemblies: Mapped[List["Assembly"]] = relationship(
        back_populates="release", lazy="noload"
    )
    variant_summaries: Mapped[List["VariantSummary"]] = relationship(
        back_populates="release", lazy="noload"
    )
    mutant_lines: Mapped[List["MutantLine"]] = relationship(
        back_populates="release", lazy="noload"
    )
    download_files: Mapped[List["DownloadFile"]] = relationship(
        back_populates="release", lazy="noload"
    )

    __table_args__ = (Index("ix_release_status", "status"),)

    def __repr__(self) -> str:
        return f"<Release id={self.id} version={self.version!r} status={self.status}>"


class NewsStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class NewsArticle(Base, TimestampMixin):
    """News article with the operations pipeline (B1) fields.

    Double-write contract (migration 0010): ``is_published`` is kept in sync
    with ``status`` and is NOT dropped.  ``status`` is the source of truth for
    the new endpoints; ``is_published`` remains for backwards compatibility
    until migration 0011 removes it.
    """

    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title_en: Mapped[str] = mapped_column(String(512), nullable=False)
    title_zh: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content_en: Mapped[str] = mapped_column(Text, nullable=False)
    content_zh: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    slug: Mapped[str] = mapped_column(
        String(256), unique=True, nullable=False, index=True
    )
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    cover_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    featured_sort: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    carousel_group: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    carousel_sort: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), default="draft", server_default="draft", nullable=False
    )
    visible_from: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    visible_to: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_published: Mapped[bool] = mapped_column(
        default=False, server_default="false", nullable=False
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    author_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    author: Mapped[Optional["User"]] = relationship(
        back_populates="articles", lazy="joined"
    )

    __table_args__ = (
        Index("ix_news_published", "is_published", "published_at"),
        Index("ix_news_status_window", "status", "visible_from", "visible_to"),
    )

    def __repr__(self) -> str:
        return f"<NewsArticle id={self.id} slug={self.slug!r} status={self.status}>"


class Publication(Base, TimestampMixin):
    __tablename__ = "publications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    authors: Mapped[str] = mapped_column(Text, nullable=False)
    journal: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    doi: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, unique=True)
    pmid: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, unique=True)
    abstract: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_featured: Mapped[bool] = mapped_column(
        default=False, server_default="false", nullable=False
    )

    __table_args__ = (Index("ix_pub_year", "year"),)

    def __repr__(self) -> str:
        return f"<Publication id={self.id} doi={self.doi!r}>"


class StaticPage(Base, TimestampMixin):
    __tablename__ = "static_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(
        String(256), unique=True, nullable=False, index=True
    )
    title_en: Mapped[str] = mapped_column(String(512), nullable=False)
    title_zh: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content_en: Mapped[str] = mapped_column(Text, nullable=False)
    content_zh: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default="draft", server_default="draft", nullable=False
    )
    author_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    author: Mapped[Optional["User"]] = relationship(lazy="joined")
    versions: Mapped[List["ContentVersion"]] = relationship(
        back_populates="page",
        lazy="noload",
        order_by="ContentVersion.version.desc()",
    )

    __table_args__ = (Index("ix_static_page_status", "status"),)

    def __repr__(self) -> str:
        return f"<StaticPage slug={self.slug!r}>"


class ContentVersion(Base, TimestampMixin):
    """Historical version snapshot of a StaticPage."""

    __tablename__ = "content_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("static_pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title_en: Mapped[str] = mapped_column(String(512), nullable=False)
    title_zh: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content_en: Mapped[str] = mapped_column(Text, nullable=False)
    content_zh: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    edited_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    edit_comment: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    page: Mapped["StaticPage"] = relationship(
        back_populates="versions", lazy="joined"
    )

    __table_args__ = (Index("ix_content_version_page", "page_id", "version"),)

    def __repr__(self) -> str:
        return f"<ContentVersion id={self.id} page_id={self.page_id} version={self.version}>"


class DownloadFile(Base, TimestampMixin):
    __tablename__ = "download_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    release_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("releases.id", ondelete="SET NULL"), nullable=True
    )
    download_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    release: Mapped[Optional["Release"]] = relationship(
        back_populates="download_files", lazy="joined"
    )

    def __repr__(self) -> str:
        return f"<DownloadFile id={self.id} name={self.name!r}>"


__all__ = [
    "ContentVersion",
    "DownloadFile",
    "NewsArticle",
    "NewsStatus",
    "Publication",
    "Release",
    "ReleaseStatus",
    "StaticPage",
]
