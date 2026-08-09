"""Pydantic v2 schemas for the news operations pipeline (B1).

Public contract:
- ``GET /api/v1/news``           -> NewsListResponse
- ``GET /api/v1/news/featured``  -> NewsFeaturedResponse
- ``GET /api/v1/news/{slug}``    -> NewsDetailResponse (published only,
                                   or via HMAC preview token)

Admin contract (researcher+):
- ``POST   /api/v1/admin/news``                     NewsCreate       -> NewsDetailResponse
- ``PUT    /api/v1/admin/news/{news_id}``           NewsUpdate       -> NewsDetailResponse
- ``DELETE /api/v1/admin/news/{news_id}``                              -> 204
- ``PATCH  /api/v1/admin/news/reorder``             NewsReorderRequest -> NewsReorderResponse
- ``GET    /api/v1/admin/news/{news_id}/preview-token``                -> PreviewTokenResponse

``status`` (draft/published/archived) is the source of truth; ``is_published``
is kept in sync by the service layer (double-write, migration 0010).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from ..core.compat import StrEnum


class NewsStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


def _coerce_id_to_str(value: object) -> object:
    """Pydantic v2 does not coerce int -> str; ORM ids are ints."""
    if isinstance(value, int):
        return str(value)
    return value


# ---------------------------------------------------------------------------
# Public responses
# ---------------------------------------------------------------------------


class NewsSummaryResponse(BaseModel):
    """List-item view (no body content)."""

    id: str
    title_en: str
    title_zh: str | None = None
    slug: str
    category: str | None = None
    cover_url: str | None = None
    featured_sort: int = 0
    carousel_group: str | None = None
    carousel_sort: int = 0
    status: NewsStatus = NewsStatus.DRAFT
    is_published: bool = False
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    _coerce_id = field_validator("id", mode="before")(_coerce_id_to_str)


class NewsDetailResponse(NewsSummaryResponse):
    """Full article view including body content."""

    content_en: str
    content_zh: str | None = None


class NewsListResponse(BaseModel):
    """Paginated public news list (published + visible window only)."""

    items: list[NewsSummaryResponse]
    total: int
    page: int
    page_size: int


class CarouselGroupResponse(BaseModel):
    """One carousel group (grouped by ``carousel_group``, ordered by
    ``carousel_sort``)."""

    group: str
    items: list[NewsSummaryResponse]


class NewsFeaturedResponse(BaseModel):
    """Homepage block: 5 featured articles + carousel groups."""

    featured: list[NewsSummaryResponse]
    carousel: list[CarouselGroupResponse]


# ---------------------------------------------------------------------------
# Admin write payloads
# ---------------------------------------------------------------------------


class NewsCreate(BaseModel):
    title_en: str = Field(..., min_length=1, max_length=512)
    title_zh: str | None = Field(default=None, max_length=512)
    content_en: str = Field(..., min_length=1)
    content_zh: str | None = None
    slug: str = Field(..., pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    category: str | None = Field(default=None, max_length=64)
    cover_url: str | None = Field(default=None, max_length=1024)
    featured_sort: int = Field(default=0, ge=0)
    carousel_group: str | None = Field(default=None, max_length=64)
    carousel_sort: int = Field(default=0, ge=0)
    status: NewsStatus = NewsStatus.DRAFT
    visible_from: datetime | None = None
    visible_to: datetime | None = None
    is_published: bool = False


class NewsUpdate(BaseModel):
    title_en: str | None = Field(default=None, min_length=1, max_length=512)
    title_zh: str | None = Field(default=None, max_length=512)
    content_en: str | None = Field(default=None, min_length=1)
    content_zh: str | None = None
    slug: str | None = Field(
        default=None, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )
    category: str | None = Field(default=None, max_length=64)
    cover_url: str | None = Field(default=None, max_length=1024)
    featured_sort: int | None = Field(default=None, ge=0)
    carousel_group: str | None = Field(default=None, max_length=64)
    carousel_sort: int | None = Field(default=None, ge=0)
    status: NewsStatus | None = None
    visible_from: datetime | None = None
    visible_to: datetime | None = None
    is_published: bool | None = None


class NewsReorderItem(BaseModel):
    id: int
    featured_sort: int = Field(..., ge=0)


class NewsReorderRequest(BaseModel):
    items: list[NewsReorderItem] = Field(..., min_length=1)


class NewsReorderResponse(BaseModel):
    updated: int


class PreviewTokenResponse(BaseModel):
    """Short-lived HMAC preview token (15 min, stateless, NOT a JWT)."""

    preview: str
    exp: int
    url: str
