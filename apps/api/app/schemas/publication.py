"""Pydantic v2 schemas for immutable static publications (Phase 3)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ..models.publication import PublicationStatus, PublicationTarget


class PublicationRequest(BaseModel):
    target: PublicationTarget
    release_id: int = Field(..., ge=1)
    page_definition_version: int | None = Field(default=None, ge=1)


class PublicationRollbackRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class PublicationResponse(BaseModel):
    id: int
    publication_id: int
    target: PublicationTarget
    status: PublicationStatus
    release_id: int
    page_definition_version: int | None = None
    manifest_digest: str | None = None
    artifact_url: str | None = None
    remote_id: str | None = None
    previous_publication_id: int | None = None
    superseded_by_publication_id: int | None = None
    error_message: str | None = None
    requested_by: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PublicationListResponse(BaseModel):
    items: list[PublicationResponse]
    total: int
    page: int
    page_size: int


class PublicationTargetResponse(BaseModel):
    target: str
    description: str
    is_configured: bool


class PublicationTargetListResponse(BaseModel):
    items: list[PublicationTargetResponse]


__all__ = [
    "PublicationListResponse",
    "PublicationRequest",
    "PublicationResponse",
    "PublicationRollbackRequest",
    "PublicationTargetListResponse",
    "PublicationTargetResponse",
]
