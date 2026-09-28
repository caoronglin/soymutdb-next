"""Pydantic v2 schemas for immutable static publications (Phase 3)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from ..models.publication import PublicationStatus, PublicationTarget

#: Schemes a build-artifact reference may use. ``http(s)`` is a remote object
#: store; ``file`` is only useful for a co-located/local target.
_ARTIFACT_URL_SCHEMES = ("http://", "https://", "file://")


class PublicationRequest(BaseModel):
    target: PublicationTarget
    release_id: int = Field(..., ge=1)
    page_definition_version: int | None = Field(default=None, ge=1)
    #: Immutable location of the SSG build output (a directory tree archive).
    #:
    #: The worker refuses to publish without real build output, so a request
    #: without this field fails closed as ``MissingBuildOutput`` rather than
    #: deploying a synthetic placeholder page. Supplying it is what makes a
    #: publication actually publishable.
    build_artifact_url: str | None = Field(default=None, max_length=2048)

    @field_validator("build_artifact_url")
    @classmethod
    def _validate_build_artifact_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            return None
        if not trimmed.lower().startswith(_ARTIFACT_URL_SCHEMES):
            raise ValueError(
                "build_artifact_url must be an http(s) or file URL pointing at "
                "the immutable build output"
            )
        return trimmed


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
    build_artifact_url: str | None = None
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
