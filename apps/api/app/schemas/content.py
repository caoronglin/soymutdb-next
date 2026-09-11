"""Pydantic v2 schemas for CMS-style content: releases, news, publications, static pages."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from ..core.compat import StrEnum

# The release lifecycle status is owned by the database enum in
# ``app.models.content`` (draft / validated / ready / published / rolled_back).
# Re-export it here instead of declaring a second vocabulary: a divergent
# schema enum rejects legitimate rows at response serialization time and turns
# a readable release into an unhandled 500.
from ..models.content import ReleaseStatus


class ReleaseResponse(BaseModel):
    id: str
    version: str
    name: str
    description: str | None = None
    variant_count: int = Field(default=0, ge=0)
    gene_count: int = Field(default=0, ge=0)
    mutant_line_count: int = Field(default=0, ge=0)
    status: ReleaseStatus
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReleaseCreate(BaseModel):
    version: str = Field(..., pattern=r"^\d+\.\d+(\.\d+)?$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    notes: str | None = None

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        if not v:
            raise ValueError("version must not be empty")
        return v


class NewsResponse(BaseModel):
    id: str
    title_en: str
    title_zh: str | None = None
    slug: str
    category: str | None = None
    is_published: bool
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NewsCreate(BaseModel):
    title_en: str = Field(..., min_length=1, max_length=512)
    title_zh: str | None = Field(default=None, max_length=512)
    content_en: str = Field(..., min_length=1)
    content_zh: str | None = None
    slug: str = Field(..., pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    category: str | None = None
    is_published: bool = False


class PublicationResponse(BaseModel):
    id: str
    title: str
    title_zh: str | None = None
    authors: str
    authors_zh: str | None = None
    journal: str | None = None
    year: int | None = None
    doi: str | None = None
    pmid: str | None = None
    abstract: str | None = None
    abstract_zh: str | None = None
    is_featured: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("doi")
    @classmethod
    def _validate_doi_format(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("10."):
            raise ValueError("DOI must start with '10.'")
        return v


class PublicationCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=1024)
    title_zh: str | None = Field(default=None, max_length=1024)
    authors: str = Field(..., min_length=1)
    authors_zh: str | None = Field(default=None)
    journal: str | None = Field(default=None, max_length=256)
    year: int | None = Field(default=None, ge=1000, le=3000)
    doi: str | None = Field(default=None, max_length=256)
    pmid: str | None = Field(default=None, max_length=32)
    abstract: str | None = None
    abstract_zh: str | None = None
    is_featured: bool = False

    @field_validator("doi")
    @classmethod
    def _validate_doi_format(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("10."):
            raise ValueError("DOI must start with '10.'")
        return v


class PublicationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=1024)
    title_zh: str | None = Field(default=None, max_length=1024)
    authors: str | None = Field(default=None, min_length=1)
    authors_zh: str | None = Field(default=None)
    journal: str | None = Field(default=None, max_length=256)
    year: int | None = Field(default=None, ge=1000, le=3000)
    doi: str | None = Field(default=None, max_length=256)
    pmid: str | None = Field(default=None, max_length=32)
    abstract: str | None = None
    abstract_zh: str | None = None
    is_featured: bool | None = None

    @field_validator("doi")
    @classmethod
    def _validate_doi_format(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("10."):
            raise ValueError("DOI must start with '10.'")
        return v


class PublicationListResponse(BaseModel):
    items: list[PublicationResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class PageStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class StaticPageResponse(BaseModel):
    id: str
    slug: str
    title_en: str
    title_zh: str | None = None
    content_en: str
    content_zh: str | None = None
    status: PageStatus = PageStatus.DRAFT
    category: str | None = None
    summary: str | None = None
    sort_order: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StaticPageCreate(BaseModel):
    slug: str = Field(..., pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    title_en: str = Field(..., min_length=1, max_length=512)
    title_zh: str | None = Field(default=None, max_length=512)
    content_en: str = Field(..., min_length=1)
    content_zh: str | None = None
    summary: str | None = None
    category: str | None = Field(default=None, max_length=64)
    sort_order: int = Field(default=0, ge=0)
    status: PageStatus = PageStatus.DRAFT
    edit_comment: str | None = None


class StaticPageUpdate(BaseModel):
    title_en: str | None = Field(default=None, min_length=1, max_length=512)
    title_zh: str | None = None
    content_en: str | None = None
    content_zh: str | None = None
    summary: str | None = None
    category: str | None = None
    sort_order: int | None = Field(default=None, ge=0)
    edit_comment: str | None = None


class StaticPageDetailResponse(StaticPageResponse):
    """Extended response with summary, category, status, author, version info."""

    author_name: str | None = None
    published_at: datetime | None = None
    current_version: int = 1


class StaticPageMigrationDryRunRequest(BaseModel):
    """Optional unique StaticPage slug selection for a non-mutating preview."""

    slugs: list[
        Annotated[
            str,
            Field(min_length=1, max_length=256, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"),
        ]
    ] | None = Field(default=None, max_length=200)

    @field_validator("slugs")
    @classmethod
    def _reject_duplicate_slugs(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("slugs must not contain duplicates")
        return value


class StaticPageMigrationItemResponse(BaseModel):
    static_page_id: int
    slug: str
    route: str
    outcome: str
    error_code: str | None = None
    message: str | None = None


class StaticPageMigrationDryRunResponse(BaseModel):
    dry_run: bool
    created: int
    skipped: int
    invalid: int
    items: list[StaticPageMigrationItemResponse] = Field(default_factory=list)


class ContentVersionResponse(BaseModel):
    id: str
    page_id: str
    version: int
    title_en: str
    title_zh: str | None = None
    content_en: str
    content_zh: str | None = None
    summary: str | None = None
    edited_by: str | None = None
    edit_comment: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DownloadFileResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    file_url: str
    file_size: int | None = None
    category: str | None = None
    download_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class SignedUrlResponse(BaseModel):
    """Pre-signed URL response with RBAC-validated access."""

    url: str
    index_url: str | None = None
    expires_in: int = Field(..., description="URL validity in seconds.")
    request_id: str | None = None
