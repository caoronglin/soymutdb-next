"""Release, news, publication, page and download models."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, enum_values

if TYPE_CHECKING:
    from .auth import User
    from .genomic import Assembly
    from .variant import MutantLine, VariantSummary


class ReleaseStatus(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    READY = "ready"
    PUBLISHED = "published"
    ROLLED_BACK = "rolled_back"
    STAGING = VALIDATED
    ACTIVE = PUBLISHED
    ARCHIVED = ROLLED_BACK


class Release(Base, TimestampMixin):
    __tablename__ = "releases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    assembly_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    variant_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    gene_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mutant_line_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(
            ReleaseStatus,
            name="release_status_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=ReleaseStatus.DRAFT,
        server_default="draft",
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    assembly: Mapped[str | None] = mapped_column(String(128), nullable=True)
    manifest: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    assemblies: Mapped[list[Assembly]] = relationship(back_populates="release", lazy="noload")
    variant_summaries: Mapped[list[VariantSummary]] = relationship(
        back_populates="release", lazy="noload"
    )
    mutant_lines: Mapped[list[MutantLine]] = relationship(back_populates="release", lazy="noload")
    download_files: Mapped[list[DownloadFile]] = relationship(
        back_populates="release", lazy="noload"
    )

    __table_args__ = (Index("ix_release_status", "status"),)

    def __repr__(self) -> str:
        return f"<Release id={self.id} version={self.version!r} status={self.status}>"


class NewsStatus(StrEnum):
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
    title_zh: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_en: Mapped[str] = mapped_column(Text, nullable=False)
    content_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Provenance is recorded only for a controlled external-source preview that
    # an editor explicitly applies and later saves as a normal CMS draft.
    source_platform: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    slug: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # cover_url remains for backwards compatibility; new editors should bind
    # cover_asset_id so the media library is the canonical source.
    cover_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("media_assets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    cover_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    cover_alt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    featured_sort: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    carousel_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    carousel_sort: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), default="draft", server_default="draft", nullable=False
    )
    visible_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    visible_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_published: Mapped[bool] = mapped_column(
        default=False, server_default="false", nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Deleted records remain addressable only by the lifecycle restore path.
    # Keeping their slug reserves the canonical public URL and audit history.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    lock_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    schedule_generation: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    author: Mapped[User | None] = relationship(
        back_populates="articles", foreign_keys=[author_id], lazy="joined"
    )

    __table_args__ = (
        Index("ix_news_published", "is_published", "published_at"),
        Index("ix_news_status_window", "status", "visible_from", "visible_to"),
        Index("ix_news_articles_deleted_at", "deleted_at"),
        # PostgreSQL allows multiple NULLs in a unique index, so locally
        # authored articles remain unrestricted while a canonical external URL
        # can never be claimed by two CMS records.
        Index("uq_news_articles_source_url", "source_url", unique=True),
    )

    def __repr__(self) -> str:
        return f"<NewsArticle id={self.id} slug={self.slug!r} status={self.status}>"


class NewsScheduleState(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class NewsArticleRevision(Base, TimestampMixin):
    __tablename__ = "news_article_revisions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    article_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("news_articles.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("article_id", "version", name="uq_news_article_revisions_article_version"),
        Index("ix_news_article_revisions_article_id", "article_id"),
    )


class NewsPublicationSchedule(Base, TimestampMixin):
    __tablename__ = "news_publication_schedules"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    article_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("news_articles.id", ondelete="RESTRICT"), nullable=False
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(
        Enum(NewsScheduleState, name="news_schedule_state_enum", values_callable=enum_values),
        default=NewsScheduleState.PENDING,
        server_default="pending",
        nullable=False,
    )
    leased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "(state = 'leased') = (leased_at IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_news_publication_schedules_leased_lease",
        ),
        UniqueConstraint(
            "article_id", "generation", name="uq_news_publication_schedules_article_generation"
        ),
        Index("ix_news_publication_schedules_due", "state", "scheduled_for"),
    )


class Publication(Base, TimestampMixin):
    __tablename__ = "publications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    title_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    authors: Mapped[str] = mapped_column(Text, nullable=False)
    authors_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    journal: Mapped[str | None] = mapped_column(String(256), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doi: Mapped[str | None] = mapped_column(String(256), nullable=True, unique=True)
    pmid: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    abstract_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_featured: Mapped[bool] = mapped_column(default=False, server_default="false", nullable=False)

    __table_args__ = (Index("ix_pub_year", "year"),)

    def __repr__(self) -> str:
        return f"<Publication id={self.id} doi={self.doi!r}>"


class StaticPage(Base, TimestampMixin):
    __tablename__ = "static_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    title_en: Mapped[str] = mapped_column(String(512), nullable=False)
    title_zh: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_en: Mapped[str] = mapped_column(Text, nullable=False)
    content_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default="draft", server_default="draft", nullable=False
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    author: Mapped[User | None] = relationship(lazy="joined")
    versions: Mapped[list[ContentVersion]] = relationship(
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
    title_zh: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_en: Mapped[str] = mapped_column(Text, nullable=False)
    content_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    edit_comment: Mapped[str | None] = mapped_column(String(512), nullable=True)

    page: Mapped[StaticPage] = relationship(back_populates="versions", lazy="joined")

    __table_args__ = (Index("ix_content_version_page", "page_id", "version"),)

    def __repr__(self) -> str:
        return f"<ContentVersion id={self.id} page_id={self.page_id} version={self.version}>"


class DownloadFile(Base, TimestampMixin):
    __tablename__ = "download_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    release_id: Mapped[int | None] = mapped_column(
        ForeignKey("releases.id", ondelete="SET NULL"), nullable=True
    )
    download_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    release: Mapped[Release | None] = relationship(
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
