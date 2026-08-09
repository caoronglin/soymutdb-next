"""Pydantic v2 schemas for the public seed request contact module (D1)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, field_validator

from ..models.seed_request import SeedRequestStatus

#: Max gene IDs per request (mirrors the seqfetch batch cap).
MAX_GENE_IDS = 200
#: Per-entry length cap — a gene ID is a short stable identifier.
MAX_GENE_ID_LEN = 64


class SeedRequestCreate(BaseModel):
    """Public submission payload (no authentication required)."""

    name: Annotated[str, Field(min_length=1, max_length=256)]
    email: EmailStr
    institution: Annotated[str, Field(min_length=1, max_length=512)]
    country: Annotated[str, Field(min_length=1, max_length=128)]
    gene_ids: list[str] = Field(min_length=1, max_length=MAX_GENE_IDS)
    notes: Annotated[str | None, Field(max_length=5000)] = None

    @field_validator("gene_ids")
    @classmethod
    def _validate_gene_ids(cls, values: list[str]) -> list[str]:
        """Trim/dedupe entries and reject empty or over-long identifiers."""
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in values:
            gene_id = raw.strip()
            if not gene_id:
                continue
            if len(gene_id) > MAX_GENE_ID_LEN:
                raise ValueError(
                    f"Gene ID {gene_id[:40]!r}… exceeds max length {MAX_GENE_ID_LEN}"
                )
            if gene_id not in seen:
                seen.add(gene_id)
                cleaned.append(gene_id)
        if not cleaned:
            raise ValueError("At least one non-empty gene ID is required")
        if len(cleaned) > MAX_GENE_IDS:
            raise ValueError(f"Too many gene IDs: {len(cleaned)} > {MAX_GENE_IDS}")
        return cleaned


class SeedRequestResponse(BaseModel):
    """Public/admin representation of a seed request contact."""

    id: str
    name: str
    email: str
    institution: str
    country: str
    gene_ids: list[str]
    notes: str | None = None
    status: SeedRequestStatus
    created_at: datetime
    processed_at: datetime | None = None
    processed_by: str | None = None

    model_config = {"from_attributes": True}


class SeedRequestUpdate(BaseModel):
    """Admin status update payload."""

    status: SeedRequestStatus


class SeedRequestListResponse(BaseModel):
    """Paginated admin listing of seed request contacts."""

    items: list[SeedRequestResponse]
    total: int
    page: int
    page_size: int


__all__ = [
    "MAX_GENE_IDS",
    "SeedRequestCreate",
    "SeedRequestListResponse",
    "SeedRequestResponse",
    "SeedRequestStatus",
    "SeedRequestUpdate",
]
