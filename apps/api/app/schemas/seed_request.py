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
    #: Free-text gene identifiers supplied by the requester.
    #:
    #: These are **not** resolved to released records: a public submission has
    #: no assembly/release context, and the same accession can denote different
    #: loci in v4 and v5. They are stored and emailed verbatim as the
    #: requester's own description of what they want, and the curator resolves
    #: them against a specific release when processing the request. Do not add
    #: release-scoped validation here without also carrying assembly/release in
    #: the payload.
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


class SeedRequestGeneCount(BaseModel):
    """Aggregate demand for one gene ID.

    Deliberately carries no requester, timestamp or status: the public gene page
    shows "how many people asked for this material", which is demand signal, not
    personal data. Anything that could identify a requester stays behind
    ``/admin/seed-requests``.
    """

    gene_id: str
    requests: int


class SeedRequestStatsResponse(BaseModel):
    """Public aggregate counts keyed by gene ID."""

    items: list[SeedRequestGeneCount]
    #: Total request rows on record, across every gene.
    total_requests: int


__all__ = [
    "MAX_GENE_IDS",
    "SeedRequestCreate",
    "SeedRequestGeneCount",
    "SeedRequestListResponse",
    "SeedRequestResponse",
    "SeedRequestStatsResponse",
    "SeedRequestStatus",
    "SeedRequestUpdate",
]
